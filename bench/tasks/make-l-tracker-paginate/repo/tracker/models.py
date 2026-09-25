"""The Issue record."""

STATUSES = ('open', 'in_progress', 'closed')
PRIORITIES = (1, 2, 3, 4)  # 1 = most urgent


class Issue(object):
    __slots__ = ('id', 'title', 'status', 'priority', 'labels', 'assignee', 'created_at', 'updated_at')

    def __init__(self, id, title, status, priority, labels, assignee, created_at, updated_at):
        self.id = id
        self.title = title
        self.status = status
        self.priority = priority
        self.labels = tuple(sorted(set(labels)))
        self.assignee = assignee
        self.created_at = created_at
        self.updated_at = updated_at

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'status': self.status,
            'priority': self.priority,
            'labels': list(self.labels),
            'assignee': self.assignee,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }

    def __repr__(self):
        return 'Issue(%r)' % (self.to_dict(),)
