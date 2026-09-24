"""In-memory registry mapping user ids to unique handles."""
import re

_HANDLE = re.compile(r'\w{3,20}')


class RegistryError(Exception):
    """Base class for registry errors."""


class HandleTaken(RegistryError):
    def __init__(self, handle):
        super().__init__('handle already taken: %s' % handle)
        self.handle = handle


class AlreadyRegistered(RegistryError):
    """The user already has a handle; use rename()."""


class UnknownUser(RegistryError):
    """The user has no handle."""


def validate(handle):
    """Strip surrounding whitespace and require 3-20 word characters."""
    if not isinstance(handle, str):
        raise TypeError('handle must be a string')
    handle = handle.strip()
    if not _HANDLE.fullmatch(handle):
        raise ValueError('handles are 3-20 letters, digits or underscores: %r' % handle)
    return handle


class HandleRegistry:
    """Maps user ids to handles. Handles are unique ignoring case."""

    def __init__(self):
        self._owners = {}    # comparison key -> user id
        self._handles = {}   # user id -> handle as the user typed it

    def register(self, user_id, handle):
        """Give a new user a handle and return it (as stored)."""
        handle = validate(handle)
        if user_id in self._handles:
            raise AlreadyRegistered(user_id)
        key = handle.lower()
        if key in self._owners:
            raise HandleTaken(handle)
        self._owners[key] = user_id
        self._handles[user_id] = handle
        return handle

    def lookup(self, handle):
        """Return the id of the user owning `handle` (any spelling), or None."""
        try:
            handle = validate(handle)
        except ValueError:
            return None
        return self._owners.get(handle.lower())

    def handle_of(self, user_id):
        """The handle as the user typed it."""
        try:
            return self._handles[user_id]
        except KeyError:
            raise UnknownUser(user_id) from None

    def rename(self, user_id, new_handle):
        """Change a user's handle and return the new one.

        Renaming to another spelling of your own handle ('bob' -> 'Bob') is
        allowed and only changes how it is displayed.
        """
        new_handle = validate(new_handle)
        current = self.handle_of(user_id)
        new_key = new_handle.lower()
        owner = self._owners.get(new_key)
        if owner is not None and owner != user_id:
            raise HandleTaken(new_handle)
        del self._owners[current.lower()]
        self._owners[new_key] = user_id
        self._handles[user_id] = new_handle
        return new_handle

    def mentions(self, text):
        """User ids mentioned as @handle in `text`, in order of first mention."""
        seen = []
        for match in re.finditer(r'@(\w+)', text):
            user_id = self.lookup(match.group(1))
            if user_id is not None and user_id not in seen:
                seen.append(user_id)
        return seen

    def release(self, user_id):
        """Forget a user's handle so someone else may take it."""
        handle = self.handle_of(user_id)
        del self._owners[handle.lower()]
        del self._handles[user_id]

    def __len__(self):
        return len(self._handles)

    def __contains__(self, handle):
        return self.lookup(handle) is not None
