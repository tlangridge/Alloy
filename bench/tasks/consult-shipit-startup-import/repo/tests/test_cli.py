import contextlib
import io
import unittest

from shipit import cli
from shipit.commands import REGISTRY


class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(list(argv))
        return code, out.getvalue()

    def test_commands_registered(self):
        self.assertEqual(sorted(REGISTRY), ['deploy', 'report', 'status'])

    def test_status(self):
        code, out = self.run_cli('status')
        self.assertEqual(code, 0)
        self.assertIn('# Status: production', out)

    def test_markdown_report(self):
        code, out = self.run_cli('report', '2.3.0')
        self.assertTrue(out.startswith('# Release 2.3.0'))

    def test_deploy_k8s(self):
        code, out = self.run_cli('deploy', '2.3.0')
        self.assertIn('k8s rollout 2.3.0', out)


if __name__ == '__main__':
    unittest.main()
