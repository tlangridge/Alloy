# notemark

The lightweight markup used in ticket comments. `notemark.to_html(source)`
renders untrusted user input to HTML that is inserted into the ticket page, so
the renderer is a security boundary.

Pipeline: `inline.py` (markup -> nodes) -> `render.py` (nodes -> HTML), using
`entities.py` (character references), `urls.py` (link policy) and
`escape.py` (output escaping).

## Rendering rules

- `\r\n` and `\r` become `\n`. Paragraphs are separated by blank lines (lines
  containing only spaces/tabs); each becomes `<p>…</p>` and paragraphs are
  joined with `\n`. Inside a paragraph each line is trimmed, empty lines are
  dropped and line ends become `<br>`.
- `**strong**` → `<strong>`, `_em_` → `<em>`; an unclosed marker is literal.
- `` `code` `` → `<code>…</code>`. Code content is shown **literally**: no
  markup and no character-reference decoding (`` `&lt;` `` shows `&lt;`).
- `\` before one of ``\ ` * _ [ ] ( ) < > @ & ! #`` makes that character literal.
- `[text](destination)` → link. The destination contains no spaces or
  newlines and ends at the first `)`. The text may contain markup except links:
  autolinks and mentions inside link text are shown as plain text.
- `<https://…>`, `<http://…>`, `<mailto:…>` (no spaces) → autolink whose text is
  the URL.
- `@name` (letters, digits, `_`; not preceded by one of those) →
  `<a href="/u/name">@name</a>`.
- Text: character references — `&amp; &lt; &gt; &quot; &apos;`, decimal
  `&#38;`, hex `&#x26;` (valid, non-zero, non-surrogate code points) — are
  decoded once and the result is escaped, so `AT&amp;T` and `AT&T` render the
  same. Unknown references stay literal (`&copy;` → `&amp;copy;`).
- Escaping: element content escapes `& < >`; attribute values also escape
  `"` and `'` (`&quot;`, `&#39;`).

## Link policy (links and autolinks)

1. Decode the character references in the destination **exactly once**.
2. Remove every tab, LF and CR anywhere, then strip C0 control characters
   (U+0000–U+001F) and spaces from both ends — browsers do the same before
   they look at a URL's scheme.
3. If the result is empty it is not linked. If it starts with a scheme
   (`[A-Za-z][A-Za-z0-9+.-]*` followed by `:`) the scheme, compared
   case-insensitively, must be `http`, `https` or `mailto`; otherwise it is not
   linked. Anything else is a relative URL and is allowed (`/docs`, `?q=1`,
   `foo/bar:baz` — a `/` before the `:` means there is no scheme).
4. Allowed: `<a href="URL">text</a>` where URL is the result of step 2,
   attribute-escaped (the original letter case is kept). Not allowed: only the
   link text is rendered (for an autolink, its URL as text).

## Tests

```
python3 -m unittest discover -s tests -v
```
