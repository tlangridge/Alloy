# ledger

Event-sourced customer ledger. Every change to an account is an immutable
event appended to the account's stream in the `EventStore`; the current state
of an `Account` is the left fold of its events (`Account.apply`).

```
LedgerService  ->  AccountRepository  ->  EventStore     (events, JSON text)
   (commands)        load/save/rebuild ->  SnapshotStore  (state every N versions)
                                       ->  Account         (aggregate: commands + apply)
```

## Domain rules

- Amounts are `Decimal` with two decimal places; `money.amount()` accepts
  `str`, `int` or `Decimal` (not `float`/`bool`) and requires a positive value
  (fees may be zero).
- `available = balance - sum(outstanding hold amounts)`.
- `withdraw`, `place_hold` and `transfer` (amount + fee) require enough
  *available* funds, otherwise `InsufficientFunds`.
- Hold ids are per-account positive integers starting at 1 and incremented for
  every hold placed; they are never reused. Hold events carry the id as an
  `int`, and the service takes and returns ids as `int`.
- `capture_hold` debits the held amount from the balance; `release_hold` just
  removes the hold. Unknown (or already finished) holds raise `HoldNotFound`.
- `release_expired_holds(account_id, now)` releases every hold whose
  `expires_at <= now` in ascending hold-id order, as one batch of
  `HoldReleased` events, and returns the released ids in that order.
- `transfer(source, target, amount, fee)` appends `TransferSent` followed by
  `FeeCharged` (only when `fee > 0`) to the source stream as **one batch**, and
  `TransferReceived` to the target stream.
- Opening an existing account raises `AccountExists`; any operation on an
  unknown account raises `AccountNotFound`.

## Persistence rules

- Stream versions are 1-based; a stream's version is its number of events.
  `EventStore.append(stream, events, expected_version)` is atomic and raises
  `ConcurrencyError` when the stream is not at `expected_version`.
- `EventStore.events_read` counts the events returned by `read()`.
- `AccountRepository.save` appends an account's pending events as one batch.
  Whenever a save makes the stream version reach or cross a multiple of
  `snapshot_every`, a snapshot of the account state is written.
- `AccountRepository.load` starts from the latest snapshot (highest version)
  and replays only the events after it. `AccountRepository.rebuild` replays
  the whole stream and is what the nightly audit uses. Both must always agree.

Snapshot state (as stored, JSON text):

```json
{"balance": "52.00", "holds": {"1": {"amount": "20.00", "expires_at": 100}},
 "next_hold_id": 2, "opened": true, "owner": "cat"}
```

## Tests

```
python3 -m unittest discover -s tests -v
```
