# SPEC: `--name=value`, short-option bundling and `--` in bakctl's parser

## Goal
`bakctl` ships a tiny dependency-free argument parser (`bakctl/args.py`).
Users expect the usual POSIX/GNU conveniences, which it lacks. Extend
`ArgParser.parse` so it supports `--name=VALUE`, bundled short options and the
`--` end-of-options marker, exactly as specified below, without changing any
behavior that already works.

## Current behavior
- `--output=out.tar` raises `UsageError: unknown option: --output=out.tar`.
- `-vn` (two short flags) raises `UsageError: unknown option: -vn`, and so does
  `-oout.tar`.
- `--` raises `UsageError: unknown option: --`, so a file literally named
  `-v` cannot be passed as a positional argument.

Behavior that already works and must be kept: `--name VALUE` and `-s VALUE`
take the *next* argument as the value even if it begins with `-`
(`--output -v` sets `output` to `"-v"`); a value option at the very end of
`argv` raises `UsageError`; unknown options raise `UsageError`; a lone `-` is a
positional argument; options and positionals may be interleaved; repeatable
options (`repeat=True`) collect values in command-line order; for other value
options the last occurrence wins; flags are set to `True`; every `parse` call
starts from fresh defaults.

## Desired behavior
The public API is unchanged: `ArgParser()`, `add_flag(name, short=None)`,
`add_option(name, short=None, repeat=False, default=None)`, and
`parse(argv) -> (values: dict, positionals: list)` raising `UsageError` for
invalid command lines.

1. **`--name=VALUE`.** A long option may be written `--name=VALUE`. The name
   is the text between `--` and the first `=`; the value is everything after
   that first `=`, and may be empty or contain further `=` characters
   (`--output=` sets `""`; `--output=a=b` sets `"a=b"`). If the name is
   unknown, `UsageError`. If the option is a flag, `--flag=anything`
   (including `--flag=`) raises `UsageError`.
2. **Short-option bundles.** An argument that starts with a single `-`
   followed by one or more characters is a bundle of short options, processed
   left to right: `-vn` is equivalent to `-v -n`. When a letter names a
   value-taking option, the rest of the bundle after that letter is its value
   if non-empty (`-oout.tar` sets `output` to `"out.tar"`; `-voout.tar` sets
   `verbose` and `output="out.tar"`; `-ov` sets `output="v"`, it does not set
   `verbose`); if that letter is the last character of the argument, the next
   argument is its value (`-vo out.tar`), and if there is no next argument,
   `UsageError`. Any character of the bundle that is processed as an option
   and is not a registered short option (`-vz`, `-v-`) raises `UsageError`.
3. **`--`.** The first argument that is exactly `--` ends option processing:
   it is dropped, and every following argument is a positional verbatim, even
   if it starts with `-` or is another `--`. An argument consumed as an
   option's value is not an end-of-options marker (`--output -- -v` sets
   `output` to `"--"` and sets `verbose`).
4. **Consistency.** The new spellings behave exactly like the existing ones:
   repeatable options collect values from every spelling in command-line order
   (`--exclude=a -xb -x c --exclude d` gives `["a", "b", "c", "d"]`), and for a
   non-repeatable option the last occurrence wins whatever its spelling. All
   behavior listed under *Current behavior* as already working is preserved.

## Allowed paths
- `bakctl/`
- `tests/`

## Non-goals
- No abbreviations of long option names, no negative-number heuristics, no
  help/usage text generation, no changes to `add_flag`/`add_option`.
- Exact `UsageError` message wording is not specified.
- No third-party dependencies; Python 3.8+ standard library only.

## Acceptance criteria
- Every rule above holds, including every example given.
- The visible test suite passes; add tests of your own for the new rules.

## Test commands
- `python3 -m unittest discover -s tests -v`

## Handoff
Report the files you changed, the test command output, and any rule you
found ambiguous and how you resolved it.
