"""Parsing list/export query parameters into an IssueQuery, and opaque cursors."""
import base64
import binascii
import json
import re

from .models import STATUSES
from .service import ValidationError

SORT_FIELDS = {'id': 'id', 'priority': 'priority', 'created': 'created_at', 'updated': 'updated_at', 'title': 'title'}
SINGLE_VALUED = ('assignee', 'q', 'sort', 'limit', 'cursor')
LIST_PARAMS = ('status', 'label', 'assignee', 'q', 'sort', 'limit', 'cursor')
EXPORT_PARAMS = ('status', 'label', 'assignee', 'q', 'sort')
DEFAULT_PAGE = 25
MAX_PAGE = 100
UNASSIGNED = 'none'


class IssueQuery(object):
    """What to fetch: filters, sort order, keyset position and page size."""

    def __init__(self, statuses=frozenset(), labels=frozenset(), assignee=None, text=None,
                 sort=(('id', False),), after=None, limit=None):
        self.statuses = frozenset(statuses)
        self.labels = frozenset(labels)
        self.assignee = assignee      # None: any; UNASSIGNED: no assignee; str: exact match
        self.text = text              # casefolded substring of the title, or None
        self.sort = tuple(sort)       # ((field, descending), ...), always ends with id
        self.after = after            # key tuple of the last item already returned, or None
        self.limit = limit            # max items, or None for all

    def fingerprint(self):
        return [sorted(self.statuses), sorted(self.labels), self.assignee, self.text,
                [[f, d] for f, d in self.sort]]

    # -- predicates used by every storage backend ---------------------------
    def matches(self, issue):
        if self.statuses and issue.status not in self.statuses:
            return False
        if not self.labels <= set(issue.labels):
            return False
        if self.assignee == UNASSIGNED:
            if issue.assignee is not None:
                return False
        elif self.assignee is not None and issue.assignee != self.assignee:
            return False
        if self.text and self.text not in issue.title.casefold():
            return False
        return True

    def key(self, issue):
        return tuple(sort_value(issue, field) for field, _ in self.sort)

    def is_after(self, key, position):
        for (field, descending), a, b in zip(self.sort, key, position):
            if a == b:
                continue
            return a < b if descending else a > b
        return False

    def order(self, issues):
        """Sort, apply the keyset position and the limit."""
        items = list(issues)
        for field, descending in reversed(self.sort):
            items.sort(key=lambda i: sort_value(i, field), reverse=descending)
        if self.after is not None:
            items = [i for i in items if self.is_after(self.key(i), self.after)]
        if self.limit is not None:
            items = items[:self.limit]
        return items


def sort_value(issue, field):
    if field == 'title':
        return issue.title.casefold()
    return getattr(issue, SORT_FIELDS[field])


def parse_sort(raw):
    fields, seen = [], set()
    for part in raw.split(','):
        descending = part.startswith('-')
        name = part[1:] if descending else part
        if name not in SORT_FIELDS or name in seen:
            raise ValidationError('invalid_sort', 'sort')
        seen.add(name)
        fields.append((name, descending))
    if 'id' not in seen:
        fields.append(('id', False))
    return tuple(fields)


def encode_cursor(query, key):
    payload = json.dumps({'f': query.fingerprint(), 'k': list(key)}, separators=(',', ':'), sort_keys=True)
    return base64.urlsafe_b64encode(payload.encode('utf-8')).decode('ascii').rstrip('=')


def decode_cursor(raw, query):
    try:
        padded = raw + '=' * (-len(raw) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode('ascii')).decode('utf-8'))
    except (ValueError, UnicodeError, binascii.Error):
        raise ValidationError('invalid_cursor', 'cursor')
    if not raw or not isinstance(data, dict) or 'f' not in data or not isinstance(data.get('k'), list):
        raise ValidationError('invalid_cursor', 'cursor')
    if data['f'] != query.fingerprint():
        raise ValidationError('cursor_mismatch', 'cursor')
    key = data['k']
    if len(key) != len(query.sort):
        raise ValidationError('invalid_cursor', 'cursor')
    for (field, _), value in zip(query.sort, key):
        expected = str if field == 'title' else int
        if isinstance(value, bool) or not isinstance(value, expected):
            raise ValidationError('invalid_cursor', 'cursor')
    return tuple(key)


def parse(params, allowed, default_sort):
    """Validate raw query params (name -> list of values).

    Returns ``(query, paginated)``; raises ValidationError(code, param).
    """
    unknown = sorted(set(params) - set(allowed))
    if unknown:
        raise ValidationError('unknown_param', unknown[0])
    for name in SINGLE_VALUED:
        if len(params.get(name, ())) > 1:
            raise ValidationError('duplicate_param', name)

    statuses = params.get('status', [])
    if any(s != 'all' and s not in STATUSES for s in statuses):
        raise ValidationError('invalid_filter', 'status')
    if 'all' in statuses and any(s != 'all' for s in statuses):
        raise ValidationError('invalid_filter', 'status')
    statuses = frozenset(s for s in statuses if s != 'all')

    labels = params.get('label', [])
    if any(not label for label in labels):
        raise ValidationError('invalid_filter', 'label')

    assignee = None
    if 'assignee' in params:
        assignee = params['assignee'][0]
        if not assignee:
            raise ValidationError('invalid_filter', 'assignee')

    text = None
    if 'q' in params and params['q'][0]:
        text = params['q'][0].casefold()

    sort = parse_sort(params['sort'][0]) if 'sort' in params else default_sort

    limit = None
    if 'limit' in params:
        raw = params['limit'][0]
        if not re.fullmatch(r'[0-9]+', raw) or not 1 <= int(raw) <= MAX_PAGE:
            raise ValidationError('invalid_limit', 'limit')
        limit = int(raw)

    query = IssueQuery(statuses, labels, assignee, text, sort)
    if 'cursor' in params:
        query.after = decode_cursor(params['cursor'][0], query)
    paginated = 'limit' in params or 'cursor' in params
    if paginated:
        query.limit = limit if limit is not None else DEFAULT_PAGE
    return query, paginated
