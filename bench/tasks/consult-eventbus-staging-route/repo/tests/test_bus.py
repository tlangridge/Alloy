import unittest

from eventbus.bus import Bus
from eventbus.channels import Channel
from eventbus.config import DEFAULT_ROUTES, routes_for
from eventbus.routing import install_audit


class BusTests(unittest.TestCase):
    def test_publish_calls_subscribers_in_order(self):
        bus, seen = Bus(), []
        bus.subscribe('a', lambda p: seen.append(('first', p)))
        bus.subscribe('a', lambda p: seen.append(('second', p)))
        self.assertEqual(bus.publish('a', 1), 2)
        self.assertEqual(seen, [('first', 1), ('second', 1)])

    def test_publish_without_subscribers(self):
        self.assertEqual(Bus().publish('nobody.listens', {}), 0)

    def test_audit_records_event_type(self):
        bus, audit = Bus(), Channel('audit')
        install_audit(bus, ['user.created', 'user.deleted'], audit)
        bus.publish('user.created', {'id': 1})
        self.assertEqual(audit.delivered, [('user.created', {'id': 1})])

    def test_routes_for_production_is_default(self):
        self.assertEqual(routes_for('production'), DEFAULT_ROUTES)


if __name__ == '__main__':
    unittest.main()
