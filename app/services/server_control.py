from __future__ import annotations

import json
import shlex
import socket
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path

from flask import current_app

from app.models import ManagedAction
from app.services.system_settings import get_setting


class ServerControlError(ValueError):
    pass


@dataclass(frozen=True)
class MinecraftServerStatus:
    state: str
    label: str
    detail: str


def validate_minecraft_command(command: str) -> str:
    cleaned = command.strip().lstrip("/")
    if not cleaned or len(cleaned) > 512:
        raise ServerControlError("Minecraft commands must be between 1 and 512 characters.")
    if any(character in cleaned for character in {"\n", "\r", "\x00"}):
        raise ServerControlError("Minecraft commands must be a single line.")
    return cleaned


def _resolve_managed_action_command(action: ManagedAction) -> tuple[list[str], str | None]:
    executable = Path(action.executable_path).expanduser().resolve()
    if not executable.is_absolute() or not executable.exists():
        raise ServerControlError("The configured action path is invalid.")

    try:
        arguments = json.loads(action.arguments_json or "[]")
        if not isinstance(arguments, list) or any(not isinstance(item, str) for item in arguments):
            raise ValueError
    except ValueError:
        arguments = shlex.split(action.arguments_json or "")

    cwd = str(Path(action.working_directory).resolve()) if action.working_directory else None
    return [str(executable), *arguments], cwd


def _format_managed_action_failure(returncode: int, stdout: str, stderr: str) -> str:
    detail = stderr.strip() or stdout.strip()
    if detail:
        return f"Managed action exited with status {returncode}: {detail}"
    return f"Managed action exited with status {returncode}."


def _run_blocking_managed_action(command: list[str], cwd: str | None) -> dict[str, str | int]:
    timeout = int(current_app.config["MANAGED_ACTION_TIMEOUT"])

    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ServerControlError(f"Managed action timed out after {timeout} seconds.") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise ServerControlError(str(exc)) from exc

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    if result.returncode != 0:
        raise ServerControlError(_format_managed_action_failure(result.returncode, stdout, stderr))

    return {
        "returncode": result.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "status": "completed",
    }


def _run_background_start_action(command: list[str], cwd: str | None) -> dict[str, str | int]:
    grace_period = float(current_app.config["MANAGED_ACTION_START_GRACE_PERIOD"])

    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ServerControlError(str(exc)) from exc

    try:
        returncode = process.wait(timeout=grace_period)
    except subprocess.TimeoutExpired:
        return {
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "status": "launched",
            "detail": "Managed action is still running in the background.",
            "pid": process.pid,
        }

    if returncode != 0:
        raise ServerControlError(f"Managed action exited immediately with status {returncode}.")

    return {
        "returncode": returncode,
        "stdout": "",
        "stderr": "",
        "status": "completed",
    }


def run_managed_action(action_key: str) -> dict[str, str | int]:
    action = ManagedAction.query.filter_by(key=action_key, enabled=True).first()
    if action is None:
        raise ServerControlError("That managed action is not configured.")

    command, cwd = _resolve_managed_action_command(action)
    if action.key == "server.start":
        return _run_background_start_action(command, cwd)
    return _run_blocking_managed_action(command, cwd)


@dataclass
class RconPacket:
    request_id: int
    packet_type: int
    payload: bytes


class RconClient:
    def __init__(self, host: str, port: int, password: str, timeout: int) -> None:
        self.host = host
        self.port = port
        self.password = password
        self.timeout = timeout
        self._socket: socket.socket | None = None

    def __enter__(self) -> "RconClient":
        self._socket = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._authenticate()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def _send_packet(self, request_id: int, packet_type: int, payload: str) -> None:
        if self._socket is None:
            raise ServerControlError("RCON connection is not open.")
        body = payload.encode("utf-8") + b"\x00\x00"
        packet = struct.pack("<iii", len(body) + 8, request_id, packet_type) + body
        self._socket.sendall(packet)

    def _recv_exact(self, length: int) -> bytes:
        if self._socket is None:
            raise ServerControlError("RCON connection is not open.")
        data = bytearray()
        while len(data) < length:
            chunk = self._socket.recv(length - len(data))
            if not chunk:
                raise ServerControlError("RCON connection closed unexpectedly.")
            data.extend(chunk)
        return bytes(data)

    def _read_packet(self) -> RconPacket:
        if self._socket is None:
            raise ServerControlError("RCON connection is not open.")
        length = struct.unpack("<i", self._recv_exact(4))[0]
        data = self._recv_exact(length)
        request_id, packet_type = struct.unpack("<ii", data[:8])
        payload = data[8:-2]
        return RconPacket(request_id=request_id, packet_type=packet_type, payload=payload)

    def _authenticate(self) -> None:
        self._send_packet(1, 3, self.password)
        response = self._read_packet()
        if response.request_id == -1:
            raise ServerControlError("RCON authentication failed.")

    def command(self, command: str) -> str:
        self._send_packet(2, 2, command)
        response = self._read_packet()
        return response.payload.decode("utf-8", errors="replace")


def get_rcon_connection_settings() -> tuple[str, int, str, int]:
    host = get_setting("rcon_host", current_app.config["RCON_HOST"])
    port = int(get_setting("rcon_port", str(current_app.config["RCON_PORT"])))
    password = get_setting("rcon_password", current_app.config["RCON_PASSWORD"])
    timeout = int(current_app.config["RCON_TIMEOUT"])
    return host, port, password, timeout


def get_minecraft_server_status() -> MinecraftServerStatus:
    try:
        host, port, password, timeout = get_rcon_connection_settings()
    except ValueError:
        return MinecraftServerStatus(
            state="warning",
            label="unknown",
            detail="MCPortal has an invalid RCON host or port configured.",
        )

    endpoint = f"{host}:{port}"

    if not password:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return MinecraftServerStatus(
                    state="warning",
                    label="on",
                    detail=f"RCON is reachable on {endpoint}, but MCPortal has no password configured.",
                )
        except OSError:
            return MinecraftServerStatus(
                state="offline",
                label="off",
                detail=f"No RCON listener responded on {endpoint}.",
            )

    try:
        with RconClient(host, port, password, timeout):
            return MinecraftServerStatus(
                state="online",
                label="on",
                detail=f"RCON accepted a connection on {endpoint}.",
            )
    except ServerControlError as exc:
        if str(exc) == "RCON authentication failed.":
            return MinecraftServerStatus(
                state="warning",
                label="on",
                detail=f"The server is reachable on {endpoint}, but the saved RCON password was rejected.",
            )
        return MinecraftServerStatus(
            state="warning",
            label="unknown",
            detail=str(exc),
        )
    except OSError:
        return MinecraftServerStatus(
            state="offline",
            label="off",
            detail=f"No RCON listener responded on {endpoint}.",
        )


def send_minecraft_command(command: str) -> str:
    validated = validate_minecraft_command(command)
    host, port, password, timeout = get_rcon_connection_settings()
    if not password:
        raise ServerControlError("RCON is not configured yet.")
    with RconClient(host, port, password, timeout) as client:
        return client.command(validated)
