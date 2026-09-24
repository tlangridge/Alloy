import unittest

from confkit import ConfigError, load

SAMPLE = """\
# deploy settings
[DEFAULT]
root = /srv/app
logs = ${root}/logs

[web]
port = 8080
workers = 4   ; per host
url = http://example.test/#top

[db]
host = db.internal
dsn = postgres://${host}:5432/app
"""


class LoadTests(unittest.TestCase):
    def test_basic_values(self):
        cfg = load(SAMPLE)
        self.assertEqual(cfg.sections(), ['web', 'db'])
        self.assertEqual(cfg.getint('web', 'port'), 8080)
        self.assertEqual(cfg.get('web', 'workers'), '4')
        self.assertEqual(cfg.get('web', 'url'), 'http://example.test/#top')
        self.assertEqual(cfg.get('db', 'dsn'), 'postgres://db.internal:5432/app')
        self.assertEqual(cfg.get('db', 'logs'), '/srv/app/logs')

    def test_error_line_numbers(self):
        with self.assertRaises(ConfigError) as ctx:
            load('[a]\nx = 1\nnonsense\n')
        self.assertEqual(ctx.exception.lineno, 3)
        self.assertEqual(str(ctx.exception), 'line 3: expected "key = value" or "[section]"')

    def test_undefined_reference(self):
        with self.assertRaises(ConfigError) as ctx:
            load('[a]\nx = ${nope}\n')
        self.assertEqual(ctx.exception.lineno, 2)


if __name__ == '__main__':
    unittest.main()
