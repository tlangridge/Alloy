"""Issue tracker API."""
from .handlers import App
from .http import Request, Response
from .service import FakeClock, IssueService
from .storage import MemoryIssueStore, SqliteIssueStore


def create_app(store=None, clock=None):
    return App(IssueService(store if store is not None else MemoryIssueStore(), clock))


__all__ = ['App', 'Request', 'Response', 'FakeClock', 'IssueService', 'MemoryIssueStore',
           'SqliteIssueStore', 'create_app']
