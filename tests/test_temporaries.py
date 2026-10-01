"""Allocation, atexit and signal regressions; no coding CLI or HOME changes."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_execution import core, ROOT


class TemporaryLifecycleTests(unittest.TestCase):
    def test_partial_allocation_failure_removes_first_runtime(self):
        with tempfile.TemporaryDirectory() as base:
            allocated = []
            real_temp = core.tempfile.mkdtemp
            def allocate(*args, **kwargs):
                if allocated:
                    raise OSError('second allocation failed')
                path = real_temp(*args, **kwargs)
                allocated.append(path)
                return path
            with patch.dict(os.environ, ALLOY_RUN_ROOT=base + '/runs'), \
                    patch.object(core.tempfile, 'mkdtemp', side_effect=allocate):
                with self.assertRaisesRegex(OSError, 'second allocation failed'):
                    core.cursor_make_runtime(source=base)
            self.assertEqual(len(allocated), 1)
            self.assertFalse(Path(allocated[0]).exists())

    def test_exit_and_signals_remove_registered_runtimes(self):
        script = '''import importlib.machinery, importlib.util, os, signal, sys
loader = importlib.machinery.SourceFileLoader('temp_core', sys.argv[1])
spec = importlib.util.spec_from_loader(loader.name, loader)
core = importlib.util.module_from_spec(spec)
loader.exec_module(core)
root, outside = sys.argv[2:4]
os.mkdir(root); os.mkdir(outside)
core._LIVE_RUNTIMES.add(core.CursorRuntime(root, outside))
core._install_signal_handlers()
if sys.argv[4] != 'exit':
    os.kill(os.getpid(), getattr(signal, sys.argv[4]))
'''
        with tempfile.TemporaryDirectory() as base:
            for mode in ('exit', 'SIGTERM', 'SIGINT'):
                with self.subTest(mode=mode):
                    root, outside = Path(base) / (mode + '-runtime'), Path(base) / (mode + '-canary')
                    env = dict(os.environ, ALLOY_RUN_ROOT=base + '/runs')
                    result = subprocess.run([sys.executable, '-c', script, str(ROOT / 'bin/alloy'),
                        str(root), str(outside), mode], env=env, capture_output=True, text=True, timeout=15)
                    self.assertEqual(result.returncode, 0 if mode == 'exit' else 130, result.stderr)
                    self.assertFalse(root.exists())
                    self.assertFalse(outside.exists())
