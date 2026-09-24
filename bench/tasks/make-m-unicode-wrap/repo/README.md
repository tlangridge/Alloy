# termtext

Fixed-width layout helpers for the CLI: display width (`termtext.width`) and
wrapping / truncating / padding (`termtext.layout`). Output goes to terminals,
so everything is measured in display columns, not code points: CJK and
fullwidth characters take two columns, combining marks take none.

Run the tests with `python3 -m unittest discover -s tests -v`.
