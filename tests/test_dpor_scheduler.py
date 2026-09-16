"""
Comprehensive test suite for DPOR Scheduler with Vector Clocks.

This test suite validates:
- VectorClock implementation (happens-before tracking)
- MemoryAccessEvent recording
- ConflictDetector (Write-Write, Read-Write)
- PermissiveMockProxy async protocols
- DeterministicVirtualScheduler orchestration
- Integration with other layers

Test Strategy:
- Unit tests: 1:1 per module function
- Integration tests: Layer interaction
- Defect hunting: Edge cases designed to break implementation
- Regression tests: Post-refactor validation

Target: 35/35 tests passing, Coverage ≥ 90%
"""

from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional
from unittest.mock import MagicMock

import pytest

from src.core.dpor_scheduler import (
    ConflictDetector,
    ConflictInfo,
    DeterministicVirtualScheduler,
    EventId,
    EventState,
    MemoryAccessEvent,
    PermissiveMockProxy,
    VectorClock,
    create_scheduler,
)
from src.core.types import AccessType as AccessTypeType
from src.core.types import ConflictType as ConflictTypeType


# ============================================================================
# VECTOR CLOCK TESTS (8 tests)
# ============================================================================

class TestVectorClock:
    """Test suite for VectorClock implementation."""

    def test_vector_clock_initialization(self) -> None:
        """Test vector clock initialization with default parameters."""
        clock = VectorClock(num_threads=3)
        assert clock.clock == {0: 0, 1: 0, 2: 0}
        assert clock._num_threads == 3

    def test_vector_clock_initialization_single_thread(self) -> None:
        """Test vector clock initialization with single thread."""
        clock = VectorClock(num_threads=1)
        assert clock.clock == {0: 0}

    def test_vector_clock_initialization_zero_fails(self) -> None:
        """Test that zero threads raises ValueError."""
        with pytest.raises(ValueError, match="num_threads must be positive"):
            VectorClock(num_threads=0)

    def test_vector_clock_initialization_negative_fails(self) -> None:
        """Test that negative threads raises ValueError."""
        with pytest.raises(ValueError, match="num_threads must be positive"):
            VectorClock(num_threads=-1)

    def test_vector_clock_increment(self) -> None:
        """Test vector clock increment operation."""
        clock = VectorClock(num_threads=3)
        assert clock.get(0) == 0
        clock.increment(0)
        assert clock.get(0) == 1
        clock.increment(0)
        assert clock.get(0) == 2

    def test_vector_clock_increment_multiple_threads(self) -> None:
        """Test vector clock increment across multiple threads."""
        clock = VectorClock(num_threads=3)
        clock.increment(0)
        clock.increment(1)
        clock.increment(2)
        assert clock.clock == {0: 1, 1: 1, 2: 1}

    def test_vector_clock_merge(self) -> None:
        """Test vector clock merge operation."""
        clock1 = VectorClock(num_threads=3)
        clock2 = VectorClock(num_threads=3)

        clock1.increment(0)
        clock1.increment(1)
        clock2.increment(1)
        clock2.increment(2)

        merged = clock1.merge(clock2.clock)
        assert merged == {0: 1, 1: 1, 2: 1}

    def test_vector_clock_merge_dimension_mismatch(self) -> None:
        """Test that merging clocks with different dimensions raises ValueError."""
        clock1 = VectorClock(num_threads=3)
        clock2 = VectorClock(num_threads=2)

        with pytest.raises(ValueError, match="Clocks have different dimensions"):
            clock1.merge(clock2.clock)

    def test_vector_clock_happens_before(self) -> None:
        """Test happens-before relationship detection."""
        clock1 = VectorClock(num_threads=3)
        clock2 = VectorClock(num_threads=3)

        # clock1 happens before clock2
        clock1.increment(0)
        clock2.increment(0)
        clock2.increment(1)

        assert clock1.happens_before(clock2.clock)
        assert not clock2.happens_before(clock1.clock)

    def test_vector_clock_concurrent(self) -> None:
        """Test concurrent relationship detection."""
        clock1 = VectorClock(num_threads=3)
        clock2 = VectorClock(num_threads=3)

        # clock1 and clock2 are concurrent
        clock1.increment(0)
        clock2.increment(1)

        assert clock1.concurrent_with(clock2.clock)
        assert clock2.concurrent_with(clock1.clock)

    def test_vector_clock_consistency(self) -> None:
        """Test vector clock consistency across operations."""
        clock = VectorClock(num_threads=3)
        original = clock.clock.copy()

        clock.increment(0)
        clock.increment(1)

        assert clock.get(0) > original[0]
        assert clock.get(1) > original[1]
        assert clock.get(2) == original[2]

    def test_vector_clock_thread_safety(self) -> None:
        """Test vector clock thread safety with concurrent increments."""
        clock = VectorClock(num_threads=10)
        num_threads = 10
        increments_per_thread = 100

        def increment_thread(tid: int) -> None:
            for _ in range(increments_per_thread):
                clock.increment(tid)

        threads = [
            threading.Thread(target=increment_thread, args=(i,))
            for i in range(num_threads)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Each thread should have incremented exactly once
        for i in range(num_threads):
            assert clock.get(i) == increments_per_thread

    def test_vector_clock_edge_cases(self) -> None:
        """Test vector clock edge cases."""
        clock = VectorClock(num_threads=1)

        # Increment with invalid thread_id
        with pytest.raises(RuntimeError, match="thread_id.*is out of range"):
            clock.increment(1)

        # Get with invalid thread_id
        with pytest.raises(RuntimeError, match="thread_id.*is out of range"):
            clock.get(1)

    def test_vector_clock_memory_leak(self) -> None:
        """Test that vector clock doesn't leak memory."""
        import gc

        clock = VectorClock(num_threads=3)
        original_count = sum(gc.get_count())

        # Perform many operations
        for _ in range(1000):
            clock.increment(0)
            clock.increment(1)
            clock.increment(2)

        # Force garbage collection
        gc.collect()

        # Should not leak significantly
        new_count = sum(gc.get_count())
        assert new_count <= original_count + 1000  # Allow some overhead


# ============================================================================
# MEMORY ACCESS EVENT TESTS (6 tests)
# ============================================================================

class TestMemoryAccessEvent:
    """Test suite for MemoryAccessEvent."""

    def test_memory_access_event_creation(self) -> None:
        """Test basic memory access event creation."""
        event = MemoryAccessEvent(
            thread_id=0,
            address=0x1000,
            access_type="READ",
            timestamp=1.0,
            event_id=1,
        )
        assert event.thread_id == 0
        assert event.address == 0x1000
        assert event.access_type_str == "READ"
        assert event.access_type_class_attr == "READ"
        assert event.timestamp == 1.0
        assert event.event_id == 1

    def test_memory_access_event_thread_id(self) -> None:
        """Test memory access event thread ID validation."""
        event = MemoryAccessEvent(
            thread_id=5,
            address=0x2000,
            access_type="WRITE",
            timestamp=2.0,
            event_id=2,
        )
        assert event.thread_id == 5

    def test_memory_access_event_address(self) -> None:
        """Test memory access event address validation."""
        event = MemoryAccessEvent(
            thread_id=0,
            address=0x4000,
            access_type="READ",
            timestamp=3.0,
            event_id=3,
        )
        assert event.address == 0x4000

    def test_memory_access_event_access_type(self) -> None:
        """Test memory access event access type validation."""
        for access_type_str in ['WRITE', 'READ', 'SHARED']:
            event = MemoryAccessEvent(
                thread_id=0,
                address=0x5000,
                access_type=AccessTypeType.from_string(access_type_str),
                timestamp=4.0,
                event_id=4,
            )
            assert event.access_type_str == access_type_str
            assert event.access_type_class_attr is not None

    def test_memory_access_event_ordering(self) -> None:
        """Test memory access event ordering."""
        events = []
        for i in range(5):
            event = MemoryAccessEvent(
                thread_id=i,
                address=0x6000,
                access_type="READ",
                timestamp=float(i),
                event_id=i,
            )
            events.append(event)

        assert events[0].event_id == 0
        assert events[1].event_id == 1
        assert events[4].event_id == 4

    def test_memory_access_event_cleanup(self) -> None:
        """Test memory access event cleanup."""
        event = MemoryAccessEvent(
            thread_id=0,
            address=0x7000,
            access_type="WRITE",
            timestamp=5.0,
            event_id=5,
        )
        assert event.state == EventState.PENDING
        assert event.access_type_str == "WRITE"


# ============================================================================
# CONFLICT DETECTOR TESTS (7 tests)
# ============================================================================

class TestConflictDetector:
    """Test suite for ConflictDetector."""

    def test_conflict_detection_write_write(self) -> None:
        """Test Write-Write conflict detection."""
        detector = ConflictDetector()

        event1 = MemoryAccessEvent(
            thread_id=0,
            address=0x1000,
            access_type="WRITE",
            timestamp=1.0,
            event_id=1,
        )
        event2 = MemoryAccessEvent(
            thread_id=1,
            address=0x1000,
            access_type="WRITE",
            timestamp=2.0,
            event_id=2,
        )

        conflict = detector.detect_conflict(event1, event2)
        assert conflict is not None
        assert conflict.conflict_type == ConflictTypeType.WRITE_WRITE

    def test_conflict_detection_read_write(self) -> None:
        """Test Read-Write conflict detection."""
        detector = ConflictDetector()

        event1 = MemoryAccessEvent(
            thread_id=0,
            address=0x2000,
            access_type="READ",
            timestamp=1.0,
            event_id=1,
        )
        event2 = MemoryAccessEvent(
            thread_id=1,
            address=0x2000,
            access_type="WRITE",
            timestamp=2.0,
            event_id=2,
        )

        conflict = detector.detect_conflict(event1, event2)
        assert conflict is not None
        assert conflict.conflict_type == ConflictTypeType.READ_WRITE

    def test_conflict_detection_read_read(self) -> None:
        """Test Read-Read (should NOT be a conflict - no write involved)."""
        detector = ConflictDetector()

        event1 = MemoryAccessEvent(
            thread_id=0,
            address=0x3000,
            access_type="READ",
            timestamp=1.0,
            event_id=1,
        )
        event2 = MemoryAccessEvent(
            thread_id=1,
            address=0x3000,
            access_type="READ",
            timestamp=2.0,
            event_id=2,
        )

        conflict = detector.detect_conflict(event1, event2)
        # Read-Read is NOT a data race (no write conflict)
        assert conflict is None

    def test_conflict_detection_no_conflict(self) -> None:
        """Test no conflict when addresses differ."""
        detector = ConflictDetector()

        event1 = MemoryAccessEvent(
            thread_id=0,
            address=0x4000,
            access_type="WRITE",
            timestamp=1.0,
            event_id=1,
        )
        event2 = MemoryAccessEvent(
            thread_id=1,
            address=0x5000,
            access_type="WRITE",
            timestamp=2.0,
            event_id=2,
        )

        conflict = detector.detect_conflict(event1, event2)
        assert conflict is None  # Different addresses, no conflict

    def test_conflict_detection_concurrent(self) -> None:
        """Test concurrent event detection."""
        detector = ConflictDetector()

        # Create proper VectorClock instances
        vc1 = VectorClock(num_threads=2)
        vc1.increment(0)
        vc1_clock = vc1.clock.copy()

        vc2 = VectorClock(num_threads=2)
        vc2.increment(1)
        vc2_clock = vc2.clock.copy()

        event1 = MemoryAccessEvent(
            thread_id=0,
            address=0x6000,
            access_type="WRITE",
            timestamp=1.0,
            event_id=1,
            vector_clock=vc1_clock,
        )
        event2 = MemoryAccessEvent(
            thread_id=1,
            address=0x6000,
            access_type="WRITE",
            timestamp=2.0,
            event_id=2,
            vector_clock=vc2_clock,
        )

        conflict = detector.detect_conflict(event1, event2)
        assert conflict is not None
        
        # Check concurrent using detector.is_concurrent which handles dict
        assert detector.is_concurrent(event1, event2)

    def test_conflict_detection_false_positive(self) -> None:
        """Test false positive detection (same thread)."""
        from src.core.dpor_scheduler import DeterministicVirtualScheduler
        
        # Use DeterministicVirtualScheduler which properly manages vector clocks
        scheduler = DeterministicVirtualScheduler(num_workers=2)
        
        # Record events using scheduler (which sets up proper vector clocks)
        scheduler.record_event(0, 0x7000, "WRITE")
        scheduler.record_event(0, 0x7000, "WRITE")
        
        races = scheduler.detect_race_conditions()
        assert len(races) == 0  # Same thread, same address, no race

    def test_conflict_detection_false_negative(self) -> None:
        """Test false negative detection (different addresses)."""
        from src.core.dpor_scheduler import DeterministicVirtualScheduler
        
        # Use DeterministicVirtualScheduler which properly manages vector clocks
        scheduler = DeterministicVirtualScheduler(num_workers=2)
        
        # Record events using scheduler (which sets up proper vector clocks)
        scheduler.record_event(0, 0x8000, "WRITE")
        scheduler.record_event(1, 0x9000, "WRITE")
        
        races = scheduler.detect_race_conditions()
        assert len(races) == 0  # Different addresses, no race


# ============================================================================
# DPOR INTERLEAVING TESTS (5 tests)
# ============================================================================

class TestDPORInterleaving:
    """Test suite for DPOR interleaving reduction."""

    def test_dpOR_interleaving_reduction(self) -> None:
        """Test DPOR interleaving reduction from O(n!) to data-race bound."""
        scheduler = DeterministicVirtualScheduler(num_workers=3)

        # Record events
        scheduler.record_event(0, 0x1000, "WRITE")
        scheduler.record_event(1, 0x1000, "READ")
        scheduler.record_event(2, 0x2000, "WRITE")

        # Detect race conditions
        races = scheduler.detect_race_conditions()

        # Should detect at least one race condition
        assert len(races) >= 1

    def test_data_race_detection(self) -> None:
        """Test data race detection across multiple addresses."""
        scheduler = DeterministicVirtualScheduler(num_workers=2)

        # Multiple addresses with races
        scheduler.record_event(0, 0x1000, "WRITE")
        scheduler.record_event(1, 0x1000, "READ")

        scheduler.record_event(0, 0x2000, "WRITE")
        scheduler.record_event(1, 0x2000, "READ")

        races = scheduler.detect_race_conditions()

        # Should detect races at both addresses
        assert len(races) >= 2

    def test_event_ordering(self) -> None:
        """Test event ordering preservation."""
        scheduler = DeterministicVirtualScheduler(num_workers=2)

        events = []
        for i in range(5):
            event = scheduler.record_event(i % 2, 0x3000, "READ")
            events.append(event)

        # Events should be ordered by event_id
        for i in range(len(events) - 1):
            assert events[i].event_id < events[i + 1].event_id

    def test_clock_consistency(self) -> None:
        """Test vector clock consistency during event recording."""
        scheduler = DeterministicVirtualScheduler(num_workers=2)

        # Record events and check clock consistency
        for i in range(10):
            scheduler.record_event(i % 2, 0x4000, "READ")

        # Each thread's clock should be monotonically increasing
        clock = scheduler.vector_clock
        assert clock[0] == 5
        assert clock[1] == 5

    def test_deadlock_detection(self) -> None:
        """Test deadlock detection."""
        scheduler = DeterministicVirtualScheduler(num_workers=2)

        # Simulate a potential deadlock scenario
        scheduler.record_event(0, 0x5000, "WRITE")
        scheduler.record_event(1, 0x5000, "WRITE")

        has_deadlock = scheduler.check_deadlock()
        # Simple implementation may not detect this, but should not crash
        assert isinstance(has_deadlock, bool)


# ============================================================================
# PERMISSIVE MOCK PROXY TESTS (4 tests)
# ============================================================================

class TestPermissiveMockProxy:
    """Test suite for PermissiveMockProxy."""

    @pytest.mark.asyncio
    async def test_permissive_mock_proxy(self) -> None:
        """Test basic permissive mock proxy functionality."""
        proxy = PermissiveMockProxy()

        async def mock_func(x: int) -> int:
            return x * 2

        result = await proxy.call_async(mock_func, 5)
        assert result == 10

    def test_async_protocol_support(self) -> None:
        """Test async protocol support."""
        proxy = PermissiveMockProxy()

        async def async_func() -> str:
            return "async result"

        result = asyncio.run(proxy.call_async(async_func))
        assert result == "async result"

    @pytest.mark.asyncio
    async def test_async_context_manager(self) -> None:
        """Test async context manager support."""
        proxy = PermissiveMockProxy()

        async with proxy:
            async def inner_func() -> int:
                return 42

            result = await proxy.call_async(inner_func)
            assert result == 42

    def test_async_timeout(self) -> None:
        """Test async timeout handling."""
        proxy = PermissiveMockProxy()
        proxy.set_timeout(0.1)  # 100ms timeout

        async def slow_func() -> int:
            await asyncio.sleep(0.5)
            return 42

        with pytest.raises(TimeoutError, match="timed out"):
            asyncio.run(proxy.call_async(slow_func))


# ============================================================================
# INTEGRATION TESTS (5 tests)
# ============================================================================

class TestIntegration:
    """Integration tests for DPOR Scheduler with other layers."""

    def test_full_pipeline_execution(self) -> None:
        """Test full pipeline execution with DPOR."""
        scheduler = DeterministicVirtualScheduler(num_workers=2)

        def thread_func_0(tid: int) -> None:
            scheduler.record_event(tid, 0x1000, "WRITE")
            scheduler.record_event(tid, 0x2000, "READ")

        def thread_func_1(tid: int) -> None:
            scheduler.record_event(tid, 0x1000, "READ")
            scheduler.record_event(tid, 0x2000, "WRITE")

        scheduler.run_concurrent_execution([thread_func_0, thread_func_1])

        # Should detect races at both addresses
        races = scheduler.detect_race_conditions()
        assert len(races) >= 2

    def test_integration_with_concolic(self) -> None:
        """Test integration with concolic engine (simulated)."""
        scheduler = DeterministicVirtualScheduler(num_workers=2)

        # Simulate concolic execution
        scheduler.record_event(0, 0x3000, "WRITE")
        scheduler.record_event(1, 0x3000, "READ")

        races = scheduler.detect_race_conditions()
        assert len(races) >= 1

    def test_integration_with_dual_solver(self) -> None:
        """Test integration with dual solver consensus (simulated)."""
        scheduler = DeterministicVirtualScheduler(num_workers=2)

        # Simulate dual solver input
        scheduler.record_event(0, 0x4000, "WRITE")
        scheduler.record_event(1, 0x4000, "WRITE")

        races = scheduler.detect_race_conditions()
        assert len(races) >= 1

    def test_integration_with_octagon(self) -> None:
        """Test integration with octagon domain (simulated)."""
        scheduler = DeterministicVirtualScheduler(num_workers=2)

        # Simulate octagon domain constraints
        scheduler.record_event(0, 0x5000, "READ")
        scheduler.record_event(1, 0x5000, "WRITE")

        races = scheduler.detect_race_conditions()
        assert len(races) >= 1

    def test_integration_with_dominator(self) -> None:
        """Test integration with dominator tree (simulated)."""
        scheduler = DeterministicVirtualScheduler(num_workers=2)

        # Simulate dominator tree analysis
        scheduler.record_event(0, 0x6000, "WRITE")
        scheduler.record_event(1, 0x6000, "READ")

        races = scheduler.detect_race_conditions()
        assert len(races) >= 1

    def test_regression_test_1(self) -> None:
        """Regression test 1: Basic race detection."""
        scheduler = DeterministicVirtualScheduler(num_workers=2)

        scheduler.record_event(0, 0x7000, "WRITE")
        scheduler.record_event(1, 0x7000, "READ")

        races = scheduler.detect_race_conditions()
        assert len(races) == 1
        assert races[0].conflict_type == ConflictTypeType.READ_WRITE

    def test_regression_test_2(self) -> None:
        """Regression test 2: Gas limit enforcement."""
        scheduler = DeterministicVirtualScheduler(num_workers=2, gas_limit=5)

        try:
            scheduler.record_event(0, 0x8000, "WRITE")
            scheduler.record_event(1, 0x8000, "READ")
            scheduler.record_event(0, 0x9000, "WRITE")
            scheduler.record_event(1, 0x9000, "READ")
            scheduler.record_event(0, 0xA000, "WRITE")
            # This should raise RuntimeError
            scheduler.record_event(1, 0xA000, "READ")
            assert False, "Should have raised RuntimeError"
        except RuntimeError as e:
            assert "Gas limit exceeded" in str(e)


# ============================================================================
# THREAD SAFETY TESTS (2 tests)
# ============================================================================

class TestThreadSafety:
    """Thread safety tests for DPOR Scheduler."""

    def test_thread_safety_vector_clock(self) -> None:
        """Test vector clock thread safety."""
        clock = VectorClock(num_threads=10)
        num_threads = 10
        increments_per_thread = 100

        def increment_thread(tid: int) -> None:
            for _ in range(increments_per_thread):
                clock.increment(tid)

        threads = [
            threading.Thread(target=increment_thread, args=(i,))
            for i in range(num_threads)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Each thread should have incremented exactly once
        for i in range(num_threads):
            assert clock.get(i) == increments_per_thread

    def test_thread_safety_conflict_detector(self) -> None:
        """Test conflict detector thread safety."""
        detector = ConflictDetector()
        num_threads = 5
        events_per_thread = 100

        def add_events(thread_id: int) -> None:
            for i in range(events_per_thread):
                event = MemoryAccessEvent(
                    thread_id=thread_id,
                    address=0x1000 + i * 1000,  # Unique address per event to avoid conflicts
                    access_type="READ" if i % 2 == 0 else "WRITE",
                    timestamp=float(i),
                    event_id=i + thread_id * events_per_thread,  # Unique event_id
                )
                detector.add_event(event)

        threads = [
            threading.Thread(target=add_events, args=(i,))
            for i in range(num_threads)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should not crash and should have recorded events
        stats = detector.get_stats()
        assert stats["total_events"] == num_threads * events_per_thread


# ============================================================================
# ERROR HANDLING TESTS (2 tests)
# ============================================================================

class TestErrorHandling:
    """Error handling tests for DPOR Scheduler."""

    def test_error_handling_invalid_thread_id(self) -> None:
        """Test error handling for invalid thread ID."""
        scheduler = DeterministicVirtualScheduler(num_workers=2)

        with pytest.raises(RuntimeError, match="thread_id.*is out of range"):
            scheduler.record_event(5, 0x1000, "READ")

    def test_error_handling_invalid_address(self) -> None:
        """Test error handling for invalid address."""
        scheduler = DeterministicVirtualScheduler(num_workers=2)

        with pytest.raises(ValueError, match="address must be non-negative"):
            scheduler.record_event(0, -1, "READ")


# ============================================================================
# RECOVERY AFTER FAILURE TESTS (1 test)
# ============================================================================

class TestRecovery:
    """Recovery tests after failure."""

    def test_recovery_after_failure(self) -> None:
        """Test recovery after scheduler failure."""
        scheduler = DeterministicVirtualScheduler(num_workers=2, gas_limit=10)

        # Cause gas limit error
        try:
            for i in range(20):
                scheduler.record_event(i % 2, 0x1000, "READ")
            assert False, "Should have raised RuntimeError"
        except RuntimeError:
            pass

        # Reset and continue
        scheduler.reset()
        scheduler.record_event(0, 0x2000, "READ")
        scheduler.record_event(1, 0x2000, "WRITE")

        races = scheduler.detect_race_conditions()
        assert len(races) >= 1


# ============================================================================
# FULL PIPELINE EXECUTION TEST (1 test)
# ============================================================================

class TestFullPipeline:
    """Full pipeline execution test."""

    def test_full_pipeline_execution(self) -> None:
        """Test full pipeline execution from L1 to L7."""
        scheduler = DeterministicVirtualScheduler(num_workers=2)

        # Simulate full pipeline
        def thread_func_0(tid: int) -> None:
            # L1: CST Merkle
            scheduler.record_event(tid, 0x1000, "WRITE")
            # L2: Octagon Domain
            scheduler.record_event(tid, 0x2000, "READ")
            # L3: Dual SMT
            scheduler.record_event(tid, 0x3000, "WRITE")
            # L4: DPOR (this test)
            scheduler.record_event(tid, 0x4000, "READ")
            # L5: Invariant Harvester
            scheduler.record_event(tid, 0x5000, "WRITE")
            # L6: Provenance Semiring
            scheduler.record_event(tid, 0x6000, "READ")
            # L7: Empirical Witness
            scheduler.record_event(tid, 0x7000, "WRITE")

        def thread_func_1(tid: int) -> None:
            # L1: CST Merkle
            scheduler.record_event(tid, 0x1000, "READ")
            # L2: Octagon Domain
            scheduler.record_event(tid, 0x2000, "WRITE")
            # L3: Dual SMT
            scheduler.record_event(tid, 0x3000, "READ")
            # L4: DPOR (this test)
            scheduler.record_event(tid, 0x4000, "WRITE")
            # L5: Invariant Harvester
            scheduler.record_event(tid, 0x5000, "READ")
            # L6: Provenance Semiring
            scheduler.record_event(tid, 0x6000, "WRITE")
            # L7: Empirical Witness
            scheduler.record_event(tid, 0x7000, "READ")

        scheduler.run_concurrent_execution([thread_func_0, thread_func_1])

        # Should detect races at multiple addresses
        races = scheduler.detect_race_conditions()
        assert len(races) >= 6  # At least one race per address pair


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--cov=src/core/dpor_scheduler", "--cov-report=xml"])
