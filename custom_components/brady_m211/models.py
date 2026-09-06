"""Data models for Brady M211 printer status."""

from __future__ import annotations

from dataclasses import dataclass, field


def _as_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in {"true", "1", "yes"}:
        return True
    if lowered in {"false", "0", "no"}:
        return False
    return None


def _as_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value.split(".")[0])
    except ValueError:
        return None


@dataclass
class PrinterStatus:
    """Live Compact PICL properties from an M211."""

    raw: dict[str, str] = field(default_factory=dict)
    battery: str | None = None
    battery_ac: bool | None = None
    media_remaining: int | None = None
    printable_width: int | None = None
    printable_height: int | None = None
    left_offset: int | None = None
    vertical_offset: int | None = None
    die_cut: bool | None = None
    self_lam: bool | None = None
    permasleeve: bool | None = None
    firmware: str | None = None
    unique_id: int | None = None
    fatal_error: bool | None = None
    cut_error: bool | None = None
    media_invalid: bool | None = None
    media_out: bool | None = None
    media_low: bool | None = None
    print_job_error: bool | None = None
    low_power: bool | None = None
    dismissible_error: bool | None = None
    job_complete: bool | None = None
    job_status: str | None = None
    shutdown_timeout: int | None = None
    knockoff_count: int | None = None

    @classmethod
    def from_properties(cls, values: dict[str, str]) -> PrinterStatus:
        """Build status from Compact PICL ID → value map."""
        from .const import (
            PROP_AC_CONNECTED,
            PROP_BATTERY,
            PROP_CUT_ERROR,
            PROP_DIE_CUT,
            PROP_DISMISSIBLE_ERROR,
            PROP_FATAL_ERROR,
            PROP_FIRMWARE,
            PROP_JOB_COMPLETE,
            PROP_JOB_STATUS,
            PROP_KNOCKOFF,
            PROP_LEFT_OFFSET,
            PROP_LOW_POWER,
            PROP_MEDIA_INVALID,
            PROP_MEDIA_LOW,
            PROP_MEDIA_OUT,
            PROP_MEDIA_REMAINING,
            PROP_PERMASLEEVE,
            PROP_PRINT_JOB_ERROR,
            PROP_PRINTABLE_HEIGHT,
            PROP_PRINTABLE_WIDTH,
            PROP_SELF_LAM,
            PROP_SHUTDOWN_TIMEOUT,
            PROP_UNIQUE_ID,
            PROP_VERTICAL_OFFSET,
        )

        return cls(
            raw=dict(values),
            battery=values.get(PROP_BATTERY),
            battery_ac=_as_bool(values.get(PROP_AC_CONNECTED)),
            media_remaining=_as_int(values.get(PROP_MEDIA_REMAINING)),
            printable_width=_as_int(values.get(PROP_PRINTABLE_WIDTH)),
            printable_height=_as_int(values.get(PROP_PRINTABLE_HEIGHT)),
            left_offset=_as_int(values.get(PROP_LEFT_OFFSET)),
            vertical_offset=_as_int(values.get(PROP_VERTICAL_OFFSET)),
            die_cut=_as_bool(values.get(PROP_DIE_CUT)),
            self_lam=_as_bool(values.get(PROP_SELF_LAM)),
            permasleeve=_as_bool(values.get(PROP_PERMASLEEVE)),
            firmware=values.get(PROP_FIRMWARE),
            unique_id=_as_int(values.get(PROP_UNIQUE_ID)),
            fatal_error=_as_bool(values.get(PROP_FATAL_ERROR)),
            cut_error=_as_bool(values.get(PROP_CUT_ERROR)),
            media_invalid=_as_bool(values.get(PROP_MEDIA_INVALID)),
            media_out=_as_bool(values.get(PROP_MEDIA_OUT)),
            media_low=_as_bool(values.get(PROP_MEDIA_LOW)),
            print_job_error=_as_bool(values.get(PROP_PRINT_JOB_ERROR)),
            low_power=_as_bool(values.get(PROP_LOW_POWER)),
            dismissible_error=_as_bool(values.get(PROP_DISMISSIBLE_ERROR)),
            job_complete=_as_bool(values.get(PROP_JOB_COMPLETE)),
            job_status=values.get(PROP_JOB_STATUS),
            shutdown_timeout=_as_int(values.get(PROP_SHUTDOWN_TIMEOUT)),
            knockoff_count=_as_int(values.get(PROP_KNOCKOFF)),
        )

    @property
    def has_error(self) -> bool:
        """Return True if the printer is reporting a blocking error."""
        return self.print_blocked_reason() is not None or bool(self.print_job_error)

    def print_blocked_reason(self) -> str | None:
        """Android ThereAreShowStoppingPrinterErrors, in the same check order."""
        checks = (
            (self.media_low, "media remaining is empty"),
            (self.media_out, "media is out"),
            (self.media_invalid, "media is invalid"),
            (self.cut_error, "cutter error"),
            (self.low_power, "battery too low"),
            (self.fatal_error, "fatal error"),
        )
        for flag, reason in checks:
            if flag:
                return reason
        return None

    def job_succeeded(self, job_name: str | None = None) -> bool | None:
        """Interpret PrintJobIdAndStatus (`id: Successful|Failed`)."""
        if not self.job_status:
            return None
        parts = [part.strip() for part in self.job_status.split(":", 1)]
        if len(parts) != 2:
            return None
        job_id, result = parts
        if job_name and job_id and job_name not in (job_id, job_name):
            if job_id != job_name:
                return None
        return result.lower() == "successful"
