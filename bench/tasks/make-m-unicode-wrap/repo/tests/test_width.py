import unittest

from termtext.width import char_width, text_width


class WidthTests(unittest.TestCase):
    def test_char_widths(self):
        self.assertEqual(char_width('a'), 1)
        self.assertEqual(char_width('漢'), 2)      # CJK ideograph
        self.assertEqual(char_width('Ａ'), 2)      # FULLWIDTH LATIN CAPITAL A
        self.assertEqual(char_width('́'), 0)      # COMBINING ACUTE ACCENT
        self.assertEqual(char_width('‍'), 0)      # ZERO WIDTH JOINER

    def test_text_width(self):
        self.assertEqual(text_width('café'), 4)
        self.assertEqual(text_width('漢字 ok'), 7)
