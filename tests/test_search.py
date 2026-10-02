"""Jevgrep integration with a fake executable; no npm, keys or paid inference."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('search_test_core', str(REPO / 'bin/alloy'))
spec = importlib.util.spec_from_loader(loader.name, loader)
core = importlib.util.module_from_spec(spec)
sys.modules[loader.name] = core
loader.exec_module(core)
s = core.search

MOCK = '''#!{python}
import json, os, pathlib, subprocess, sys, time
args = sys.argv[1:]
log = pathlib.Path(os.environ['JG_LOG'])
with log.open('a') as f:
    f.write(json.dumps(dict(args=args, key_env=any(k in os.environ for k in ('TYPESAFE_API_KEY', 'OPENROUTER_API_KEY')))) + '\\n')
if args == ['--version']:
    print(os.environ.get('JG_VERSION', '0.3.2'))
elif args[0] == 'auth':
    secret = sys.stdin.read().strip()
    target = pathlib.Path(os.environ['XDG_CONFIG_HOME']) / 'jevgrep' / 'credentials.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(provider=args[2], apiKey=secret)))
    target.chmod(0o600)
    print(secret)  # Even a broken CLI must not leak an auth input through Alloy.
    print(secret, file=sys.stderr)
else:
    mode = os.environ.get('JG_MODE', '')
    if mode == 'timeout':
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        pathlib.Path(os.environ['JG_CHILD']).write_text(str(child.pid))
        print('Partial context', flush=True)
        time.sleep(30)
    if mode == 'flood':
        print('x' * 300000)
    else:
        print(os.environ.get('JG_OUTPUT', 'Source packet\\nfile.py:1\\nEnd context.'))
    sys.exit(int(os.environ.get('JG_EXIT', '0')))
'''


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.project = self.base / 'project'
        self.project.mkdir()
        self.bindir = self.base / 'tools'
        self.bindir.mkdir()
        self.binary = self.bindir / 'jg'
        self.binary.write_text(MOCK.format(python=sys.executable))
        self.binary.chmod(0o700)
        self.log = self.base / 'calls.jsonl'
        self.child = self.base / 'child'
        env = dict(PATH=str(self.bindir) + os.pathsep + os.environ.get('PATH', ''),
                   XDG_CONFIG_HOME=str(self.base / 'config'),
                   ALLOY_ROUTING_HOME=str(self.base / 'routing'),
                   JG_LOG=str(self.log), JG_CHILD=str(self.child),
                   TYPESAFE_API_KEY='fake-typesafe-key', OPENROUTER_API_KEY='fake-router-key')
        patch.dict(os.environ, env).start()
        self.addCleanup(patch.stopall)
        for key in ('JG_MODE', 'JG_EXIT', 'JG_OUTPUT', 'JG_VERSION'):
            os.environ.pop(key, None)
        self.write_credentials()

    def write_credentials(self, provider='openrouter', secret='fake-jg-key'):
        path = s.credentials_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(provider=provider, apiKey=secret)))

    def run_search(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = core.main(['search', '--root', str(self.project)] + list(args))
        return code, stdout.getvalue(), stderr.getvalue()

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_native_defaults_and_output_are_preserved(self):
        code, out, _ = self.run_search('Where is retry behavior?')
        self.assertEqual(code, 0)
        self.assertEqual(out, 'Source packet\nfile.py:1\nEnd context.\n')
        self.assertEqual(self.calls()[-1]['args'], ['--', 'Where is retry behavior?', str(self.project.resolve())])
        self.assertFalse(any(call['key_env'] for call in self.calls()))

    def test_check_only_never_calls_doctor_or_search(self):
        code, out, _ = self.run_search('--check', '--json')
        value = json.loads(out)
        self.assertEqual(code, 0)
        self.assertTrue(value['ready'])
        self.assertFalse(value['access_verified'])
        self.assertEqual(value['provider'], 'openrouter')
        self.assertNotIn('fake-jg-key', out)
        self.assertEqual([call['args'] for call in self.calls()], [['--version']])

    def test_current_cli_and_custom_credentials_preserve_saved_endpoint(self):
        os.environ['JG_VERSION'] = '0.8.0'
        record = dict(provider='custom', apiKey='fake-jg-key',
                      baseURL='https://gateway.example.test/typesafe/v1', model='gateway/jev')
        s.credentials_path().write_text(json.dumps(record))
        before = s.credentials_path().read_bytes()
        code, out, _ = self.run_search('--check', '--json')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)['provider'], 'custom')
        self.assertNotIn(record['baseURL'], out)
        code, _, _ = self.run_search('Locate retries')
        self.assertEqual(code, 0)
        self.assertEqual(self.calls()[-1]['args'], ['--', 'Locate retries', str(self.project.resolve())])
        self.assertEqual(s.credentials_path().read_bytes(), before)
        os.environ['JG_VERSION'] = '0.3.2'
        code, out, _ = self.run_search('--check', '--json')
        self.assertEqual(code, 1)
        self.assertIn('0.8.0', out)

    def test_invalid_custom_credentials_do_not_search(self):
        os.environ['JG_VERSION'] = '0.8.0'
        for fields in ({}, {'baseURL': 'http://remote.test', 'model': 'jev'},
                       {'baseURL': 'https://key@remote.test', 'model': 'jev'},
                       {'baseURL': 'https://remote.test?key=x', 'model': 'jev'},
                       {'baseURL': 'https://remote.test', 'model': 'two words'}):
            with self.subTest(fields=fields):
                s.credentials_path().write_text(json.dumps(dict(provider='custom', apiKey='fake-jg-key', **fields)))
                code, out, _ = self.run_search('--check', '--json')
                self.assertEqual(code, 1)
                self.assertFalse(json.loads(out)['ready'])
        self.assertTrue(all(call['args'] == ['--version'] for call in self.calls()))

    def test_missing_binary_and_auth_reported_together(self):
        s.credentials_path().unlink()
        with patch.object(s.shutil, 'which', return_value=None):
            code, out, _ = self.run_search('--check', '--json')
        self.assertEqual(code, 1)
        self.assertEqual(len(json.loads(out)['blockers']), 2)
        self.assertEqual(self.calls(), [])

    def test_outdated_cli_never_dispatches(self):
        os.environ['JG_VERSION'] = '0.1.0'
        code, _, err = self.run_search('Find retry code')
        self.assertNotEqual(code, 0)
        self.assertIn('0.3.2', err)
        self.assertEqual(len(self.calls()), 1)

    def test_project_executable_not_run(self):
        binary = self.project / 'jg'
        binary.write_text(self.binary.read_text())
        binary.chmod(0o700)
        with patch.object(s.shutil, 'which', return_value=str(binary)):
            code, out, _ = self.run_search('--check', '--json')
        self.assertEqual(code, 1)
        self.assertIn('Refusing', out)
        self.assertEqual(self.calls(), [])

    def test_home_setup_allows_a_global_user_install(self):
        # npm/nvm normally installs below HOME; setup run from HOME must work.
        with patch.object(s.Path, 'home', return_value=self.base), patch.object(s.Path, 'cwd', return_value=self.base):
            code, out, _ = self.run_search('--root', str(self.base), '--check', '--json')
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)['ready'])
        self.assertEqual([call['args'] for call in self.calls()], [['--version']])

    def test_explicit_controls_forwarded_but_no_filter_bypass(self):
        code, _, _ = self.run_search('Find retry code', '--no-cache', '--concurrency', '2', '--max-source-bytes', '0')
        self.assertEqual(code, 0)
        self.assertEqual(self.calls()[-1]['args'], ['--max-source-bytes', '0', '--concurrency', '2', '--no-cache', '--', 'Find retry code', str(self.project.resolve())])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            core.build_parser().parse_args(['search', 'question', '--include-sensitive'])

    def test_incomplete_is_not_pass_and_keeps_context(self):
        os.environ['JG_EXIT'] = '2'
        code, out, _ = self.run_search('Find retry code', '--json')
        result = json.loads(out)
        self.assertEqual(code, 2)
        self.assertEqual(result['status'], 'incomplete')
        self.assertFalse(result['complete'])
        self.assertIn('End context.', result['context'])

    def test_failed_and_interrupted_are_not_complete(self):
        for exit_code, status in ((1, 'failed'), (130, 'interrupted')):
            with self.subTest(exit_code=exit_code):
                os.environ['JG_EXIT'] = str(exit_code)
                code, out, _ = self.run_search('Find retry code', '--json')
                self.assertEqual(code, exit_code)
                self.assertEqual(json.loads(out)['status'], status)
                self.assertFalse(json.loads(out)['complete'])

    def test_timeout_kills_child_and_retains_partial_context(self):
        os.environ['JG_MODE'] = 'timeout'
        started = time.monotonic()
        code, out, _ = self.run_search('Find retry code', '--timeout', '1', '--json')
        self.assertEqual(code, 124)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(json.loads(out)['status'], 'timeout')
        self.assertIn('Partial context', json.loads(out)['context'])
        self.assertFalse(core._LIVE_PGIDS)
        # A killed orphan may be a zombie until the OS reaps it; it must not run.
        import subprocess
        pid = self.child.read_text()
        status = subprocess.run(['ps', '-o', 'stat=', '-p', pid], capture_output=True, text=True).stdout.strip()
        self.assertTrue(not status or status.startswith('Z'), status)

    def test_output_guard_is_explicitly_incomplete(self):
        os.environ['JG_MODE'] = 'flood'
        with patch.object(s, 'MAX_OUTPUT', 10000):
            code, out, _ = self.run_search('Find retry code', '--json')
        result = json.loads(out)
        self.assertEqual(code, 2)
        self.assertEqual(result['status'], 'output_limit')
        self.assertFalse(result['complete'])
        self.assertEqual(len(result['context']), 10000)

    def test_source_and_diagnostic_secrets_redacted(self):
        os.environ['JG_OUTPUT'] = 'diagnostic fake-jg-key and api_key="sensitive_value_123456"'
        _, out, err = self.run_search('Find retry code')
        self.assertNotIn('fake-jg-key', out + err)
        self.assertNotIn('sensitive_value_123456', out + err)
        self.assertIn('REDACTED', out)

    def test_auth_explicit_no_key_in_argv_output_or_env(self):
        s.credentials_path().unlink()
        core.routing.save(core.routing.root() / 'routing.json', dict(jev_provider='openrouter'))
        code, out, err = self.run_search('--auth-from-routing', '--json')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)['provider'], 'openrouter')
        self.assertEqual(s.credentials(), ('openrouter', 'fake-router-key'))
        self.assertNotIn('fake-router-key', out + err + self.log.read_text())
        self.assertEqual(self.calls()[-1]['args'], ['auth', '--provider', 'openrouter', '--stdin'])
        self.assertFalse(self.calls()[-1]['key_env'])

    def test_existing_auth_preserved_without_explicit_replace(self):
        before = s.credentials_path().read_bytes()
        code, _, err = self.run_search('--auth-from-routing')
        self.assertNotEqual(code, 0)
        self.assertIn('--replace-auth', err)
        self.assertEqual(s.credentials_path().read_bytes(), before)
        self.assertEqual(len(self.calls()), 1)
        code, _, _ = self.run_search('--auth-from-routing', '--replace-auth')
        self.assertEqual(code, 0)
        self.assertEqual(s.credentials()[0], 'typesafe')

    def test_missing_query_reserved_commands_and_conflicts_do_not_dispatch(self):
        for args in ([], ['auth'], ['doctor'], ['skill'], ['cache'], ['files'], ['  '], ['question', '--check'], ['--replace-auth'], ['bad\x00query']):
            with self.subTest(args=args):
                code, _, _ = self.run_search(*args)
                self.assertNotEqual(code, 0)
        self.assertEqual(self.calls(), [])

    def test_query_shell_text_is_only_one_positional_argument(self):
        question = '--include-sensitive $(touch sentinel); "quote"'
        code, _, _ = self.run_search('--', question)
        self.assertEqual(code, 0)
        self.assertEqual(self.calls()[-1]['args'][1], question)

    def test_malformed_credentials_and_invalid_root_fail_without_search(self):
        for value in ('[]', 'null', '{"apiKey":3}', '{"apiKey":"x","provider":"other"}', '{"apiKey":"two words"}'):
            with self.subTest(value=value):
                s.credentials_path().write_text(value)
                code, out, _ = self.run_search('--check', '--json')
                self.assertEqual(code, 1)
                self.assertFalse(json.loads(out)['ready'])
        self.assertTrue(all(call['args'] == ['--version'] for call in self.calls()))
        self.log.unlink()
        code, _, _ = self.run_search('Find retry code', '--root', str(self.base / 'missing'))
        self.assertNotEqual(code, 0)
        self.assertEqual(self.calls(), [])


if __name__ == '__main__':
    unittest.main()
