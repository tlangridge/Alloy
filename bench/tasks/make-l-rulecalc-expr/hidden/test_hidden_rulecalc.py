import unittest
from decimal import Decimal

import rulecalc
from rulecalc import EvalError, LexError, ParseError, compile_rule, evaluate

D = Decimal


class Base(unittest.TestCase):
    def raises_at(self, exc_type, line, column, source, variables=None, compile_only=False):
        with self.assertRaises(exc_type) as ctx:
            if compile_only:
                compile_rule(source)
            else:
                evaluate(source, variables)
        self.assertEqual((ctx.exception.line, ctx.exception.column), (line, column),
                         'wrong position for %r: %s' % (source, ctx.exception))
        return ctx.exception

    def eval_error_at(self, column, source, variables=None, line=1):
        rule = compile_rule(source)  # must compile fine
        with self.assertRaises(EvalError) as ctx:
            rule.evaluate(variables)
        self.assertEqual((ctx.exception.line, ctx.exception.column), (line, column),
                         'wrong position for %r: %s' % (source, ctx.exception))


class PrecedenceTests(Base):
    def test_power_is_right_associative_and_takes_unary_exponent(self):
        self.assertEqual(evaluate('2 ** 3 ** 2'), D(512))
        self.assertEqual(evaluate('2 ** -1'), D('0.5'))
        self.assertEqual(evaluate('2 ** -2'), D('0.25'))

    def test_unary_minus_binds_looser_than_power(self):
        self.assertEqual(evaluate('-2 ** 2'), D(-4))
        self.assertEqual(evaluate('(-2) ** 2'), D(4))

    def test_unary_minus_binds_tighter_than_multiplication(self):
        self.assertEqual(evaluate('-3 * -2 - -1'), D(7))

    def test_not_binds_looser_than_comparison(self):
        self.assertIs(evaluate('not 1 == 2'), True)
        self.assertIs(evaluate('not 1 < 2 and true'), False)

    def test_not_in_versus_not_prefix(self):
        self.assertIs(evaluate('x not in [1, 2]', {'x': 3}), True)
        self.assertIs(evaluate('not x in [1, 2]', {'x': 1}), False)

    def test_coalesce_binds_looser_than_or_and_arithmetic(self):
        self.assertEqual(evaluate('null ?? 1 + 2'), D(3))
        self.assertIs(evaluate('null ?? false or true'), True)

    def test_conditional_is_right_associative_and_lowest(self):
        self.assertEqual(evaluate('false ? 1 : true ? 2 : 3'), D(2))
        self.assertEqual(evaluate('true ? 1 : true ? 2 : 3'), D(1))
        self.assertEqual(evaluate('x ?? true ? "y" : "n"', {'x': None}), 'y')
        self.assertEqual(evaluate('true ? false ? 1 : 2 : 3'), D(2))


class ArithmeticTests(Base):
    def test_exact_decimals_and_result_type(self):
        self.assertIs(evaluate('0.1 + 0.2 == 0.3'), True)
        result = evaluate('7 / 2')
        self.assertIsInstance(result, Decimal)
        self.assertEqual(result, D('3.5'))

    def test_floored_division(self):
        self.assertEqual(evaluate('-7 // 2'), D(-4))
        self.assertEqual(evaluate('7 // -2'), D(-4))
        self.assertEqual(evaluate('7 // 2'), D(3))

    def test_floored_modulo(self):
        self.assertEqual(evaluate('-7 % 3'), D(2))
        self.assertEqual(evaluate('7 % -3'), D(-2))
        self.assertEqual(evaluate('5.5 % 2'), D('1.5'))
        self.assertEqual(evaluate('-5.5 % 2'), D('0.5'))

    def test_division_by_zero_positions(self):
        self.eval_error_at(7, '1 + 4 / (2 - 2)')
        self.eval_error_at(3, '5 // 0')
        self.eval_error_at(3, '5 % 0')

    def test_power_rules(self):
        self.eval_error_at(3, '2 ** 0.5')
        self.eval_error_at(3, '0 ** -1')
        self.assertEqual(evaluate('2 ** 2.0'), D(4))

    def test_plus_concatenates_strings_and_lists_only(self):
        self.assertEqual(evaluate('[1] + [true]'), [D(1), True])
        self.eval_error_at(5, '"a" + 1')
        self.eval_error_at(3, '1 - "a"')
        self.eval_error_at(1, '-"a"')

    def test_booleans_are_not_numbers_in_arithmetic(self):
        self.eval_error_at(6, 'true + 1')


