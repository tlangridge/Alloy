# SPEC: snapshot + replay diverges from the audit rebuild (incident LED-412)

## Goal

Find and fix the root causes of the divergence between what the ledger
serves (`AccountRepository.load`: cache / snapshot + replay) and what the
nightly audit computes (`AccountRepository.rebuild`: full replay), without
giving up snapshots and without changing the domain rules documented in
`README.md`.

## Current behavior

Bug report from the payments team (all amounts in EUR):

> The dashboard and the nightly audit disagree for a handful of accounts, and
> we have seen two related errors in the API logs. Our API servers restart
> often, so most reads are served by a repository that has just been created.
> Everything below reproduces on a clean checkout:
>
> ```python
> from ledger import *
> store, snaps = EventStore(), SnapshotStore()
> repo = AccountRepository(store, snaps, snapshot_every=5)
> svc = LedgerService(repo)
> fresh = lambda: AccountRepository(store, snaps, snapshot_every=5)
>
> # 1) balance too low after a transfer with a fee
> svc.open_account('A', 'ann'); svc.open_account('B', 'bob')
> for _ in range(3):
>     svc.deposit('A', '100.00')
> svc.transfer('A', 'B', '10.00', fee='1.50')
> svc.balance('A')              # Decimal('288.50')   (the server that wrote it)
> fresh().load('A').balance     # Decimal('287.00')   <- dashboard after a restart
> repo.rebuild('A').balance     # Decimal('288.50')   (audit)
>
> # 2) holds placed a while ago cannot be captured on another server
> svc.open_account('C', 'cat'); svc.deposit('C', '50.00')
> h = svc.place_hold('C', '20.00', expires_at=100)       # h == 1
> svc.deposit('C', '1.00'); svc.deposit('C', '1.00')
> LedgerService(fresh()).capture_hold('C', h)            # HoldNotFound: 1
>
> # 3) ...and the expiry job releases them "successfully", but the audit disagrees
> LedgerService(fresh()).release_expired_holds('C', now=200)   # ['1']  (a str?)
> fresh().load('C').available   # Decimal('52.00')
> repo.rebuild('C').available   # Decimal('32.00')
>
> # 4) the expiry job crashes for some accounts
> svc.open_account('D', 'dan'); svc.deposit('D', '50.00')
> svc.place_hold('D', '5.00', expires_at=100)
> svc.deposit('D', '1.00'); svc.deposit('D', '1.00')
> LedgerService(fresh()).place_hold('D', '5.00', expires_at=100)
> LedgerService(fresh()).release_expired_holds('D', now=200)
> # TypeError: '<' not supported between instances of 'int' and 'str'
>
> # 5) after a write conflict between two servers, the losing server shows a
> #    deposit that was rejected and misses the other server's withdrawal
> repo1 = AccountRepository(store, snaps); svc1 = LedgerService(repo1)
> repo2 = AccountRepository(store, snaps); svc2 = LedgerService(repo2)
> svc1.open_account('E', 'eve'); svc1.deposit('E', '10.00')
> acct = repo2.load('E')        # server 2 starts handling a deposit request
> svc1.withdraw('E', '3.00')    # server 1 commits a withdrawal meanwhile
> acct.deposit('5.00')
> repo2.save(acct)              # ConcurrencyError -- expected, the client retries
> svc2.balance('E')             # Decimal('15.00')  <- should be 7.00
> repo2.rebuild('E').balance    # Decimal('7.00')
> ```

The audit (`rebuild`) is correct in every case above.

## Desired behavior

The domain and persistence rules in `README.md` remain in force. In addition:

1. **Agreement.** For every sequence of `LedgerService` commands (including
   commands issued through several `LedgerService`/`AccountRepository`
   instances that share one `EventStore` and one `SnapshotStore`, and including
   saves that fail with `ConcurrencyError`), and for every `snapshot_every >= 1`:
   `load(id).describe()` of a newly created repository, `load(id).describe()`
   of every existing repository, and `LedgerService.account(id)` all equal
   `rebuild(id).describe()` of the current store contents. `balance()` and
   `available()` agree accordingly.
2. **Snapshot correctness.** A snapshot recorded with version `v` must contain
   exactly the state after events `1..v` of the stream.
3. **Snapshot frequency.** Whenever one `save` makes the stream version reach
   or cross a multiple of `snapshot_every`, at least one snapshot is written
   during that save, recorded at a version reached by that save (for example
   the multiple itself or the batch's final version), obeying rule 2.
4. **Snapshots stay in use.** A repository that has not loaded an account
   before (e.g. a newly created one) builds it from the snapshot with the
   highest version plus the events after it: its `load` makes the store return
   exactly `stream_version - latest_snapshot_version` events (observable via
   `EventStore.events_read`).
5. **Hold ids are ints everywhere.** Service methods return and accept hold
   ids as `int`; `describe()['holds']` is keyed by `int`; `HoldPlaced`,
   `HoldReleased` and `HoldCaptured` events read back from the store carry an
   `int` `hold_id`. A hold placed before a snapshot can be captured or released
   after it, through any repository. Hold ids are never reused (a new hold's id
   is one more than the highest id ever placed on the account).
6. **Expiry order.** `release_expired_holds` releases in ascending *numeric*
   hold-id order (hold 2 before hold 10) and returns the ids as `int`s.
7. **Caching.** A repository may cache aggregates, but `load` must never
   return state that includes uncommitted events or misses committed ones. In
   particular, after a save fails with `ConcurrencyError`, the next `load` of
   that account from the same repository reflects exactly the store, and a
   retried command through that repository succeeds.
8. **Conflicts write nothing.** A save based on a stale version raises
   `ConcurrencyError` and writes neither events nor snapshots.
9. **Existing snapshots.** Snapshots already written by the current code (the
   JSON format shown in `README.md`, whose hold-id keys are strings) must never
   produce wrong state after your fix: either decode them correctly or ignore
   them (fall back to an older usable snapshot or to a full replay).
10. Keep the public APIs of `EventStore`, `SnapshotStore`
    (`save(account_id, version, state)`, `latest(account_id)`,
    `versions(account_id)`), `AccountRepository`
    (`load`, `rebuild`, `save`, `exists`), `Account` (`describe()`, commands,
    `apply`) and `LedgerService` unchanged.

## Allowed paths

`ledger/`, `tests/`, `README.md`.

## Non-goals

- No migration tooling for the production snapshot table.
- No changes to event names, event fields or the event record format.
- Transfers are not made atomic across the two streams.

## Acceptance criteria

- The five reproductions above behave correctly (1: 288.50 everywhere;
  2: capture succeeds; 3/4: correct releases with int ids and agreement with
  the audit; 5: `svc2.balance('E')` is 7.00 and a retried deposit through
  `svc2` succeeds).
- Rules 1–10 hold; regression tests added under `tests/`.
- `python3 -m unittest discover -s tests -v` passes.

## Test commands

```
python3 -m unittest discover -s tests -v
```

## Handoff

For each root cause: where it was, why it only showed up in specific
sequences, and how the fix preserves rules 3, 4 and 9.
