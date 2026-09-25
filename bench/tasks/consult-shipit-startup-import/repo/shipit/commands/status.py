from shipit.commands.registry import command
from shipit.render import formats
from shipit.render.table import table

# Status output is always plain markdown.
STATUS_RENDERER = formats.renderer_for('markdown')


@command('status', help='show deployment status')
class StatusCommand:
    @staticmethod
    def configure(parser):
        parser.add_argument('--env', default='production')

    @staticmethod
    def run(args):
        rows = [('api', '2.3.0', 'healthy'), ('worker', '2.2.9', 'rolling')]
        print(STATUS_RENDERER.render('Status: %s' % args.env, table(rows)))
        return 0
