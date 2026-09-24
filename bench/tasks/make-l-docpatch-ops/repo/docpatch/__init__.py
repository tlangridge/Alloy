"""docpatch: pointer-addressed patches for JSON-like documents."""
from .diff import diff
from .equality import json_equal
from .errors import PatchError
from .ops import apply_patch
from .pointer import format_pointer, parse_pointer, resolve

__all__ = ['PatchError', 'apply_patch', 'diff', 'json_equal', 'parse_pointer', 'format_pointer', 'resolve']
