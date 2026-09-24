# staticserve

The static-file handler used by our internal docs server. Request paths are
mapped onto files below a document root by `staticserve.paths`; the handler
answers 400 when `resolve_request_path` raises `PathTraversalError`, and 404
when the resolved file does not exist.

```python
from staticserve.paths import resolve_request_path

resolve_request_path('/srv/www', '/guide/intro.html')   # '/srv/www/guide/intro.html'
```

Run the tests with `python3 -m unittest discover -s tests -v`.