class EqualityAndComparisonTests(Base):
    def test_no_cross_type_equality_numbers_by_value(self):
        self.assertIs(evaluate('true == 1'), False)
        self.assertIs(evaluate('false != 0'), True)
        self.assertIs(evaluate('null == false'), False)
        self.assertIs(evaluate('"1" == 1'), False)
        self.assertIs(evaluate('1 == 1.00'), True)

    def test_deep_equality(self):
        self.assertIs(evaluate('[true] == [1]'), False)
        self.assertIs(evaluate('[1, [2, "x"]] == [1.0, [2, "x"]]'), True)
        self.assertIs(evaluate('a == b', {'a': {'k': 1, 'j': [True]}, 'b': {'j': [True], 'k': 1.0}}), True)
        self.assertIs(evaluate('a == b', {'a': {'k': 1}, 'b': {'k': True}}), False)

    def test_comparison_chains(self):
        self.assertIs(evaluate('1 < 2 < 3'), True)
        self.assertIs(evaluate('1 < 3 < 2'), False)
        self.assertIs(evaluate('3 > 2 >= 2 == 2'), True)

    def test_chain_short_circuits_later_operands(self):
        self.assertIs(evaluate('2 < 1 < missing'), False)
        self.eval_error_at(11, '1 < 2 < 1 / 0')

    def test_chain_error_reported_at_failing_operator(self):
        self.eval_error_at(7, '1 < 2 < "a"')

    def test_ordering_rules(self):
        self.assertIs(evaluate('"apple" < "banana"'), True)
        self.assertIs(evaluate('"Z" < "a"'), True)
        self.eval_error_at(5, '"a" < 1')
        self.eval_error_at(6, 'null >= 1')

    def test_in_operator(self):
        self.assertIs(evaluate('"ell" in "hello"'), True)
        self.assertIs(evaluate('true in [1, 2]'), False)
        self.assertIs(evaluate('1.0 in [1, 2]'), True)
        self.assertIs(evaluate('"k" in m', {'m': {'k': 0}}), True)
        self.eval_error_at(3, '1 in "abc"')
        self.eval_error_at(3, '1 in 5')
        self.eval_error_at(3, '1 not in 5')


class LogicTests(Base):
    def test_short_circuit(self):
        self.assertIs(evaluate('false and 1 / 0 > 0'), False)
        self.assertIs(evaluate('true or missing_var'), True)

    def test_non_boolean_operands_and_conditions_are_errors(self):
        self.eval_error_at(3, '1 and true')
        self.eval_error_at(6, 'true and 1')
        self.eval_error_at(7, 'false or "x"')
        self.eval_error_at(1, 'not 1')
        self.eval_error_at(3, '1 ? 2 : 3')

    def test_only_selected_branch_is_evaluated(self):
        self.assertEqual(evaluate('true ? 1 : 1 / 0'), D(1))
        self.assertEqual(evaluate('false ? missing : 2'), D(2))


