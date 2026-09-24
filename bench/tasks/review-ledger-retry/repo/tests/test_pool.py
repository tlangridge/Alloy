import unittest

from ledger.pool import ConnectionPool, PoolExhausted

from helpers import TempDatabase


class PoolTests(unittest.TestCase):
    def setUp(self):
        self.db = TempDatabase()

    def tearDown(self):
        self.db.cleanup()

    def test_connections_are_created_lazily_and_reused(self):
        pool = ConnectionPool(self.db.connect, size=2)
        a = pool.acquire()
        pool.release(a)
        self.assertIs(pool.acquire(), a)
        self.assertEqual(len(self.db.opened), 1)

    def test_exhausted_pool_times_out(self):
        pool = ConnectionPool(self.db.connect, size=1, timeout=0.01)
        pool.acquire()
        with self.assertRaises(PoolExhausted):
            pool.acquire()

    def test_discard_frees_a_slot(self):
        pool = ConnectionPool(self.db.connect, size=1, timeout=0.01)
        a = pool.acquire()
        pool.discard(a)
        b = pool.acquire()
        self.assertIsNot(a, b)
        self.assertEqual(pool.stats(), dict(size=1, created=1, idle=0, in_use=1))

    def test_stats(self):
        pool = ConnectionPool(self.db.connect, size=3)
        a = pool.acquire()
        pool.acquire()
        pool.release(a)
        self.assertEqual(pool.stats(), dict(size=3, created=2, idle=1, in_use=1))


if __name__ == '__main__':
    unittest.main()
