# tagstats

Counts hashtags in a plain-text export of posts (one post per line) and prints
the most common ones.

```
python3 tagstats.py data/posts.txt --top 5
```

Tags are case-insensitive (`#Rust` and `#rust` are the same tag). Output rows
look like `1. #perf (4)`.

Run the tests with `python3 -m unittest discover -s tests -v`.
