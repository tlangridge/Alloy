"""Topic-based event bus."""
import collections
import logging
from dataclasses import dataclass
from typing import Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Delivery:
    """Outcome of one publish()."""
    topic: str
    delivered: int              # handlers that returned normally
    failed: Tuple[str, ...]     # names of handlers that raised, in call order


class DeliveryError(Exception):
    """Raised by publish(strict=True) after every handler ran and some failed."""

    def __init__(self, delivery):
        super().__init__('%d handler(s) failed for topic %r: %s'
                         % (len(delivery.failed), delivery.topic, ', '.join(delivery.failed)))
        self.delivery = delivery


def handler_name(handler):
    """'module.QualName' for functions and methods, repr() for anything else."""
    qualname = getattr(handler, '__qualname__', None)
    if qualname is None:
        return repr(handler)
    module = getattr(handler, '__module__', None)
    return '%s.%s' % (module, qualname) if module else qualname


class EventBus:
    def __init__(self):
        self._handlers = {}        # topic -> handlers in subscription order
        self.failures = collections.Counter()   # topic -> failed handler calls, cumulative

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

    def publish(self, topic, payload, strict=False):
        """Call every handler of topic in subscription order and report the outcome.

        One subscriber failing must never stop the others (billing must not
        miss an order because the analytics hook crashed), so any Exception
        from a handler is logged with its traceback, counted and reported in
        the returned Delivery. KeyboardInterrupt, SystemExit and other
        BaseExceptions are not caught. With strict=True a DeliveryError,
        chained to the first failure, is raised once every handler has run.
        """
        handlers = list(self._handlers.get(topic, ()))   # changes apply from the next publish
        delivered = 0
        failed = []
        first_error = None
        for handler in handlers:
            try:
                handler(topic, payload)
            except Exception as exc:
                name = handler_name(handler)
                logger.exception('event handler %s failed for topic %r', name, topic)
                self.failures[topic] += 1
                failed.append(name)
                if first_error is None:
                    first_error = exc
            else:
                delivered += 1
        delivery = Delivery(topic, delivered, tuple(failed))
        if strict and first_error is not None:
            raise DeliveryError(delivery) from first_error
        return delivery
