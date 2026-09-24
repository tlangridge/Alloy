# envfile

Loads `.env` files for local development of our services.

```python
from envfile import load_env, parse_env

parse_env("DEBUG=1\nNAME=api\n")     # {'DEBUG': '1', 'NAME': 'api'}
load_env(".env")                     # copies into os.environ without overriding
```

Run the tests with `python3 -m unittest discover -s tests -v`.