class NullAndAccessTests(Base):
    def test_coalesce_replaces_only_null(self):
        self.assertEqual(evaluate('null ?? 5'), D(5))
        self.assertEqual(evaluate('0 ?? 5'), D(0))
        self.assertIs(evaluate('false ?? 5'), False)
        self.assertEqual(evaluate('1 ?? 1 / 0'), D(1))

    def test_member_access_on_null_propagates(self):
        self.assertEqual(evaluate('user.plan.tier ?? "free"', {'user': {'plan': None}}), 'free')
        self.assertIsNone(evaluate('user.plan.tier', {'user': {'plan': None}}))

    def test_coalesce_does_not_suppress_errors(self):
        self.eval_error_at(6, 'user.missing ?? 1', {'user': {}})

    def test_member_errors_point_at_member_name(self):
        self.eval_error_at(6, 'name.first', {'name': 'x'})
        self.eval_error_at(7, 'a.b.  c', {'a': {'b': {}}})

    def test_indexing(self):
        self.assertEqual(evaluate('[10, 20, 30][1]'), D(20))
        self.assertEqual(evaluate('[10, 20, 30][-1]'), D(30))
        self.assertEqual(evaluate('"héllo"[1]'), 'é')
        self.assertEqual(evaluate('m["k"]', {'m': {'k': 'v'}}), 'v')
        self.assertIsNone(evaluate('x[0]', {'x': None}))

    def test_index_errors_point_at_bracket(self):
        self.eval_error_at(4, '[1][1]')
        self.eval_error_at(4, '[1][0.5]')
        self.eval_error_at(4, '[1][true]')
        self.eval_error_at(2, 'm["x"]', {'m': {}})
        self.eval_error_at(2, 'm[0]', {'m': {'0': 1}})
        self.eval_error_at(2, '5[0]')


class VariableTests(Base):
    def test_unknown_variable_fails_at_evaluation_not_compile(self):
        rule = compile_rule('1 + foo')
        with self.assertRaises(EvalError) as ctx:
            rule.evaluate({})
        self.assertEqual((ctx.exception.line, ctx.exception.column), (1, 5))
        self.assertEqual(rule.evaluate({'foo': 2}), D(3))

    def test_keywords_are_case_sensitive(self):
        self.assertEqual(evaluate('True', {'True': 'yes'}), 'yes')
        self.eval_error_at(1, 'True')

    def test_bool_variables_stay_booleans(self):
        self.assertIs(evaluate('flag and true', {'flag': True}), True)
        self.assertIs(evaluate('flag == 1', {'flag': True}), False)
        self.assertIs(evaluate('flags[0] == true', {'flags': (True,)}), True)

    def test_int_and_float_conversion(self):
        self.assertIs(evaluate('price + 0.2 == 0.3', {'price': 0.1}), True)
        result = evaluate('n', {'n': 3})
        self.assertIsInstance(result, Decimal)
        self.assertEqual(result, D(3))

    def test_unsupported_values_error_at_root_name(self):
        self.eval_error_at(5, '1 + x.a', {'x': {'a': 1, 'b': object()}})
        self.eval_error_at(1, 'x', {'x': float('nan')})
        self.eval_error_at(1, 'x', {'x': {1: 'a'}})

    def test_variables_property(self):
        rule = compile_rule('a.b[c] + len(d) ?? (e ? f.x : a) # g')
        self.assertEqual(rule.variables, ['a', 'c', 'd', 'e', 'f'])
        self.assertEqual(compile_rule('1 + 2').variables, [])


