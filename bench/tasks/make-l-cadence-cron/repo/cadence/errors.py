"""Errors for schedule expressions."""


class CronSyntaxError(ValueError):
    """An invalid schedule expression.

    ``field`` is the field name ('minute', 'hour', 'day_of_month', 'month',
    'day_of_week') or None for whole-expression problems; ``item`` is the
    offending comma-separated item exactly as written (or None).
    """

    def __init__(self, message, field=None, item=None):
        super().__init__(message if field is None else '%s: %s (%r)' % (field, message, item))
        self.field = field
        self.item = item
