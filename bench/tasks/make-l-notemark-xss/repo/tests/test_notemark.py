import unittest

from notemark import to_html


class RenderTests(unittest.TestCase):
    def test_paragraphs_and_breaks(self):
        self.assertEqual(to_html('first line\n  second line  \n\n\nnext'),
                         '<p>first line<br>second line</p>\n<p>next</p>')

    def test_inline_markup(self):
        self.assertEqual(to_html('**bold** and _em_ and `x < y`'),
                         '<p><strong>bold</strong> and <em>em</em> and <code>x &lt; y</code></p>')

    def test_links(self):
        self.assertEqual(to_html('[the docs](https://docs.example.com/a?b=1)'),
                         '<p><a href="https://docs.example.com/a?b=1">the docs</a></p>')
        self.assertEqual(to_html('[home](/)'), '<p><a href="/">home</a></p>')

    def test_plain_javascript_link_is_not_linked(self):
        self.assertEqual(to_html('[click](javascript:alert%281%29)'), '<p>click</p>')

    def test_mentions_and_escapes(self):
        self.assertEqual(to_html('ping @kim_2 \\@not \\*x\\*'),
                         '<p>ping <a href="/u/kim_2">@kim_2</a> @not *x*</p>')

    def test_text_is_escaped(self):
        self.assertEqual(to_html('<img src=x onerror=alert(1)>'), '<p>&lt;img src=x onerror=alert(1)&gt;</p>')


if __name__ == '__main__':
    unittest.main()
