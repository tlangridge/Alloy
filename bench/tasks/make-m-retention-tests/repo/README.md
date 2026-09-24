# retention

Plans which database backups to keep with a grandfather-father-son policy
(daily / weekly / monthly slots, pinned backups, an optional maximum age).
`retention.plan()` is pure: the caller passes `now`, and the backup agent
executes the returned plan.

Run the tests with `python3 -m unittest discover -s tests -v`.
