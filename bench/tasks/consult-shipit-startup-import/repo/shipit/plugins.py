"""Optional plugins, loaded only with --plugins."""
try:
    from shipit.render import pdf as _pdf
    HAVE_PDF = True
except ImportError:  # pragma: no cover - pdf support is optional in slim builds
    _pdf = None
    HAVE_PDF = False

LOADED = []


def load_all():
    if HAVE_PDF:
        LOADED.append('pdf-watermark')
    return LOADED
