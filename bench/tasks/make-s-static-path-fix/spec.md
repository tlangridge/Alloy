# SPEC: fix document-root escapes in `resolve_request_path`

## Goal
`staticserve.paths.resolve_request_path` maps a request path onto a file
below the document root. A security review found that it lets requests
escape the root. Fix `staticserve/paths.py` so the function meets the full
contract below, and add regression tests.

## Current behavior
Security review findings, reproduced with the document root `/srv/www`:

> 1. Sibling directories whose name starts with the root's name are
>    reachable:
>    ```python
>    resolve_request_path('/srv/www', '/../www-private/keys.txt')
>    # returns '/srv/www-private/keys.txt'   (expected: PathTraversalError)
>    resolve_request_path('/srv/www', '/%2e%2e/www-private/keys.txt')
>    # returns '/srv/www-private/keys.txt'   (expected: PathTraversalError)
>    ```
> 2. A request for `/a%00b` returns `'/srv/www/a\x00b'`; the handler's
>    later `open()` then crashes with `ValueError: embedded null byte` and
>    the client gets a 500 instead of a 400.

## Desired behavior
`resolve_request_path(root: str, url_path: str) -> str`; failures raise
`PathTraversalError` (the existing subclass of `ValueError`).

1. **Decoding.** `url_path` is the raw path component of the request URL.
   Percent-escapes are decoded exactly once (as `urllib.parse.unquote` does),
   so `%20` becomes a space and `%252e` becomes the literal three characters
   `%2e`, which is an ordinary name, not a dot.
2. **Resolution.** The decoded path is interpreted relative to `root`:
   leading slashes are ignored, repeated slashes collapse, and `.` and `..`
   segments are resolved lexically. The function never consults the
   filesystem: it must not check existence or resolve symlinks (a symlink
   inside the root is returned as the path inside the root).
3. **Containment.** The result must be `root` itself or a path below it,
   compared segment by segment: `/srv/www-private` and `/srv/wwwx` are **not**
   below `/srv/www`. Anything else raises `PathTraversalError`. `..` segments
   are fine as long as the resolved result stays inside (`/docs/../index.html`
   under `/srv/www` resolves to `/srv/www/index.html`).
4. **Root forms.** `root` is an absolute POSIX path and may be given with a
   trailing slash (`/srv/www/` behaves exactly like `/srv/www`). It may also be
   `/`, in which case every request resolves inside it.
5. **NUL bytes.** A decoded path containing a NUL character (`\x00`) raises
   `PathTraversalError`.
6. **Return value.** The returned path is absolute and normalized: no `.` or
   `..` segments, no repeated slashes and no trailing slash (the root itself
   is returned as the normalized root, e.g. `/srv/www`, or `/`).

## Allowed paths
- `staticserve/`
- `tests/`

## Non-goals
- No filesystem access (no `os.path.realpath`, `os.path.exists`, `open`).
- No handling of query strings, fragments or backslashes (backslash is an
  ordinary character on POSIX).
- No change to the function's signature or the exception class.
- No third-party dependencies; Python 3.8+ standard library only.

## Acceptance criteria
- Both findings are fixed and every rule above holds.
- The visible test suite passes, and new regression tests cover the findings.

## Test commands
- `python3 -m unittest discover -s tests -v`

## Handoff
Report the root cause, the files you changed, and the test command output
before and after the fix.
