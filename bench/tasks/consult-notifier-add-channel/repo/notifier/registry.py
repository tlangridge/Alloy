"""Maps channel names to channel classes."""
from notifier.channels.email import EmailChannel
from notifier.channels.slack import SlackChannel
from notifier.channels.sms import SmsChannel

_CHANNELS = {
    'email': EmailChannel,
    'slack': SlackChannel,
    'sms': SmsChannel,
}


def names():
    """All channel names the CLI accepts, sorted."""
    return sorted(_CHANNELS)


def create(name, **options):
    try:
        cls = _CHANNELS[name]
    except KeyError:
        raise ValueError('unknown channel %r (known: %s)' % (name, ', '.join(names()))) from None
    return cls(**options)
