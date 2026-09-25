import sqlite3
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



def flaky(failures, message='database is locked'):
    """work() that raises a transient error `failures` times, then inserts."""
    calls = []

    def work(conn):
        calls.append(conn)
        if len(calls) <= failures:
            conn.execute('INSERT INTO entries (account, cents) VALUES (?, ?)', ('partial', 1))
            raise sqlite3.OperationalError(message)
        conn.execute('INSERT INTO entries (account, cents) VALUES (?, ?)', ('cash', 700))
        return 'done'
    work.calls = calls
    return work


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.db = TempDatabase()
        self.pool = ConnectionPool(self.db.connect, size=4, timeout=0.05)
        self.sleeps = []

    def tearDown(self):
        self.pool.close()
        self.db.cleanup()

    def run_tx(self, work, **kw):
        return run_in_transaction(self.pool, work, sleep=self.sleeps.append, **kw)

    def test_transient_failure_is_retried_on_a_fresh_connection(self):
        work = flaky(1)
        self.assertEqual(self.run_tx(work), 'done')
        self.assertEqual(len(work.calls), 2)
        self.assertIsNot(work.calls[0], work.calls[1])
        self.assertEqual(self.sleeps, [0.05])
        self.assertEqual(self.db.rows(), [('cash', 700)])

    def test_gives_up_after_attempts_and_raises_last_error(self):
        work = flaky(5)
        with self.assertRaises(sqlite3.OperationalError):
            self.run_tx(work)
        self.assertEqual(len(work.calls), 3)
        self.assertEqual(self.sleeps, [0.05, 0.1])
        self.assertEqual(self.db.rows(), [])

    def test_custom_attempts_and_backoff(self):
        work = flaky(3)
        self.assertEqual(self.run_tx(work, attempts=4, backoff=1), 'done')
        self.assertEqual(self.sleeps, [1, 2, 4])

    def test_non_transient_error_is_not_retried(self):
        work = flaky(1, message='no such table: nope')
        with self.assertRaises(sqlite3.OperationalError):
            self.run_tx(work)
        self.assertEqual(len(work.calls), 1)
        self.assertEqual(self.sleeps, [])
        self.assertEqual(self.pool.stats()['in_use'], 0)

    def test_connection_reused_after_success(self):
        self.run_tx(flaky(0))
        self.run_tx(flaky(0))
        self.assertEqual(self.pool.stats(), dict(size=4, created=1, idle=1, in_use=0))

    def test_attempts_must_be_positive(self):
        for bad in (0, -1, 1.5, True):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.run_tx(flaky(0), attempts=bad)


if __name__ == '__main__':
    unittest.main()
