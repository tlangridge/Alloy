import random
import unittest
from decimal import Decimal

from ledger import (AccountNotFound, AccountRepository, ConcurrencyError, EventStore, HoldNotFound,
                    InsufficientFunds, LedgerService, SnapshotStore)
from ledger.events import HoldCaptured, HoldPlaced, HoldReleased


class World(object):
    def __init__(self, every=5):
        self.every = every
        self.store, self.snaps = EventStore(), SnapshotStore()
        self.repo = AccountRepository(self.store, self.snaps, snapshot_every=every)
        self.svc = LedgerService(self.repo)

    def fresh(self):
        return AccountRepository(self.store, self.snaps, snapshot_every=self.every)

    def fresh_svc(self):
        return LedgerService(self.fresh())

    def truth(self, account_id):
        return self.fresh().rebuild(account_id).describe()


class Base(unittest.TestCase):
    def assertAgrees(self, world, account_id, *repos):
        truth = world.truth(account_id)
        self.assertEqual(world.fresh().load(account_id).describe(), truth, 'fresh repository load differs')
        for repo in repos + (world.repo,):
            self.assertEqual(repo.load(account_id).describe(), truth, 'existing repository load differs')


class ReproTests(Base):
    def test_repro1_fee_batch_straddling_snapshot(self):
        w = World(5)
        w.svc.open_account('A', 'ann')
        w.svc.open_account('B', 'bob')
        for _ in range(3):
            w.svc.deposit('A', '100.00')
        w.svc.transfer('A', 'B', '10.00', fee='1.50')
        self.assertEqual(w.fresh().load('A').balance, Decimal('288.50'))
        self.assertEqual(w.svc.balance('A'), Decimal('288.50'))
        self.assertAgrees(w, 'A')
        self.assertAgrees(w, 'B')

    def _hold_world(self):
        w = World(5)
        w.svc.open_account('C', 'cat')
        w.svc.deposit('C', '50.00')
        h = w.svc.place_hold('C', '20.00', expires_at=100)
        w.svc.deposit('C', '1.00')
        w.svc.deposit('C', '1.00')
        return w, h

    def test_repro2_capture_after_snapshot_on_fresh_repository(self):
        w, h = self._hold_world()
        self.assertEqual(h, 1)
        w.fresh_svc().capture_hold('C', h)
        self.assertEqual(w.fresh().load('C').balance, Decimal('32.00'))
        self.assertEqual(w.fresh().load('C').available, Decimal('32.00'))
        self.assertAgrees(w, 'C')
        with self.assertRaises(HoldNotFound):
            w.fresh_svc().capture_hold('C', h)

    def test_repro3_release_after_snapshot_agrees_with_audit(self):
        w, h = self._hold_world()
        released = w.fresh_svc().release_expired_holds('C', now=200)
        self.assertEqual(released, [1])
        self.assertIs(type(released[0]), int)
        self.assertEqual(w.fresh().load('C').available, Decimal('52.00'))
        self.assertEqual(w.repo.rebuild('C').available, Decimal('52.00'))
        self.assertAgrees(w, 'C')

    def test_repro4_holds_before_and_after_snapshot(self):
        w = World(5)
        w.svc.open_account('D', 'dan')
        w.svc.deposit('D', '50.00')
        w.svc.place_hold('D', '5.00', expires_at=100)
        w.svc.deposit('D', '1.00')
        w.svc.deposit('D', '1.00')
        h2 = w.fresh_svc().place_hold('D', '5.00', expires_at=100)
        self.assertEqual(h2, 2)
        self.assertEqual(w.fresh_svc().release_expired_holds('D', now=200), [1, 2])
        self.assertEqual(w.truth('D')['holds'], {})
        self.assertAgrees(w, 'D')

    def test_repro5_conflict_does_not_leave_phantom_state(self):
        w = World(5)
        repo1, repo2 = w.fresh(), w.fresh()
        svc1, svc2 = LedgerService(repo1), LedgerService(repo2)
        svc1.open_account('E', 'eve')
        svc1.deposit('E', '10.00')
        acct = repo2.load('E')
        svc1.withdraw('E', '3.00')
        acct.deposit('5.00')
        with self.assertRaises(ConcurrencyError):
            repo2.save(acct)
        self.assertEqual(svc2.balance('E'), Decimal('7.00'))
        svc2.deposit('E', '5.00')  # the client's retry
        self.assertEqual(svc2.balance('E'), Decimal('12.00'))
        self.assertEqual(svc1.balance('E'), Decimal('12.00'))
        self.assertAgrees(w, 'E', repo1, repo2)


