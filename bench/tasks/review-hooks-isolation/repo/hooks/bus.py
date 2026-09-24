"""Topic-based event bus."""
import logging

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self):
        self._handlers = {}        # topic -> handlers in subscription order

    def subscribe(self, topic, handler):
        """Register handler(topic, payload) for topic; subscribing twice is a no-op."""
        if not callable(handler):
            raise TypeError('handler must be callable')
        handlers = self._handlers.setdefault(topic, [])
        if handler not in handlers:
            handlers.append(handler)

    def unsubscribe(self, topic, handler):
        """Remove a handler; unknown handlers are ignored."""
        handlers = self._handlers.get(topic)
        if handlers and handler in handlers:
            handlers.remove(handler)
            if not handlers:
                del self._handlers[topic]

    def subscribers(self, topic):
        return list(self._handlers.get(topic, ()))

    def publish(self, topic, payload):
        """Call every handler of topic in subscription order; return how many ran."""
        count = 0
        for handler in self._handlers.get(topic, []):
            handler(topic, payload)
            count += 1
        return count
