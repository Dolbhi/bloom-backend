from datetime import date

from django.test import SimpleTestCase

from core import bloom


class DayOfYearTests(SimpleTestCase):
    def test_round_trip(self):
        self.assertEqual(bloom.day_of_year(date(2026, 1, 1)), 1)
        self.assertEqual(bloom.day_of_year(date(2026, 12, 31)), 365)
        self.assertEqual(bloom.doy_to_mmdd(bloom.day_of_year(date(2026, 8, 15))), "08-15")

    def test_leap_day_counts_as_feb_28(self):
        self.assertEqual(bloom.day_of_year(date(2028, 2, 29)), bloom.day_of_year(date(2026, 2, 28)))


class CircularMeanTests(SimpleTestCase):
    def test_plain_average(self):
        days = [bloom.day_of_year(date(2026, 8, 1)), bloom.day_of_year(date(2026, 8, 11))]
        self.assertEqual(bloom.doy_to_mmdd(bloom.circular_mean_doy(days)), "08-06")

    def test_new_year_wrap_does_not_land_in_july(self):
        days = [bloom.day_of_year(date(2026, 12, 28)), bloom.day_of_year(date(2027, 1, 3))]
        mean = bloom.doy_to_mmdd(bloom.circular_mean_doy(days))
        self.assertIn(mean, {"12-30", "12-31", "01-01"})


class WindowTests(SimpleTestCase):
    def test_in_window_normal_and_wrapping(self):
        self.assertTrue(bloom.in_window(100, 90, 120))
        self.assertFalse(bloom.in_window(130, 90, 120))
        self.assertTrue(bloom.in_window(5, 350, 20))      # Dec -> Jan
        self.assertTrue(bloom.in_window(355, 350, 20))
        self.assertFalse(bloom.in_window(100, 350, 20))

    def test_status(self):
        self.assertEqual(bloom.window_status(100, 90, 120, 30), (bloom.BLOOMING_NOW, None))
        self.assertEqual(bloom.window_status(80, 90, 120, 30), (bloom.BLOOMING_SOON, 10))
        self.assertEqual(bloom.window_status(360, 10, 40, 30), (bloom.BLOOMING_SOON, 15))   # soon across new year
        self.assertEqual(bloom.window_status(200, 90, 120, 30), (bloom.NOT_BLOOMING, None))

    def test_full_year_sighting_is_always_blooming(self):
        status, _ = bloom.dates_status(date(2026, 1, 1), date(2026, 12, 31), date(2026, 6, 1), 30)
        self.assertEqual(status, bloom.BLOOMING_NOW)

    def test_overlap(self):
        self.assertTrue(bloom.windows_overlap(240, 270, 244, 334))
        self.assertTrue(bloom.windows_overlap(350, 20, 1, 59))    # wrapping window overlaps summer
        self.assertFalse(bloom.windows_overlap(100, 120, 244, 334))


class SeasonTests(SimpleTestCase):
    def test_hemispheres(self):
        self.assertEqual(bloom.current_season(-37.8, date(2026, 11, 22)), "spring")
        self.assertEqual(bloom.current_season(51.5, date(2026, 11, 22)), "autumn")
        self.assertEqual(bloom.season_months("summer", -37.8), (12, 1, 2))

    def test_ranges(self):
        start, end = bloom.season_doy_range("spring", -37.8)
        self.assertEqual(bloom.doy_to_mmdd(start), "09-01")
        self.assertEqual(bloom.doy_to_mmdd(end), "11-30")
        start, end = bloom.season_doy_range("summer", -37.8)
        self.assertEqual((bloom.doy_to_mmdd(start), bloom.doy_to_mmdd(end)), ("12-01", "02-28"))
        self.assertEqual(bloom.season_md_range("summer", -37.8), (1201, 231))
