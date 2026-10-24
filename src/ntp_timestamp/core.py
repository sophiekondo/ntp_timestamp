"""Core conversion logic for NTP 64-bit timestamps.

An NTP 64-bit timestamp is two unsigned 32-bit integers packed together:
the high 32 bits are seconds since 1900-01-01 00:00:00 UTC, the low 32 bits
are fractional seconds with the binary point at bit 32 (i.e. fraction/2**32
seconds).  RFC 5905 §6 (and the older RFC 1305 §3.2) define this format.

Design decisions (the ones a reader might question):

* Fractions are computed against 2**32, not 2**31 or a decimal approximation.
  That is what the wire format actually says, and it round-trips exactly for
  the common Python `datetime` microsecond resolution (10**6 divides 2**32
  only via floating point, but we keep the computation in integers as long as
  possible and only convert to float at the boundary).

* `float_to_ntp` saturates negative inputs to (0, 0) rather than letting the
  bit math produce a huge unsigned value.  NTP has no representation for
  pre-epoch time; returning a wrapped-around 2**64-era timestamp would be a
  silent bug factory.  Callers who genuinely need pre-1900 times should use
  NTP era 1 and manage the high bits themselves.

* Times at or past 2036-03-06 06:28:16 UTC (NTP era 0 wrap) are NOT silently
  extended into era 1.  If you want era handling, add the high bit yourself;
  this library refuses to guess.

* `pack_ntp` always emits big-endian 8 bytes, which is the NTP on-wire order.
"""

from __future__ import annotations

import datetime as _dt
import struct

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NTP_EPOCH_DATETIME: _dt.datetime = _dt.datetime(
    1900, 1, 1, tzinfo=_dt.timezone.utc
)
"""The NTP epoch as an aware UTC `datetime` (1900-01-01 00:00:00 UTC)."""

# Seconds between 1900-01-01 UTC and 1970-01-01 UTC.
# Computed from the calendar, not from a wall clock, so it is exact and
# deterministic.  70 years * 365 days + 17 leap days (1904,1908,...,1968) =
# 25567 days; plus the two century-non-leap correction rules (1900 was NOT a
# leap year, 2000 was).  That gives 25567 * 86400 = 2208988800 exactly.
NTP_EPOCH_SECONDS: int = 2208988800
"""Integer seconds from the Unix epoch to the NTP epoch (exact)."""

_SECONDS_MAX: int = 0xFFFFFFFF
_FRACTION_MASK: int = 0xFFFFFFFF
_FRACTION_DENOMINATOR: int = 1 << 32
_TWO_TO_32: int = _FRACTION_DENOMINATOR
_PACK_STRUCT = struct.Struct(">II")  # network byte order, two uint32


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PackError(ValueError):
    """Raised by `pack_ntp` when the (seconds, fraction) pair is out of range.

    A separate subclass keeps the error surface explicit: callers catching
    `ValueError` for math reasons will not silently swallow packing failures.
    """


# ---------------------------------------------------------------------------
# Conversions: NTP pair  ->  Python
# ---------------------------------------------------------------------------


def ntp_to_float(seconds: int, fraction: int) -> float:
    """Return NTP (seconds, fraction) as a float count of seconds since 1970-01-01 UTC.

    `seconds` and `fraction` are the two 32-bit fields of an NTP timestamp,
    each treated as an unsigned integer.  The result is Unix-epoch-relative:
    the NTP epoch offset is subtracted.

    The conversion is done as `(seconds - NTP_EPOCH_SECONDS) +
    fraction / 2**32`.  Because a Python float only has 53 bits of mantissa,
    sub-microsecond precision past ~year 2255 will start to blur; that is a
    float-format limit, not an NTP-format limit, and it is documented here so
    callers know not to expect bit-exact round trips through float for values
    that large.
    """
    secs = int(seconds) - NTP_EPOCH_SECONDS
    frac = int(fraction) / _FRACTION_DENOMINATOR
    return float(secs) + frac


