from shipit.render.notes import render_notes
from shipit.targets.base import Target


class ArtifactTarget(Target):
    name = 'artifacts'

    def deploy(self, version, changes=('bump version',)):
        notes = render_notes(list(changes))
        return 'uploaded %s with notes: %s' % (version, notes)
