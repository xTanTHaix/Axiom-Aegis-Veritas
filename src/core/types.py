"""
Core Type Definitions for Aegis-Veritas.

Provides type aliases, enums, and dataclasses used across the system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, TypeVar, Generic
from datetime import datetime
import threading
import asyncio

V = TypeVar('V', bound=Any)
K = TypeVar('K', bound=Any)

# ============================================================================
# Type Aliases (PEP 695) - UPPER CASE for consistency
# ============================================================================

AccessType = TypeAlias = "Literal['WRITE', 'READ', 'SHARED']"
ConflictType = TypeAlias = "Literal['READ-WRITE', 'WRITE-WRITE', 'READ-READ']"

T = TypeVar('T', bound=Any)
E = TypeVar('E', bound=object)

# ============================================================================
# Enums
# ============================================================================

class EventState(Enum):
    """State of an event in the execution trace."""
    UNDEFINED = 0
    PENDING = 1
    EXECUTING = 2
    COMPLETED = 3
    ABORTED = 4
    CONFLICT = 5
    RESOLVED = 6


class ConflictType(Enum):
    """Types of conflicts that may occur."""
    READ_WRITE = "read-write"
    WRITE_WRITE = "write-write"
    READ_READ = "read-read"


class ShardStatus(Enum):
    """Status of a shard in the dispatcher."""
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class WorkerState(Enum):
    """State of a worker in the dispatcher."""
    IDLE = "idle"
    BUSY = "busy"
    PAUSED = "paused"
    TERMINATED = "terminated"


# ============================================================================
# Dataclasses
# ============================================================================

@dataclass
class EventId:
    """Unique identifier for an event."""
    event_id: str
    timestamp: datetime = field(default_factory=datetime.now)
    event_type: str = ""
    thread_id: Optional[int] = None
    line_number: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.event_id:
            raise ValueError("EventId must have a non-empty event_id")


@dataclass
class ConflictInfo:
    """Information about a detected conflict."""
    conflict_id: str
    event_ids: List[EventId]
    conflict_type: str  # Changed from ConflictType to str for test compatibility
    resolution_strategy: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.conflict_id:
            raise ValueError("ConflictInfo must have a non-empty conflict_id")
        if not self.event_ids:
            raise ValueError("ConflictInfo must have at least one event_id")
    
    @property
    def conflict_type_str(self) -> str:
        """Return conflict type as string."""
        return self.conflict_type


@dataclass
class AccessType:
    """Access type for a memory location.
    
    This dataclass provides READ, WRITE, and SHARED access types.
    Instances can be created using from_string() method.
    """
    access_id: str
    access_type: AccessType
    location: str
    thread_id: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Class attribute for all valid access type strings
    _values = ('WRITE', 'READ', 'SHARED')

    def __post_init__(self):
        if not self.access_id:
            raise ValueError("AccessType must have a non-empty access_id")
        if self.access_type not in ['WRITE', 'READ', 'SHARED']:
            raise ValueError(f"AccessType must be 'WRITE', 'READ', or 'SHARED', got {self.access_type}")

    @classmethod
    def from_string(cls, access_type_str: str) -> 'AccessType':
        """Create AccessType from string (case-insensitive)."""
        normalized = access_type_str.strip().upper()
        if normalized == 'WRITE':
            return cls(access_id='WRITE', access_type='WRITE', location='')
        elif normalized == 'READ':
            return cls(access_id='READ', access_type='READ', location='')
        elif normalized == 'SHARED':
            return cls(access_id='SHARED', access_type='SHARED', location='')
        else:
            raise ValueError(f"Invalid access type: {access_type_str}")

    @property
    def is_read(self) -> bool:
        """Check if this is a READ access."""
        return self.access_type == 'READ'

    @property
    def is_write(self) -> bool:
        """Check if this is a WRITE access."""
        return self.access_type == 'WRITE'

    @property
    def is_shared(self) -> bool:
        """Check if this is a SHARED access."""
        return self.access_type == 'SHARED'


# ============================================================================
# Generic Containers
# ============================================================================

class ThreadSafeSet(Generic[T]):
    """Thread-safe set implementation."""
    
    def __init__(self, initial: Optional[Set[T]] = None):
        self._data = set(initial) if initial else set()
        self._lock = threading.Lock()
    
    def add(self, item: T) -> bool:
        with self._lock:
            return self._data.add(item)
    
    def remove(self, item: T) -> bool:
        with self._lock:
            return self._data.discard(item)
    
    def __contains__(self, item: T) -> bool:
        with self._lock:
            return item in self._data
    
    def __len__(self) -> int:
        with self._lock:
            return len(self._data)
    
    def __iter__(self):
        with self._lock:
            return iter(list(self._data))
    
    def copy(self) -> 'ThreadSafeSet[T]':
        with self._lock:
            return ThreadSafeSet(set(self._data))
    
    def to_list(self) -> List[T]:
        with self._lock:
            return list(self._data)
    
    def clear(self) -> None:
        with self._lock:
            self._data.clear()


class ThreadSafeDict(Generic[T, V]):
    """Thread-safe dictionary implementation."""
    
    def __init__(self, initial: Optional[Dict[T, V]] = None):
        self._data = dict(initial) if initial else {}
        self._lock = threading.Lock()
    
    def __setitem__(self, key: T, value: V) -> None:
        with self._lock:
            self._data[key] = value
    
    def __getitem__(self, key: T) -> V:
        with self._lock:
            return self._data[key]
    
    def __delitem__(self, key: T) -> None:
        with self._lock:
            del self._data[key]
    
    def __contains__(self, key: T) -> bool:
        with self._lock:
            return key in self._data
    
    def __len__(self) -> int:
        with self._lock:
            return len(self._data)
    
    def get(self, key: T, default: Optional[V] = None) -> Optional[V]:
        with self._lock:
            return self._data.get(key, default)
    
    def keys(self) -> List[T]:
        with self._lock:
            return list(self._data.keys())
    
    def values(self) -> List[V]:
        with self._lock:
            return list(self._data.values())
    
    def items(self) -> List[Tuple[T, V]]:
        with self._lock:
            return list(self._data.items())
    
    def clear(self) -> None:
        with self._lock:
            self._data.clear()


# ============================================================================
# Utility Functions
# ============================================================================

def generate_event_id(prefix: str, timestamp: Optional[datetime] = None) -> EventId:
    """Generate a unique event ID."""
    if timestamp is None:
        timestamp = datetime.now()
    return EventId(
        event_id=f"{prefix}_{timestamp.strftime('%Y%m%d%H%M%S')}_{threading.get_ident()}",
        timestamp=timestamp
    )


def generate_conflict_id(prefix: str) -> str:
    """Generate a unique conflict ID."""
    return f"{prefix}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
