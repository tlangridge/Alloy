"""Helpers used by application code to raise events."""
import logging

logger = logging.getLogger(__name__)


def emit(bus, topic, payload, strict=False):
    """Publish an event and warn when nobody is listening; return the Delivery."""
    delivery = bus.publish(topic, payload, strict=strict)
    if not delivery.delivered and not delivery.failed:
        logger.warning('no subscribers for %s', topic)
    return delivery