class HoldIdTests(Base):
    def test_release_order_is_numeric_across_snapshots(self):
        w = World(5)
        w.svc.open_account('H', 'hal')
        w.svc.deposit('H', '1000.00')
        ids = []
        for i in range(12):
            svc = w.fresh_svc() if i % 2 else w.svc
            ids.append(svc.place_hold('H', '1.00', expires_at=10))
        self.assertEqual(ids, list(range(1, 13)))
        before = w.store.version('H')
        released = w.fresh_svc().release_expired_holds('H', now=10)
        self.assertEqual(released, list(range(1, 13)))
        events = [e for _, e in w.store.read('H', after_version=before)]
        self.assertEqual([type(e) for e in events], [HoldReleased] * 12)
        self.assertEqual([e.hold_id for e in events], list(range(1, 13)))
        self.assertTrue(all(type(e.hold_id) is int for e in events))
        self.assertAgrees(w, 'H')

    def test_hold_events_and_describe_use_int_ids(self):
        w = World(3)
        w.svc.open_account('I', 'ivy')
        w.svc.deposit('I', '100.00')
        w.svc.place_hold('I', '10.00', expires_at=5)
        w.svc.place_hold('I', '10.00', expires_at=50)
        w.svc.deposit('I', '1.00')
        s = w.fresh_svc()
        s.capture_hold('I', 1)
        s.release_hold('I', 2)
        for _, event in w.store.read('I'):
            if isinstance(event, (HoldPlaced, HoldReleased, HoldCaptured)):
                self.assertIs(type(event.hold_id), int, event)
        w.fresh_svc().place_hold('I', '1.00', expires_at=1)
        holds = w.fresh().load('I').describe()['holds']
        self.assertEqual(list(holds), [3])
        self.assertIs(type(list(holds)[0]), int)

    def test_hold_ids_never_reused_after_snapshot(self):
        w = World(4)
        w.svc.open_account('J', 'jo')
        w.svc.deposit('J', '100.00')
        w.svc.place_hold('J', '1.00', expires_at=1)
        w.svc.place_hold('J', '1.00', expires_at=1)   # version 4 -> snapshot
        w.fresh_svc().release_hold('J', 2)
        w.fresh_svc().capture_hold('J', 1)
        self.assertEqual(w.fresh_svc().place_hold('J', '1.00', expires_at=1), 3)
        self.assertEqual(w.fresh().load('J').describe()['next_hold_id'], 4)
        self.assertAgrees(w, 'J')


class SnapshotRuleTests(Base):
    def test_snapshots_keep_being_used(self):
        w = World(5)
        w.svc.open_account('K', 'kim')
        for _ in range(22):
            w.svc.deposit('K', '1.00')
        versions = w.snaps.versions('K')
        self.assertTrue(versions and max(versions) >= 20, versions)
        latest = max(versions)
        before = w.store.events_read
        account = w.fresh().load('K')
        self.assertEqual(w.store.events_read - before, 23 - latest)
        self.assertEqual(account.balance, Decimal('22.00'))

    def test_snapshot_written_when_batch_crosses_boundary(self):
        w = World(5)
        w.svc.open_account('A', 'ann')
        w.svc.open_account('B', 'bob')
        for _ in range(3):
            w.svc.deposit('A', '10.00')
        w.svc.transfer('A', 'B', '1.00', fee='0.50')   # versions 5 and 6
        versions = w.snaps.versions('A')
        self.assertTrue(any(v in (5, 6) for v in versions), versions)
        latest = max(versions)
        before = w.store.events_read
        self.assertEqual(w.fresh().load('A').balance, Decimal('28.50'))
        self.assertEqual(w.store.events_read - before, 6 - latest)

    def test_every_snapshot_is_exact_when_it_is_the_latest(self):
        for every in (1, 2, 3):
            w = World(every)
            w.svc.open_account('A', 'ann')
            w.svc.open_account('B', 'bob')
            w.svc.deposit('A', '50.00')
            for i in range(6):
                w.svc.transfer('A', 'B', '1.00', fee='0.25')
                self.assertAgrees(w, 'A')
                w.svc.place_hold('A', '1.00', expires_at=i)
                self.assertAgrees(w, 'A')
                w.fresh_svc().release_expired_holds('A', now=i)
                self.assertAgrees(w, 'A')
            self.assertAgrees(w, 'B')

    def test_conflicting_save_writes_nothing(self):
        w = World(5)
        w.svc.open_account('A', 'ann')
        for _ in range(3):
            w.svc.deposit('A', '10.00')
        stale = w.fresh().load('A')          # version 4
        w.fresh_svc().deposit('A', '1.00')   # version 5 (snapshot)
        snaps_before = w.snaps.versions('A')
        stale.send_transfer('B', '1.00', '0.50')
        with self.assertRaises(ConcurrencyError):
            w.fresh().save(stale)
        self.assertEqual(w.store.version('A'), 5)
        self.assertEqual(w.snaps.versions('A'), snaps_before)
        self.assertAgrees(w, 'A')

    def test_legacy_snapshot_with_string_keys(self):
        w = World(1000)
        w.svc.open_account('C', 'cat')
        w.svc.deposit('C', '50.00')
        w.svc.place_hold('C', '20.00', expires_at=100)
        w.svc.deposit('C', '1.00')
        w.svc.deposit('C', '1.00')
        w.svc.deposit('C', '2.00')
        # what the code before the fix stored at version 5 (JSON turns int keys into strings)
        w.snaps.save('C', 5, {'balance': '52.00', 'holds': {'1': {'amount': '20.00', 'expires_at': 100}},
                              'next_hold_id': 2, 'opened': True, 'owner': 'cat'})
        self.assertAgrees(w, 'C')
        s = w.fresh_svc()
        s.capture_hold('C', 1)
        self.assertEqual(w.fresh().load('C').balance, Decimal('34.00'))
        self.assertEqual(w.fresh_svc().place_hold('C', '1.00', expires_at=1), 2)
        self.assertAgrees(w, 'C')


