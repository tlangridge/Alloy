"""confkit: the INI-style configuration loader used by the deploy tools."""
from confkit.errors import ConfigError
from confkit.loader import Config, load

__all__ = ['Config', 'ConfigError', 'load']
