# roster

In-memory registry of community handles (the `@name` people are mentioned by).

* Handles are 3-20 word characters (letters, digits, underscore; any script).
* Each user has at most one handle and a handle belongs to at most one user.
* Handles are compared case-insensitively; the spelling the user typed is kept
  for display.

Run the tests with `python3 -m unittest discover -s tests -v`.