class MoreSnapshotTests(Base):
    def test_every_1_batch_loads_from_final_state(self):
        w = World(1)
        w.svc.open_account('A', 'ann')
        w.svc.open_account('B', 'bob')
        w.svc.deposit('A', '9.00')
        w.svc.transfer('A', 'B', '2.00', fee='0.10')
        self.assertIn(4, w.snaps.versions('A'))
        before = w.store.events_read
        self.assertEqual(w.fresh().load('A').balance, Decimal('6.90'))
        self.assertEqual(w.store.events_read - before, 0)
        self.assertAgrees(w, 'A')

    def test_expiry_job_from_writer_and_fresh_repositories(self):
        w = World(3)
        w.svc.open_account('A', 'ann')
        w.svc.deposit('A', '30.00')
        for expires in (5, 1, 3, 9, 2):
            w.svc.place_hold('A', '1.00', expires_at=expires)
        self.assertEqual(w.fresh_svc().release_expired_holds('A', now=2), [2, 5])
        self.assertEqual(w.svc.release_expired_holds('A', now=5), [1, 3])
        self.assertEqual(sorted(w.fresh().load('A').describe()['holds']), [4])
        self.assertAgrees(w, 'A')


class CacheTests(Base):
    def test_repeated_conflicts_then_retry(self):
        w = World(2)
        repo1, repo2 = w.fresh(), w.fresh()
        svc1, svc2 = LedgerService(repo1), LedgerService(repo2)
        svc1.open_account('A', 'ann')
        svc1.deposit('A', '50.00')
        for i in range(3):
            stale = repo2.load('A')
            svc1.withdraw('A', '1.00')
            stale.withdraw('2.00')
            with self.assertRaises(ConcurrencyError):
                repo2.save(stale)
            self.assertEqual(svc2.balance('A'), Decimal('50.00') - (i + 1))
        svc2.withdraw('A', '2.00')
        self.assertEqual(svc1.balance('A'), Decimal('45.00'))
        self.assertAgrees(w, 'A', repo1, repo2)

    def test_unsaved_changes_are_never_served(self):
        w = World(5)
        w.svc.open_account('A', 'ann')
        w.svc.deposit('A', '10.00')
        acct = w.repo.load('A')
        acct.deposit('99.00')   # never saved
        self.assertEqual(w.svc.balance('A'), Decimal('10.00'))

    def test_failed_transfer_target_save_then_reads(self):
        w = World(5)
        repo1, repo2 = w.fresh(), w.fresh()
        svc1, svc2 = LedgerService(repo1), LedgerService(repo2)
        svc1.open_account('A', 'ann')
        svc1.open_account('B', 'bob')
        svc1.deposit('A', '20.00')
        svc2.balance('B')                      # repo2 caches B at version 1
        target = repo2.load('B')
        svc1.deposit('B', '4.00')              # B moves to version 2 elsewhere
        target.receive_transfer('A', '3.00')   # stale in-memory change
        with self.assertRaises(ConcurrencyError):
            repo2.save(target)
        self.assertEqual(svc2.balance('B'), Decimal('4.00'))
        svc2.transfer('A', 'B', '3.00', fee='0')
        self.assertEqual(svc2.balance('B'), Decimal('7.00'))
        self.assertAgrees(w, 'A', repo1, repo2)
        self.assertAgrees(w, 'B', repo1, repo2)


