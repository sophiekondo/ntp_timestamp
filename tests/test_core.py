import datetime as dt
import math
import struct
import unittest

from ntp_timestamp import (
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


class TestEpochConstants(unittest.TestCase):
    def test_epoch_datetime_is_aware_utc(self):
        self.assertEqual(NTP_EPOCH_DATETIME,
                         dt.datetime(1900, 1, 1, tzinfo=dt.timezone.utc))

    def test_epoch_seconds_value(self):
        self.assertEqual(NTP_EPOCH_SECONDS, 2208988800)


class TestNtpToFloat(unittest.TestCase):
    def test_zero_is_unix_negative_offset(self):
        # (0,0) in NTP is 1900-01-01, i.e. -NTP_EPOCH_SECONDS in Unix time.
        self.assertAlmostEqual(ntp_to_float(0, 0),
                               -float(NTP_EPOCH_SECONDS),
                               places=6)

    def test_unix_epoch_is_ntp_epoch_offset(self):
        self.assertAlmostEqual(ntp_to_float(NTP_EPOCH_SECONDS, 0),
                               0.0, places=6)

    def test_half_second_fraction(self):
        # fraction 0x80000000 == exactly 0.5s
        self.assertAlmostEqual(ntp_to_float(NTP_EPOCH_SECONDS, 0x80000000),
                               0.5, places=6)

    def test_one_full_fraction_increments_second(self):
        # fraction == 2**32 should carry into the seconds field.
        # The function treats fraction as an unsigned int; a value of 2**32
        # is mathematically 1.0s added to the float result.
        self.assertAlmostEqual(ntp_to_float(NTP_EPOCH_SECONDS, 1 << 32),
                               1.0, places=6)


class TestNtpToDatetime(unittest.TestCase):
    def test_unix_epoch(self):
        self.assertEqual(ntp_to_datetime(NTP_EPOCH_SECONDS, 0),
                         dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc))

    def test_known_instant_with_microseconds(self):
        # 2009-02-13 23:31:30.123456 UTC -- arbitrary fixed value.
        target = dt.datetime(2009, 2, 13, 23, 31, 30, 123456,
                             tzinfo=dt.timezone.utc)
        secs, frac = datetime_to_ntp(target)
        back = ntp_to_datetime(secs, frac)
        self.assertEqual(back, target)

    def test_pre_epoch_raises(self):
        with self.assertRaises(ValueError):
            ntp_to_datetime(NTP_EPOCH_SECONDS - 1, 0)

    def test_fraction_rounds_to_microsecond(self):
        # fraction corresponding to 0.5s should yield .500000
        d = ntp_to_datetime(NTP_EPOCH_SECONDS, 0x80000000)
        self.assertEqual(d.microsecond, 500000)

    def test_fraction_carry_into_seconds(self):
        # fraction that rounds up to 1_000_000 us should increment seconds.
        # microseconds = (frac * 1_000_000 + 2**31) // 2**32 == 1_000_000
        # pick frac = 2**32 - 1 (all ones) -> us = 999999 (no carry) ... so to
        # force a carry we need frac close to 2**32.  Use frac such that
        # frac*1e6 + 2**31 >= 2**32 * 1e6.  frac = 2**32 - 2**31 // 1e6 + 1 works.
        # Easier: use the carry path directly by constructing a fraction that
        # represents 0.9999995s (just above 0.5 of the last microsecond).
        # 0.9999995 * 2**32 ~ 4294966783.3 -> use 4294966784
        frac = 4294966784
        d = ntp_to_datetime(NTP_EPOCH_SECONDS, frac)
        # Should roll into the next second.
        self.assertEqual(d.second, 1)
        self.assertEqual(d.microsecond, 0)


class TestFloatToNtp(unittest.TestCase):
    def test_unix_zero(self):
        self.assertEqual(float_to_ntp(0.0), (NTP_EPOCH_SECONDS, 0))

    def test_half_second(self):
        secs, frac = float_to_ntp(0.5)
        self.assertEqual(secs, NTP_EPOCH_SECONDS)
        self.assertEqual(frac, 0x80000000)

    def test_negative_saturates_to_zero(self):
        self.assertEqual(float_to_ntp(-1.5), (0, 0))

    def test_nan_raises(self):
        with self.assertRaises(ValueError):
            float_to_ntp(float("nan"))

    def test_inf_raises(self):
        with self.assertRaises(ValueError):
            float_to_ntp(float("inf"))
        with self.assertRaises(ValueError):
            float_to_ntp(float("-inf"))

    def test_fraction_never_overflows(self):
        # A float just below an integer second should not produce fraction=2**32.
        for ts in (0.9999999, 1.9999999, 1234567890.9999999):
            _secs, frac = float_to_ntp(ts)
            self.assertLessEqual(frac, 0xFFFFFFFF)
            self.assertGreaterEqual(frac, 0)


