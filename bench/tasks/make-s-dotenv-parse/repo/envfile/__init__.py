"""Minimal ``.env`` support."""
from .loader import load_env
from .parser import DotenvError, parse_env

__all__ = ['DotenvError', 'load_env', 'parse_env']
