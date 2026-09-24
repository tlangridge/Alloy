# shipit

Internal release tool: deploys builds to targets, reports on releases and
shows deployment status.

```
python3 -m shipit --help
python3 -m shipit deploy --target k8s 2.3.0
python3 -m shipit report --format markdown 2.3.0
python3 -m shipit status
python3 -m shipit --plugins status
```

Renderers are looked up by name in `shipit/render/formats.py` and imported
lazily, because `shipit.render.pdf` is expensive to import (it builds font
metric tables). Only commands that actually produce a PDF should load it.

Run the tests with `python3 -m unittest discover -s tests -v`.
