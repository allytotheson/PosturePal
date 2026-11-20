"""Application readings and settings; absent firmware fields stay unknown."""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    upper_threshold: float = 15
    lower_threshold: float = 12
    dwell_ms: int = 3000
    upper_recovery: float = 4
    lower_recovery: float = 4

    def __post_init__(self):
        for trigger, recovery in (
            (self.upper_threshold, self.upper_recovery),
            (self.lower_threshold, self.lower_recovery),
        ):
            if (
                not all(math.isfinite(v) for v in (trigger, recovery))
                or not 0 < recovery < trigger <= 90
            ):
                raise ValueError("Require 0 < recovery < trigger <= 90 degrees")
        if (
            isinstance(self.dwell_ms, bool)
            or not isinstance(self.dwell_ms, int)
            or not 1 <= self.dwell_ms <= 3600000
        ):
            raise ValueError(
                "Dwell must be an integer between 1 and 3600000 milliseconds"
            )


@dataclass(frozen=True)
class Frame:
    sequence: int
    device_time_ms: float | None
    received_at: float
    upper_deg: float
    lower_deg: float
    upper_state: str
    lower_state: str
    battery_pct: float | None
    device_status: str
    buzz: bool | None = None

    @classmethod
    def decode(cls, payload: dict, received_at: float):
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise ValueError("Unsupported frame version")
        for key in (
            "sequence",
            "device_time_ms",
            "upper_deg",
            "lower_deg",
            "battery_pct",
        ):
            value = payload.get(key)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"Invalid {key}")
        if (
            not isinstance(payload["sequence"], int)
            or payload["sequence"] < 0
            or payload["device_time_ms"] < 0
        ):
            raise ValueError("Invalid sequence or device timestamp")
        if (
            any(abs(payload[k]) > 90 for k in ("upper_deg", "lower_deg"))
            or not 0 <= payload["battery_pct"] <= 100
        ):
            raise ValueError("Angle or battery out of range")
        if any(
            payload.get(k) not in ("aligned", "pending", "cue")
            for k in ("upper_state", "lower_state")
        ):
            raise ValueError("Invalid posture state")
        if payload.get("device_status") not in ("ready", "calibrating", "fault"):
            raise ValueError("Invalid device status")
        return cls(
            **{
                k: payload[k]
                for k in cls.__dataclass_fields__
                if k not in ("received_at", "buzz")
            },
            received_at=received_at,
        )


class Dwell:
    """Used by the fake MCU only. Production feedback remains on firmware."""

    def __init__(self):
        self.since = None

    def update(self, angle, threshold, now, dwell_ms):
        if abs(angle) <= threshold:
            self.since = None
            return "aligned"
        if self.since is None:
            self.since = now
        return "cue" if (now - self.since) * 1000 >= dwell_ms else "pending"


def spine_points(upper, lower):
    y, z, result = 0.0, 0.0, []
    for i in range(24):
        t = i / 23
        angle = math.radians(lower + upper * max(0, (t - 0.45) / 0.55))
        y += math.cos(angle) * 0.135
        z += math.sin(angle) * 0.135
        result.append((0.0, y, z + 0.095 * math.sin(t * math.tau)))
    return result
