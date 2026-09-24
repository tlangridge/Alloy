"""Append-only audit trail."""


class AuditLog:
    def __init__(self):
        self.events = []

    def record(self, user_id, action, doc_ids):
        self.events.append((user_id, action, tuple(doc_ids)))
