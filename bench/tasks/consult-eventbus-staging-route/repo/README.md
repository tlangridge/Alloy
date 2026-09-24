# eventbus

In-process event bus used by the billing and account services. Each event type
is routed to exactly one delivery channel; every event is also copied to the
`audit` channel.

Routes live in `eventbus/config.py`: `DEFAULT_ROUTES` applies everywhere and
`STAGING_OVERRIDES` re-points a few event types while staging is being tested.

```
python3 -m eventbus.demo --env production
python3 -m eventbus.demo --env staging
```

The demo publishes a single `invoice.paid` event and prints every delivery each
channel recorded, one per line, as `<channel>: <event type> <payload>`.

Run the tests with `python3 -m unittest discover -s tests -v`.
