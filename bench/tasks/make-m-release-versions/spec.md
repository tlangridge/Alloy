# SPEC: ordering and rollout constraints for firmware release tags

## Goal
Give `fwver.Version` a correct total ordering and implement the rollout
constraint language in `fwver/constraints.py` (`satisfies`, `max_satisfying`,
`sort_versions`), so the fleet updater can pick the newest build a device may
install. Parsing (`fwver.version.parse`) already follows the grammar in
`fwver/version.py` and must keep doing so.

## Current behavior
`Version` has no ordering (`<` raises `TypeError`) and its equality compares the
rendered string, so build metadata makes equal releases unequal.
`constraints.satisfies` only understands `>= <= > < == !=`, silently ignores
clauses it cannot parse, knows nothing about `~`, `^` or pre-releases, and
`max_satisfying` / `sort_versions` do not exist.

## Desired behavior

### Ordering (`fwver/version.py`, class `Version`)
1. Versions compare by `epoch` first (higher epoch is always newer), then by
   `(major, minor, patch)` numerically, then by *phase*, then by channel number.
2. Phase order for the same epoch and numbers:
   `dev < alpha < beta < rc < final < hotfix` (a final release has no channel;
   `hotfix` is a post-release and sorts **after** the final release).
   Channel numbers compare numerically (`rc.2 < rc.10`); a channel written
   without a number has number 0 (`1.0-rc` == `1.0-rc.0`).
3. Build metadata and the optional `v` prefix never affect ordering or
   equality, and a missing patch is 0: `1.2`, `1.2.0`, `v1.2.0+b7` are all
   equal. Equal versions must have equal hashes.
4. `Version` supports `==, !=, <, <=, >, >=` between `Version` objects.
   Comparing with a non-`Version` returns `NotImplemented` (so `==` is `False`
   and ordering operators raise `TypeError`).

### Constraints (`fwver/constraints.py`)
Public API:
- `class InvalidConstraint(ValueError)`
- `satisfies(version, spec) -> bool` — `version` is a `Version` or a tag string
  (a bad tag string raises `fwver.InvalidVersion`).
- `max_satisfying(tags, spec) -> str | None`
- `sort_versions(tags) -> list[str]`

5. **Syntax.** A spec is one or more clauses separated by commas; whitespace
   around clauses and between an operator and its version is ignored. A clause
   is an optional operator followed by a tag: `>=`, `<=`, `>`, `<`, `==`, `!=`,
   `~`, `^`; no operator means `==`. A version satisfies a spec only if it
   satisfies **every** clause. An empty spec, an empty clause (e.g. `1.0,,2.0`
   or a trailing comma), an unknown operator (e.g. `=>1.0`, `=1.0`) or an
   invalid tag in a clause raises `InvalidConstraint`.
6. **Comparison clauses** use the ordering above, so `==1.2` matches
   `1.2.0+b3`, and `<=1.2.0` does not match `1.2.0-hotfix.1`.
7. **Tilde** `~V`: at least `V` and less than the final release
   `<V.epoch>!<V.major>.<V.minor + 1>.0` (same epoch). `~1.4` and `~1.4.0`
   both mean `>=1.4.0, <1.5.0`; `~1.4.2` means `>=1.4.2, <1.5.0`.
8. **Caret** `^V`: at least `V` and less than (same epoch)
   `<V.major + 1>.0.0` when `V.major > 0`, or `0.<V.minor + 1>.0` when
   `V.major == 0`. There is **no** special case for `0.0.x`:
   `^0.0.3` means `>=0.0.3, <0.1.0`.
9. **Pre-releases.** A version whose channel is `dev`, `alpha`, `beta` or `rc`
   satisfies a spec only if it satisfies every clause **and** at least one
   clause's tag is itself a pre-release with the same epoch, major, minor and
   patch as the version. Otherwise pre-releases never match, even when they are
   inside the range (so `^1.4.0` does not match `2.0.0-rc.1`, and `>=1.0` does
   not match `1.5.0-rc.1`, but `>=1.5.0-beta` matches `1.5.0-rc.1` and not
   `1.6.0-alpha`). `hotfix` versions are not pre-releases and match normally.
10. **max_satisfying(tags, spec)** parses the spec first (an invalid spec
    raises `InvalidConstraint` even for an empty `tags`), ignores entries of
    `tags` that are not valid tags, and returns the tag string exactly as given
    (not normalised) of the highest satisfying version, or `None` if none
    satisfies. When several satisfying tags are equal versions (e.g. differ only
    in build metadata or `v` prefix), the one appearing first in `tags` wins.
11. **sort_versions(tags)** returns a new list of the given tag strings (exactly
    as given) sorted ascending by version; equal versions keep their input
    order. An invalid tag raises `fwver.InvalidVersion`.

## Allowed paths
`fwver/`, `tests/`, `README.md`.

## Non-goals
Changing the tag grammar or `parse`; OR (`||`) groups; wildcard versions
(`1.x`); caching.

## Acceptance criteria
- Rules 1–11 hold; existing visible tests pass; add tests of your own.
- Standard library only, Python 3.8+.

## Test commands
`python3 -m unittest discover -s tests -v`

## Handoff
Summarise the ordering key and how each operator is evaluated, list changed
files and paste the test output.