class TestDatetimeToNtp(unittest.TestCase):
    def test_unix_epoch(self):
        self.assertEqual(
            datetime_to_ntp(dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)),
            (NTP_EPOCH_SECONDS, 0),
        )

    def test_ntp_epoch(self):
        self.assertEqual(datetime_to_ntp(NTP_EPOCH_DATETIME), (0, 0))

    def test_naive_datetime_raises(self):
        with self.assertRaises(ValueError):
            datetime_to_ntp(dt.datetime(2020, 1, 1))

    def test_non_utc_timezone_is_converted(self):
        # +02:00 at 00:00 is 1900-01-01 minus-2h? No -- 2020-01-01 00:00 +02:00
        # is 2019-12-31 22:00 UTC.  Just check it equals the UTC version.
        aware = dt.datetime(2020, 1, 1, tzinfo=dt.timezone(dt.timedelta(hours=2)))
        utc = dt.datetime(2020, 1, 1, 0, 0, tzinfo=dt.timezone.utc)
        utc -= dt.timedelta(hours=2)
        self.assertEqual(datetime_to_ntp(aware), datetime_to_ntp(utc))

    def test_pre_ntp_epoch_raises(self):
        pre = dt.datetime(1899, 12, 31, 23, 59, 59, tzinfo=dt.timezone.utc)
        with self.assertRaises(ValueError):
            datetime_to_ntp(pre)

    def test_microsecond_round_trip(self):
        target = dt.datetime(2021, 7, 4, 12, 0, 0, 500000,
                             tzinfo=dt.timezone.utc)
        secs, frac = datetime_to_ntp(target)
        back = ntp_to_datetime(secs, frac)
        self.assertEqual(back, target)


class TestPacking(unittest.TestCase):
    def test_pack_unpack_round_trip(self):
        pair = (NTP_EPOCH_SECONDS + 42, 0x12345678)
        packed = pack_ntp(*pair)
        self.assertEqual(len(packed), 8)
        self.assertEqual(unpack_ntp(packed), pair)

    def test_pack_byte_order_is_big_endian(self):
        # seconds=1, fraction=0 -> big-endian 00 00 00 01 00 00 00 00
        self.assertEqual(pack_ntp(1, 0),
                         struct.pack(">II", 1, 0))

    def test_pack_rejects_out_of_range_seconds(self):
        with self.assertRaises(PackError):
            pack_ntp(-1, 0)
        with self.assertRaises(PackError):
            pack_ntp(1 << 32, 0)

    def test_pack_rejects_out_of_range_fraction(self):
        with self.assertRaises(PackError):
            pack_ntp(0, -1)
        with self.assertRaises(PackError):
            pack_ntp(0, 1 << 32)

    def test_pack_error_is_value_error_subclass(self):
        self.assertTrue(issubclass(PackError, ValueError))

    def test_unpack_rejects_wrong_length(self):
        with self.assertRaises(PackError):
            unpack_ntp(b"\x00\x00")
        with self.assertRaises(PackError):
            unpack_ntp(b"\x00" * 9)

    def test_unpack_accepts_bytearray(self):
        packed = pack_ntp(5, 6)
        self.assertEqual(unpack_ntp(bytearray(packed)), (5, 6))

    def test_unpack_accepts_memoryview(self):
        packed = pack_ntp(7, 8)
        self.assertEqual(unpack_ntp(memoryview(packed)), (7, 8))


class TestFullRoundTrips(unittest.TestCase):
    def _round_trip_float(self, ts):
        secs, frac = float_to_ntp(ts)
        back = ntp_to_float(secs, frac)
        # Allow sub-microsecond slack from float quantization.
        self.assertLessEqual(abs(back - ts), 1e-6)

    def test_float_round_trip_zero(self):
        self._round_trip_float(0.0)

    def test_float_round_trip_large(self):
        # 2050-01-01ish -- within era 0, within float precision.
        self._round_trip_float(2524608000.0)

    def test_float_round_trip_fractional(self):
        self._round_trip_float(1234567890.125)

    def test_datetime_round_trip_whole_second(self):
        target = dt.datetime(2030, 5, 6, 7, 8, 9, tzinfo=dt.timezone.utc)
        secs, frac = datetime_to_ntp(target)
        self.assertEqual(ntp_to_datetime(secs, frac), target)

    def test_datetime_round_trip_microsecond(self):
        target = dt.datetime(2030, 5, 6, 7, 8, 9, 765432,
                             tzinfo=dt.timezone.utc)
        secs, frac = datetime_to_ntp(target)
        self.assertEqual(ntp_to_datetime(secs, frac), target)


if __name__ == "__main__":
    unittest.main()
