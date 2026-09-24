REGISTRY = {}


def command(name, help):
    """Class decorator registering a sub-command under `name`."""
    def register(cls):
        cls.name = name
        cls.help = help
        REGISTRY[name] = cls
        return cls
    return register
