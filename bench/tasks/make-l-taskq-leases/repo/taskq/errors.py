"""Queue errors."""


class LeaseLost(Exception):
    """The lease is no longer valid (expired, or the job was re-leased/finished)."""


class WorkerCrash(Exception):
    """Raised by ``ctx.crash()`` inside a handler to simulate the worker process dying."""
