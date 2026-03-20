#!/usr/bin/env python3
"""
Regression tests for overtime *calculations* only (not print formatting).

Run from the payroll directory:
  python3 -m unittest test_pay_calc -v
"""

import unittest
from datetime import date, datetime, time, timedelta

import pay_calc


def _assert_hours(
    testcase: unittest.TestCase,
    summary: pay_calc.OvertimeSummary,
    *,
    total: float,
    regular: float,
    ot_15: float,
    ot_2: float,
) -> None:
    testcase.assertAlmostEqual(summary.total_hours, total, places=5)
    testcase.assertAlmostEqual(summary.regular_hours, regular, places=5)
    testcase.assertAlmostEqual(summary.overtime_1_5x, ot_15, places=5)
    testcase.assertAlmostEqual(summary.overtime_2x, ot_2, places=5)


class ApplyOvertimeRulesDailyAndWeekly(unittest.TestCase):
    """apply_overtime_rules with seventh_consecutive_days empty (normal daily + weekly pass)."""

    def test_empty_week(self) -> None:
        s = pay_calc.apply_overtime_rules({}, set())
        _assert_hours(self, s, total=0, regular=0, ot_15=0, ot_2=0)

    def test_single_day_exactly_8(self) -> None:
        d = date(2025, 1, 6)
        s = pay_calc.apply_overtime_rules({d: 8.0}, set())
        _assert_hours(self, s, total=8, regular=8, ot_15=0, ot_2=0)

    def test_single_day_10_hours_daily_ot_only(self) -> None:
        d = date(2025, 1, 6)
        s = pay_calc.apply_overtime_rules({d: 10.0}, set())
        _assert_hours(self, s, total=10, regular=8, ot_15=2, ot_2=0)

    def test_single_day_12_hours_daily_ot_boundary(self) -> None:
        d = date(2025, 1, 6)
        s = pay_calc.apply_overtime_rules({d: 12.0}, set())
        _assert_hours(self, s, total=12, regular=8, ot_15=4, ot_2=0)

    def test_single_day_14_hours_daily_double_ot(self) -> None:
        d = date(2025, 1, 6)
        s = pay_calc.apply_overtime_rules({d: 14.0}, set())
        _assert_hours(self, s, total=14, regular=8, ot_15=4, ot_2=2)

    def test_weekly_only_all_days_under_9h(self) -> None:
        # 6 x 7h = 42h, no daily OT; weekly should move 2h from regular to 1.5x
        base = date(2025, 1, 6)  # Monday
        daily = {base + timedelta(days=i): 7.0 for i in range(6)}
        s = pay_calc.apply_overtime_rules(daily, set())
        _assert_hours(self, s, total=42, regular=40, ot_15=2, ot_2=0)

    def test_five_days_10h_daily_ot_absorbs_weekly(self) -> None:
        # 5 x (8 reg + 2 OT) => 40 reg, 10 OT; week > 40 but regular not > 40
        base = date(2025, 1, 6)
        daily = {base + timedelta(days=i): 10.0 for i in range(5)}
        s = pay_calc.apply_overtime_rules(daily, set())
        _assert_hours(self, s, total=50, regular=40, ot_15=10, ot_2=0)

    def test_exactly_40_hours_no_weekly_reclass(self) -> None:
        base = date(2025, 1, 6)
        daily = {base + timedelta(days=i): 8.0 for i in range(5)}
        s = pay_calc.apply_overtime_rules(daily, set())
        _assert_hours(self, s, total=40, regular=40, ot_15=0, ot_2=0)


class ApplyOvertimeRulesSeventhDay(unittest.TestCase):
    """Seventh-day branch via explicit seventh_consecutive_days (isolated from finder)."""

    def test_seventh_day_6_hours_all_time_and_half(self) -> None:
        d7 = date(2025, 1, 8)
        s = pay_calc.apply_overtime_rules({d7: 6.0}, {d7})
        _assert_hours(self, s, total=6, regular=0, ot_15=6, ot_2=0)

    def test_seventh_day_10_hours_split_8_and_2(self) -> None:
        d7 = date(2025, 1, 8)
        s = pay_calc.apply_overtime_rules({d7: 10.0}, {d7})
        _assert_hours(self, s, total=10, regular=0, ot_15=8, ot_2=2)

    def test_six_normal_days_plus_seventh_with_weekly_interaction(self) -> None:
        # Workweek Thu 2025-01-02 .. Wed 2025-01-08; Wed is 7th consecutive calendar workday.
        days = [date(2025, 1, 2) + timedelta(days=i) for i in range(7)]
        daily = {days[i]: (6.0 if i < 6 else 10.0) for i in range(7)}
        seventh = {days[6]}
        s = pay_calc.apply_overtime_rules(daily, seventh)
        # 6 x 6h regular = 36; 7th: 8 @ 1.5 + 2 @ 2x
        _assert_hours(self, s, total=46, regular=36, ot_15=8, ot_2=2)


