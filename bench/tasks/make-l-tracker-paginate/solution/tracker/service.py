"""Business rules for issues."""
from .models import PRIORITIES, STATUSES


class ValidationError(Exception):
    def __init__(self, code, param=None):
        super().__init__('%s (%s)' % (code, param))
        self.code = code
        self.param = param


class NotFound(Exception):
    pass


class Clock(object):
    """Injected time source (seconds). Tests use FakeClock."""

    def now(self):
        import time
        return int(time.time())


class FakeClock(Clock):
    def __init__(self, start=1000):
        self.value = start

    def now(self):
        return self.value

    def advance(self, seconds=1):
        self.value += seconds


def _check_labels(labels):
    if not isinstance(labels, (list, tuple)) or not all(isinstance(l, str) and l for l in labels):
        raise ValidationError('invalid_field', 'labels')
    return list(labels)


class IssueService(object):
    def __init__(self, store, clock=None):
        self.store = store
        self.clock = clock or Clock()

    def create(self, data):
        if not isinstance(data, dict):
            raise ValidationError('invalid_body')
        title = data.get('title')
        if not isinstance(title, str) or not title.strip():
            raise ValidationError('invalid_field', 'title')
        priority = data.get('priority', 3)
        if isinstance(priority, bool) or priority not in PRIORITIES:
            raise ValidationError('invalid_field', 'priority')
        status = data.get('status', 'open')
        if status not in STATUSES:
            raise ValidationError('invalid_field', 'status')
        labels = _check_labels(data.get('labels', []))
        assignee = data.get('assignee')
        if assignee is not None and (not isinstance(assignee, str) or not assignee or assignee == 'none'):
            raise ValidationError('invalid_field', 'assignee')
        return self.store.add(title, status, priority, labels, assignee, self.clock.now())

    def update(self, issue_id, data):
        if self.store.get(issue_id) is None:
            raise NotFound(issue_id)
        if not isinstance(data, dict) or not data:
            raise ValidationError('invalid_body')
        changes = {}
        for field, value in data.items():
            if field == 'title':
                if not isinstance(value, str) or not value.strip():
                    raise ValidationError('invalid_field', 'title')
            elif field == 'priority':
                if isinstance(value, bool) or value not in PRIORITIES:
                    raise ValidationError('invalid_field', 'priority')
            elif field == 'status':
                if value not in STATUSES:
                    raise ValidationError('invalid_field', 'status')
            elif field == 'labels':
                value = _check_labels(value)
            elif field == 'assignee':
                if value is not None and (not isinstance(value, str) or not value or value == 'none'):
                    raise ValidationError('invalid_field', 'assignee')
            else:
                raise ValidationError('invalid_field', field)
            changes[field] = value
        changes['updated_at'] = self.clock.now()
        return self.store.update(issue_id, **changes)

    def search(self, query):
        """Return ``(issues, has_more)`` for an IssueQuery."""
        if query.limit is None:
            return self.store.query(query), False
        wanted = query.limit
        query.limit = wanted + 1
        try:
            items = self.store.query(query)
        finally:
            query.limit = wanted
        return items[:wanted], len(items) > wanted

    def get(self, issue_id):
        issue = self.store.get(issue_id)
        if issue is None:
            raise NotFound(issue_id)
        return issue
