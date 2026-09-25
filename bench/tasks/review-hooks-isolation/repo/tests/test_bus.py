import unittest

from hooks.bus import EventBus
from hooks.signals import emit


class BusTests(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        self.calls = []

    def recorder(self, name):
        def handler(topic, payload):
            self.calls.append((name, topic, payload))
        return handler

    def test_handlers_called_in_order(self):
        a, b = self.recorder('a'), self.recorder('b')
        self.bus.subscribe('order.placed', a)
        self.bus.subscribe('order.placed', b)
        self.bus.subscribe('order.placed', a)
        self.bus.publish('order.placed', {'id': 1})
        self.assertEqual(self.calls, [('a', 'order.placed', {'id': 1}), ('b', 'order.placed', {'id': 1})])

    def test_unsubscribe(self):
        a = self.recorder('a')
        self.bus.subscribe('t', a)
        self.bus.unsubscribe('t', a)
        self.bus.unsubscribe('t', a)
        self.bus.publish('t', None)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.bus.subscribers('t'), [])

    def test_non_callable_rejected(self):
        with self.assertRaises(TypeError):
            self.bus.subscribe('t', 'nope')

    def test_emit_warns_without_subscribers(self):
        with self.assertLogs('hooks.signals', 'WARNING') as logs:
            emit(self.bus, 'nobody.listens', {})
        self.assertIn('no subscribers for nobody.listens', logs.output[0])


if __name__ == '__main__':
    unittest.main()
