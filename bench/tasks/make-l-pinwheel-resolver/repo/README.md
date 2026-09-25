# pinwheel

Dependency resolver for internal deploy bundles. A `Registry` holds published
releases (`name`, `MAJOR.MINOR.PATCH`, dependencies as constraint strings,
optional `yanked` flag). `resolve()` picks one version per required package and
`install_order()` sorts the result for installation; `install.plan()` combines
both for the deploy tool.

```python
from pinwheel import Registry
from pinwheel.install import plan
reg = Registry()
reg.add('web', '2.1.0', {'http': '^1.4', 'log': '~0.3'})
reg.add('http', '1.4.2', {'log': '>=0.3'})
reg.add('log', '0.3.9')
plan(reg, {'web': '^2'})   # ['log==0.3.9', 'http==1.4.2', 'web==2.1.0']
```

Constraint syntax, the resolution algorithm and the ordering rules are
specified in the task specification.

## Tests

```
python3 -m unittest discover -s tests -v
```
