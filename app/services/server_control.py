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


def validate_minecraft_command(command: str) -> str:
    cleaned = command.strip().lstrip("/")
    if not cleaned or len(cleaned) > 512:
        raise ServerControlError("Minecraft commands must be between 1 and 512 characters.")
    if any(character in cleaned for character in {"\n", "\r", "\x00"}):
        raise ServerControlError("Minecraft commands must be a single line.")
    return cleaned


def run_managed_action(action_key: str) -> dict[str, str | int]:
    action = ManagedAction.query.filter_by(key=action_key, enabled=True).first()
    if action is None:
        raise ServerControlError("That managed action is not configured.")

    executable = Path(action.executable_path).expanduser().resolve()
    if not executable.is_absolute() or not executable.exists():
        raise ServerControlError("The configured action path is invalid.")

    try:
        arguments = json.loads(action.arguments_json or "[]")
        if not isinstance(arguments, list) or any(not isinstance(item, str) for item in arguments):
            raise ValueError
    except ValueError:
        arguments = shlex.split(action.arguments_json or "")

    try:
        result = subprocess.run(
            [str(executable), *arguments],
            cwd=Path(action.working_directory).resolve() if action.working_directory else None,
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ServerControlError(str(exc)) from exc
    return {
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


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


def send_minecraft_command(command: str) -> str:
    validated = validate_minecraft_command(command)
    password = get_setting("rcon_password", current_app.config["RCON_PASSWORD"])
    if not password:
        raise ServerControlError("RCON is not configured yet.")

    host = get_setting("rcon_host", current_app.config["RCON_HOST"])
    port = int(get_setting("rcon_port", str(current_app.config["RCON_PORT"])))
    timeout = int(current_app.config["RCON_TIMEOUT"])
    with RconClient(host, port, password, timeout) as client:
        return client.command(validated)
