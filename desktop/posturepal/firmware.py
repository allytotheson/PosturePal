"""Feather v3 Nordic UART protocol (firmware commit 6fbfdc0)."""

import math
import re
from dataclasses import dataclass

from .domain import Settings

SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
RX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
NUMBER = r"(-?\d+(?:\.\d+)?)"
STATES = "SETTLING|CALIBRATING|MONITORING|ALERT|PAUSED|FAULT"


@dataclass(frozen=True)
class Reading:
    upper: float
    lower: float
    buzz: bool
    received_at: float


@dataclass(frozen=True)
class DeviceState:
    state: str
    detail: str

    @property
    def fault_reason(self):
        if self.state != "FAULT":
            return None
        # EVENT carries reason=, whereas STATUS carries mounting flags then fault=.
        match = re.search(r"(?:^| )(?:reason|fault)=(.*)", self.detail)
        reason = match[1] if match else self.detail
        return reason if reason and reason != "none" else None


@dataclass(frozen=True)
class Readback:
    settings: Settings


@dataclass(frozen=True)
class Baseline:
    angles: tuple[float, float] | None


@dataclass(frozen=True)
class ProtocolVersion:
    version: int


class FirmwareCodec:
    """Bounded line reassembly; discard an entire corrupt line through its LF."""

    def __init__(self):
        self.buffer = bytearray()
        self.discarding = False

    def feed(self, data: bytes, received_at: float):
        events = []
        for byte in data:
            if byte == 10:
                if not self.discarding:
                    line = self.buffer.decode("ascii").removesuffix("\r")
                    events.append(line)
                    try:
                        event = self.parse(line, received_at)
                        if event is not None:
                            events.append(event)
                    except ValueError as exc:
                        events.append(ValueError(str(exc)))
                self.buffer.clear()
                self.discarding = False
            elif not self.discarding:
                if byte not in (13,) and not 32 <= byte <= 126:
                    self.discarding = True
                    self.buffer.clear()
                    events.append(ValueError("Non-ASCII firmware response discarded"))
                elif len(self.buffer) >= 638:
                    self.discarding = True
                    self.buffer.clear()
                    events.append(
                        ValueError(
                            "Oversized firmware response discarded; request status"
                        )
                    )
                else:
                    self.buffer.append(byte)
        return events

    @staticmethod
    def parse(line, received_at):
        match = re.fullmatch(
            rf"upper_deg={NUMBER} lower_deg={NUMBER} buzz=([01])", line
        )
        if match:
            upper, lower = map(float, match.group(1, 2))
            if not all(math.isfinite(x) and abs(x) <= 180 for x in (upper, lower)):
                raise ValueError("Firmware angle outside ±180 degrees")
            return Reading(upper, lower, match[3] == "1", received_at)
        match = re.fullmatch(rf"(?:EVENT|STATUS) state=({STATES}) (.*)", line)
        if match:
            return DeviceState(match[1], match[2])
        match = re.fullmatch(
            rf"SETTINGS trigger={NUMBER},{NUMBER} recovery={NUMBER},{NUMBER} duration_ms=(\d+) motor_rtp=\d+ \(TUNING VALUES\)",
            line,
        )
        if match:
            upper, lower, upper_recovery, lower_recovery = map(
                float, match.group(1, 2, 3, 4)
            )
            return Readback(
                Settings(upper, lower, int(match[5]), upper_recovery, lower_recovery)
            )
        match = re.fullmatch(rf"BASELINE valid=([01]) sag={NUMBER},{NUMBER}", line)
        if match:
            values = tuple(map(float, match.group(2, 3)))
            if not all(math.isfinite(x) and abs(x) <= 180 for x in values):
                raise ValueError("Invalid firmware baseline")
            return Baseline(values if match[1] == "1" else None)
        match = re.fullmatch(r"PROTOCOL version=(\d+) transport=newline-ascii", line)
        if match:
            if match[1] != "1":
                raise ValueError(f"Unsupported firmware protocol {match[1]}")
            return ProtocolVersion(1)
        if line.startswith(
            ("upper_deg=", "SETTINGS ", "BASELINE ", "PROTOCOL ", "STATUS ", "EVENT ")
        ):
            raise ValueError(f"Malformed firmware response: {line}")

    @staticmethod
    def encode_command(command):
        if not isinstance(command, str) or not re.fullmatch(
            r"[\x20-\x7e]{1,159}", command
        ):
            raise ValueError("Use 1–159 printable ASCII characters, without newlines")
        return (command + "\n").encode("ascii")

    @staticmethod
    def settings_command(settings):
        return (
            f"set {settings.upper_threshold:.2f} {settings.upper_recovery:.2f} "
            f"{settings.lower_threshold:.2f} {settings.lower_recovery:.2f} {settings.dwell_ms}"
        )
