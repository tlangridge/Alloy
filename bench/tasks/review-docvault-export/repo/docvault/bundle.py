"""File naming for downloads."""
import re
import unicodedata


def slugify(title, max_length=48):
    """ASCII, lower-case, hyphen-separated; 'untitled' if nothing is left."""
    ascii_title = unicodedata.normalize('NFKD', title).encode('ascii', 'ignore').decode('ascii')
    slug = re.sub(r'[^a-z0-9]+', '-', ascii_title.lower()).strip('-')
    return slug[:max_length].rstrip('-') or 'untitled'


def filename_for(doc):
    """Download file name; unique because it starts with the document id."""
    return '%s-%s.txt' % (doc.id, slugify(doc.title))
