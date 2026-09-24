import unittest

from taskq import FakeClock, JobQueue, LeaseLost, WorkerPool


def steps_handler(payload, ctx):
    for _ in range(payload['steps']):
        yield
    return payload.get('name', 'ok')


def one_step(payload, ctx):
    payload.setdefault('seen', []).append((ctx.job_id, ctx.worker, ctx.now()))
    yield
    return payload.get('name')


def oom(payload, ctx):
    yield
    ctx.crash()


class QueueBase(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.q = JobQueue(self.clock)

    def at(self, t):
        self.clock.advance(t - self.clock.now())


class ClaimAndLeaseTests(QueueBase):
    def test_claim_order_priority_age_id(self):
        a = self.q.enqueue('a')
        b = self.q.enqueue('b', priority=5, delay=10)
        c = self.q.enqueue('c', priority=5)
        d = self.q.enqueue('d')
        self.assertEqual(self.q.claim('w', 30).job_id, c)
        self.at(10)
        self.assertEqual([self.q.claim('w', 30).job_id for _ in range(3)], [b, a, d])
        self.assertIsNone(self.q.claim('w', 30))

    def test_delay_available_exactly_at_time(self):
        jid = self.q.enqueue('x', delay=15)
        self.at(14)
        self.assertIsNone(self.q.claim('w', 30))
        self.at(15)
        self.assertEqual(self.q.claim('w', 30).job_id, jid)

    def test_lease_valid_strictly_before_expiry(self):
        j1 = self.q.enqueue('x')
        j2 = self.q.enqueue('y')
        l1 = self.q.claim('w1', 30)
        l2 = self.q.claim('w1', 30)
        self.at(29)
        self.q.ack(l1)
        self.assertEqual(self.q.job(j1).state, 'done')
        self.at(30)
        with self.assertRaises(LeaseLost):
            self.q.ack(l2)
        info = self.q.job(j2)
        self.assertEqual((info.state, info.attempts, info.available_at), ('ready', 1, 30))

    def test_stale_lease_rejected_after_reclaim(self):
        jid = self.q.enqueue('x')
        old = self.q.claim('w1', 30)
        self.at(30)
        new = self.q.claim('w2', 30)
        self.assertEqual((new.job_id, new.attempt), (jid, 2))
        for call in (lambda: self.q.ack(old), lambda: self.q.nack(old, 0), lambda: self.q.extend(old, 30)):
            with self.assertRaises(LeaseLost):
                call()
        info = self.q.job(jid)
        self.assertEqual((info.state, info.worker, info.expires_at, info.attempts), ('leased', 'w2', 60, 2))
        self.q.ack(new)
        self.assertEqual(self.q.job(jid).state, 'done')

    def test_extend_counts_from_now(self):
        jid = self.q.enqueue('x')
        lease = self.q.claim('w1', 30)
        self.at(25)
        self.assertEqual(self.q.extend(lease, 30), 55)
        self.assertEqual(self.q.job(jid).expires_at, 55)
        self.at(54)
        self.q.ack(lease)
        self.assertEqual(self.q.job(jid).state, 'done')

    def test_extend_of_expired_lease_changes_nothing(self):
        jid = self.q.enqueue('x')
        lease = self.q.claim('w1', 30)
        self.at(30)
        with self.assertRaises(LeaseLost):
            self.q.extend(lease, 30)
        info = self.q.job(jid)
        self.assertEqual((info.state, info.expires_at), ('ready', 30))

    def test_expiry_dead_letters_at_max_attempts(self):
        jid = self.q.enqueue('x', max_attempts=2)
        self.q.claim('w1', 30)
        self.at(30)
        self.assertEqual(self.q.stats(), {'ready': 1, 'leased': 0, 'done': 0, 'dead': 0})
        self.assertEqual(self.q.claim('w2', 30).attempt, 2)
        self.at(60)
        info = self.q.job(jid)
        self.assertEqual((info.state, info.dead_reason, info.attempts), ('dead', 'lease-expired', 2))
        self.assertEqual(self.q.stats()['dead'], 1)
        self.assertIsNone(self.q.claim('w1', 30))

    def test_expired_job_available_from_its_expiry(self):
        old = self.q.enqueue('old')
        self.q.claim('w1', 30)
        self.at(20)
        newer = self.q.enqueue('newer')
        self.at(40)
        self.assertEqual(self.q.claim('w2', 30).job_id, newer)
        self.assertEqual(self.q.claim('w2', 30).job_id, old)

    def test_nack_after_expiry(self):
        jid = self.q.enqueue('x', max_attempts=1)
        lease = self.q.claim('w1', 10)
        self.at(10)
        with self.assertRaises(LeaseLost):
            self.q.nack(lease, 5)
        info = self.q.job(jid)
        self.assertEqual((info.state, info.dead_reason), ('dead', 'lease-expired'))


class DedupeTests(QueueBase):
    def test_key_released_on_first_claim(self):
        first = self.q.enqueue({'rev': 1}, key='reindex:42')
        self.q.claim('w1', 30)
        second = self.q.enqueue({'rev': 2}, key='reindex:42')
        self.assertNotEqual(second, first)
        self.assertEqual(self.q.enqueue({'rev': 3}, key='reindex:42'), second)
        self.assertEqual(self.q.stats(), {'ready': 1, 'leased': 1, 'done': 0, 'dead': 0})

    def test_new_holder_keeps_key_when_old_job_finishes(self):
        j1 = self.q.enqueue('a', key='k')
        l1 = self.q.claim('w1', 30)
        j2 = self.q.enqueue('b', key='k')
        self.q.ack(l1)
        self.assertEqual(self.q.enqueue('c', key='k'), j2)
        self.q.claim('w1', 30)
        j3 = self.q.enqueue('d', key='k')
        self.assertNotIn(j3, (j1, j2))

    def test_retry_does_not_reacquire_key(self):
        j1 = self.q.enqueue('a', key='k')
        self.q.nack(self.q.claim('w1', 30), 0)
        self.assertEqual(self.q.job(j1).state, 'ready')
        j2 = self.q.enqueue('b', key='k')
        self.assertNotEqual(j2, j1)
        self.assertEqual(self.q.enqueue('c', key='k'), j2)

    def test_dead_or_failed_old_job_does_not_release_new_key(self):
        j1 = self.q.enqueue('a', key='k', max_attempts=1)
        l1 = self.q.claim('w1', 30)
        j2 = self.q.enqueue('b', key='k')
        self.q.nack(l1, 0)                      # j1 -> dead ('failed')
        self.assertEqual(self.q.enqueue('c', key='k'), j2)
        j3 = self.q.enqueue('x', key='other', max_attempts=1)
        self.q.claim('w1', 30)                   # claims j2 (same priority and time, lower id)
        j4 = self.q.enqueue('y', key='k')        # j2 was claimed -> new job
        self.assertNotIn(j4, (j1, j2))
        self.assertEqual(self.q.enqueue('z', key='other'), j3)

    def test_expired_old_job_does_not_release_new_key(self):
        self.q.enqueue('a', key='k', max_attempts=1)
        self.q.claim('w1', 30)
        j2 = self.q.enqueue('b', key='k', delay=100)
        self.at(30)                              # first job expires and is dead-lettered
        self.assertEqual(self.q.stats()['dead'], 1)
        self.assertEqual(self.q.enqueue('c', key='k'), j2)

    def test_delayed_job_holds_key(self):
        j1 = self.q.enqueue('a', key='k', delay=100)
        self.assertEqual(self.q.enqueue('b', key='k'), j1)
        self.assertEqual(self.q.stats()['ready'], 1)


class PoolTests(unittest.TestCase):
    def pool(self, handler, **kw):
        self.clock = FakeClock()
        self.q = JobQueue(self.clock)
        return WorkerPool(self.q, self.clock, handler, **kw)

    def test_inc1_long_export_completes_once(self):
        pool = self.pool(steps_handler, workers=('w1', 'w2'), lease_seconds=30, heartbeat_margin=10,
                         round_seconds=10)
        jid = self.q.enqueue({'name': 'march', 'steps': 8})
        pool.run_until_idle(max_rounds=100)
        self.assertEqual(pool.results, [(jid, 'w1', 'march')])
        self.assertEqual(pool.lost, [])
        info = self.q.job(jid)
        self.assertEqual((info.state, info.attempts), ('done', 1))

    def test_long_jobs_under_several_timings(self):
        for lease, margin, round_s in ((30, 10, 10), (25, 5, 5), (30, 10, 7), (40, 20, 10)):
            pool = self.pool(steps_handler, workers=('w1', 'w2'), lease_seconds=lease, heartbeat_margin=margin,
                             round_seconds=round_s)
            a = self.q.enqueue({'name': 'a', 'steps': 12})
            b = self.q.enqueue({'name': 'b', 'steps': 20})
            pool.run_until_idle(max_rounds=200)
            self.assertEqual(sorted(pool.results), [(a, 'w1', 'a'), (b, 'w2', 'b')], (lease, margin, round_s))
            self.assertEqual(pool.lost, [], (lease, margin, round_s))
            self.assertEqual([self.q.job(a).attempts, self.q.job(b).attempts], [1, 1])

    def test_heartbeat_fires_once_margin_is_reached(self):
        pool = self.pool(steps_handler, workers=('w1',), lease_seconds=30, heartbeat_margin=10, round_seconds=10)
        jid = self.q.enqueue({'steps': 50})
        expiries = []
        for _ in range(6):                        # turns at t = 0, 10, 20, 30, 40, 50
            pool.run_round()
            expiries.append(self.q.job(jid).expires_at)
        self.assertEqual(expiries, [30, 30, 50, 50, 70, 70])

    def test_inc3_crashing_job_is_dead_lettered(self):
        pool = self.pool(oom)
        jid = self.q.enqueue({'huge': True})
        rounds = pool.run_until_idle(max_rounds=200)
        info = self.q.job(jid)
        self.assertEqual((info.state, info.dead_reason, info.attempts), ('dead', 'lease-expired', 3))
        self.assertEqual(rounds, 9)
        self.assertEqual((pool.results, pool.lost), ([], []))

    def test_failing_job_retry_timing(self):
        starts = []

        def failing(payload, ctx):
            starts.append((ctx.attempt, ctx.worker, ctx.now()))
            yield
            raise ValueError('boom')

        pool = self.pool(failing, retry_delay=5)
        jid = self.q.enqueue('x')
        pool.run_until_idle()
        self.assertEqual(starts, [(1, 'w1', 0), (2, 'w1', 20), (3, 'w1', 40)])
        info = self.q.job(jid)
        self.assertEqual((info.state, info.dead_reason), ('dead', 'failed'))

    def test_reindex_requested_during_run_runs_again(self):
        runs = []

        def reindex(payload, ctx):
            yield
            yield
            runs.append(payload['rev'])
            return payload['rev']

        pool = self.pool(reindex, workers=('w1',))
        first = self.q.enqueue({'rev': 1}, key='reindex:42')
        pool.run_round()                                    # rev 1 claimed and running
        second = self.q.enqueue({'rev': 2}, key='reindex:42')
        self.assertEqual(self.q.enqueue({'rev': 3}, key='reindex:42'), second)
        pool.run_until_idle()
        self.assertNotEqual(first, second)
        self.assertEqual(runs, [1, 2])

    def test_lost_leases_without_timely_heartbeat(self):
        pool = self.pool(steps_handler, workers=('w1', 'w2'), lease_seconds=15, heartbeat_margin=0,
                         round_seconds=10)
        jid = self.q.enqueue({'steps': 5})
        pool.run_until_idle(max_rounds=50)
        self.assertEqual(pool.lost, [(jid, 'w1', 1), (jid, 'w2', 2), (jid, 'w1', 3)])
        self.assertEqual(pool.results, [])
        info = self.q.job(jid)
        self.assertEqual((info.state, info.dead_reason, info.attempts), ('dead', 'lease-expired', 3))

    def test_round_order_and_first_step_in_claim_turn(self):
        pool = self.pool(one_step, workers=('w1', 'w2'))
        payloads = [{'name': n} for n in ('a', 'b', 'c')]
        for p in payloads:
            self.q.enqueue(p)
        pool.run_until_idle()
        self.assertEqual(pool.results, [(1, 'w1', 'a'), (2, 'w2', 'b'), (3, 'w1', 'c')])
        self.assertEqual([p['seen'] for p in payloads], [[(1, 'w1', 0)], [(2, 'w2', 0)], [(3, 'w1', 20)]])

    def test_run_until_idle_waits_for_delayed_jobs(self):
        pool = self.pool(one_step)
        self.q.enqueue({'name': 'later'}, delay=35)
        self.assertEqual(pool.run_until_idle(), 6)
        self.assertEqual(pool.results, [(1, 'w1', 'later')])

    def test_max_rounds(self):
        pool = self.pool(steps_handler, workers=('w1',))
        self.q.enqueue({'steps': 30})
        with self.assertRaises(RuntimeError):
            pool.run_until_idle(max_rounds=5)


if __name__ == '__main__':
    unittest.main()
