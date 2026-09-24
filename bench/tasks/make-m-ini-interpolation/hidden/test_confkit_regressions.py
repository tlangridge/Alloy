import unittest

from confkit import ConfigError, load


def error_of(text):
    try:
        load(text)
    except ConfigError as exc:
        return exc
    raise AssertionError('no ConfigError raised')


def lines(*rows):
    return '\n'.join(rows) + '\n'


class InheritedValueTests(unittest.TestCase):
    def test_reported_default_inheritance(self):
        cfg = load(lines('[DEFAULT]', 'root = /srv/app', 'logs = ${root}/logs', '',
                         '[web]', 'port = 8080', '', '[worker]', 'root = /srv/worker'))
        self.assertEqual(cfg.get('web', 'logs'), '/srv/app/logs')
        self.assertEqual(cfg.get('worker', 'logs'), '/srv/worker/logs')

    def test_each_section_resolves_default_independently(self):
        cfg = load(lines('[a]', 'name = alpha', '[DEFAULT]', 'greeting = hi ${name}',
                         '[b]', 'name = beta', '[c]', 'name = gamma'))
        self.assertEqual([cfg.get(s, 'greeting') for s in ('a', 'b', 'c')],
                         ['hi alpha', 'hi beta', 'hi gamma'])

    def test_chained_default_references(self):
        cfg = load(lines('[DEFAULT]', 'root = /srv', 'base = ${root}/${env}', 'logs = ${base}/logs',
                         '[prod]', 'env = prod', '[stage]', 'env = stage', 'root = /mnt'))
        self.assertEqual(cfg.get('prod', 'logs'), '/srv/prod/logs')
        self.assertEqual(cfg.get('stage', 'logs'), '/mnt/stage/logs')
        self.assertEqual(cfg.get('stage', 'base'), '/mnt/stage')

    def test_cross_section_reference_uses_target_context(self):
        cfg = load(lines('[DEFAULT]', 'root = /srv', 'logs = ${root}/logs',
                         '[web]', 'tail = tail -f ${worker:logs}',
                         '[worker]', 'root = /w'))
        self.assertEqual(cfg.get('web', 'tail'), 'tail -f /w/logs')
        self.assertEqual(cfg.get('web', 'logs'), '/srv/logs')
        self.assertEqual(cfg.get('worker', 'logs'), '/w/logs')

    def test_own_keys_then_inherited_keys(self):
        cfg = load(lines('[DEFAULT]', 'b = 2', 'a = 1', '[s]', 'z = 26', 'a = one'))
        self.assertEqual(list(cfg['s'].items()), [('z', '26'), ('a', 'one'), ('b', '2')])
        self.assertEqual(cfg.sections(), ['s'])


class InterpolationRulesTests(unittest.TestCase):
    def test_dollar_escape_and_case_insensitive_keys(self):
        cfg = load(lines('[s]', 'Price = 5', 'label = costs $$${PRICE}', 'raw = $$HOME'))
        self.assertEqual(cfg.get('s', 'label'), 'costs $5')
        self.assertEqual(cfg.get('s', 'raw'), '$HOME')
        self.assertEqual(cfg.get('S'.lower(), 'PRICE'), '5')

    def test_section_names_are_case_sensitive(self):
        exc = error_of(lines('[db]', 'host = h', '[app]', 'dsn = ${Db:host}'))
        self.assertEqual(exc.lineno, 4)

    def test_undefined_section_and_key(self):
        self.assertEqual(error_of(lines('[a]', 'x = 1', 'y = ${nosuch:x}')).lineno, 3)
        self.assertEqual(error_of(lines('[a]', 'x = 1', '[b]', 'y = ${a:missing}')).lineno, 4)

    def test_cycles(self):
        exc = error_of(lines('[s]', 'a = ${b}', 'b = x', '    ${a}'))
        self.assertEqual(exc.lineno, 3)
        self.assertEqual(error_of(lines('[s]', 'a = <${a}>')).lineno, 2)
        exc = error_of(lines('[DEFAULT]', 'p = ${q}', 'q = ${p}', '[s]', 'k = v'))
        self.assertEqual(exc.lineno, 3)


class ContinuationTests(unittest.TestCase):
    def test_joining_comments_and_blank_line(self):
        cfg = load(lines('[s]', 'hosts = web1,', '    web2,   ; second', '  # skipped',
                         '\tweb3', 'url = http://x/#frag', '', 'other = 1'))
        self.assertEqual(cfg.get('s', 'hosts'), 'web1, web2, web3')
        self.assertEqual(cfg.get('s', 'url'), 'http://x/#frag')

    def test_empty_first_line_value(self):
        cfg = load(lines('[s]', 'cmd =', '    run', '    --fast'))
        self.assertEqual(cfg.get('s', 'cmd'), 'run --fast')


class ErrorLineTests(unittest.TestCase):
    def test_reported_multiline_undefined_reference(self):
        exc = error_of('[deploy]\nhosts = web1,\n    web2,\n    # web3 is being rebuilt\n'
                       '    ${spare_host}\nregion = eu-west\n')
        self.assertEqual(exc.lineno, 2)
        self.assertEqual(str(exc), 'line 2: undefined reference ${spare_host}')

    def test_bad_dollar_in_multiline_value(self):
        exc = error_of(lines('[s]', 'ok = 1', 'price = 5', '    costs $5'))
        self.assertEqual(exc.lineno, 3)

    def test_unterminated_reference_in_multiline_value(self):
        exc = error_of(lines('[s]', 'v = a', '  ; note', '  ${b', 'w = 2'))
        self.assertEqual(exc.lineno, 2)

    def test_duplicate_key_spanning_lines(self):
        exc = error_of(lines('[s]', 'k = 1', 'j = 2', 'k = first', '    second', '    third'))
        self.assertEqual(exc.lineno, 4)
        self.assertTrue(str(exc).startswith('line 4: '))

    def test_lines_after_multiline_value_unaffected(self):
        exc = error_of(lines('[s]', 'a = 1', '    2', '    3', 'garbage line'))
        self.assertEqual(exc.lineno, 5)
        exc = error_of(lines('[s]', 'a = 1', '    2', '[s]'))
        self.assertEqual(exc.lineno, 4)

    def test_structural_errors(self):
        self.assertEqual(error_of(lines('# c', 'x = 1', '[s]')).lineno, 2)
        self.assertEqual(error_of(lines('[s]', 'a = 1', '= 1')).lineno, 3)
        self.assertEqual(error_of(lines('[s]', 'a = 1', '', '    orphan')).lineno, 4)
        self.assertEqual(error_of(lines('  indented = first')).lineno, 1)

    def test_cycle_line_is_start_of_multiline_entry(self):
        exc = error_of(lines('[s]', 'a = ${b}', 'b = one', '    two', '    ${a}'))
        self.assertEqual(exc.lineno, 3)

    def test_getint_reports_entry_start_line(self):
        cfg = load(lines('[s]', 'n = 12', '    34', 'm = 5'))
        with self.assertRaises(ConfigError) as ctx:
            cfg.getint('s', 'n')
        self.assertEqual(ctx.exception.lineno, 2)
        self.assertEqual(cfg.getint('s', 'm'), 5)

    def test_getint_on_inherited_default_value(self):
        cfg = load(lines('[DEFAULT]', 'size = big', '    enough', '[s]', 'x = 1'))
        with self.assertRaises(ConfigError) as ctx:
            cfg.getint('s', 'size')
        self.assertEqual(ctx.exception.lineno, 2)


if __name__ == '__main__':
    unittest.main()
