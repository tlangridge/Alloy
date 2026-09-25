import unittest

from ledger.pool import ConnectionPool
from ledger.tx import run_in_transaction

from helpers import TempDatabase


def insert(account, cents):
    def work(conn):
        conn.execute('INSERT INTO entries (account, cents) VALUES (?, ?)', (account, cents))
        return cents
    return work


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.db = TempDatabase()
        self.pool = ConnectionPool(self.db.connect, size=2, timeout=0.05)

    def tearDown(self):
        self.pool.close()
        self.db.cleanup()

    def test_commits_and_returns_result(self):
        self.assertEqual(run_in_transaction(self.pool, insert('cash', 500)), 500)
        self.assertEqual(self.db.rows(), [('cash', 500)])
        self.assertEqual(self.pool.stats()['in_use'], 0)

    def test_rolls_back_and_reraises(self):
        def work(conn):
            insert('cash', 1)(conn)
            raise KeyError('boom')
        with self.assertRaises(KeyError):
            run_in_transaction(self.pool, work)
        self.assertEqual(self.db.rows(), [])
        self.assertEqual(self.pool.stats()['in_use'], 0)


if __name__ == '__main__':
    unittest.main()
