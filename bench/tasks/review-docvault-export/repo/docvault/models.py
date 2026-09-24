from dataclasses import dataclass, field
from typing import FrozenSet, Optional, Set


@dataclass(frozen=True)
class User:
    id: str
    workspace_id: str
    roles: FrozenSet[str] = frozenset()


@dataclass
class Folder:
    id: str
    workspace_id: str
    name: str
    members: Set[str] = field(default_factory=set)      # user ids


@dataclass
class Document:
    id: str
    workspace_id: str
    owner_id: str
    title: str
    body: str
    folder_id: Optional[str] = None
    shared_with: Set[str] = field(default_factory=set)  # user ids
    archived: bool = False


@dataclass(frozen=True)
class Summary:
    """What listings and search results show: never the body."""
    id: str
    title: str
    archived: bool
