"""Helpers used by application code to raise events."""
import logging

logger = logging.getLogger(__name__)


def emit(bus, topic, payload):
    """Publish an event and warn when nobody is listening."""
    called = bus.publish(topic, payload)
    if not called:
        logger.warning('no subscribers for %s', topic)
    return called
