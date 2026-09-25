from notifier.channels.base import Channel, ChannelError


class SlackChannel(Channel):
    name = 'slack'

    def validate(self, recipient, message):
        super().validate(recipient, message)
        if not recipient.startswith(('#', '@')):
            raise ChannelError('slack: recipient must be #channel or @user')

    def deliver(self, recipient, message):
        return 'slack %s: %s' % (recipient, message)
