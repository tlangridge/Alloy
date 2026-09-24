"""Run units of work inside a database transaction."""


def run_in_transaction(pool, work):
    """Call work(conn) in a transaction; commit on success, roll back on error.

    Returns whatever `work` returns. The connection always goes back to the pool.
    """
    conn = pool.acquire()
    try:
        result = work(conn)
        conn.commit()
        return result
    except BaseException:
        conn.rollback()
        raise
    finally:
        pool.release(conn)
