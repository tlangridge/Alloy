import os
import tempfile
import unittest

import logprune


class ParseKeepTests(unittest.TestCase):
    def test_units(self):
        self.assertEqual(logprune.parse_keep('36h'), 36 * 3600)
        self.assertEqual(logprune.parse_keep('14d'), 14 * 86400)
        self.assertEqual(logprune.parse_keep(' 2W '), 2 * 7 * 86400)

    def test_rejects_fraction(self):
        with self.assertRaises(ValueError):
            logprune.parse_keep('1.5d')


class PruneTests(unittest.TestCase):
    def test_only_old_rotated_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            names = ['app.log', 'app.log.1', 'app.log.2.gz', 'notes.txt']
            for name in names:
                with open(os.path.join(tmp, name), 'w') as fh:
                    fh.write('x')
                os.utime(os.path.join(tmp, name), (1000, 1000))
            removed = logprune.prune(tmp, keep_seconds=500, now=2000, dry_run=True)
            self.assertEqual([os.path.basename(p) for p in removed], ['app.log.1', 'app.log.2.gz'])
            self.assertEqual(len(os.listdir(tmp)), 4)

    def test_cli_bad_value_is_usage_error(self):
        with self.assertRaises(SystemExit) as cm:
            logprune.build_parser().parse_args(['--keep', 'x7', '/tmp'])
        self.assertEqual(cm.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
