from notifier.channels.base import Channel, ChannelError


class EmailChannel(Channel):
    name = 'email'
    max_length = 100000

    def validate(self, recipient, message):
        super().validate(recipient, message)
        if '@' not in recipient:
            raise ChannelError('email: %r is not an address' % recipient)

    def deliver(self, recipient, message):
        subject = message.splitlines()[0][:78] if message else '(no subject)'
        return 'email to %s: %s' % (recipient, subject)
