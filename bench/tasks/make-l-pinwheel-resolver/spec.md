# SPEC: version constraints, backtracking resolver and install order (pinwheel)

## Goal

Implement `pinwheel.Constraint`, `pinwheel.resolve` and
`pinwheel.install_order` exactly as specified. When several valid resolutions
exist, the algorithm below decides which one is returned, so follow it
precisely — tests check the chosen versions, not just validity.

## Current behavior

`pinwheel/version.py` (plain `MAJOR.MINOR.PATCH` versions), `errors.py`,
`registry.py` and `install.py` are complete. `Constraint.parse`,
`Constraint.allows`, `resolve` and `install_order` raise
`NotImplementedError` (so `Registry.add` with dependencies fails too).

## Desired behavior

### Constraints (`pinwheel/constraint.py`)

`Constraint.parse(text) -> Constraint` raises `pinwheel.InvalidConstraint`
for invalid text. `Constraint.allows(version) -> bool` accepts a `Version` or
a version string.

1. Syntax: `constraint := group ("||" group)*`, `group := term ("," term)*`.
   A version matches a constraint when it matches **every** term of **at
   least one** group. Whitespace around groups, terms and between an operator
   and its version is ignored. An empty constraint, group or term is invalid.
2. A *partial version* is `M`, `M.m` or `M.m.p` (decimal integers without
   leading zeros, `0` allowed). Its *floor* fills missing parts with 0
   (`1.2` → `1.2.0`). For a partial with missing parts, *next-up* is the
   smallest version above everything it covers: `M.m` → `M.(m+1).0`,
   `M` → `(M+1).0.0`.
3. Terms:
   - `*` matches everything. `M.*` means `>=M.0.0, <(M+1).0.0`; `M.m.*` means
     `>=M.m.0, <M.(m+1).0`.
   - `=P` or a bare `P`: a full version matches exactly; a partial matches
     every version it covers (`1.2` = `1.2.*`, `=1` = `1.*`).
   - `!=P`: the negation of `=P`.
   - `>=P` → `>= floor`; `<P` → `< floor` (`<2` is `<2.0.0`).
   - `>P`: full → strictly greater; partial → `>= next-up` (`>1.2` is `>=1.3.0`).
   - `<=P`: full → less or equal; partial → `< next-up` (`<=1.2` is `<1.3.0`).
   - `^P` (compatible): `>= floor` and below: `(M+1).0.0` if `M > 0`;
     otherwise (`M == 0`): `1.0.0` for `^0`; `0.(m+1).0` if `m > 0`; `0.1.0` for
     `^0.0`; `0.0.(p+1)` for `^0.0.p`. (`^1.2.3` <2.0.0, `^0.2.3` <0.3.0,
     `^0.0.3` <0.0.4.)
   - `~P` (approximately): `>= floor` and below `M.(m+1).0` when `m` is given,
     else below `(M+1).0.0` (`~1.2.3` <1.3.0, `~1` <2.0.0).
4. Everything else is invalid, including: unknown or doubled operators (`>>1`,
   `=>1`, `==1`), an operator combined with a wildcard (`>=1.*`), `^*`, `~*`,
   wildcards not at the end (`1.*.3`), four components, leading zeros (`01.2`),
   a `v` prefix, and empty terms/groups (`1.2 ||`, `,1.0`).

### Resolution (`pinwheel.resolve(registry, requirements, locked=None)`)

`requirements` maps package name → constraint text (the *root
requirements*); `locked` optionally maps package name → version string. The
result is a dict mapping each resolved package name → version string.

5. Before searching, every root requirement is parsed (invalid →
   `InvalidConstraint`), and if any root requirement names a package the
   registry does not know, `pinwheel.UnknownPackage` is raised with `.name` =
   the alphabetically smallest such name.
6. **Active requirements** are the root requirements plus, for every decided
   package, the dependencies of its decided version.
7. **Candidates** of a package, computed from the active requirements at the
   moment the package is chosen: the registry versions that satisfy every
   active constraint on it, excluding *yanked* versions — except that the
   locked version (if `locked` names this package, the version exists and
   satisfies every active constraint) is always a candidate, yanked or not.
   Candidate order: the locked version first (when it is a candidate), then
   the others from highest to lowest. A package the registry does not know has
   no candidates.
8. **Search** (depth-first, chronological backtracking):
   1. If every package named by an active requirement is decided, the search
      succeeds; the result is exactly the decided packages.
   2. Otherwise choose, among undecided packages named by an active
      requirement, the one with the **fewest candidates** (rule 7, computed
      now); ties go to the alphabetically smallest name.
   3. Try its candidates in order. A candidate is *inconsistent* — skipped —
      if one of its dependencies names an already-decided package whose
      decided version it does not allow, or names the package itself without
      allowing the candidate. The first consistent candidate is decided, its
      dependencies become active, and the search continues at step 1.
   4. If that continuation fails, the decision is undone (its dependencies stop
      being active) and the next candidate is tried. When no candidates remain,
      this choice fails and control returns to the previous decision. If the
      very first choice fails, raise `pinwheel.ResolutionError`.
   Candidate lists are not recomputed when backtracking to a choice; later
   choices are recomputed from the then-active requirements.
9. The result never contains packages that were only required by undone
   decisions, and does not depend on the order in which releases were added to
   the registry or on the order of keys in `requirements`.

### Install order (`pinwheel.install_order(registry, resolution)`)

10. Returns every package name of `resolution` such that each package comes
    after all of its dependencies (those of its resolved version that are in the
    resolution). Whenever several packages are ready, the alphabetically
    smallest comes first.
11. If the dependencies among the resolved packages contain a cycle,
    `install_order` raises `pinwheel.CycleError` whose `.members` is the sorted
    list of **every package that lies on at least one cycle** (including a
    package that depends on itself). Packages that merely depend on a cycle are
    not members. `resolve` itself does not reject cycles.

## Allowed paths

`pinwheel/`, `tests/`, `README.md`.

## Non-goals

- No pre-release or build-metadata versions.
- No explanation/"why" output for failures beyond the exception types above.
- No performance work beyond registries of a few dozen releases.

## Acceptance criteria

- All rules hold through the public API; `pinwheel/install.py` works unchanged.
- `python3 -m unittest discover -s tests -v` passes.
- Standard library only; Python 3.8+.

## Test commands

```
python3 -m unittest discover -s tests -v
```

## Handoff

Describe how your search implements rules 7–8 (especially candidate ordering,
the choice of the next package and backtracking), and list any rule you found
ambiguous.
