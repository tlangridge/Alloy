"""Actual image receipts and the scoped read boundary, without model calls."""
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import alloy_artifacts as artifacts


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'render').mkdir()
        self.data = b'\x89PNG\r\n\x1a\n' + b'sample pixels'
        (self.root / 'render/page.png').write_bytes(self.data)

    def test_receipt_describes_the_attached_bytes(self):
        rows, images = artifacts.capture(self.root, ['render/page.png'], ['render'])
        self.assertEqual(images, [self.data])
        self.assertEqual(rows, [dict(path='render/page.png', mime_type='image/png', bytes=len(self.data),
                                     sha256=hashlib.sha256(images[0]).hexdigest())])

    def test_escape_and_out_of_scope_are_refused(self):
        for name, allowed in (('.', ['.']), ('../page.png', ['.']), (str(self.root / 'render/page.png'), ['.']),
                              ('render/page.png', ['src'])):
            with self.subTest(name=name), self.assertRaises(ValueError):
                artifacts.receipts(self.root, [name], allowed)

    def test_symlink_files_and_directories_are_refused(self):
        (self.root / 'link.png').symlink_to(self.root / 'render/page.png')
        (self.root / 'link').symlink_to(self.root / 'render', target_is_directory=True)
        for name in ('link.png', 'link/page.png'):
            with self.subTest(name=name), self.assertRaises(OSError):
                artifacts.receipts(self.root, [name], ['.'])

    def test_oversize_non_image_and_fifo_fail_closed(self):
        with patch.object(artifacts, 'MAX_BYTES', 9), self.assertRaises(ValueError):
            artifacts.receipts(self.root, ['render/page.png'], ['.'])
        (self.root / 'render/page.png').write_bytes(b'PNG description only')
        with self.assertRaises(ValueError):
            artifacts.receipts(self.root, ['render/page.png'], ['.'])
        os.mkfifo(self.root / 'pipe')
        with self.assertRaises(ValueError):
            artifacts.receipts(self.root, ['pipe'], ['.'])

    def test_changed_bytes_produce_a_different_revision_receipt(self):
        first = artifacts.receipts(self.root, ['render/page.png'], ['.'])
        (self.root / 'render/page.png').write_bytes(self.data + b'changed layout')
        self.assertNotEqual(first, artifacts.receipts(self.root, ['render/page.png'], ['.']))

    def test_attachment_count_and_total_bytes_are_bounded(self):
        with self.assertRaisesRegex(ValueError, '8'):
            artifacts.receipts(self.root, ['render/page.png'] * 9, ['.'])
        with patch.object(artifacts, 'MAX_TOTAL_BYTES', len(self.data)), self.assertRaisesRegex(ValueError, 'total'):
            artifacts.receipts(self.root, ['render/page.png'] * 2, ['.'])
