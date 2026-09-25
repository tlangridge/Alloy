import unittest

from roster import AlreadyRegistered, HandleRegistry, HandleTaken, UnknownUser, validate


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.reg = HandleRegistry()

    def test_register_and_lookup(self):
        self.assertEqual(self.reg.register(1, ' Alice '), 'Alice')
        self.assertEqual(self.reg.lookup('alice'), 1)
        self.assertEqual(self.reg.handle_of(1), 'Alice')
        self.assertIn('ALICE', self.reg)

    def test_case_insensitive_uniqueness(self):
        self.reg.register(1, 'alice')
        with self.assertRaises(HandleTaken):
            self.reg.register(2, 'ALICE')

    def test_one_handle_per_user(self):
        self.reg.register(1, 'alice')
        with self.assertRaises(AlreadyRegistered):
            self.reg.register(1, 'alice2')

    def test_validation(self):
        for bad in ('ab', 'a' * 21, 'has space', 'dash-ed', ''):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    validate(bad)
        with self.assertRaises(TypeError):
            validate(None)

    def test_rename(self):
        self.reg.register(1, 'alice')
        self.reg.register(2, 'bob')
        self.assertEqual(self.reg.rename(1, 'alicia'), 'alicia')
        self.assertIsNone(self.reg.lookup('alice'))
        self.assertEqual(self.reg.lookup('Alicia'), 1)
        with self.assertRaises(HandleTaken):
            self.reg.rename(2, 'ALICIA')

    def test_rename_own_handle_spelling(self):
        self.reg.register(1, 'bob')
        self.reg.rename(1, 'Bob')
        self.assertEqual(self.reg.handle_of(1), 'Bob')
        self.assertEqual(self.reg.lookup('BOB'), 1)

    def test_release_frees_handle(self):
        self.reg.register(1, 'alice')
        self.reg.release(1)
        self.assertEqual(len(self.reg), 0)
        self.reg.register(2, 'Alice')
        with self.assertRaises(UnknownUser):
            self.reg.handle_of(1)

    def test_mentions(self):
        self.reg.register(1, 'alice')
        self.reg.register(2, 'bob')
        self.assertEqual(self.reg.mentions('hi @Bob and @alice, cc @bob @nobody'), [2, 1])


if __name__ == '__main__':
    unittest.main()
