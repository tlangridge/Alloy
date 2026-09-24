# logprune

Small cron helper that deletes rotated log files (`*.1`, `*.gz`, `*.old`, ...)
once they are older than a retention window.

```
python3 logprune.py --keep 14d /var/log/myapp
python3 logprune.py --keep 36h --dry-run /var/log/myapp
```

Retention is a whole number followed by a unit: `h` (hours), `d` (days) or
`w` (weeks). Invalid `--keep` values are reported by argparse as a usage error
(exit status 2), so cron mails a readable message instead of a traceback.

Run the tests with `python3 -m unittest discover -s tests -v`.
