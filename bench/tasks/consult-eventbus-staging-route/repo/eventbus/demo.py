"""Publish one invoice.paid event and show where it was delivered."""
import argparse
import sys

from eventbus.bus import Bus
from eventbus.channels import Channel
from eventbus.config import routes_for
from eventbus.routing import install_audit, install_routes


def run(env):
    bus = Bus()
    routes = routes_for(env)
    channels = install_routes(bus, routes, {})
    audit = Channel('audit')
    install_audit(bus, list(routes), audit)
    bus.publish('invoice.paid', {'invoice': 'INV-1042', 'amount': '120.00'})
    lines = []
    for name in sorted(channels):
        for event_type, payload in channels[name].delivered:
            lines.append('%s: %s %s' % (name, event_type, payload))
    for event_type, payload in audit.delivered:
        lines.append('audit: %s %s' % (event_type, payload))
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(prog='eventbus.demo')
    parser.add_argument('--env', default='production', choices=['production', 'staging'])
    args = parser.parse_args(argv)
    for line in run(args.env):
        print(line)
    return 0


if __name__ == '__main__':
    sys.exit(main())
