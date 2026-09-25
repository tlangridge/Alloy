# notifier

Tiny CLI that sends one-off operational notifications through a pluggable
channel (email, Slack, SMS).

```
python3 -m notifier channels
python3 -m notifier send --channel slack --to '#ops' "deploy finished"
```

## Adding a channel

1. Create `notifier/channels/<name>.py` with a subclass of
   `notifier.channels.base.Channel` implementing `deliver()`.
2. Add the channel name to `CHANNEL_CHOICES` in `notifier/cli.py` so the
   `--channel` flag accepts it.

Channels are offline stubs in this repository: `deliver()` returns a receipt
string instead of talking to a real provider.

Run the tests with `python3 -m unittest discover -s tests -v`.
