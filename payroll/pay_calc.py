#!/usr/bin/env python3
"""
California Overtime Calculator

Calculates regular and overtime hours according to California labor law (CA DLSE).
Processes Clockify time report CSV files.
"""

import csv
import argparse
from dataclasses import dataclass
from datetime import date, datetime, timedelta, time
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

# Configuration
WORKWEEK_START_DAY = 3  # 0=Monday, 1=Tuesday, 2=Wednesday, 3=Thursday, etc.
REGULAR_HOURS_CAP = 80.0


class TimeEntry:
    """Represents a single time tracking entry."""
    def __init__(self, user: str, email: str, start_date: str, start_time: str,
                 end_date: str, end_time: str, duration: str):
        self.user = user
        self.email = email
        self.start_date = start_date
        self.start_time = start_time
        self.end_date = end_date
        self.end_time = end_time
        self.duration_str = duration

        self.start_dt = self._parse_datetime(start_date, start_time)
        self.end_dt = self._parse_datetime(end_date, end_time)

        if self.start_dt and self.end_dt and self.end_dt > self.start_dt:
            self.duration_hours = (self.end_dt - self.start_dt).total_seconds() / 3600.0
        else:
            self.duration_hours = self._parse_duration(duration)

    def _parse_duration(self, duration_str: str) -> float:
        """Parse duration string (H:MM) to hours as float."""
        if not duration_str:
            return 0.0
        parts = duration_str.split(':')
        if len(parts) == 2:
            hours = int(parts[0])
            minutes = int(parts[1])
            return hours + minutes / 60.0
        return 0.0

    def _parse_datetime(self, date_str: str, time_str: str) -> datetime:
        """Parse date/time strings to datetime."""
        if not date_str or not time_str:
            return None
        try:
            return datetime.strptime(f"{date_str} {time_str}", '%m/%d/%Y %I:%M %p')
        except ValueError:
            return None


@dataclass
class OvertimeExplanation:
    """Human-readable reason for overtime hours in one workweek."""
    sort_date: Optional[date]
    message: str


class OvertimeSummary:
    """Holds overtime calculation results."""
    def __init__(self):
        self.total_hours = 0.0
        self.regular_hours = 0.0
        self.overtime_1_5x = 0.0
        self.overtime_2x = 0.0
        self.overtime_explanations: List[OvertimeExplanation] = []
    
    def add(self, other: 'OvertimeSummary'):
        """Add another summary to this one."""
        self.total_hours += other.total_hours
        self.regular_hours += other.regular_hours
        self.overtime_1_5x += other.overtime_1_5x
        self.overtime_2x += other.overtime_2x
        self.overtime_explanations.extend(other.overtime_explanations)


def _sorted_overtime_explanations(
    items: List[OvertimeExplanation],
) -> List[OvertimeExplanation]:
    """Daily rows by date; workweek-level (weekly rule) rows last."""
    return sorted(
        items,
        key=lambda e: (e.sort_date is None, e.sort_date or date.min),
    )


def parse_csv(filepath: str) -> List[TimeEntry]:
    """Read and parse Clockify CSV file."""
    entries = []
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Skip empty rows
            if not row.get('User') or not row.get('Start Date'):
                continue
            
            entry = TimeEntry(
                user=row['User'],
                email=row['Email'],
                start_date=row['Start Date'],
                start_time=row['Start Time'],
                end_date=row['End Date'],
                end_time=row['End Time'],
                duration=row['Duration (h)']
            )
            entries.append(entry)
    
    return entries


def get_workweek_key(date: datetime, start_day: int = WORKWEEK_START_DAY) -> datetime:
    """
    Determine which workweek a date belongs to.
    Returns the date of the first day (start_day) of that workweek.
    """
    # Calculate days since the start of the week
    days_since_start = (date.weekday() - start_day) % 7
    workweek_start = date - timedelta(days=days_since_start)
    return workweek_start.replace(hour=0, minute=0, second=0, microsecond=0)


