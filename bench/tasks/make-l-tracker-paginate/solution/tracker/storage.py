"""Issue storage backends. Both must behave identically."""
import sqlite3

from .models import Issue

FIELDS = ('title', 'status', 'priority', 'labels', 'assignee', 'created_at', 'updated_at')


class MemoryIssueStore(object):
    def __init__(self):
        self._rows = {}
        self._next_id = 1

    def add(self, title, status, priority, labels, assignee, created_at):
        issue = Issue(self._next_id, title, status, priority, labels, assignee, created_at, created_at)
        self._rows[issue.id] = issue
        self._next_id += 1
        return issue

    def get(self, issue_id):
        return self._rows.get(issue_id)

    def update(self, issue_id, **changes):
        current = self._rows[issue_id]
        values = {f: getattr(current, f) for f in FIELDS}
        values.update(changes)
        issue = Issue(issue_id, **values)
        self._rows[issue_id] = issue
        return issue

    def all(self):
        return [self._rows[k] for k in sorted(self._rows)]

    def query(self, query):
        """Issues matching ``query`` in its sort order, after its keyset position, up to its limit."""
        return query.order(i for i in self._rows.values() if query.matches(i))


class SqliteIssueStore(object):
    def __init__(self, path=':memory:'):
        self.db = sqlite3.connect(path)
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS issues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                priority INTEGER NOT NULL,
                assignee TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS issue_labels (
                issue_id INTEGER NOT NULL REFERENCES issues(id),
                label TEXT NOT NULL,
                PRIMARY KEY (issue_id, label)
            );
        ''')

    def _labels(self, issue_id):
        rows = self.db.execute('SELECT label FROM issue_labels WHERE issue_id = ? ORDER BY label', (issue_id,))
        return [r[0] for r in rows]

    def _issue(self, row):
        issue_id, title, status, priority, assignee, created_at, updated_at = row
        return Issue(issue_id, title, status, priority, self._labels(issue_id), assignee, created_at, updated_at)

    def add(self, title, status, priority, labels, assignee, created_at):
        with self.db:
            cur = self.db.execute(
                'INSERT INTO issues (title, status, priority, assignee, created_at, updated_at) '
                'VALUES (?, ?, ?, ?, ?, ?)', (title, status, priority, assignee, created_at, created_at))
            issue_id = cur.lastrowid
            self.db.executemany('INSERT INTO issue_labels (issue_id, label) VALUES (?, ?)',
                                [(issue_id, label) for label in sorted(set(labels))])
        return self.get(issue_id)

    def get(self, issue_id):
        row = self.db.execute('SELECT id, title, status, priority, assignee, created_at, updated_at '
                              'FROM issues WHERE id = ?', (issue_id,)).fetchone()
        return self._issue(row) if row else None

    def update(self, issue_id, **changes):
        labels = changes.pop('labels', None)
        with self.db:
            for field, value in changes.items():
                if field not in FIELDS:
                    raise KeyError(field)
                self.db.execute('UPDATE issues SET %s = ? WHERE id = ?' % field, (value, issue_id))
            if labels is not None:
                self.db.execute('DELETE FROM issue_labels WHERE issue_id = ?', (issue_id,))
                self.db.executemany('INSERT INTO issue_labels (issue_id, label) VALUES (?, ?)',
                                    [(issue_id, label) for label in sorted(set(labels))])
        return self.get(issue_id)

    def all(self):
        rows = self.db.execute('SELECT id, title, status, priority, assignee, created_at, updated_at '
                               'FROM issues ORDER BY id').fetchall()
        return [self._issue(r) for r in rows]

    def query(self, query):
        """Same contract as MemoryIssueStore.query. Structured filters run in SQL; the
        casefold-based title filter and ordering run in Python because SQLite's
        NOCASE/LIKE only fold ASCII."""
        from .query import UNASSIGNED
        where, args = [], []
        if query.statuses:
            where.append('status IN (%s)' % ','.join('?' * len(query.statuses)))
            args.extend(sorted(query.statuses))
        if query.assignee == UNASSIGNED:
            where.append('assignee IS NULL')
        elif query.assignee is not None:
            where.append('assignee = ?')
            args.append(query.assignee)
        for label in sorted(query.labels):
            where.append('EXISTS (SELECT 1 FROM issue_labels l WHERE l.issue_id = issues.id AND l.label = ?)')
            args.append(label)
        sql = 'SELECT id, title, status, priority, assignee, created_at, updated_at FROM issues'
        if where:
            sql += ' WHERE ' + ' AND '.join(where)
        rows = self.db.execute(sql, args).fetchall()
        return query.order(i for i in (self._issue(r) for r in rows) if query.matches(i))
