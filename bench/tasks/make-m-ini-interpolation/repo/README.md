# confkit

INI-style configuration loader for the deploy tools.

```ini
[DEFAULT]
root = /srv/app
logs = ${root}/logs        ; inherited by every section, resolved per section

[worker]
root = /srv/worker          ; so worker's logs is /srv/worker/logs
queues = high,
    default,                ; indented lines continue the value
    low
```

* `[section]` headers; `key = value` or `key: value` entries (keys are
  case-insensitive, section names are case-sensitive).
* Comment lines start with `#` or `;`; inline comments need whitespace before
  the `#`/`;`. Comment lines inside a multi-line value are skipped; a blank line
  ends the value. Continuation pieces are joined with single spaces.
* `${key}` (same section, then `[DEFAULT]`), `${section:key}`, and `$$` for a
  literal dollar. Values inherited from `[DEFAULT]` are interpolated in the
  inheriting section's context. `[DEFAULT]` itself is not returned as a
  section.
* Every `ConfigError` carries `lineno`: the line on which the offending entry
  or header **starts** (for a multi-line value, its first line), and
  `str(err)` is `"line N: message"`.

Run the tests with `python3 -m unittest discover -s tests -v`.
