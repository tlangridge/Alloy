# hooks

In-process publish/subscribe used by the order service: when an order is
placed, billing, e-mail, analytics and search-index subscribers are notified.

* `hooks.bus.EventBus` - subscribe handlers to topics and publish events.
* `hooks.signals.emit` - convenience wrapper used by application code.

Handlers are called as `handler(topic, payload)`.

Run the tests with `python3 -m unittest discover -s tests -v`.
