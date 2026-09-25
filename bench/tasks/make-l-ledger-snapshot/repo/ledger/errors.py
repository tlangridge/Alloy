"""Domain errors."""


class LedgerError(Exception):
    pass


class AccountNotFound(LedgerError):
    pass


class AccountExists(LedgerError):
    pass


class InsufficientFunds(LedgerError):
    pass


class HoldNotFound(LedgerError):
    pass


class ConcurrencyError(LedgerError):
    """A save was based on a stale stream version."""
