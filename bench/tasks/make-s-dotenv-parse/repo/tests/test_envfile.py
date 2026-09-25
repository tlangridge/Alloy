import os
import tempfile
import unittest

from envfile import DotenvError, load_env, parse_env


class ParseEnvTests(unittest.TestCase):
    def test_simple_assignments(self):
        self.assertEqual(parse_env('DEBUG=1\nNAME=api\n'), {'DEBUG': '1', 'NAME': 'api'})

    def test_blank_lines_and_comments(self):
        text = '# settings\n\nPORT=8080\n   # indented comment\n'
        self.assertEqual(parse_env(text), {'PORT': '8080'})

    def test_double_quoted_value(self):
        self.assertEqual(parse_env('GREETING="hello world"'), {'GREETING': 'hello world'})

    def test_inline_comment(self):
        self.assertEqual(parse_env('PORT=8080 # default'), {'PORT': '8080'})

    def test_line_without_equals(self):
        with self.assertRaises(DotenvError) as ctx:
            parse_env('A=1\nnonsense\n')
        self.assertEqual(ctx.exception.lineno, 2)


class LoadEnvTests(unittest.TestCase):
    def test_load_does_not_override_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, '.env')
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write('A=1\nB=2\n')
            environ = {'A': 'keep'}
            load_env(path, environ)
            self.assertEqual(environ, {'A': 'keep', 'B': '2'})
            load_env(path, environ, override=True)
            self.assertEqual(environ, {'A': '1', 'B': '2'})


if __name__ == '__main__':
    unittest.main()
