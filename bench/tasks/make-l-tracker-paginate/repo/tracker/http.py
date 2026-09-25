"""Minimal request/response objects (the real service mounts App on a WSGI adapter)."""
from urllib.parse import parse_qs, urlsplit


class Request(object):
    def __init__(self, method, target, body=None):
        parts = urlsplit(target)
        self.method = method.upper()
        self.path = parts.path
        # name -> list of values, in the order they appear; blank values kept
        self.query = parse_qs(parts.query, keep_blank_values=True)
        self.body = body


class Response(object):
    def __init__(self, status, body, content_type='application/json'):
        self.status = status
        self.body = body
        self.content_type = content_type

    def __repr__(self):
        return 'Response(%d, %r)' % (self.status, self.body)


def error(status, code, param=None):
    detail = {'code': code}
    if param is not None:
        detail['param'] = param
    return Response(status, {'error': detail})
