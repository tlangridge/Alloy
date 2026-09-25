import unittest

from termtext.layout import pad, truncate, wrap
from termtext.width import text_width

KAN, JI = '漢', '字'          # 漢 字 (2 columns each)
TE, SU, TO = 'テ', 'ス', 'ト'   # テ ス ト (2 columns each)
ACUTE = '́'                      # combining acute (0 columns)
E_ACUTE = 'e' + ACUTE                 # é, decomposed: 2 code points, 1 column
FULL_A = 'Ａ'                     # fullwidth A (2 columns)
IDEO_SPACE = '　'                 # ideographic space (2 columns, not a separator)
ZWJ = '‍'


class WrapBasicsTests(unittest.TestCase):
    def test_width_validation(self):
        for bad in (0, 1, -4):
            with self.assertRaises(ValueError):
                wrap('abc', bad)

    def test_exact_fit_and_greedy(self):
        self.assertEqual(wrap('aa bb cc', 5), ['aa bb', 'cc'])
        self.assertEqual(wrap('the quick brown fox', 9), ['the quick', 'brown fox'])

    def test_spaces_collapse_and_are_trimmed(self):
        self.assertEqual(wrap('  a   b  ', 10), ['a b'])
        self.assertEqual(wrap('a    bb', 3), ['a', 'bb'])

    def test_paragraphs(self):
        self.assertEqual(wrap('a b\n\nc', 10), ['a b', '', 'c'])
        self.assertEqual(wrap('', 5), [''])
        self.assertEqual(wrap('ab\n', 5), ['ab', ''])
        self.assertEqual(wrap('x\n   \ny', 5), ['x', '', 'y'])


class WrapWidthTests(unittest.TestCase):
    def test_cjk_words_measured_in_columns(self):
        self.assertEqual(wrap(KAN + JI + ' ' + TE + SU + TO, 6), [KAN + JI, TE + SU + TO])
        self.assertEqual(wrap(KAN + JI + ' ' + TE, 7), [KAN + JI + ' ' + TE])

    def test_combining_marks_take_no_width(self):
        cafe = 'caf' + E_ACUTE
        self.assertEqual(wrap(cafe + ' ok', 7), [cafe + ' ok'])
        self.assertEqual(wrap(E_ACUTE * 5, 5), [E_ACUTE * 5])

    def test_fullwidth_letters(self):
        self.assertEqual(wrap(FULL_A * 2 + ' ' + FULL_A, 5), [FULL_A * 2, FULL_A])

    def test_zero_width_joiner_stays_inside_word(self):
        self.assertEqual(wrap('ab' + ZWJ + 'c d', 5), ['ab' + ZWJ + 'c d'])

    def test_every_line_fits(self):
        text = ('Configuration ' + KAN * 7 + ' caf' + E_ACUTE + ' ' + FULL_A * 3 + 'xyz '
                + 'e' + ACUTE * 2 + 'long' * 4)
        for width in range(2, 16):
            lines = wrap(text, width)
            too_wide = [l for l in lines if text_width(l) > width]
            self.assertEqual(too_wide, [], width)
            self.assertEqual(''.join(lines).replace(' ', ''), text.replace(' ', ''), width)


class WrapLongWordTests(unittest.TestCase):
    def test_long_ascii_word_starts_new_line_and_chunks(self):
        self.assertEqual(wrap('ab abcdefghij xy', 5), ['ab', 'abcde', 'fghij', 'xy'])

    def test_last_chunk_accepts_following_words(self):
        self.assertEqual(wrap('abcdefg x', 5), ['abcde', 'fg x'])

    def test_cjk_long_word_chunks_by_columns(self):
        self.assertEqual(wrap(KAN + JI + KAN + JI + KAN, 5), [KAN + JI, KAN + JI, KAN])

    def test_wide_cluster_moves_to_next_chunk(self):
        self.assertEqual(wrap('a' + KAN + JI, 4), ['a' + KAN, JI])
        self.assertEqual(wrap('abc' + KAN + 'd', 4), ['abc', KAN + 'd'])

    def test_combining_marks_never_split_from_base(self):
        lines = wrap(E_ACUTE * 6, 4)
        self.assertEqual(lines, [E_ACUTE * 4, E_ACUTE * 2])
        lines = wrap('ab' + 'c' + ACUTE + ACUTE + 'de', 3)
        self.assertEqual(lines, ['abc' + ACUTE + ACUTE, 'de'])

    def test_ideographic_space_is_not_a_separator(self):
        self.assertEqual(wrap(KAN + IDEO_SPACE + JI, 4), [KAN + IDEO_SPACE, JI])


class TruncateTests(unittest.TestCase):
    def test_fits_unchanged(self):
        self.assertEqual(truncate('hello', 5), 'hello')
        self.assertEqual(truncate(KAN + JI, 4), KAN + JI)
        self.assertEqual(truncate('caf' + E_ACUTE, 4), 'caf' + E_ACUTE)

    def test_basic_cut(self):
        self.assertEqual(truncate('hello world', 8), 'hello w…')

    def test_trailing_spaces_removed_before_ellipsis(self):
        self.assertEqual(truncate('hello world', 7), 'hello…')
        self.assertEqual(truncate('ab   cdef', 6, ellipsis='..'), 'ab..')

    def test_wide_characters(self):
        self.assertEqual(truncate(KAN + JI + TE + SU + TO, 6), KAN + JI + '…')
        self.assertEqual(text_width(truncate(KAN + JI + TE + SU + TO, 6)), 5)

    def test_combining_marks_kept_with_base(self):
        self.assertEqual(truncate(E_ACUTE * 4, 3), E_ACUTE * 2 + '…')
        self.assertEqual(truncate('ab' + E_ACUTE + ACUTE + 'cd', 4, ellipsis='.'),
                         'ab' + E_ACUTE + ACUTE + '.')

    def test_custom_and_empty_ellipsis(self):
        self.assertEqual(truncate('abcdefgh', 6, ellipsis='...'), 'abc...')
        self.assertEqual(truncate('abcdefgh', 3, ellipsis=''), 'abc')
        self.assertEqual(truncate(KAN + JI, 3, ellipsis=''), KAN)

    def test_validation(self):
        with self.assertRaises(ValueError):
            truncate('abcdef', 2, ellipsis='...')
        with self.assertRaises(ValueError):
            truncate('abcdef', -1, ellipsis='')


class PadTests(unittest.TestCase):
    def test_left_right_center_by_columns(self):
        self.assertEqual(pad(KAN + JI, 7), KAN + JI + '   ')
        self.assertEqual(pad(KAN + JI, 7, 'right'), '   ' + KAN + JI)
        self.assertEqual(pad(KAN + JI, 7, 'center'), ' ' + KAN + JI + '  ')
        self.assertEqual(pad('ab', 6, 'center'), '  ab  ')

    def test_combining_text(self):
        self.assertEqual(pad('caf' + E_ACUTE, 6), 'caf' + E_ACUTE + '  ')

    def test_wide_text_unchanged_and_bad_align(self):
        self.assertEqual(pad(KAN * 3, 4, 'center'), KAN * 3)
        with self.assertRaises(ValueError):
            pad('x', 4, 'middle')


if __name__ == '__main__':
    unittest.main()
