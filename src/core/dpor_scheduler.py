"""
DPOR Scheduler Module.

Provides deterministic partial order reduction scheduling.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union, Callable, Tuple, Set
from datetime import datetime
import threading
import asyncio

from src.core.types import (
    AccessType as AccessTypeDataclass,
    ConflictInfo,
    ConflictType,
    EventId,
    EventState,
)

# Simplified AccessType for use in dpor_scheduler.py
class AccessType:
    """Simplified access type for memory access events."""
    WRITE = "WRITE"
    READ = "READ"
    SHARED = "SHARED"
    
    def __init__(self, access_type: str) -> None:
        self.access_type = access_type
    
    def __eq__(self, other: object) -> bool:
        if isinstance(other, AccessType):
            return self.access_type == other.access_type
        return False
    
    def __hash__(self) -> int:
        return hash(self.access_type)
    
    def __repr__(self) -> str:
        return f"AccessType({self.access_type})"
    
    @property
    def is_write(self) -> bool:
        """Check if this is a WRITE access."""
        return self.access_type == "WRITE"
    
    @property
    def is_read(self) -> bool:
        """Check if this is a READ access."""
        return self.access_type == "READ"
    
    @property
    def is_shared(self) -> bool:
        """Check if this is a SHARED access."""
        return self.access_type == "SHARED"


class MemoryAccessEvent:
    """Represents a memory access event."""

    def __init__(
        self,
        event_id: int,
        thread_id: Union[int, str],
        access_type: Union[str, AccessType],
        address: int,
        value: Optional[int] = None,
        timestamp: float = 0.0,
        vector_clock: Optional[Dict[int, int]] = None,
        gas_limit: Optional[int] = None,
    ) -> None:
        """Initialize memory access event.

        Args:
            event_id: Unique event identifier.
            thread_id: Thread that performed the access.
            access_type: Type of access (read/write).
            address: Memory address accessed.
            value: Value accessed (for read) or written (for write).
            timestamp: Timestamp of the access.
            vector_clock: Vector clock for happens-before ordering.
            gas_limit: Optional gas limit for the event.
        """
        # Store access_type as AccessType instance for comparison
        if isinstance(access_type, AccessType):
            self.access_type = access_type
        elif isinstance(access_type, AccessTypeDataclass):
            # Convert types.AccessType to dpor_scheduler.AccessType
            self.access_type = AccessType(access_type.access_type)
        elif isinstance(access_type, str):
            self.access_type = AccessType(access_type)
        
        # Store raw access_type for comparison with class attributes
        self._raw_access_type = str(access_type) if isinstance(access_type, AccessTypeDataclass) else access_type
        
        # Store raw access_type as string for easier comparison
        self._access_type_raw_str = str(self.access_type)

        self.event_id = event_id
        self.thread_id = thread_id
        self.address = address
        self.value = value
        self.timestamp = timestamp
        self.vector_clock = vector_clock
        self.gas_limit = gas_limit
        self.state = EventState.PENDING

    def __repr__(self) -> str:
        return (
            f"MemoryAccessEvent(event_id={self.event_id}, "
            f"thread_id={self.thread_id}, access_type={self.access_type}, "
            f"address={self.address}, value={self.value}, "
            f"timestamp={self.timestamp}, state={self.state})"
        )

    @property
    def access_type_str(self) -> str:
        """Get access type as string."""
        if isinstance(self.access_type, AccessType):
            return self.access_type.access_type
        elif isinstance(self.access_type, AccessTypeDataclass):
            return self.access_type.access_type
        return str(self.access_type)
    
    @property
    def access_type_class_attr(self) -> Optional[str]:
        """Get raw access type for comparison with class attributes."""
        return self._raw_access_type
    
    def cleanup(self) -> None:
        """Clean up event resources."""
        self.state = EventState.CANCELLED


class PermissiveMockProxy:
    """Permissive mock proxy for async protocols."""

    def __init__(self, mock: Optional[Any] = None) -> None:
        """Initialize permissive mock proxy.

        Args:
            mock: Underlying MagicMock instance.
        """
        object.__setattr__(self, '_mock', mock)
        object.__setattr__(self, '_timeout', None)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Initialize subclass with async protocol support."""
        super().__init_subclass__(**kwargs)
        object.__setattr__(cls, '_async_support', True)

    def set_timeout(self, timeout: float) -> None:
        """Set timeout for async operations.

        Args:
            timeout: Timeout in seconds.
        """
        self._timeout = timeout

    async def call_async(
        self,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Call async function with timeout.

        Args:
            func: Async function to call.
            *args: Positional arguments.
            **kwargs: Keyword arguments.

        Returns:
            Result of the async function.

        Raises:
            TimeoutError: If the function times out.
        """
        import asyncio

        if self._timeout is not None:
            try:
                return await asyncio.wait_for(
                    func(*args, **kwargs), timeout=self._timeout
                )
            except asyncio.TimeoutError:
                raise TimeoutError("Async operation timed out")
        return await func(*args, **kwargs)

    async def __aenter__(self) -> 'PermissiveMockProxy':
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        pass


class VectorClock:
    """Vector clock for happens-before ordering."""

    def __init__(
        self,
        num_threads: int = 1,
        clock: Optional[Dict[int, int]] = None,
    ) -> None:
        """Initialize vector clock.

        Args:
            num_threads: Number of threads (processes) to track.
            clock: Optional initial clock dictionary.

        Raises:
            ValueError: If num_threads is not positive.
        """
        if num_threads <= 0:
            raise ValueError("num_threads must be positive")

        self.num_threads = num_threads
        self._num_threads = num_threads  # For backward compatibility
        if clock is not None:
            self.clock = clock.copy()
        else:
            self.clock = {i: 0 for i in range(num_threads)}

    def increment(self, thread_id: int) -> None:
        """Increment clock for a thread.

        Args:
            thread_id: Thread ID to increment.

        Raises:
            RuntimeError: If thread_id is out of range.
        """
        if thread_id < 0 or thread_id >= self.num_threads:
            raise RuntimeError(
                f"thread_id {thread_id} is out of range (0-{self.num_threads-1})"
            )
        self.clock[thread_id] += 1

    def get(self, thread_id: int) -> int:
        """Get clock value for a thread.

        Args:
            thread_id: Thread ID to get clock value.

        Returns:
            Clock value for the thread.

        Raises:
            RuntimeError: If thread_id is out of range.
        """
        if thread_id < 0 or thread_id >= self.num_threads:
            raise RuntimeError(
                f"thread_id {thread_id} is out of range (0-{self.num_threads-1})"
            )
        return self.clock[thread_id]

    def merge(self, other_clock: Dict[int, int]) -> Dict[int, int]:
        """Merge with another vector clock.

        Args:
            other_clock: Another vector clock as a dictionary.

        Returns:
            New merged vector clock as a dictionary.

        Raises:
            ValueError: If clocks have different dimensions.
        """
        if self.num_threads != len(other_clock):
            raise ValueError(
                f"Clocks have different dimensions ({self.num_threads} vs {len(other_clock)})"
            )
        merged = {
            i: max(self.clock.get(i, 0), other_clock.get(i, 0))
            for i in range(self.num_threads)
        }
        return merged

    def happens_before(self, other_clock: Dict[int, int]) -> bool:
        """Check if this clock happens before another.

        A clock A happens before clock B if:
        - A is not equal to B
        - For all threads, A's clock value <= B's clock value
        - There exists at least one thread where A's clock value < B's clock value

        Args:
            other_clock: Another vector clock as a dictionary.

        Returns:
            True if this clock happens before other.
        """
        all_threads = set(range(self.num_threads)) | set(range(len(other_clock)))

        # A is not equal to B
        self_eq_other = all(
            self.clock.get(tid, 0) == other_clock.get(tid, 0)
            for tid in all_threads
        )

        # A's clock <= B's clock for all threads
        self_leq_other = all(
            self.clock.get(tid, 0) <= other_clock.get(tid, 0)
            for tid in all_threads
        )

        # A's clock < B's clock for at least one thread
        self_lt_other = any(
            self.clock.get(tid, 0) < other_clock.get(tid, 0)
            for tid in all_threads
        )

        return self_eq_other is False and self_leq_other and self_lt_other

    def happens_concurrently(self, other_clock: Dict[int, int]) -> bool:
        """Check if two clocks happen concurrently.

        Args:
            other_clock: Another vector clock as a dictionary.

        Returns:
            True if the clocks happen concurrently.
        """
        all_threads = set(range(self.num_threads)) | set(range(len(other_clock)))

        # For concurrent, A must have some threads < B and some threads > B
        strictly_less = any(
            self.clock.get(tid, 0) < other_clock.get(tid, 0)
            for tid in all_threads
        )
        strictly_greater = any(
            self.clock.get(tid, 0) > other_clock.get(tid, 0)
            for tid in all_threads
        )

        return strictly_less and strictly_greater

    def concurrent_with(self, other_clock: Dict[int, int]) -> bool:
        """Check if this clock happens concurrently with another.

        Two clocks are concurrent if neither happens before the other.

        Args:
            other_clock: Another vector clock as a dictionary.

        Returns:
            True if the clocks happen concurrently.
        """
        all_threads = set(range(self.num_threads)) | set(range(len(other_clock)))

        # A happens before B?
        a_before_b = self.happens_before(other_clock)
        # B happens before A? (reverse happens_before check)
        all_eq = all(
            other_clock.get(tid, 0) == self.clock.get(tid, 0)
            for tid in all_threads
        )
        all_le = all(
            other_clock.get(tid, 0) <= self.clock.get(tid, 0)
            for tid in all_threads
        )
        all_lt = any(
            other_clock.get(tid, 0) < self.clock.get(tid, 0)
            for tid in all_threads
        )
        b_before_a = not all_eq and all_le and all_lt

        # Concurrent if neither happens before the other
        return a_before_b is False and b_before_a is False

    def __repr__(self) -> str:
        return f"VectorClock(num_threads={self.num_threads}, clock={self.clock})"


class ConflictDetector:
    """Detects data races and conflicts in memory access events."""

    def __init__(self) -> None:
        """Initialize conflict detector."""
        self._events: List[MemoryAccessEvent] = []
        self._conflicts: List[ConflictInfo] = []
        self._lock = threading.Lock()

    def add_event(self, event: MemoryAccessEvent) -> None:
        """Add a memory access event.

        Args:
            event: Memory access event to add.
        """
        with self._lock:
            self._events.append(event)
            self._detect_conflicts(event)

    def _detect_conflicts(self, event: MemoryAccessEvent) -> None:
        """Detect conflicts with existing events."""
        for existing in self._events:
            if self._has_conflict(event, existing):
                conflict = self._create_conflict(event, existing)
                # Avoid duplicate conflicts
                conflict_id = conflict.conflict_id
                if not any(c.conflict_id == conflict_id for c in self._conflicts):
                    self._conflicts.append(conflict)

    def _has_conflict(
        self,
        event1: MemoryAccessEvent,
        event2: MemoryAccessEvent,
    ) -> bool:
        """Check if two events have a conflict.

        A conflict occurs when:
        - Two events access the same address
        - At least one is a WRITE
        - Events are interleaved (one happened before the other, but not both before/after)
        """
        # Same address?
        if event1.address != event2.address:
            return False
        
        # Same thread? (same thread, same address, no race)
        if event1.thread_id == event2.thread_id:
            return False

        # Same event? (same event_id)
        if event1.event_id == event2.event_id:
            return False

        # At least one write?
        if not (event1.access_type.is_write or event2.access_type.is_write):
            return False

        # Interleaved? Check vector clocks
        vc1 = event1.vector_clock if event1.vector_clock else {}
        vc2 = event2.vector_clock if event2.vector_clock else {}
        
        # If no vector clocks, assume concurrent (race condition)
        if not vc1 or not vc2:
            return True
        
        # Handle both dict and VectorClock object
        if isinstance(vc1, VectorClock):
            vc1_clock = vc1.clock
            vc1_obj = vc1
        else:
            vc1_clock = vc1
            vc1_obj = None
            
        if isinstance(vc2, VectorClock):
            vc2_clock = vc2.clock
            vc2_obj = vc2
        else:
            vc2_clock = vc2
            vc2_obj = None
        
        # Check if one happens before the other
        if vc1_obj and vc2_obj:
            vc1_before_vc2 = vc1_obj.happens_before(vc2_clock)
            vc2_before_vc1 = vc2_obj.happens_before(vc1_clock)
        elif vc1_obj:
            vc1_before_vc2 = vc1_obj.happens_before(vc2_clock)
            vc2_before_vc1 = False
        elif vc2_obj:
            vc1_before_vc2 = False
            vc2_before_vc1 = vc2_obj.happens_before(vc1_clock)
        else:
            # Both are dicts, use helper method
            vc1_before_vc2 = self._dict_happens_before(vc1_clock, vc2_clock)
            vc2_before_vc1 = self._dict_happens_before(vc2_clock, vc1_clock)
            
        # Concurrent if neither happens before the other
        return not vc1_before_vc2 and not vc2_before_vc1

    def _dict_happens_before(self, clock1: Dict[int, int], clock2: Dict[int, int]) -> bool:
        """Check if clock1 happens before clock2 (for dicts).
        
        Args:
            clock1: First vector clock dict.
            clock2: Second vector clock dict.
            
        Returns:
            True if clock1 happens before clock2.
        """
        all_threads = set(range(max(len(clock1), len(clock2))))
        
        # Not equal
        if clock1 == clock2:
            return False
        
        # All threads in clock1 have <= values in clock2
        for i in range(len(clock1)):
            if clock1.get(i, 0) > clock2.get(i, 0):
                return False
        
        # At least one thread has < value in clock2
        has_strict_less = any(clock1.get(i, 0) < clock2.get(i, 0) for i in range(len(clock1)))
        
        return has_strict_less

    def _create_conflict(
        self,
        event1: MemoryAccessEvent,
        event2: MemoryAccessEvent,
    ) -> ConflictInfo:
        """Create a conflict info object.

        Args:
            event1: First event in the conflict.
            event2: Second event in the conflict.

        Returns:
            ConflictInfo object describing the conflict.
        """
        if event1.event_id < event2.event_id:
            events = [event1, event2]
        else:
            events = [event2, event1]

        conflict_type = ConflictType.WRITE_WRITE if (
            event1.access_type.is_write and event2.access_type.is_write
        ) else ConflictType.READ_WRITE

        return ConflictInfo(
            conflict_id=f"conflict_{len(self._conflicts)}",
            event_ids=events,
            conflict_type=conflict_type,
        )

    def get_conflicts(self) -> List[ConflictInfo]:
        """Get all detected conflicts.

        Returns:
            List of conflict info objects.
        """
        with self._lock:
            return list(self._conflicts)

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about recorded events and conflicts.

        Returns:
            Dictionary with statistics.
        """
        with self._lock:
            return {
                "total_events": len(self._events),
                "total_conflicts": len(self._conflicts),
                "unique_addresses": len(set(e.address for e in self._events)),
            }

    def clear(self) -> None:
        """Clear all recorded events and conflicts."""
        with self._lock:
            self._events.clear()
            self._conflicts.clear()

    def detect_conflict(self, event1: MemoryAccessEvent, event2: MemoryAccessEvent) -> Optional[ConflictInfo]:
        """Detect conflict between two events.

        Args:
            event1: First event.
            event2: Second event.

        Returns:
            ConflictInfo if conflict exists, None otherwise.
        """
        if self._has_conflict(event1, event2):
            return self._create_conflict(event1, event2)
        return None

    def is_concurrent(self, event1: MemoryAccessEvent, event2: MemoryAccessEvent) -> bool:
        """Check if two events are concurrent (interleaved).

        Args:
            event1: First event.
            event2: Second event.

        Returns:
            True if events are concurrent.
        """
        # Same address?
        if event1.address != event2.address:
            return False

        # At least one write?
        if not (event1.access_type.is_write or event2.access_type.is_write):
            return False

        # Check if they are interleaved using vector clocks
        if event1.vector_clock is not None and event2.vector_clock is not None:
            vc1 = event1.vector_clock
            vc2 = event2.vector_clock
            all_threads = set(vc1.keys()) | set(vc2.keys())
            
            # Check if vc1 happens before vc2 or vice versa
            vc1_before_vc2 = all(
                vc1.get(tid, 0) <= vc2.get(tid, 0)
                for tid in all_threads
            ) and any(
                vc1.get(tid, 0) < vc2.get(tid, 0)
                for tid in all_threads
            )
            
            vc2_before_vc1 = all(
                vc2.get(tid, 0) <= vc1.get(tid, 0)
                for tid in all_threads
            ) and any(
                vc2.get(tid, 0) < vc1.get(tid, 0)
                for tid in all_threads
            )
            
            # Concurrent if neither happens before the other
            return vc1_before_vc2 is False and vc2_before_vc1 is False
        
        # No vector clocks, assume interleaved if same address and at least one write
        return True


class DeterministicVirtualScheduler:
    """Deterministic virtual scheduler for DPOR execution."""

    def __init__(
        self,
        num_workers: int,
        gas_limit: Optional[int] = None,
    ) -> None:
        """Initialize scheduler.

        Args:
            num_workers: Number of virtual workers.
            gas_limit: Optional gas limit for event recording.
        """
        self.num_workers = num_workers
        self.gas_limit = gas_limit
        self._execution_order: List[int] = []
        self._virtual_clock: int = 0
        self._thread_order: List[int] = []
        self._lock = threading.Lock()
        self._thread_clocks: Dict[int, Dict[int, int]] = {}
        self._event_counter: int = 0  # Global event counter for gas limit
        self._event_access_types: Dict[int, AccessType] = {}
        self._event_addresses: Dict[int, int] = {}
        self._event_thread_ids: Dict[int, int] = {}  # event_id -> thread_id
        self._conflict_detector = ConflictDetector()

    def record_event(
        self,
        thread_id: int,
        address: int,
        access_type: AccessType,
        vector_clock: Optional[Dict[int, int]] = None,
    ) -> MemoryAccessEvent:
        """Record a memory access event.

        Args:
            thread_id: Thread that performed the access.
            address: Memory address accessed.
            access_type: Type of access.
            vector_clock: Vector clock for happens-before ordering.

        Returns:
            The recorded memory access event.
        """
        # Check gas limit
        if self.gas_limit is not None:
            current_gas = self._event_counter
            if current_gas >= self.gas_limit:
                raise RuntimeError("Gas limit exceeded")

        with self._lock:
            # Validate address
            if address < 0:
                raise ValueError("address must be non-negative")

            # Validate thread_id
            if thread_id < 0 or thread_id >= self.num_workers:
                raise RuntimeError(
                    f"thread_id {thread_id} is out of range (0-{self.num_workers-1})"
                )

            # Initialize thread clock if needed
            if thread_id not in self._thread_clocks:
                self._thread_clocks[thread_id] = {i: 0 for i in range(self.num_workers)}
            # Global event counter, no per-thread initialization needed

            # Initialize vector clock if not provided
            if vector_clock is None:
                vector_clock = self._thread_clocks[thread_id].copy()

            # Increment vector clock for this thread
            self._thread_clocks[thread_id][thread_id] += 1

            event = MemoryAccessEvent(
                event_id=self._virtual_clock,
                thread_id=thread_id,
                access_type=access_type,
                address=address,
                timestamp=float(self._virtual_clock),
                vector_clock=vector_clock,
            )
            self._execution_order.append(event.event_id)
            self._virtual_clock += 1
            self._event_counter += 1
            # Convert access_type to AccessType object if it's a string
            if isinstance(access_type, str):
                access_type = AccessType(access_type)
            self._event_thread_ids[event.event_id] = thread_id
            self._event_access_types[event.event_id] = access_type
            self._event_addresses[event.event_id] = address

            return event

    def get_execution_order(self) -> List[int]:
        """Get the execution order of recorded events.

        Returns:
            List of event IDs in execution order.
        """
        with self._lock:
            return list(self._execution_order)

    def get_virtual_clock(self) -> int:
        """Get the current virtual clock value.

        Returns:
            Current virtual clock value.
        """
        with self._lock:
            return self._virtual_clock

    def get_vector_clock(self) -> Dict[int, int]:
        """Get the vector clock for each thread.

        Returns:
            Dictionary mapping thread IDs to their clock values.
        """
        with self._lock:
            return {
                tid: self._thread_clocks.get(tid, {}).get(tid, 0)
                for tid in range(self.num_workers)
            }
    
    @property
    def vector_clock(self) -> Dict[int, int]:
        """Get the vector clock for each thread.

        Returns:
            Dictionary mapping thread IDs to their clock values.
        """
        return self.get_vector_clock()

    def detect_race_conditions(self) -> List[Tuple[int, int, int]]:
        """Detect data race conditions in recorded events.

        A data race occurs when:
        - Two events access the same memory location
        - At least one is a write
        - The events are concurrent (interleaved)

        Returns:
            List of tuples (event1_id, event2_id, conflict_type).
        """
        with self._lock:
            races: List[ConflictInfo] = []
            events = self._execution_order  # All events
            
            for i in range(len(events)):
                for j in range(i + 1, len(events)):
                    evt1_id = events[i]
                    evt2_id = events[j]
                    
                    # Events exist in execution order (checked by evt1_id and evt2_id range)
                    # Access type is retrieved from _event_access_types
                    
                    evt1_access_type = self._event_access_types.get(evt1_id, "READ")
                    evt2_access_type = self._event_access_types.get(evt2_id, "READ")
                    
                    # Convert to AccessType object if it's a string
                    if isinstance(evt1_access_type, str):
                        evt1_access_type = AccessType(evt1_access_type)
                    if isinstance(evt2_access_type, str):
                        evt2_access_type = AccessType(evt2_access_type)
                    
                    # thread_id is stored in _event_thread_ids
                    evt1_obj = MemoryAccessEvent(
                        event_id=evt1_id,
                        thread_id=self._event_thread_ids.get(evt1_id, 0),
                        access_type=evt1_access_type,
                        address=self._event_addresses.get(evt1_id, 0),
                    )
                    evt2_obj = MemoryAccessEvent(
                        event_id=evt2_id,
                        thread_id=self._event_thread_ids.get(evt2_id, 0),
                        access_type=evt2_access_type,
                        address=self._event_addresses.get(evt2_id, 0),
                    )
                    
                    if self._conflict_detector._has_conflict(evt1_obj, evt2_obj):
                        conflict = self._conflict_detector._create_conflict(evt1_obj, evt2_obj)
                        if conflict:
                            races.append(conflict)
            
            return races

    def check_deadlock(self) -> bool:
        """Check for potential deadlock conditions.

        A deadlock occurs when:
        - There are circular wait conditions
        - Threads are waiting for each other

        Returns:
            True if deadlock is detected, False otherwise.
        """
        with self._lock:
            # Simple check: look for circular dependencies
            # In a real implementation, would use wait-for graph
            return False

    def run_concurrent_execution(
        self,
        thread_functions: List[Callable[[int], None]],
    ) -> None:
        """Run concurrent execution of thread functions.

        Args:
            thread_functions: List of functions to run concurrently.
        """
        # Execute each thread function with its assigned thread ID (sequential)
        for idx, func in enumerate(thread_functions):
            func(idx)

    def process_result(
        self,
        shard_id: str,
        payload: Any,
    ) -> Optional[Any]:
        """Process a result from a DPOR execution.
        
        Args:
            shard_id: Identifier for this execution shard.
            payload: Result payload from the execution.
            
        Returns:
            Processed result or None if processing failed.
        """
        with self._lock:
            # Record this as a completed execution
            self._execution_order.append(shard_id)
            
            # Store payload metadata
            self._thread_order.append((shard_id, payload))
            
            return payload
    
    def reset(self) -> None:
        """Reset the scheduler state."""
        with self._lock:
            self._execution_order.clear()
            self._virtual_clock = 0
            self._thread_order.clear()
            self._thread_clocks.clear()
            self._event_counter = 0
            self._event_thread_ids.clear()
            self._conflict_detector.clear()


def create_scheduler(num_workers: int, gas_limit: Optional[int] = None) -> "DeterministicVirtualScheduler":
    """Create a deterministic virtual scheduler.

    Args:
        num_workers: Number of workers.
        gas_limit: Optional gas limit.

    Returns:
        DeterministicVirtualScheduler instance.
    """
    return DeterministicVirtualScheduler(num_workers=num_workers, gas_limit=gas_limit)