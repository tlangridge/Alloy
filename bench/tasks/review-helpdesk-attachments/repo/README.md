# helpdesk

Filesystem storage for helpdesk ticket attachments.

Files live under `<root>/tickets/<ticket id>/<relative path>`. Every ticket has
its own directory; agents and customers of one ticket must never be able to
reach another ticket's files.

```python
from helpdesk import AttachmentStore

store = AttachmentStore('/srv/helpdesk')
store.save(42, 'screens/login.png', data)
store.list(42)            # ['screens/login.png']
```

Run the tests with `python3 -m unittest discover -s tests -v`.
