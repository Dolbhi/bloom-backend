"""
Date maths for bloom windows (features F2 filters and F9 prediction).

Bloom windows repeat every year, so the year is ignored: a date becomes a day-of-year
(1..365) or a month-day number (MMDD, e.g. 15 Aug = 815). Windows can wrap the new year
(Dec -> Jan), so "is X inside the window" is a circular check, and averages are circular
(days treated as angles) so a Dec 28 + Jan 3 average lands on Dec 31, not in July.
"""
import math
from datetime import date, timedelta

from django.db.models import DurationField, ExpressionWrapper, F, Q
from django.db.models.functions import ExtractDay, ExtractMonth

YEAR_DAYS = 365
_BASE_YEAR = 2025   # any non-leap year, used to turn day-of-year back into a month and day

SEASONS = ("spring", "summer", "autumn", "winter")
_NORTH_MONTHS = {"spring": (3, 4, 5), "summer": (6, 7, 8), "autumn": (9, 10, 11), "winter": (12, 1, 2)}
_SOUTH_MONTHS = {"spring": (9, 10, 11), "summer": (12, 1, 2), "autumn": (3, 4, 5), "winter": (6, 7, 8)}

BLOOMING_NOW = "blooming_now"
BLOOMING_SOON = "blooming_soon"
NOT_BLOOMING = "not_blooming"


# --- Day of year ------------------------------------------------------------

def day_of_year(d):
    """1..365. 29 Feb counts as 28 Feb."""
    day = 28 if (d.month == 2 and d.day == 29) else d.day
    return date(_BASE_YEAR, d.month, day).timetuple().tm_yday


def doy_to_date(doy):
    return date(_BASE_YEAR, 1, 1) + timedelta(days=(doy - 1) % YEAR_DAYS)


def doy_to_mmdd(doy):
    return doy_to_date(doy).strftime("%m-%d")


def circular_mean_doy(days):
    """Average of days-of-year on a circle. Returns 1..365."""
    angles = [2 * math.pi * (d - 1) / YEAR_DAYS for d in days]
    s = sum(math.sin(a) for a in angles)
    c = sum(math.cos(a) for a in angles)
    mean = math.atan2(s, c) % (2 * math.pi)
    return round(mean * YEAR_DAYS / (2 * math.pi)) % YEAR_DAYS + 1


def in_window(doy, start, end):
    """Is doy inside [start, end] on the year circle (window may wrap past 31 Dec)?"""
    if start <= end:
        return start <= doy <= end
    return doy >= start or doy <= end


def days_until(from_doy, to_doy):
    return (to_doy - from_doy) % YEAR_DAYS


def windows_overlap(a_start, a_end, b_start, b_end):
    return in_window(a_start, b_start, b_end) or in_window(b_start, a_start, a_end)


def window_status(today_doy, start, end, soon_days):
    """(status, starts_in_days). starts_in_days is only set for blooming_soon."""
    if in_window(today_doy, start, end):
        return BLOOMING_NOW, None
    wait = days_until(today_doy, start)
    if wait <= soon_days:
        return BLOOMING_SOON, wait
    return NOT_BLOOMING, None


def dates_status(bloom_start, bloom_end, today, soon_days):
    """Status of one sighting's own window (used for map pins)."""
    if (bloom_end - bloom_start).days >= YEAR_DAYS - 1:
        return BLOOMING_NOW, None
    return window_status(day_of_year(today), day_of_year(bloom_start), day_of_year(bloom_end), soon_days)


def part_of_month(d):
    return "early" if d.day <= 10 else ("mid" if d.day <= 20 else "late")


def describe_doy(doy):
    d = doy_to_date(doy)
    return f"{part_of_month(d)} {d:%b}"


# --- Seasons ----------------------------------------------------------------

def hemisphere(lat):
    return "southern" if lat < 0 else "northern"


def season_months(season, lat):
    table = _SOUTH_MONTHS if lat < 0 else _NORTH_MONTHS
    return table[season]


def current_season(lat, today):
    table = _SOUTH_MONTHS if lat < 0 else _NORTH_MONTHS
    return next(name for name, months in table.items() if today.month in months)


def season_doy_range(season, lat):
    months = season_months(season, lat)
    first = date(_BASE_YEAR, months[0], 1)
    last_month = months[-1]
    next_month = date(_BASE_YEAR + (last_month == 12), last_month % 12 + 1, 1)
    last = next_month - timedelta(days=1)
    return day_of_year(first), day_of_year(last)


def season_md_range(season, lat):
    """Season as MMDD numbers, e.g. southern spring -> (901, 1131). 31 works as 'end of any month'."""
    months = season_months(season, lat)
    return months[0] * 100 + 1, months[-1] * 100 + 31


# --- Database filters -------------------------------------------------------
# Same circular logic, but as SQL so the map can filter thousands of rows in Postgres.

def annotate_window(queryset):
    """Adds start_md, end_md (MMDD ints) and span (bloom_end - bloom_start) to a Submission queryset."""
    return queryset.annotate(
        start_md=ExtractMonth("bloom_start") * 100 + ExtractDay("bloom_start"),
        end_md=ExtractMonth("bloom_end") * 100 + ExtractDay("bloom_end"),
        span=ExpressionWrapper(F("bloom_end") - F("bloom_start"), output_field=DurationField()),
    )


def md(d):
    return d.month * 100 + d.day


def md_in_window_q(value):
    """Q: the MMDD `value` falls inside the row's bloom window. Needs annotate_window()."""
    full_year = Q(span__gte=timedelta(days=YEAR_DAYS - 1))
    normal = Q(start_md__lte=F("end_md")) & Q(start_md__lte=value, end_md__gte=value)
    wraps = Q(start_md__gt=F("end_md")) & (Q(start_md__lte=value) | Q(end_md__gte=value))
    return full_year | normal | wraps


def window_overlaps_md_range_q(start, end):
    """Q: the row's bloom window overlaps the MMDD range [start, end]. Needs annotate_window()."""
    if start <= end:
        row_starts_inside = Q(start_md__gte=start, start_md__lte=end)
    else:
        row_starts_inside = Q(start_md__gte=start) | Q(start_md__lte=end)
    return row_starts_inside | md_in_window_q(start)
