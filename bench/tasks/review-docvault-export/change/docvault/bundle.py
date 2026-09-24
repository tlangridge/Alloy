"""File naming and archives for downloads."""
import io
import json
import re
import unicodedata
import zipfile

# Fixed timestamp so identical exports produce identical archives.
_EPOCH = (1980, 1, 1, 0, 0, 0)


def slugify(title, max_length=48):
    """ASCII, lower-case, hyphen-separated; 'untitled' if nothing is left."""
    ascii_title = unicodedata.normalize('NFKD', title).encode('ascii', 'ignore').decode('ascii')
    slug = re.sub(r'[^a-z0-9]+', '-', ascii_title.lower()).strip('-')
    return slug[:max_length].rstrip('-') or 'untitled'


def filename_for(doc):
    """Download file name; unique because it starts with the document id."""
    return '%s-%s.txt' % (doc.id, slugify(doc.title))


def make_zip(entries, manifest):
    """A deterministic zip: manifest.json first, then (name, text) entries in order."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as archive:
        items = [('manifest.json', json.dumps(manifest, indent=2, sort_keys=True))] + list(entries)
        for name, text in items:
            info = zipfile.ZipInfo(name, date_time=_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, text.encode('utf-8'))
    return buf.getvalue()