class DomainRegressionTests(Base):
    def test_domain_rules_unchanged(self):
        w = World(2)
        w.svc.open_account('A', 'ann')
        w.svc.open_account('B', 'bob')
        w.svc.deposit('A', '10.00')
        w.svc.place_hold('A', '4.00', expires_at=10)
        with self.assertRaises(InsufficientFunds):
            w.fresh_svc().withdraw('A', '6.01')
        with self.assertRaises(InsufficientFunds):
            w.fresh_svc().transfer('A', 'B', '5.80', fee='0.25')
        with self.assertRaises(InsufficientFunds):
            w.fresh_svc().place_hold('A', '6.01', expires_at=1)
        w.fresh_svc().transfer('A', 'B', '5.75', fee='0.25')
        self.assertEqual(w.fresh().load('A').available, Decimal('0.00'))
        with self.assertRaises(AccountNotFound):
            w.fresh_svc().transfer('A', 'Z', '1.00')
        self.assertEqual(w.store.version('A'), 5)
        with self.assertRaises(HoldNotFound):
            w.fresh_svc().release_hold('A', 7)
        self.assertEqual(w.fresh_svc().release_expired_holds('A', now=9), [])
        self.assertEqual(w.fresh_svc().release_expired_holds('A', now=10), [1])
        self.assertAgrees(w, 'A')
        self.assertAgrees(w, 'B')


class MoneyRegressionTests(Base):
    def test_amount_validation_unchanged(self):
        w = World(5)
        w.svc.open_account('A', 'ann')
        with self.assertRaises(TypeError):
            w.svc.deposit('A', 1.5)
        with self.assertRaises(ValueError):
            w.svc.deposit('A', '1.005')
        with self.assertRaises(ValueError):
            w.svc.deposit('A', '0')
        w.svc.deposit('A', 5)
        w.svc.open_account('B', 'bob')
        w.svc.transfer('A', 'B', '1.00', fee='0.00')
        self.assertEqual(w.store.version('A'), 3)
        self.assertEqual(w.fresh().load('A').balance, Decimal('4.00'))


def _money(rng, low, high):
    cents = rng.randrange(int(low * 100), int(high * 100) + 1)
    return '%d.%02d' % (cents // 100, cents % 100)


class PropertyTests(Base):
    ACCOUNTS = ('A', 'B', 'C')

    def run_random(self, every, seed, steps=70):
        rng = random.Random(seed * 1000 + every)
        w = World(every)
        services = [w.svc, LedgerService(w.fresh()), LedgerService(w.fresh())]
        for account_id in self.ACCOUNTS:
            w.svc.open_account(account_id, account_id.lower())
            w.svc.deposit(account_id, '100.00')
        for step in range(steps):
            svc = rng.choice(services)
            acc = rng.choice(self.ACCOUNTS)
            truth = w.truth(acc)
            kind = rng.randrange(8)
            try:
                if kind == 0:
                    svc.deposit(acc, _money(rng, 0.01, 40))
                elif kind == 1:
                    svc.withdraw(acc, _money(rng, 0.01, 30))
                elif kind == 2:
                    svc.place_hold(acc, _money(rng, 0.01, 15), expires_at=rng.randrange(20))
                elif kind == 3 and truth['holds']:
                    svc.capture_hold(acc, rng.choice(sorted(truth['holds'])))
                elif kind == 4 and truth['holds']:
                    svc.release_hold(acc, rng.choice(sorted(truth['holds'])))
                elif kind == 5:
                    svc.release_expired_holds(acc, now=rng.randrange(20))
                elif kind == 6:
                    other = rng.choice([a for a in self.ACCOUNTS if a != acc])
                    svc.transfer(acc, other, _money(rng, 0.01, 10), fee=rng.choice(['0', '0.25', '1.00']))
                else:
                    loser = rng.choice(services)
                    stale = loser.repo.load(acc)
                    rng.choice([s for s in services if s is not loser]).deposit(acc, '1.00')
                    stale.deposit('2.00')
                    with self.assertRaises(ConcurrencyError):
                        loser.repo.save(stale)
            except InsufficientFunds:
                pass
            for account_id in self.ACCOUNTS:
                truth = w.truth(account_id)
                self.assertEqual(w.fresh().load(account_id).describe(), truth,
                                 'every=%d seed=%d step=%d fresh load of %s' % (every, seed, step, account_id))
                for i, s in enumerate(services):
                    self.assertEqual(s.account(account_id), truth,
                                     'every=%d seed=%d step=%d service %d %s' % (every, seed, step, i, account_id))

    def test_random_sequences_every_1(self):
        for seed in range(3):
            self.run_random(1, seed)

    def test_random_sequences_every_2(self):
        for seed in range(3):
            self.run_random(2, seed)

    def test_random_sequences_every_3(self):
        for seed in range(3):
            self.run_random(3, seed)

    def test_random_sequences_every_5(self):
        for seed in range(3):
            self.run_random(5, seed)

    def test_random_sequences_every_7(self):
        for seed in range(3):
            self.run_random(7, seed)


if __name__ == '__main__':
    unittest.main()
