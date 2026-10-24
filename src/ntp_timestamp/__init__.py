"""ntp_timestamp: convert between NTP 64-bit timestamps and Python datetime/float.

Public surface:
    NTP_EPOCH_DATETIME  -- datetime at the NTP epoch (1900-01-01 00:00:00 UTC)
    NTP_EPOCH_SECONDS   -- same epoch as float seconds since Unix epoch
    ntp_to_float
    ntp_to_datetime
    float_to_ntp
    datetime_to_ntp
    pack_ntp
    unpack_ntp
    PackError

All conversion semantics live in core.py; this module re-exports the names above
so callers can write `from ntp_timestamp import ntp_to_float` without reaching
into submodules.
"""

from .core import (
    NTP_EPOCH_DATETIME,
    NTP_EPOCH_SECONDS,
    PackError,
    datetime_to_ntp,
    float_to_ntp,
    ntp_to_datetime,
    ntp_to_float,
    pack_ntp,
    unpack_ntp,
)

__all__ = [
    "NTP_EPOCH_DATETIME",
    "NTP_EPOCH_SECONDS",
    "PackError",
    "datetime_to_ntp",
    "float_to_ntp",
    "ntp_to_datetime",
    "ntp_to_float",
    "pack_ntp",
    "unpack_ntp",
]