class FunctionTests(Base):
    def test_round_ties_away_from_zero(self):
        self.assertEqual(evaluate('round(2.5)'), D(3))
        self.assertEqual(evaluate('round(-2.5)'), D(-3))
        self.assertEqual(evaluate('round(1.005, 2)'), D('1.01'))
        self.assertEqual(evaluate('round(0.125, 2)'), D('0.13'))

    def test_round_places_validation(self):
        self.eval_error_at(1, 'round(1, 0.5)')
        self.eval_error_at(1, 'round(1, -1)')
        self.eval_error_at(1, 'round("1")')

    def test_len_counts_code_points(self):
        self.assertEqual(evaluate('len("héllo")'), D(5))
        self.assertEqual(evaluate('len([1, 2]) + len(m)', {'m': {'a': 1}}), D(3))
        self.eval_error_at(3, '1+len(5)')

    def test_min_max_lower_upper_abs(self):
        self.assertEqual(evaluate('min(3, 1, 2)'), D(1))
        self.assertEqual(evaluate('max("b", "a")'), 'b')
        self.assertEqual(evaluate('max(7)'), D(7))
        self.eval_error_at(1, 'min(1, "a")')
        self.assertEqual(evaluate('upper("abc") + lower("DEF")'), 'ABCdef')
        self.assertEqual(evaluate('abs(-2.5)'), D('2.5'))
        self.eval_error_at(1, 'abs(true)')

    def test_unknown_function_and_arity_are_compile_errors(self):
        self.raises_at(ParseError, 1, 5, '1 + nope(1)', compile_only=True)
        self.raises_at(ParseError, 1, 1, 'len(1, 2)', compile_only=True)
        self.raises_at(ParseError, 1, 1, 'min()', compile_only=True)
        self.raises_at(ParseError, 1, 1, 'round(1, 2, 3)', compile_only=True)


class LexerTests(Base):
    def test_string_escapes(self):
        self.assertEqual(evaluate(r'"a\tb\n\\\"\u{1F600}\u{e9}"'), 'a\tb\n\\"\U0001F600é')
        self.assertEqual(evaluate(r"'it\'s'"), "it's")

    def test_bad_escapes_point_at_backslash(self):
        self.raises_at(LexError, 1, 3, r'"a\qb"', compile_only=True)
        self.raises_at(LexError, 1, 2, r'"\u{D800}"', compile_only=True)
        self.raises_at(LexError, 1, 3, r'"x\u{110000}"', compile_only=True)
        self.raises_at(LexError, 1, 2, r'"\u{}"', compile_only=True)
        self.raises_at(LexError, 1, 2, r'"\u0041"', compile_only=True)

    def test_unterminated_string_points_at_opening_quote(self):
        self.raises_at(LexError, 1, 5, '1 + "abc', compile_only=True)
        self.raises_at(LexError, 1, 1, "'ab\ncd'", compile_only=True)

    def test_unexpected_characters(self):
        self.raises_at(LexError, 1, 3, 'a = 1', compile_only=True)
        self.raises_at(LexError, 1, 1, '!x', compile_only=True)
        self.raises_at(LexError, 1, 7, '"é" + é', compile_only=True)

    def test_comments_and_multiline_positions(self):
        self.assertEqual(evaluate('1 + # comment\n 2'), D(3))
        self.raises_at(LexError, 2, 3, '1 +\n\t\t@', compile_only=True)
        self.raises_at(ParseError, 3, 1, '1 +\n  (2 *\n)', compile_only=True)

    def test_columns_count_code_points(self):
        self.eval_error_at(5, '"é" + 1')
        self.eval_error_at(6, '"\U0001F600\U0001F600" - 1')

    def test_eof_parse_error_position(self):
        self.raises_at(ParseError, 1, 5, '1 + ', compile_only=True)
        self.raises_at(ParseError, 1, 1, '', compile_only=True)
        self.raises_at(ParseError, 2, 8, 'x ?\n  1 # c', compile_only=True)

    def test_parse_error_positions(self):
        self.raises_at(ParseError, 1, 3, '1 2', compile_only=True)
        self.raises_at(ParseError, 1, 8, '[1, 2, ]', compile_only=True)
        self.raises_at(ParseError, 1, 5, 'a.b.and', compile_only=True)
        self.raises_at(ParseError, 1, 6, 'a ? 1', compile_only=True)

    def test_maximal_munch(self):
        self.assertEqual(evaluate('7//2*2**2'), D(12))
        self.assertIs(evaluate('1<=1'), True)
        self.assertEqual(evaluate('null??2'), D(2))
        self.assertEqual(evaluate('x??y?1:2', {'x': None, 'y': False}), D(2))


if __name__ == '__main__':
    unittest.main()
