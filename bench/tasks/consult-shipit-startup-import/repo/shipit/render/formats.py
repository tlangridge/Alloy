import importlib

# name -> "module:Class"; modules are imported only when a renderer is requested.
_FORMATS = {
    'markdown': 'shipit.render.markdown:MarkdownRenderer',
    'pdf': 'shipit.render.pdf:PdfRenderer',
    'release-notes': 'shipit.render.pdf:PdfRenderer',
}


def available():
    """Formats a user may pick on the command line."""
    return sorted(name for name in _FORMATS if name != 'release-notes')


def renderer_for(name):
    """Import (on first use) and instantiate the renderer registered as `name`."""
    module_name, _, class_name = _FORMATS[name].partition(':')
    return getattr(importlib.import_module(module_name), class_name)()
