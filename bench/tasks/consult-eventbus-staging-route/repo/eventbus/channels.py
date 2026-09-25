class Channel:
    """A delivery target. Deliveries are recorded instead of sent (offline build)."""

    def __init__(self, name):
        self.name = name
        self.delivered = []

    def deliver(self, event_type, payload):
        self.delivered.append((event_type, dict(payload)))

    def __repr__(self):
        return 'Channel(%r, %d deliveries)' % (self.name, len(self.delivered))


def get_or_create(channels, name):
    """Return channels[name], creating the Channel on first use."""
    if name not in channels:
        channels[name] = Channel(name)
    return channels[name]
