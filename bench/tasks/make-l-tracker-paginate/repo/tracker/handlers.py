"""HTTP handlers."""
import csv
import io
import re

from .http import Response, error
from .models import STATUSES
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
        unknown = sorted(set(request.query) - {'status'})
        if unknown:
            return error(400, 'unknown_param', unknown[0])
        values = request.query.get('status', [])
        if len(values) > 1:
            return error(400, 'duplicate_param', 'status')
        status = values[0] if values else 'all'
        if status != 'all' and status not in STATUSES:
            return error(400, 'invalid_filter', 'status')
        issues = [i for i in self.service.store.all() if status == 'all' or i.status == status]
        return Response(200, {'items': [i.to_dict() for i in issues]})

    def export_issues(self, request):
        unknown = sorted(set(request.query) - {'status'})
        if unknown:
            return error(400, 'unknown_param', unknown[0])
        values = request.query.get('status', [])
        if len(values) > 1:
            return error(400, 'duplicate_param', 'status')
        status = values[0] if values else 'all'
        if status != 'all' and status not in STATUSES:
            return error(400, 'invalid_filter', 'status')
        issues = [i for i in self.service.store.all() if status == 'all' or i.status == status]
        issues.sort(key=lambda i: (i.created_at, i.id))
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(EXPORT_COLUMNS)
        for i in issues:
            writer.writerow([i.id, i.title, i.status, i.priority, ';'.join(i.labels), i.assignee or ''])
        return Response(200, out.getvalue(), content_type='text/csv')
