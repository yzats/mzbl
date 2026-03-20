# California Overtime Calculator

A Python script that calculates regular and overtime hours according to California labor law (CA DLSE) from Clockify time tracking CSV reports.

## Features

- **California Overtime Rules Compliance**: Implements all CA DLSE overtime rules
  - Daily overtime: 1.5x for hours 8-12, 2x for hours > 12
  - Weekly overtime: 1.5x for hours > 40 in a workweek
  - 7th consecutive day: 1.5x for first 8 hours, 2x for hours > 8
  - Automatically applies the higher rate when multiple rules apply

- **Configurable Workweek**: Default Thursday-Wednesday workweek (configurable in code)

- **Detailed Output**: Per-employee summaries with workweek breakdowns showing:
  - Total hours worked
  - Regular hours
  - Overtime at 1.5x rate
  - Overtime at 2x rate
  - **Overtime breakdown**: plain-language lines for each daily, 7th-day, and weekly overtime bucket (same math as totals)
  - Employee totals across all workweeks (including merged breakdown across workweeks)

## Requirements

- Python 3.6 or higher
- Standard library only (no external dependencies)

## Usage

```bash
python3 pay_calc.py <path_to_clockify_csv>
```

### Example

```bash
python3 pay_calc.py /path/to/Clockify_Time_Report_Detailed_12_11_2025-12_24_2025.csv
```

## Input Format

The script expects a Clockify CSV export with the following columns:
- User
- Email
- Start Date (MM/DD/YYYY format)
- Start Time
- End Date
- End Time
- Duration (h) (H:MM format)

## Configuration

To change the workweek start day, edit the `WORKWEEK_START_DAY` constant in the script:

```python
WORKWEEK_START_DAY = 3  # 0=Monday, 1=Tuesday, 2=Wednesday, 3=Thursday, etc.
```

## Output Example

```
Employee: Julian Tobias (juliancat@icloud.com)
  Workweek: 12/11/2025 - 12/17/2025
    Total Hours: 15.88
    Regular Hours: 15.63
    Overtime (1.5x): 0.25
    Overtime (2x): 0.00
    Overtime breakdown:
      - Daily overtime (12/15/2025): 0.25h at 1.5x (worked 8.25h; CA daily OT after 8h).

  Workweek: 12/18/2025 - 12/24/2025
    Total Hours: 37.48
    Regular Hours: 35.08
    Overtime (1.5x): 2.40
    Overtime (2x): 0.00
    Overtime breakdown:
      - Daily overtime (12/19/2025): 2.40h at 1.5x (worked 10.40h; CA daily OT after 8h).

  EMPLOYEE TOTAL:
    Total Hours: 53.37
    Regular Hours: 50.72
    Overtime (1.5x): 2.65
    Overtime (2x): 0.00
    Overtime breakdown:
      - Daily overtime (12/15/2025): 0.25h at 1.5x (worked 8.25h; CA daily OT after 8h).
      - Daily overtime (12/19/2025): 2.40h at 1.5x (worked 10.40h; CA daily OT after 8h).
```

## California Overtime Rules Reference

Based on CA DLSE regulations from: https://www.dir.ca.gov/dlse/faq_overtime.htm

### Daily Overtime
- Hours 1-8: Regular pay
- Hours 8-12: 1.5x overtime
- Hours 12+: 2x overtime

### Weekly Overtime
- First 40 hours: Regular pay
- Hours 40+: 1.5x overtime

### 7th Consecutive Day
- First 8 hours on 7th consecutive workday: 1.5x overtime
- Hours 8+ on 7th consecutive workday: 2x overtime

**Important**: When multiple rules apply, the employee receives the higher overtime rate.

## License

MIT License
