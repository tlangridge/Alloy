"""A small blocking connection pool."""
import queue
import threading


class PoolExhausted(Exception):
    """No connection became available within the timeout."""


class ConnectionPool:
    """Hands out at most `size` live connections, created lazily by `factory`.

    Every connection returned by acquire() goes back through exactly one of:

    * release(conn) - the connection is healthy and is reused by later callers;
    * discard(conn) - the connection is closed and its slot is freed, so the
      pool may create a replacement.
    """

    def __init__(self, factory, size=4, timeout=5.0):
        if size < 1:
            raise ValueError('size must be at least 1')
        self._factory = factory
        self.size = size
        self.timeout = timeout
        self._idle = queue.LifoQueue()
        self._lock = threading.Lock()
        self._created = 0

    def acquire(self, timeout=None):
        """Return an idle connection, create one if below `size`, else wait."""
        try:
            return self._idle.get_nowait()
        except queue.Empty:
            pass
        with self._lock:
            create = self._created < self.size
            if create:
                self._created += 1
        if create:
            try:
                return self._factory()
            except BaseException:
                with self._lock:
                    self._created -= 1
                raise
        wait = self.timeout if timeout is None else timeout
        try:
            return self._idle.get(timeout=wait)
        except queue.Empty:
            raise PoolExhausted('no connection available after %.3fs' % wait) from None

    def release(self, conn):
        self._idle.put(conn)

    def discard(self, conn):
        try:
            conn.close()
        finally:
            with self._lock:
                self._created -= 1

    def stats(self):
        """Counts for monitoring: size, created (live), idle and in_use."""
        with self._lock:
            created = self._created
        idle = self._idle.qsize()
        return dict(size=self.size, created=created, idle=idle, in_use=created - idle)

    def close(self):
        """Close every idle connection."""
        while True:
            try:
                conn = self._idle.get_nowait()
            except queue.Empty:
                return
            self.discard(conn)
