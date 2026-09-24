import os
import sqlite3
import tempfile


class TempDatabase:
    """A throwaway on-disk SQLite database with an `entries` table."""

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

    def rows(self):
        conn = sqlite3.connect(self.path)
        try:
            return conn.execute('SELECT account, cents FROM entries ORDER BY id').fetchall()
        finally:
            conn.close()

    def cleanup(self):
        for conn in self.opened:
            try:
                conn.close()
            except Exception:
                pass
        self._tmp.cleanup()
