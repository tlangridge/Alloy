"""PDF renderer. Expensive to import: builds font metric tables up front."""
import unicodedata

# Stand-in for the real font-metrics build that dominates start-up time.
GLYPH_WIDTHS = {cp: (2 if unicodedata.east_asian_width(chr(cp)) in 'WF' else 1)
                for cp in range(0x3000)}


class PdfRenderer:
    def render(self, title, body):
        width = sum(GLYPH_WIDTHS.get(ord(ch), 1) for ch in body)
        return '%%PDF-1.7 [%s] (%d glyph units)' % (title, width)
