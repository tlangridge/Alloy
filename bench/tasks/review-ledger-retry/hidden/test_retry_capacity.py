import os
import sqlite3
import tempfile
import unittest

from ledger.pool import ConnectionPool, PoolExhausted
from ledger.tx import run_in_transaction


class Database:
    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, 'ledger.db')
        conn = sqlite3.connect(self.path)
        conn.execute('CREATE TABLE entries (id INTEGER PRIMARY KEY, account TEXT, cents INTEGER)')
        conn.commit()
        conn.close()
        self.opened = []

    def connect(self):
        conn = sqlite3.connect(self.path, check_same_thread=False)
        self.opened.append(conn)
        return conn

    def cleanup(self):
        for conn in self.opened:
            try:
                conn.close()
            except Exception:
                pass
        self._tmp.cleanup()


def locked_then_ok(failures):
    calls = []

    def work(conn):
        calls.append(conn)
        if len(calls) <= failures:
            raise sqlite3.OperationalError('database is locked')
        conn.execute("INSERT INTO entries (account, cents) VALUES ('cash', 1)")
        return 'ok'
    return work


def always_locked(conn):
    raise sqlite3.OperationalError('database is locked')


class RetryKeepsPoolCapacityTests(unittest.TestCase):
    """A transiently failed connection must give its pool slot back."""

    def setUp(self):
        self.db = Database()

    def tearDown(self):
        self.db.cleanup()

    def test_retry_succeeds_with_single_connection_pool(self):
        pool = ConnectionPool(self.db.connect, size=1, timeout=0.05)
        try:
            result = run_in_transaction(pool, locked_then_ok(1), sleep=lambda s: None)
        except PoolExhausted:
            self.fail('retry could not get a connection: the failed one still holds the only slot')
        self.assertEqual(result, 'ok')
        self.assertEqual(pool.stats()['in_use'], 0)

    def test_capacity_unchanged_after_transient_retry(self):
        pool = ConnectionPool(self.db.connect, size=3, timeout=0.05)
        run_in_transaction(pool, locked_then_ok(2), sleep=lambda s: None)
        self.assertEqual(pool.stats()['in_use'], 0)
        held = [pool.acquire() for _ in range(3)]   # full capacity still available
        self.assertEqual(len(held), 3)

    def test_capacity_unchanged_after_giving_up(self):
        pool = ConnectionPool(self.db.connect, size=3, timeout=0.05)
        with self.assertRaises(sqlite3.OperationalError):
            run_in_transaction(pool, always_locked, sleep=lambda s: None)
        self.assertEqual(pool.stats()['in_use'], 0)
        self.assertEqual(run_in_transaction(pool, locked_then_ok(0), sleep=lambda s: None), 'ok')

    def test_repeated_calls_do_not_exhaust_pool(self):
        pool = ConnectionPool(self.db.connect, size=2, timeout=0.05)
        for _ in range(4):
            self.assertEqual(run_in_transaction(pool, locked_then_ok(1), sleep=lambda s: None), 'ok')
        self.assertEqual(pool.stats()['in_use'], 0)


if __name__ == '__main__':
    unittest.main()
