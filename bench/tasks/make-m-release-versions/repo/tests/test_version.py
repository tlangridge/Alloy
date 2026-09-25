import unittest

from fwver import InvalidVersion, parse


class ParseTests(unittest.TestCase):
    def test_full_tag(self):
        v = parse('v2!1.4.3-RC.2+build.77')
        self.assertEqual((v.epoch, v.major, v.minor, v.patch), (2, 1, 4, 3))
        self.assertEqual((v.channel, v.channel_num, v.build), ('rc', 2, 'build.77'))
        self.assertEqual(v.text, 'v2!1.4.3-RC.2+build.77')

    def test_defaults(self):
        v = parse(' 1.4 ')
        self.assertEqual((v.epoch, v.release, v.channel, v.channel_num), (0, (1, 4, 0), None, None))
        self.assertEqual(parse('1.4.0-beta').channel_num, 0)

    def test_invalid(self):
        for bad in ('1', '1.02', '01.2', '1.2.3.4', '1.2-gamma', 'x1.2', '1.2+', '', '1.2-rc.01'):
            with self.subTest(bad=bad), self.assertRaises(InvalidVersion):
                parse(bad)

    def test_prerelease_flag(self):
        self.assertTrue(parse('1.0-dev').is_prerelease)
        self.assertFalse(parse('1.0-hotfix.1').is_prerelease)
        self.assertFalse(parse('1.0').is_prerelease)


class OrderingSmokeTests(unittest.TestCase):
    def test_numeric_order(self):
        self.assertLess(parse('1.2.9'), parse('1.10.0'))
        self.assertGreater(parse('2.0'), parse('1.99.99'))


if __name__ == '__main__':
    unittest.main()
