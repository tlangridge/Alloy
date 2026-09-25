"""Static description of the five schedule fields."""

MONTH_NAMES = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
               'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}
DAY_NAMES = {'SUN': 0, 'MON': 1, 'TUE': 2, 'WED': 3, 'THU': 4, 'FRI': 5, 'SAT': 6}


class FieldSpec(object):
    def __init__(self, name, low, high, names=None, star_high=None):
        self.name = name
        self.low = low            # smallest value that may be written
        self.high = high          # largest value that may be written
        self.names = names or {}  # upper-case name -> value
        self.star_high = high if star_high is None else star_high  # upper bound used by '*' and 'V/S'


FIELDS = (
    FieldSpec('minute', 0, 59),
    FieldSpec('hour', 0, 23),
    FieldSpec('day_of_month', 1, 31),
    FieldSpec('month', 1, 12, MONTH_NAMES),
    FieldSpec('day_of_week', 0, 7, DAY_NAMES, star_high=6),   # 0 and 7 are both Sunday
)

MACROS = {
    '@yearly': '0 0 1 1 *',
    '@annually': '0 0 1 1 *',
    '@monthly': '0 0 1 * *',
    '@weekly': '0 0 * * 0',
    '@daily': '0 0 * * *',
    '@midnight': '0 0 * * *',
    '@hourly': '0 * * * *',
}
