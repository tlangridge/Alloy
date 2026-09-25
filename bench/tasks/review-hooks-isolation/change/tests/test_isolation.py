import functools
import logging
import unittest

from hooks.bus import Delivery, DeliveryError, EventBus, handler_name
from hooks.signals import emit


def explode(topic, payload):
    raise RuntimeError('analytics down')


class Indexer:
    def __init__(self):
        self.seen = []

    def on_event(self, topic, payload):
        self.seen.append(payload)


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        self.calls = []

    def recorder(self, name):
        def handler(topic, payload):
            self.calls.append(name)
        return handler

    def test_failure_does_not_stop_later_handlers(self):
        self.bus.subscribe('order.placed', self.recorder('billing'))
        self.bus.subscribe('order.placed', explode)
        self.bus.subscribe('order.placed', self.recorder('email'))
        with self.assertLogs('hooks.bus', 'ERROR') as logs:
            delivery = self.bus.publish('order.placed', {'id': 7})
        self.assertEqual(self.calls, ['billing', 'email'])
        self.assertEqual(delivery, Delivery('order.placed', 2, ('test_isolation.explode',)))
        self.assertEqual(len(logs.records), 1)
        record = logs.records[0]
        self.assertIn('test_isolation.explode', record.getMessage())
        self.assertIn('order.placed', record.getMessage())
        self.assertIsNotNone(record.exc_info)

    def test_failures_are_counted_per_topic(self):
        self.bus.subscribe('a', explode)
        self.bus.subscribe('a', functools.partial(explode))
        self.bus.subscribe('b', explode)
        with self.assertLogs('hooks.bus', 'ERROR'):
            self.bus.publish('a', None)
            self.bus.publish('a', None)
            self.bus.publish('b', None)
        self.assertEqual(self.bus.failures, {'a': 4, 'b': 1})

    def test_strict_raises_after_all_handlers_ran(self):
        self.bus.subscribe('t', explode)
        self.bus.subscribe('t', self.recorder('after'))
        with self.assertLogs('hooks.bus', 'ERROR'):
            with self.assertRaises(DeliveryError) as ctx:
                self.bus.publish('t', None, strict=True)
        self.assertEqual(self.calls, ['after'])
        self.assertEqual(ctx.exception.delivery.delivered, 1)
        self.assertIsInstance(ctx.exception.__cause__, RuntimeError)

    def test_strict_without_failures_returns_delivery(self):
        self.bus.subscribe('t', self.recorder('x'))
        self.assertEqual(self.bus.publish('t', None, strict=True), Delivery('t', 1, ()))

    def test_keyboard_interrupt_propagates_immediately(self):
        def interrupt(topic, payload):
            raise KeyboardInterrupt
        self.bus.subscribe('t', interrupt)
        self.bus.subscribe('t', self.recorder('never'))
        with self.assertRaises(KeyboardInterrupt):
            self.bus.publish('t', None)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.bus.failures['t'], 0)

    def test_subscription_changes_apply_from_next_publish(self):
        late = self.recorder('late')

        def first(topic, payload):
            self.calls.append('first')
            self.bus.unsubscribe('t', second)
            self.bus.subscribe('t', late)

        def second(topic, payload):
            self.calls.append('second')
        self.bus.subscribe('t', first)
        self.bus.subscribe('t', second)
        self.assertEqual(self.bus.publish('t', None).delivered, 2)
        self.assertEqual(self.calls, ['first', 'second'])
        self.calls.clear()
        self.bus.publish('t', None)
        self.assertEqual(self.calls, ['first', 'late'])

    def test_handler_names(self):
        indexer = Indexer()
        self.assertEqual(handler_name(explode), 'test_isolation.explode')
        self.assertEqual(handler_name(indexer.on_event), 'test_isolation.Indexer.on_event')
        partial = functools.partial(explode)
        self.assertEqual(handler_name(partial), repr(partial))


class EmitTests(unittest.TestCase):
    def test_emit_returns_delivery_and_warns_only_without_subscribers(self):
        bus = EventBus()
        with self.assertLogs('hooks.signals', 'WARNING'):
            self.assertEqual(emit(bus, 'nobody', {}), Delivery('nobody', 0, ()))
        bus.subscribe('crashy', explode)
        logger = logging.getLogger('hooks.signals')
        with self.assertLogs('hooks.bus', 'ERROR'):
            with self.assertRaises(AssertionError):
                with self.assertLogs(logger, 'WARNING'):
                    emit(bus, 'crashy', {})


if __name__ == '__main__':
    unittest.main()
