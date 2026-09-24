"""Sub-commands. Importing a command module registers it in REGISTRY."""
from shipit.commands.registry import REGISTRY, command  # noqa: F401
from shipit.commands import deploy, report, status  # noqa: F401,E402  (registration)
