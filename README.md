# ntp_timestamp

`ntp_timestamp` converts between NTP 64-bit timestamps (seconds since 1900-01-01 UTC with a 32-bit fractional part) and Python `datetime` objects or Unix-epoch floats. It also packs and unpacks the 8-byte wire representation. Standard library only.

## Usage

```python
import datetime
from ntp_timestamp import (
    NTP_EPOCH_DATETIME,
    datetime_to_ntp,
    ntp_to_datetime,
    ntp_to_float,
    float_to_ntp,
    pack_ntp,
    unpack_ntp,
)

# datetime <-> NTP pair
dt = datetime.datetime(2024, 1, 1, 0, 0, 0, 123456, tzinfo=datetime.timezone.utc)
seconds, fraction = datetime_to_ntp(dt)
back = ntp_to_datetime(seconds, fraction)
assert back == dt

# float seconds since 1970 <-> NTP pair
secs, frac = float_to_ntp(1700000000.5)
assert abs(ntp_to_float(secs, frac) - 1700000000.5) < 1e-6

# wire bytes
wire = pack_ntp(seconds, fraction)
assert unpack_ntp(wire) == (seconds, fraction)
```

## Why this exists

Code that speaks NTP (SNTP clients, log parsers, telemetry decoders) needs to turn the 64-bit `(seconds, fraction)` pair into something Python can reason about without pulling in a framework. The standard library gives you `struct` and `datetime` but leaves the epoch arithmetic and the 2**32 fraction scaling to you; getting either subtly wrong is common. This library is that small, boring glue layer.

The trade-off: I have chosen Unix-epoch floats and UTC-aware `datetime` as the output types, because those are the types the rest of a Python program already understands. That means NTP era handling (the wrap at 2036-03-06 06:28:16 UTC) is explicitly out of scope -- if you need era 1, you add the high bit yourself. The alternative would be inventing an NTP-era-aware time type, which is a different library.

## Edge cases you will hit

* **Negative float input.** `float_to_ntp(-1.5)` returns `(0, 0)` rather than wrapping into a huge unsigned value. NTP has no representation for pre-epoch time; silent wraparound is worse than saturation.
* **Naive datetimes.** `datetime_to_ntp` refuses them. Without a tzinfo the UTC offset is unknown and the result would be machine-local; guesswork here is a classic portability bug. Convert explicitly first.
* **NTP era 0 wrap (2036-03-06).** Values past that boundary are not silently extended into era 1. `datetime_to_ntp` raises `ValueError` for datetimes whose NTP seconds exceed `2**32 - 1`; callers needing later times must manage the era bit themselves.
* **Microsecond quantization.** `datetime` only holds microseconds, so `ntp_to_datetime` rounds the 32-bit fraction to the nearest microsecond. `ntp_to_float` keeps full float precision, but a float only has 53 bits of mantissa, so for timestamps well past the year 2255 the sub-microsecond bits start to blur. This is a float-format limit, not an NTP-format limit.
* **Packing range.** `pack_ntp` raises `PackError` (a `ValueError` subclass) if either field is outside `[0, 2**32 - 1]`, so you can catch packing failures distinctly from other arithmetic errors.

## Running the tests

```
PYTHONPATH=src python -m unittest discover -s tests
```

## Performance

The window keeps a bounded buffer, so `push` is constant time and memory does not
grow with the length of the stream. `peak` and `trough` are linear in the window
size, which is the trade that keeps `push` cheap.

