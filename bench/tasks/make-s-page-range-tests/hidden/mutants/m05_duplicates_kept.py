"""Page selection for the print queue's ``--pages`` option."""
import re

_ITEM = re.compile(r'([0-9]*)\s*-\s*([0-9]*)|([0-9]+)')


def parse_page_ranges(spec, page_count):
    """Return the sorted, de-duplicated page numbers selected by ``spec``.

    ``spec`` looks like ``"1-3, 5, 8-"``; pages are numbered from 1 to
    ``page_count``. Raises ``ValueError`` for anything malformed or out of range.
    """
    if page_count < 1:
        raise ValueError('document has no pages')
    if not spec.strip():
        return list(range(1, page_count + 1))
    pages = []
    for raw in spec.split(','):
        item = raw.strip()
        if not item:
            raise ValueError('empty item in page spec %r' % (spec,))
        match = _ITEM.fullmatch(item)
        if match is None:
            raise ValueError('bad page item %r' % (item,))
        start, end, single = match.groups()
        if single is not None:
            first = last = int(single)
        else:
            if not start and not end:
                raise ValueError('bad page item %r' % (item,))
            first = int(start) if start else 1
            last = int(end) if end else page_count
        if first > last:
            raise ValueError('reversed range %r' % (item,))
        if first < 1 or last > page_count:
            raise ValueError('page out of range in %r (document has %d pages)' % (item, page_count))
        pages.extend(range(first, last + 1))
    return sorted(pages)