def group_by_employee_and_workweek(entries: List[TimeEntry]) -> Dict[str, Dict[datetime, Dict[datetime.date, float]]]:
    """
    Organize entries by employee and workweek using Clockify report-day attribution.
    Returns: {employee_key: {workweek_start: {date: total_hours}}}

    Clockify detailed reports include entries based on the entry start date. For payroll
    summaries, keep every cross-midnight entry on its start date so the overtime rules
    are applied to the same day Clockify attributes the shift to.
    """
    grouped = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))

    for entry in entries:
        employee_key = f"{entry.user}|{entry.email}"
        if not entry.start_dt:
            continue

        segments = _entry_segments_for_clockify_report(entry)
        if not segments:
            segments = [(entry.start_dt.date(), entry.duration_hours)]

        for workday_date, hours in segments:
            workday_start = datetime.combine(workday_date, time(0, 1))
            workweek_start = get_workweek_key(workday_start)
            grouped[employee_key][workweek_start][workday_date] += hours

    return grouped


def _entry_segments_for_clockify_report(entry: TimeEntry) -> List[Tuple[datetime.date, float]]:
    """Return payroll-report day buckets, keeping cross-midnight entries on start date."""
    if not entry.start_dt:
        return []
    if entry.end_dt and entry.end_dt.date() != entry.start_dt.date():
        return [(entry.start_dt.date(), entry.duration_hours)]
    return _split_entry_by_workday(entry)


def _workday_start_for(dt: datetime) -> datetime:
    """Return the workday start boundary for a datetime (12:01am start)."""
    day_start = datetime.combine(dt.date(), time(0, 1))
    if dt < day_start:
        return day_start - timedelta(days=1)
    return day_start


def _split_entry_by_workday(entry: TimeEntry) -> List[Tuple[datetime.date, float]]:
    """
    Split a time entry across workdays.
    Workday starts at 12:01am and ends at midnight.
    Returns list of (workday_date, hours) tuples.
    """
    if not entry.start_dt or not entry.end_dt or entry.end_dt <= entry.start_dt:
        return []

    segments = []
    current = entry.start_dt

    while current < entry.end_dt:
        day_start = _workday_start_for(current)
        next_day_start = day_start + timedelta(days=1)
        segment_end = min(entry.end_dt, next_day_start)

        hours = (segment_end - current).total_seconds() / 3600.0
        if hours > 0:
            segments.append((day_start.date(), hours))

        current = segment_end

    return segments


def calculate_daily_hours(entries: List[TimeEntry]) -> Dict[datetime, float]:
    """
    Sum hours worked per day.
    Returns: {date: total_hours}
    """
    daily_hours = defaultdict(float)
    for entry in entries:
        segments = _split_entry_by_workday(entry)
        if not segments:
            if entry.start_dt:
                daily_hours[entry.start_dt.date()] += entry.duration_hours
            continue
        for workday_date, hours in segments:
            daily_hours[workday_date] += hours
    return dict(daily_hours)


def find_consecutive_work_days(daily_hours: Dict[datetime, float], 
                                workweek_start: datetime) -> Set[datetime]:
    """
    Identify which days are the 7th consecutive working day within a workweek.
    Consecutive tracking resets at workweek boundaries.
    """
    seventh_days = set()
    
    # Get all worked days in sorted order
    worked_days = sorted(daily_hours.keys())
    if not worked_days:
        return seventh_days
    
    # Only consider days within this workweek
    workweek_end = workweek_start.date() + timedelta(days=6)
    worked_days_in_week = [d for d in worked_days 
                           if workweek_start.date() <= d <= workweek_end]
    
    if not worked_days_in_week:
        return seventh_days
    
    # Track consecutive working days
    consecutive_count = 0
    current_date = workweek_start.date()
    
    # Iterate through each day in the workweek
    for i in range(7):
        check_date = workweek_start.date() + timedelta(days=i)
        
        if check_date in worked_days_in_week:
            consecutive_count += 1
            if consecutive_count == 7:
                seventh_days.add(check_date)
        else:
            consecutive_count = 0
    
    return seventh_days


