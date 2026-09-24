from eventbus.channels import get_or_create


def install_routes(bus, routes, channels):
    """Subscribe one delivery handler per (event type -> channel name) route."""
    for event_type, channel_name in routes.items():
        channel = get_or_create(channels, channel_name)

        def deliver(payload):
            channel.deliver(event_type, payload)

        bus.subscribe(event_type, deliver)
    return channels


def install_audit(bus, event_types, audit_channel):
    """Copy every listed event type to the audit channel."""
    for event_type in event_types:
        bus.subscribe(event_type,
                      lambda payload, _type=event_type: audit_channel.deliver(_type, payload))
