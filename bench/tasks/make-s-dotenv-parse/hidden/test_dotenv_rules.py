import os
import tempfile
import unittest

from envfile import DotenvError, load_env, parse_env


class LineTests(unittest.TestCase):
    def test_empty_text(self):
        self.assertEqual(parse_env(''), {})
        self.assertEqual(parse_env('\n\n   \n'), {})

    def test_comments_and_blank_lines_ignored(self):
        text = '# top\n\n  \t\nA=1\n    # indented\n\t# tabbed\nB=2\n'
        self.assertEqual(parse_env(text), {'A': '1', 'B': '2'})

    def test_crlf_line_endings(self):
        self.assertEqual(parse_env('A=1\r\nB="two"\r\nC=3 # c\r\n'), {'A': '1', 'B': 'two', 'C': '3'})


class AssignmentTests(unittest.TestCase):
    def test_whitespace_around_key_and_equals(self):
        self.assertEqual(parse_env('  NAME  =  api  '), {'NAME': 'api'})
        self.assertEqual(parse_env('\tNAME\t=\tapi'), {'NAME': 'api'})

    def test_export_prefix_discarded(self):
        self.assertEqual(parse_env('export TOKEN=abc'), {'TOKEN': 'abc'})
        self.assertEqual(parse_env('export\t  TOKEN = "abc"'), {'TOKEN': 'abc'})
        self.assertEqual(parse_env('  export TOKEN=abc'), {'TOKEN': 'abc'})

    def test_key_starting_with_export(self):
        self.assertEqual(parse_env('exporter=1'), {'exporter': '1'})
        self.assertEqual(parse_env('export_dir=/tmp/x'), {'export_dir': '/tmp/x'})

    def test_valid_key_shapes(self):
        self.assertEqual(parse_env('_A=1\na_b_9=2\nZ=3'), {'_A': '1', 'a_b_9': '2', 'Z': '3'})

    def test_invalid_keys_rejected(self):
        for line in ('1ABC=x', 'MY-KEY=x', 'MY KEY=x', '=x', 'A.B=x'):
            with self.subTest(line=line):
                with self.assertRaises(DotenvError) as ctx:
                    parse_env(line)
                self.assertEqual(ctx.exception.lineno, 1)

    def test_missing_equals_rejected(self):
        with self.assertRaises(DotenvError):
            parse_env('export TOKEN')

    def test_value_may_contain_equals(self):
        self.assertEqual(parse_env('URL=postgres://u:p@h/db?sslmode=require'),
                         {'URL': 'postgres://u:p@h/db?sslmode=require'})


class UnquotedTests(unittest.TestCase):
    def test_spec_examples(self):
        cases = {
            'A=b # note': 'b',
            'A=b#c': 'b#c',
            'COLOR=#fff': '#fff',
            'EMPTY= # nothing': '',
            'A=': '',
            'MSG=hello world': 'hello world',
        }
        for line, expected in cases.items():
            with self.subTest(line=line):
                key = line.split('=', 1)[0]
                self.assertEqual(parse_env(line), {key: expected})

    def test_tab_before_hash_starts_comment(self):
        self.assertEqual(parse_env('A=b\t# c'), {'A': 'b'})

    def test_only_first_comment_marker_matters(self):
        self.assertEqual(parse_env('A=x#y z # c # d'), {'A': 'x#y z'})

    def test_url_fragment_kept(self):
        self.assertEqual(parse_env('HOME_URL=https://example.test/#top'), {'HOME_URL': 'https://example.test/#top'})

    def test_inner_whitespace_kept(self):
        self.assertEqual(parse_env('A=  a   b  '), {'A': 'a   b'})


class DoubleQuotedTests(unittest.TestCase):
    def test_hash_and_spaces_kept(self):
        self.assertEqual(parse_env('A="x # y"'), {'A': 'x # y'})
        self.assertEqual(parse_env('A="  padded  "'), {'A': '  padded  '})

    def test_escapes(self):
        self.assertEqual(parse_env(r'A="line1\nline2"'), {'A': 'line1\nline2'})
        self.assertEqual(parse_env(r'A="col1\tcol2"'), {'A': 'col1\tcol2'})
        self.assertEqual(parse_env(r'A="say \"hi\""'), {'A': 'say "hi"'})
        self.assertEqual(parse_env(r'A="C:\\temp"'), {'A': 'C:\\temp'})

    def test_unknown_escape_kept(self):
        self.assertEqual(parse_env(r'A="\d+\s"'), {'A': '\\d+\\s'})

    def test_escaped_backslash_before_closing_quote(self):
        self.assertEqual(parse_env('A="dir\\\\"'), {'A': 'dir\\'})

    def test_leading_space_before_quote(self):
        self.assertEqual(parse_env('A=   "x"'), {'A': 'x'})

    def test_empty_quotes(self):
        self.assertEqual(parse_env('A=""'), {'A': ''})

    def test_comment_after_closing_quote(self):
        self.assertEqual(parse_env('A="x"   # note'), {'A': 'x'})
        self.assertEqual(parse_env('A="x"   '), {'A': 'x'})

    def test_unterminated_rejected(self):
        for line in ('A="x', 'A="x\\"', 'A="'):
            with self.subTest(line=line):
                with self.assertRaises(DotenvError):
                    parse_env(line)

    def test_value_does_not_span_lines(self):
        with self.assertRaises(DotenvError) as ctx:
            parse_env('A=1\nB="first\nsecond"\n')
        self.assertEqual(ctx.exception.lineno, 2)


class SingleQuotedTests(unittest.TestCase):
    def test_literal_content(self):
        self.assertEqual(parse_env(r"A='a\nb'"), {'A': 'a\\nb'})
        self.assertEqual(parse_env(r"A='C:\\temp'"), {'A': 'C:\\\\temp'})

    def test_hash_and_double_quotes_kept(self):
        self.assertEqual(parse_env("A='x # \"y\"'"), {'A': 'x # "y"'})

    def test_comment_after_closing_quote(self):
        self.assertEqual(parse_env("A='x' # note"), {'A': 'x'})

    def test_unterminated_rejected(self):
        with self.assertRaises(DotenvError):
            parse_env("A='x")


class TrailingTextTests(unittest.TestCase):
    def test_text_after_closing_quote_rejected(self):
        for line in ('A="x" y', "A='x'y", 'A="x""y"', "A='x' 'y'"):
            with self.subTest(line=line):
                with self.assertRaises(DotenvError) as ctx:
                    parse_env('OK=1\n' + line)
                self.assertEqual(ctx.exception.lineno, 2)


class DuplicateAndErrorTests(unittest.TestCase):
    def test_last_value_wins(self):
        self.assertEqual(parse_env('A=1\nB=2\nA=3\n'), {'A': '3', 'B': '2'})

    def test_lineno_counts_blank_and_comment_lines(self):
        text = '# header\n\nA=1\n   \nnot an assignment\n'
        with self.assertRaises(DotenvError) as ctx:
            parse_env(text)
        self.assertEqual(ctx.exception.lineno, 5)

    def test_error_is_value_error(self):
        with self.assertRaises(ValueError):
            parse_env('BAD-KEY=1')


class LoaderTests(unittest.TestCase):
    def test_load_env_uses_new_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, '.env')
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write('export A="x # y"\nB=2 # two\n')
            environ = {'B': 'keep'}
            values = load_env(path, environ)
            self.assertEqual(values, {'A': 'x # y', 'B': '2'})
            self.assertEqual(environ, {'A': 'x # y', 'B': 'keep'})


if __name__ == '__main__':
    unittest.main()
