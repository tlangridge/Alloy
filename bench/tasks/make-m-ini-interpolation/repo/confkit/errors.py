class ConfigError(Exception):
    """A problem in a configuration file, pinned to a 1-based line number."""

    def __init__(self, message, lineno=None):
        super(ConfigError, self).__init__(message)
        self.message = message
        self.lineno = lineno

    def __str__(self):
        if self.lineno is None:
            return self.message
        return 'line %d: %s' % (self.lineno, self.message)
