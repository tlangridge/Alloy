"""Run units of work inside a database transaction."""
import sqlite3
import time

from .errors import is_transient


def run_in_transaction(pool, work, attempts=3, backoff=0.05, sleep=time.sleep):
    """Call work(conn) in a transaction and return its result.

    Transient SQLite failures (see errors.is_transient) are retried up to
    `attempts` times in total, sleeping backoff * 2**(n - 1) seconds after the
    n-th failed attempt. Each attempt runs on its own connection. SQLite can
    leave a connection that hit a lock error in a bad state, so such a
    connection is closed rather than handed back for reuse; the pool creates a
    fresh one for the next attempt. Any other error rolls back and propagates
    immediately.
    """
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1:
        raise ValueError('attempts must be a positive integer')
    for attempt in range(1, attempts + 1):
        conn = pool.acquire()
        try:
            result = work(conn)
            conn.commit()
        except Exception as exc:
            _rollback_quietly(conn)
            if not is_transient(exc):
                pool.release(conn)
                raise
            pool.discard(conn)
            if attempt == attempts:
                raise
            sleep(backoff * 2 ** (attempt - 1))
            continue
        except BaseException:
            _rollback_quietly(conn)
            pool.release(conn)
            raise
        pool.release(conn)
        return result


def _rollback_quietly(conn):
    """Roll back, ignoring errors: the original exception is what matters."""
    try:
        conn.rollback()
    except sqlite3.Error:
        pass
