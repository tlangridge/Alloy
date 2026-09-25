import unittest
from decimal import Decimal

from ledger import (AccountExists, AccountNotFound, AccountRepository, EventStore, HoldNotFound,
                    InsufficientFunds, LedgerService, SnapshotStore)


def make(snapshot_every=5):
    store, snaps = EventStore(), SnapshotStore()
    repo = AccountRepository(store, snaps, snapshot_every=snapshot_every)
    return LedgerService(repo), repo, store, snaps


class LedgerTests(unittest.TestCase):
    def test_deposit_withdraw(self):
        svc, repo, _, _ = make()
        svc.open_account('A', 'ann')
        svc.deposit('A', '10.50')
        svc.withdraw('A', 3)
        self.assertEqual(svc.balance('A'), Decimal('7.50'))
        with self.assertRaises(InsufficientFunds):
            svc.withdraw('A', '8.00')

    def test_holds(self):
        svc, _, _, _ = make()
        svc.open_account('A', 'ann')
        svc.deposit('A', '100')
        h1 = svc.place_hold('A', '30.00', expires_at=50)
        h2 = svc.place_hold('A', '20.00', expires_at=500)
        self.assertEqual((h1, h2), (1, 2))
        self.assertEqual(svc.available('A'), Decimal('50.00'))
        svc.capture_hold('A', h1)
        self.assertEqual(svc.balance('A'), Decimal('70.00'))
        self.assertEqual(svc.release_expired_holds('A', now=499), [])
        self.assertEqual(svc.release_expired_holds('A', now=500), [2])
        with self.assertRaises(HoldNotFound):
            svc.release_hold('A', h2)

    def test_transfer_with_fee(self):
        svc, _, _, _ = make()
        svc.open_account('A', 'ann')
        svc.open_account('B', 'bob')
        svc.deposit('A', '20.00')
        svc.transfer('A', 'B', '5.00', fee='0.25')
        self.assertEqual(svc.balance('A'), Decimal('14.75'))
        self.assertEqual(svc.balance('B'), Decimal('5.00'))

    def test_accounts_must_exist_once(self):
        svc, _, _, _ = make()
        svc.open_account('A', 'ann')
        with self.assertRaises(AccountExists):
            svc.open_account('A', 'ann')
        with self.assertRaises(AccountNotFound):
            svc.deposit('Z', 1)

    def test_snapshots_are_written_and_agree_with_rebuild(self):
        svc, repo, store, snaps = make(snapshot_every=5)
        svc.open_account('A', 'ann')
        for i in range(11):
            svc.deposit('A', '1.00')
        self.assertEqual(snaps.versions('A'), [5, 10])
        fresh = AccountRepository(store, snaps, snapshot_every=5)
        self.assertEqual(fresh.load('A').describe(), repo.rebuild('A').describe())


if __name__ == '__main__':
    unittest.main()
