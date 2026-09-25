import io
import unittest

from notifier import cli


class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        code = cli.main(list(argv), out=out)
        return code, out.getvalue()

    def test_lists_channels(self):
        code, out = self.run_cli('channels')
        self.assertEqual(code, 0)
        self.assertEqual(out.split(), ['email', 'slack', 'sms'])

    def test_send_slack(self):
        code, out = self.run_cli('send', '--channel', 'slack', '--to', '#ops', 'deploy finished')
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), 'slack #ops: deploy finished')

    def test_sms_too_long(self):
        code, _ = self.run_cli('send', '--channel', 'sms', '--to', '+15550100', 'x' * 161)
        self.assertEqual(code, 1)

    def test_unknown_channel_rejected(self):
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args(['send', '--channel', 'pager', '--to', 'x', 'hi'])


if __name__ == '__main__':
    unittest.main()
