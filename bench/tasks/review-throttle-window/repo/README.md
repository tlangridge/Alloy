# throttle

Per-key request rate limiting for the public API gateway.

Clocks are injected: a limiter takes a `clock()` callable returning integer
milliseconds from a monotonic source (the gateway passes
`lambda: time.monotonic_ns() // 1_000_000`), which keeps all arithmetic exact.

Run the tests with `python3 -m unittest discover -s tests -v`.
