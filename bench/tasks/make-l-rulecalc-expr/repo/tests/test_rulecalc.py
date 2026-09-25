import unittest
from decimal import Decimal

import rulecalc


class BasicTests(unittest.TestCase):
    def test_arithmetic_precedence(self):
        self.assertEqual(rulecalc.evaluate('1 + 2 * 3'), Decimal(7))
        self.assertEqual(rulecalc.evaluate('(1 + 2) * 3'), Decimal(9))

    def test_numbers_are_decimals(self):
        result = rulecalc.evaluate('0.1 + 0.2')
        self.assertIsInstance(result, Decimal)
        self.assertEqual(result, Decimal('0.3'))

    def test_string_concatenation(self):
        self.assertEqual(rulecalc.evaluate('"ab" + \'cd\''), 'abcd')

    def test_variables_and_members(self):
        rule = rulecalc.compile_rule('order.total >= 250 and customer.tier == "gold"')
        self.assertTrue(rule.evaluate({'order': {'total': 300}, 'customer': {'tier': 'gold'}}))
        self.assertFalse(rule.evaluate({'order': {'total': 100}, 'customer': {'tier': 'gold'}}))
        self.assertEqual(rule.variables, ['customer', 'order'])

    def test_conditional(self):
        self.assertEqual(rulecalc.evaluate('x > 1 ? "big" : "small"', {'x': 5}), 'big')

    def test_lex_error_position(self):
        with self.assertRaises(rulecalc.LexError) as ctx:
            rulecalc.compile_rule('1 @ 2')
        self.assertEqual((ctx.exception.line, ctx.exception.column), (1, 3))

    def test_parse_error_is_raised_at_compile_time(self):
        with self.assertRaises(rulecalc.ParseError):
            rulecalc.compile_rule('(1 + 2')

    def test_division_by_zero_is_eval_error(self):
        rule = rulecalc.compile_rule('1 / 0')
        with self.assertRaises(rulecalc.EvalError):
            rule.evaluate()


if __name__ == '__main__':
    unittest.main()
