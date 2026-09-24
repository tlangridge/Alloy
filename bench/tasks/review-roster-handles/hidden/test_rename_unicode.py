import unittest

from roster import HandleRegistry, HandleTaken

FULLWIDTH_JOE = 'Ｊｏｅ'   # 'Ｊｏｅ'


class RenameUsesCanonicalKeyTests(unittest.TestCase):
    """rename() must compare and store handles by canonical() like register/lookup."""

    def setUp(self):
        self.reg = HandleRegistry()

    def test_rename_onto_casefold_variant_of_another_users_handle(self):
        self.reg.register(1, 'strasse')
        self.reg.register(2, 'bob')
        with self.assertRaises(HandleTaken):
            self.reg.rename(2, 'Straße')
        self.assertEqual(self.reg.handle_of(2), 'bob')

    def test_rename_onto_compatibility_variant_of_another_users_handle(self):
        self.reg.register(1, 'joe')
        self.reg.register(2, 'bob')
        with self.assertRaises(HandleTaken):
            self.reg.rename(2, FULLWIDTH_JOE)

    def test_user_with_fullwidth_handle_can_rename(self):
        self.reg.register(1, FULLWIDTH_JOE)
        self.assertEqual(self.reg.rename(1, 'joe_2'), 'joe_2')
        self.assertEqual(self.reg.lookup('JOE_2'), 1)
        self.assertIsNone(self.reg.lookup('joe'))

    def test_renamed_handle_is_found_by_any_spelling(self):
        self.reg.register(1, 'bob')
        self.reg.rename(1, 'Straße')
        self.assertEqual(self.reg.lookup('STRASSE'), 1)
        with self.assertRaises(HandleTaken):
            self.reg.register(2, 'strasse')

    def test_rename_to_other_spelling_of_own_handle(self):
        self.reg.register(1, 'strasse')
        self.reg.rename(1, 'Straße')
        self.assertEqual(self.reg.handle_of(1), 'Straße')
        self.assertEqual(self.reg.lookup('STRASSE'), 1)
        self.assertEqual(len(self.reg), 1)


if __name__ == '__main__':
    unittest.main()
