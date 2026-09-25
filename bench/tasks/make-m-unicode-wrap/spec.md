# SPEC: display-width-aware wrap, truncate and pad

## Goal
Make `termtext/layout.py` lay text out by terminal display columns (as measured
by the existing `termtext.width.char_width` / `text_width`) instead of code
points, and add `truncate`. The CLI's tables currently misalign and cut accents
off letters whenever names contain CJK text or decomposed accents.

## Current behavior
`wrap` delegates to `textwrap`, which counts code points: a line of CJK text
can be twice as wide as requested, and long words can be split between a letter
and its combining accent. `pad` uses `str.ljust`/`rjust` (code points) and has
no centring. There is no `truncate`.

## Desired behavior
Definitions: widths come from `termtext.width` (do not change that module). A
**cluster** is one character of non-zero width together with every zero-width
character that immediately follows it; zero-width characters at the very start
of a word or text belong to the first cluster. Clusters are never split by
`wrap` or `truncate`. A **space** means U+0020 only (other whitespace, such as
the ideographic space U+3000, is an ordinary character).

### `wrap(text, width) -> list[str]`
1. `width` must be an `int` >= 2, else `ValueError`.
2. `text` is split on `"\n"` into paragraphs, each wrapped independently and
   the results concatenated in order. A paragraph with no words (empty or only
   spaces) produces exactly one empty line `""`. So `wrap("", 5) == [""]` and
   `wrap("ab\n", 5) == ["ab", ""]`.
3. Words are maximal runs of non-space characters. A line is words joined by
   exactly one space, with no leading or trailing spaces.
4. Greedy filling: a word is added to the current line if the line is empty
   and the word fits (`text_width(word) <= width`), or if
   `text_width(line) + 1 + text_width(word) <= width`; otherwise the current
   line is finished and the word starts a new line.
5. A word wider than `width` always starts on a new line (a non-empty current
   line is finished first) and is broken into chunks: each chunk takes as many
   whole clusters, in order, as fit in `width` columns. A two-column cluster
   that does not fit in the one remaining column goes to the next chunk. All
   chunks but the last are finished lines; the last chunk becomes the current
   line, and following words may join it under rule 4.
6. Every returned line has display width <= `width`.

### `truncate(text, width, ellipsis='…') -> str`
7. `width` must be an `int` >= 0 and `text_width(ellipsis) <= width`, else
   `ValueError`.
8. If `text_width(text) <= width`, return `text` unchanged.
9. Otherwise return the longest prefix of `text` made of whole clusters whose
   width is <= `width - text_width(ellipsis)`, with trailing spaces removed,
   followed by `ellipsis`. (`ellipsis=''` is allowed.)

### `pad(text, width, align='left') -> str`
10. Add spaces so the result is exactly `width` display columns: `'left'`
    puts them after the text, `'right'` before, `'center'` puts
    `extra // 2` before and the rest after. If the text is already `width`
    columns or wider it is returned unchanged. Any other `align` raises
    `ValueError`.

## Allowed paths
`termtext/`, `tests/`, `README.md`.

## Non-goals
Hyphenation, tab expansion, bidirectional text, emoji/ZWJ-sequence widths
beyond what `termtext.width` reports, grapheme rules beyond the cluster
definition above, and inputs containing control characters other than `"\n"`.

## Acceptance criteria
- Rules 1–10 hold; existing tests pass; add tests of your own.
- Standard library only, Python 3.8+.

## Test commands
`python3 -m unittest discover -s tests -v`

## Handoff
Describe how clusters and chunking are handled, list changed files and paste
the test output.
