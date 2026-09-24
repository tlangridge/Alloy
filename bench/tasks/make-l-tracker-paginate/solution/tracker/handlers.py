"""HTTP handlers."""
import csv
import io
import re

from . import query as q
from .http import Response, error
from .service import NotFound, ValidationError

ISSUE_PATH = re.compile(r'^/issues/(\d+)$')
EXPORT_COLUMNS = ('id', 'title', 'status', 'priority', 'labels', 'assignee')


class App(object):
    def __init__(self, service):
        self.service = service

    def handle(self, request):
        try:
            if request.path == '/issues' and request.method == 'GET':
                return self.list_issues(request)
            if request.path == '/issues' and request.method == 'POST':
                return Response(201, self.service.create(request.body).to_dict())
            if request.path == '/issues/export.csv' and request.method == 'GET':
                return self.export_issues(request)
            match = ISSUE_PATH.match(request.path)
            if match and request.method == 'GET':
                return Response(200, self.service.get(int(match.group(1))).to_dict())
            if match and request.method == 'PATCH':
                return Response(200, self.service.update(int(match.group(1)), request.body).to_dict())
            return error(404, 'not_found')
        except NotFound:
            return error(404, 'not_found')
        except ValidationError as exc:
            return error(400, exc.code, exc.param)

    def list_issues(self, request):
        query, paginated = q.parse(request.query, q.LIST_PARAMS, (('id', False),))
        issues, more = self.service.search(query)
        body = {'items': [i.to_dict() for i in issues]}
        if paginated:
            body['next_cursor'] = q.encode_cursor(query, query.key(issues[-1])) if more else None
        return Response(200, body)

    def export_issues(self, request):
        query, _ = q.parse(request.query, q.EXPORT_PARAMS, (('created', False), ('id', False)))
        issues, _ = self.service.search(query)
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(EXPORT_COLUMNS)
        for i in issues:
            writer.writerow([i.id, i.title, i.status, i.priority, ';'.join(i.labels), i.assignee or ''])
        return Response(200, out.getvalue(), content_type='text/csv')