def apply_overtime_rules(daily_hours: Dict[datetime, float], 
                        seventh_consecutive_days: Set[datetime]) -> OvertimeSummary:
    """
    Apply California overtime rules and return breakdown.
    
    CA Rules:
    1. Daily: 1.5x for hours 8-12, 2x for hours >12
    2. Weekly: 1.5x for hours >40 in workweek
    3. 7th consecutive day: 1.5x for first 8 hours, 2x for hours >8
    4. Employee gets the higher rate when multiple rules apply
    """
    summary = OvertimeSummary()
    
    # Track daily categorization for each day
    daily_regular = {}
    daily_ot_1_5x = {}
    daily_ot_2x = {}
    
    # First pass: Apply daily and 7th day rules
    for date, hours in daily_hours.items():
        if date in seventh_consecutive_days:
            # 7th consecutive day rules
            if hours <= 8:
                # First 8 hours are 1.5x on 7th day
                daily_regular[date] = 0.0
                daily_ot_1_5x[date] = hours
                daily_ot_2x[date] = 0.0
                if daily_ot_1_5x[date] > 0:
                    ds = date.strftime('%m/%d/%Y')
                    summary.overtime_explanations.append(
                        OvertimeExplanation(
                            date,
                            f"7th consecutive workday ({ds}): "
                            f"{daily_ot_1_5x[date]:.2f}h at 1.5x "
                            f"(no regular hours on 7th day).",
                        )
                    )
            else:
                # First 8 hours at 1.5x, rest at 2x
                daily_regular[date] = 0.0
                daily_ot_1_5x[date] = 8.0
                daily_ot_2x[date] = hours - 8.0
                ds = date.strftime('%m/%d/%Y')
                summary.overtime_explanations.append(
                    OvertimeExplanation(
                        date,
                        f"7th consecutive workday ({ds}): "
                        f"{daily_ot_1_5x[date]:.2f}h at 1.5x, "
                        f"{daily_ot_2x[date]:.2f}h at 2x "
                        f"(no regular hours on 7th day).",
                    )
                )
        else:
            # Normal daily rules
            if hours <= 8:
                daily_regular[date] = hours
                daily_ot_1_5x[date] = 0.0
                daily_ot_2x[date] = 0.0
            elif hours <= 12:
                daily_regular[date] = 8.0
                daily_ot_1_5x[date] = hours - 8.0
                daily_ot_2x[date] = 0.0
                if daily_ot_1_5x[date] > 0:
                    ds = date.strftime('%m/%d/%Y')
                    summary.overtime_explanations.append(
                        OvertimeExplanation(
                            date,
                            f"Daily overtime ({ds}): "
                            f"{daily_ot_1_5x[date]:.2f}h at 1.5x "
                            f"(worked {hours:.2f}h; CA daily OT after 8h).",
                        )
                    )
            else:
                daily_regular[date] = 8.0
                daily_ot_1_5x[date] = 4.0
                daily_ot_2x[date] = hours - 12.0
                ds = date.strftime('%m/%d/%Y')
                summary.overtime_explanations.append(
                    OvertimeExplanation(
                        date,
                        f"Daily overtime ({ds}): "
                        f"{daily_ot_1_5x[date]:.2f}h at 1.5x (hours 8–12), "
                        f"{daily_ot_2x[date]:.2f}h at 2x (beyond 12h; "
                        f"worked {hours:.2f}h total).",
                    )
                )
    
    # Calculate weekly totals
    total_hours = sum(daily_hours.values())
    total_regular = sum(daily_regular.values())
    total_ot_1_5x = sum(daily_ot_1_5x.values())
    total_ot_2x = sum(daily_ot_2x.values())
    
    # Second pass: Apply weekly overtime rule (>40 hours)
    # CA law: At most 40 hours can be regular pay in a >40 hour workweek
    # Any regular hours beyond 40 must be converted to 1.5x
    if total_hours > 40 and total_regular > 40:
        hours_to_convert = total_regular - 40
        total_regular -= hours_to_convert
        total_ot_1_5x += hours_to_convert
        summary.overtime_explanations.append(
            OvertimeExplanation(
                None,
                f"Weekly overtime: {hours_to_convert:.2f}h moved from regular to 1.5x "
                f"(workweek {total_hours:.2f}h > 40h; at most 40h may stay regular "
                f"after daily rules).",
            )
        )
    
    summary.total_hours = total_hours
    summary.regular_hours = total_regular
    summary.overtime_1_5x = total_ot_1_5x
    summary.overtime_2x = total_ot_2x
    
    return summary