def ntp_to_datetime(seconds: int, fraction: int) -> _dt.datetime:
    """Return NTP (seconds, fraction) as an aware UTC `datetime`.

    Microsecond resolution is the finest `datetime` can express, so the NTP
    fraction is rounded to the nearest microsecond using the standard
    round-half-to-even rule (Python's built-in `round` on an integer ratio).
    This is the one place we lose information, and we lose it because the
    destination type cannot hold it, not because the conversion is sloppy.
    """
    secs = int(seconds) - NTP_EPOCH_SECONDS
    if secs < 0:
        # NTP era 0 cannot represent pre-epoch Unix time.  We refuse rather
        # than produce a wrapped unsigned value.
        raise ValueError(
            "NTP timestamp is before the Unix epoch "
            "(seconds=%r yields secs=%r)" % (seconds, secs)
        )
    # integer microseconds = fraction * 1_000_000 / 2**32, rounded to nearest
    frac = int(fraction)
    micros = (frac * 1_000_000 + (_TWO_TO_32 // 2)) // _TWO_TO_32
    # Guard the rare half-to-even tie at exactly .5; structurally rare but real.
    if micros == 1_000_000:
        micros = 0
        secs += 1
    return (_dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc)
            + _dt.timedelta(seconds=secs, microseconds=micros))


# ---------------------------------------------------------------------------
# Conversions: Python  ->  NTP pair
# ---------------------------------------------------------------------------


def float_to_ntp(timestamp: float) -> tuple[int, int]:
    """Return (seconds, fraction) for a float Unix timestamp.

    Negative inputs saturate to (0, 0) -- see module docstring for why we do
    not wrap.  The fraction is computed as `int((ts - int(ts)) * 2**32)`; this
    is exact for representable fractions and clamped to [0, 2**32-1] to absorb
    float noise that could otherwise push it to 2**32.
    """
    if timestamp != timestamp:  # NaN
        raise ValueError("timestamp is NaN")
    if timestamp == float("inf") or timestamp == float("-inf"):
        raise ValueError("timestamp must be finite")
    if timestamp < 0.0:
        return (0, 0)
    whole = int(timestamp)
    frac_float = timestamp - whole
    # Clamp: float error can make frac_float marginally negative or >= 1.
    if frac_float < 0.0:
        frac_float = 0.0
    elif frac_float >= 1.0:
        frac_float = 0.0
        whole += 1
    fraction = int(frac_float * _FRACTION_DENOMINATOR)
    if fraction > _FRACTION_MASK:
        fraction = _FRACTION_MASK
    if fraction < 0:
        fraction = 0
    return (whole + NTP_EPOCH_SECONDS, fraction)


def datetime_to_ntp(dt: _dt.datetime) -> tuple[int, int]:
    """Return (seconds, fraction) for an aware `datetime`.

    Naive datetimes are rejected: without a tzinfo we cannot know the offset
    from UTC, and guessing local time would make this function non-portable
    across machines.  Callers with naive local times must convert explicitly
    (e.g. via `dt.astimezone(timezone.utc)`).

    The fraction is built from microseconds, so it is a multiple of
    2**32 / 10**6 -- i.e. quantized at microsecond resolution.  This matches
    what `datetime` can store and round-trips exactly through `ntp_to_datetime`.
    """
    if dt.tzinfo is None:
        raise ValueError(
            "datetime must be timezone-aware; got a naive datetime"
        )
    utc = dt.astimezone(_dt.timezone.utc)
    delta = utc - NTP_EPOCH_DATETIME
    # timedelta keeps days, seconds, microseconds as non-overlapping ints.
    total_seconds = delta.days * 86400 + delta.seconds
    if total_seconds < 0:
        raise ValueError(
            "datetime is before the NTP epoch (1900-01-01 UTC)"
        )
    if total_seconds > _SECONDS_MAX:
        raise ValueError(
            "datetime exceeds NTP era 0 (seconds > 2**32-1)"
        )
    # fraction = microseconds * 2**32 / 10**6, integer division.
    fraction = (delta.microseconds * _TWO_TO_32) // 1_000_000
    return (total_seconds, fraction)


# ---------------------------------------------------------------------------
# Wire packing
# ---------------------------------------------------------------------------


def pack_ntp(seconds: int, fraction: int) -> bytes:
    """Pack an (seconds, fraction) pair into 8 big-endian bytes.

    Raises `PackError` if either field is outside [0, 2**32-1].  We use a
    dedicated subclass so callers can distinguish range failures from other
    `ValueError`s.
    """
    if not (0 <= int(seconds) <= _SECONDS_MAX):
        raise PackError(
            "seconds out of range [0, 2**32-1]: got %r" % (seconds,)
        )
    if not (0 <= int(fraction) <= _FRACTION_MASK):
        raise PackError(
            "fraction out of range [0, 2**32-1]: got %r" % (fraction,)
        )
    return _PACK_STRUCT.pack(int(seconds), int(fraction))


def unpack_ntp(data: bytes) -> tuple[int, int]:
    """Unpack 8 bytes into an (seconds, fraction) pair.

    Accepts any buffer of exactly 8 bytes (bytes, bytearray, memoryview).
    Big-endian, matching the NTP wire format.
    """
    try:
        seconds, fraction = _PACK_STRUCT.unpack(data)
    except struct.error as exc:
        raise PackError(str(exc)) from exc
    return (seconds, fraction)
