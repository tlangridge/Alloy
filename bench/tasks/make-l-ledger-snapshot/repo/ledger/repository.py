"""Loading and saving Account aggregates (snapshot + replay)."""
from .account import Account
from .errors import AccountNotFound
from .snapshots import decode_state, encode_state


class AccountRepository(object):
    def __init__(self, store, snapshots, snapshot_every=5):
        if snapshot_every < 1:
            raise ValueError('snapshot_every must be >= 1')
        self.store = store
        self.snapshots = snapshots
        self.snapshot_every = snapshot_every
        self._cache = {}  # account id -> Account (identity map; saves a replay per command)

    def load(self, account_id):
        """Latest snapshot + the events recorded after it."""
        cached = self._cache.get(account_id)
        if cached is not None and cached.version == self.store.version(account_id):
            return cached
        snap = self.snapshots.latest(account_id)
        if snap is not None:
            version, state = snap
            account = decode_state(account_id, version, state)
        else:
            account = Account(account_id)
        for _, event in self.store.read(account_id, after_version=account.version):
            account.apply(event)
        if account.version == 0:
            raise AccountNotFound(account_id)
        self._cache[account_id] = account
        return account

    def rebuild(self, account_id):
        """Full replay from the first event, ignoring snapshots (used by the audit)."""
        account = Account(account_id)
        for _, event in self.store.read(account_id):
            account.apply(event)
        if account.version == 0:
            raise AccountNotFound(account_id)
        return account

    def exists(self, account_id):
        return self.store.version(account_id) > 0

    def save(self, account):
        """Append the account's pending events as one batch; snapshot on boundaries."""
        pending = account.pending_events()
        if not pending:
            return account.version
        expected = account.version - len(pending)
        self.store.append(account.id, pending, expected)
        for offset in range(1, len(pending) + 1):
            if (expected + offset) % self.snapshot_every == 0:
                self.snapshots.save(account.id, expected + offset, encode_state(account))
        account.mark_committed()
        self._cache[account.id] = account
        return account.version
