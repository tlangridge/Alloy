# bakctl

Command-line front end for the backup agent. It deliberately has no
dependencies, so it ships its own tiny argument parser in `bakctl/args.py`.

```python
from bakctl.args import ArgParser

parser = ArgParser()
parser.add_flag('verbose', short='v')
parser.add_option('output', short='o')
parser.add_option('exclude', short='x', repeat=True)
values, positionals = parser.parse(['-v', '--output', 'out.tar', 'src/'])
# values == {'verbose': True, 'output': 'out.tar', 'exclude': []}
# positionals == ['src/']
```

Run the tests with `python3 -m unittest discover -s tests -v`.
