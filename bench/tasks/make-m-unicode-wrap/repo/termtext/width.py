"""Display width of text in a monospace terminal.

* zero-width: combining marks (Mn/Me or a non-zero combining class) and the
  format characters ZWSP, ZWNJ, ZWJ, WORD JOINER and BOM;
* two columns: East Asian Wide (W) and Fullwidth (F) characters;
* one column: everything else.
"""
import unicodedata

ZERO_WIDTH = frozenset('​‌‍⁠﻿')


def char_width(ch):
    if ch in ZERO_WIDTH or unicodedata.combining(ch) or unicodedata.category(ch) in ('Mn', 'Me'):
        return 0
    if unicodedata.east_asian_width(ch) in ('W', 'F'):
        return 2
    return 1


def text_width(text):
    return sum(char_width(ch) for ch in text)
