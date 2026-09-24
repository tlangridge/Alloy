"""The job table used by the scheduler daemon (relies on Schedule.next_after)."""
from .parser import parse


class JobTable(object):
    def __init__(self):
        self._jobs = {}

    def add(self, name, expression, last_run):
        """Register a job; ``last_run`` is the naive datetime it last ran (or was created)."""
        self._jobs[name] = [parse(expression), last_run]

    def next_run(self, name):
        schedule, last_run = self._jobs[name]
        return schedule.next_after(last_run)

    def due(self, now):
        """Names of jobs whose next run is at or before ``now``, earliest first (ties by name)."""
        pending = []
        for name in self._jobs:
            nxt = self.next_run(name)
            if nxt is not None and nxt <= now:
                pending.append((nxt, name))
        return [name for _, name in sorted(pending)]

    def mark_run(self, name, when):
        self._jobs[name][1] = when
