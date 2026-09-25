class Bus:
    """Synchronous publish/subscribe keyed by event type."""

    def __init__(self):
        self._subscribers = {}

    def subscribe(self, event_type, handler):
        self._subscribers.setdefault(event_type, []).append(handler)

    def publish(self, event_type, payload):
        """Call every handler subscribed to event_type; return how many ran."""
        handlers = list(self._subscribers.get(event_type, ()))
        for handler in handlers:
            handler(payload)
        return len(handlers)

    def event_types(self):
        return sorted(self._subscribers)
