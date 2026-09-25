from notifier.channels.base import Channel, ChannelError


class SmsChannel(Channel):
    name = 'sms'
    max_length = 160

    def validate(self, recipient, message):
        super().validate(recipient, message)
        digits = recipient.lstrip('+')
        if not digits.isdigit():
            raise ChannelError('sms: %r is not a phone number' % recipient)

    def deliver(self, recipient, message):
        return 'sms to %s (%d chars)' % (recipient, len(message))
