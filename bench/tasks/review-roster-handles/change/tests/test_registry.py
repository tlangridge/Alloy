import unittest

from roster import AlreadyRegistered, HandleRegistry, HandleTaken, UnknownUser, canonical, validate


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


class UnicodeHandleTests(unittest.TestCase):
    def setUp(self):
        self.reg = HandleRegistry()

    def test_canonical_forms(self):
        self.assertEqual(canonical('Straße'), 'strasse')
        self.assertEqual(canonical('\uff2a\uff4f\uff45'), 'joe')          # fullwidth 'Ｊｏｅ'
        self.assertEqual(canonical('\ufb01nn'), 'finn')                    # 'ﬁ' ligature
        self.assertEqual(canonical('Jose\u0301'), canonical('Jos\u00e9'))  # decomposed vs composed

    def test_register_rejects_casefold_variant(self):
        self.reg.register(1, 'Straße')
        with self.assertRaises(HandleTaken):
            self.reg.register(2, 'STRASSE')

    def test_register_rejects_compatibility_variant(self):
        self.reg.register(1, 'joe')
        with self.assertRaises(HandleTaken):
            self.reg.register(2, '\uff2a\uff4f\uff45')

    def test_lookup_any_spelling_and_display_form_kept(self):
        self.reg.register(1, 'Straße')
        self.assertEqual(self.reg.lookup('strasse'), 1)
        self.assertEqual(self.reg.lookup('STRASSE'), 1)
        self.assertEqual(self.reg.handle_of(1), 'Straße')
        self.assertEqual(self.reg.mentions('ping @STRASSE'), [1])

    def test_release_frees_every_spelling(self):
        self.reg.register(1, 'Straße')
        self.reg.release(1)
        self.assertIsNone(self.reg.lookup('strasse'))
        self.reg.register(2, 'strasse')
        self.assertEqual(self.reg.lookup('Straße'), 2)

    def test_rename_collision_ignores_case(self):
        self.reg.register(1, 'Anna')
        self.reg.register(2, 'bert')
        with self.assertRaises(HandleTaken):
            self.reg.rename(2, 'ANNA')
        self.assertEqual(self.reg.handle_of(2), 'bert')


if __name__ == '__main__':
    unittest.main()
