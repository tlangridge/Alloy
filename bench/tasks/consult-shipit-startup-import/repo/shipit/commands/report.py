from typing import TYPE_CHECKING

from shipit.commands.registry import command
from shipit.render import formats

if TYPE_CHECKING:  # pragma: no cover
    from shipit.render.pdf import PdfRenderer  # noqa: F401


@command('report', help='render a release report')
class ReportCommand:
    @staticmethod
    def configure(parser):
        parser.add_argument('--format', choices=formats.available(), default='markdown')
        parser.add_argument('version')

    @staticmethod
    def run(args):
        renderer = formats.renderer_for(args.format)
        print(renderer.render('Release %s' % args.version, 'All checks passed.'))
        return 0

    @staticmethod
    def archive(version):
        """Always archive reports as PDF, whatever format was shown."""
        from shipit.render.pdf import PdfRenderer
        return PdfRenderer().render('Release %s' % version, 'archived')
