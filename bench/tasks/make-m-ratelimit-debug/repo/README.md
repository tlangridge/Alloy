# throttle

Per-client rate limiting for the public API: one token bucket per client key
(`throttle.limiter.KeyedLimiter`), with limits written like `"100/min"`
(`throttle.policy`). A bucket holds up to `capacity` tokens and refills
continuously; a request costs 1 token (bulk endpoints cost more). The clock is
injected so everything is testable without sleeping.

`KeyedLimiter.allow(key, cost)` returns `Decision(allowed, retry_after,
remaining)`; the API sends `retry_after` as the `Retry-After` header and
`remaining` as `X-RateLimit-Remaining`. `sweep()` runs every minute to forget
idle clients.

Run the tests with `python3 -m unittest discover -s tests -v`.
