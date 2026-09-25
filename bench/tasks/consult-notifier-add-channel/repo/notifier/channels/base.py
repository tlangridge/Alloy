class ChannelError(Exception):
    """Raised when a channel cannot deliver a message."""


class Channel:
    """Base class for notification channels.

    Subclasses set ``name`` and implement ``deliver(recipient, message)``,
    returning a short receipt string.
    """

    name = 'base'
    max_length = 4000

    def __init__(self, **options):
        self.options = options

    def validate(self, recipient, message):
        if not recipient:
            raise ChannelError('%s: recipient is required' % self.name)
        if len(message) > self.max_length:
            raise ChannelError('%s: message longer than %d characters' % (self.name, self.max_length))

    def send(self, recipient, message):
        self.validate(recipient, message)
        return self.deliver(recipient, message)

    def deliver(self, recipient, message):  # pragma: no cover - abstract
        raise NotImplementedError
