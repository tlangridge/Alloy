"""Release notes attached to artifact uploads."""
from shipit.render.formats import renderer_for


def render_notes(changes, renderer=renderer_for('release-notes')):
    """Render release notes for `changes` (a list of one-line summaries)."""
    body = '\n'.join('- %s' % change for change in changes)
    return renderer.render('Release notes', body)
