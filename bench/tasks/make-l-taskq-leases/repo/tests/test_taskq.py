import unittest

from taskq import FakeClock, JobQueue, LeaseLost, WorkerPool


def quick(payload, ctx):
    yield
    return payload * 2


def failing(payload, ctx):
    yield
    raise ValueError('boom')


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.q = JobQueue(self.clock)

    def test_claim_ack(self):
        jid = self.q.enqueue('a')
        lease = self.q.claim('w1', 30)
        self.assertEqual((lease.job_id, lease.attempt), (jid, 1))
        self.q.ack(lease)
        self.assertEqual(self.q.job(jid).state, 'done')
        with self.assertRaises(LeaseLost):
            self.q.ack(lease)

    def test_priority_then_age(self):
        low = self.q.enqueue('low')
        high = self.q.enqueue('high', priority=5)
        self.assertEqual(self.q.claim('w1', 30).job_id, high)
        self.assertEqual(self.q.claim('w1', 30).job_id, low)

    def test_dedupe_while_pending(self):
        a = self.q.enqueue({'n': 1}, key='k')
        b = self.q.enqueue({'n': 2}, key='k')
        self.assertEqual(a, b)
        self.assertEqual(self.q.stats()['ready'], 1)

    def test_nack_until_dead(self):
        jid = self.q.enqueue('x', max_attempts=2)
        self.q.nack(self.q.claim('w1', 30), delay=5)
        self.assertIsNone(self.q.claim('w1', 30))
        self.clock.advance(5)
        self.q.nack(self.q.claim('w1', 30))
        info = self.q.job(jid)
        self.assertEqual((info.state, info.dead_reason, info.attempts), ('dead', 'failed', 2))


class PoolTests(unittest.TestCase):
    def test_short_jobs(self):
        clock = FakeClock()
        q = JobQueue(clock)
        for n in (1, 2, 3):
            q.enqueue(n)
        pool = WorkerPool(q, clock, quick)
        pool.run_until_idle()
        self.assertEqual(sorted(v for _, _, v in pool.results), [2, 4, 6])
        self.assertEqual(pool.lost, [])

    def test_failing_job_is_retried_then_dead(self):
        clock = FakeClock()
        q = JobQueue(clock)
        jid = q.enqueue('x')
        pool = WorkerPool(q, clock, failing)
        pool.run_until_idle()
        info = q.job(jid)
        self.assertEqual((info.state, info.dead_reason, info.attempts), ('dead', 'failed', 3))
        self.assertEqual(pool.results, [])


if __name__ == '__main__':
    unittest.main()