class FindConsecutiveWorkDays(unittest.TestCase):
    """Streak: seven calendar days in the workweek each with hours."""

    def _ww_start(self) -> datetime:
        # Thursday 2025-01-02
        return datetime(2025, 1, 2, 0, 0, 0)

    def test_all_seven_calendar_days_worked_flags_last_day(self) -> None:
        ws = self._ww_start()
        daily = {ws.date() + timedelta(days=i): 1.0 for i in range(7)}
        found = pay_calc.find_consecutive_work_days(daily, ws)
        self.assertEqual(found, {ws.date() + timedelta(days=6)})

    def test_midweek_gap_resets_no_seventh(self) -> None:
        ws = self._ww_start()
        # Thu–Sat, skip Sun, Mon–Wed: longest run 3
        d0 = ws.date()
        daily = {
            d0: 1.0,
            d0 + timedelta(days=1): 1.0,
            d0 + timedelta(days=2): 1.0,
            d0 + timedelta(days=4): 1.0,
            d0 + timedelta(days=5): 1.0,
            d0 + timedelta(days=6): 1.0,
        }
        found = pay_calc.find_consecutive_work_days(daily, ws)
        self.assertEqual(found, set())

    def test_days_outside_workweek_ignored_for_streak(self) -> None:
        ws = self._ww_start()
        d0 = ws.date()
        # Full week + a day before (should not create an 8th or change 7th)
        daily = {d0 + timedelta(days=i): 1.0 for i in range(7)}
        daily[d0 - timedelta(days=1)] = 5.0
        found = pay_calc.find_consecutive_work_days(daily, ws)
        self.assertEqual(found, {d0 + timedelta(days=6)})


class CalculateOvertimeForWorkweekIntegration(unittest.TestCase):
    """End-to-end for one workweek including find_consecutive_work_days."""

    def test_seventh_day_detected_and_applied(self) -> None:
        ws = datetime(2025, 1, 2, 0, 0, 0)
        d0 = ws.date()
        daily = {d0 + timedelta(days=i): 1.0 for i in range(7)}
        s = pay_calc.calculate_overtime_for_workweek(daily, ws)
        # Only last day is 7th; 1h at 1.5x bucket, days 0–5 are regular 1h each
        _assert_hours(self, s, total=7, regular=6, ot_15=1, ot_2=0)


class GetWorkweekKey(unittest.TestCase):
    def test_thursday_start_week(self) -> None:
        self.assertEqual(pay_calc.WORKWEEK_START_DAY, 3)
        # Monday 2025-01-06 belongs to workweek starting Thursday 2025-01-02
        mon = datetime(2025, 1, 6, 12, 0, 0)
        key = pay_calc.get_workweek_key(mon)
        self.assertEqual(key, datetime(2025, 1, 2, 0, 0, 0))


class SplitEntryByWorkday(unittest.TestCase):
    def test_cross_midnight_splits_two_days(self) -> None:
        entry = pay_calc.TimeEntry(
            "u",
            "e",
            "01/01/2025",
            "11:00 PM",
            "01/02/2025",
            "02:00 AM",
            "3:00",
        )
        segs = pay_calc._split_entry_by_workday(entry)
        self.assertEqual(len(segs), 2)
        self.assertAlmostEqual(sum(h for _, h in segs), 3.0, places=5)
        d1, h1 = segs[0]
        d2, h2 = segs[1]
        self.assertEqual(d2, d1 + timedelta(days=1))


class TimeEntryDurationFallback(unittest.TestCase):
    def test_uses_duration_when_end_not_after_start(self) -> None:
        entry = pay_calc.TimeEntry(
            "u",
            "e",
            "01/01/2025",
            "9:00 AM",
            "01/01/2025",
            "9:00 AM",
            "2:30",
        )
        self.assertAlmostEqual(entry.duration_hours, 2.5, places=5)


class OvertimeSummaryAdd(unittest.TestCase):
    def test_sums_numeric_fields(self) -> None:
        a = pay_calc.OvertimeSummary()
        a.total_hours = 10
        a.regular_hours = 8
        a.overtime_1_5x = 2
        a.overtime_2x = 0
        b = pay_calc.OvertimeSummary()
        b.total_hours = 5
        b.regular_hours = 5
        b.overtime_1_5x = 0
        b.overtime_2x = 0
        a.add(b)
        _assert_hours(self, a, total=15, regular=13, ot_15=2, ot_2=0)


if __name__ == "__main__":
    unittest.main()