def calculate_overtime_for_workweek(daily_hours: Dict[datetime.date, float],
                                    workweek_start: datetime) -> OvertimeSummary:
    """Calculate overtime for a single employee's workweek."""
    seventh_days = find_consecutive_work_days(daily_hours, workweek_start)
    return apply_overtime_rules(daily_hours, seventh_days)


def _print_overtime_breakdown(summary: OvertimeSummary, indent: str = "    ") -> None:
    if summary.overtime_1_5x <= 0 and summary.overtime_2x <= 0:
        return
    print(f"{indent}Overtime breakdown:")
    for exp in _sorted_overtime_explanations(summary.overtime_explanations):
        print(f"{indent}  - {exp.message}")


def print_summary(grouped_data: Dict[str, Dict[datetime, Dict[datetime.date, float]]]):
    """Format and print per-employee totals and overtime breakdown (no per-workweek section)."""
    for employee_key in sorted(grouped_data.keys()):
        user_name, email = employee_key.split('|')
        print(f"\nEmployee: {user_name} ({email})")
        
        workweeks = grouped_data[employee_key]
        employee_total = OvertimeSummary()
        
        for workweek_start in sorted(workweeks.keys()):
            daily_hours = workweeks[workweek_start]
            summary = calculate_overtime_for_workweek(daily_hours, workweek_start)
            employee_total.add(summary)

        apply_regular_hours_cap(employee_total)

        print(f"  Total Hours: {employee_total.total_hours:.2f}")
        print(f"  Regular Hours: {employee_total.regular_hours:.2f}")
        print(f"  Overtime (1.5x): {employee_total.overtime_1_5x:.2f}")
        print(f"  Overtime (2x): {employee_total.overtime_2x:.2f}")
        _print_overtime_breakdown(employee_total, indent="  ")
        print()


def apply_regular_hours_cap(summary: OvertimeSummary,
                            cap: float = REGULAR_HOURS_CAP) -> None:
    """Cap regular hours for the report and convert the remainder to 1.5x overtime."""
    if summary.regular_hours <= cap:
        return
    hours_to_convert = summary.regular_hours - cap
    summary.regular_hours = cap
    summary.overtime_1_5x += hours_to_convert
    summary.overtime_explanations.append(
        OvertimeExplanation(
            None,
            f"Regular-hour cap: {hours_to_convert:.2f}h moved from regular to 1.5x "
            f"(report regular hours capped at {cap:.2f}h).",
        )
    )


def main():
    """Main execution."""
    parser = argparse.ArgumentParser(
        description='Calculate California overtime from Clockify CSV reports'
    )
    parser.add_argument('csv_file', help='Path to Clockify CSV file')
    
    args = parser.parse_args()
    
    # Parse CSV
    print(f"Reading time entries from: {args.csv_file}")
    entries = parse_csv(args.csv_file)
    print(f"Loaded {len(entries)} time entries\n")
    print("=" * 80)
    
    # Group by employee and workweek
    grouped_data = group_by_employee_and_workweek(entries)
    
    # Print summary
    print_summary(grouped_data)


if __name__ == '__main__':
    main()
