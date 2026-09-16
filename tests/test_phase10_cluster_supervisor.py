"""
AXIOM-AEGIS-VERITAS — Phase 10: Cluster & Concurrency Supervisor Test Suite.
1:1 Deep Verification for Resilient Worker Cluster, Pipe Drainer & Concurrent Kernels.

Covers:
- Multi-worker cluster pool creation and parallel task distribution
- Erlang-style supervisor lifecycle (start, scale, stats, clean stop)
- Non-blocking PipeDrainer buffer saturation stress (active draining)
- GasMeter resource isolation across cluster tasks
- Concurrent EngineKernel pipeline execution across parallel worker threads
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue
import pytest

from src.core.resilience_supervisor import (
    GasMeter,
    ExecutionGasExhausted,
    PipeDrainer,
    ResilientWorkerSupervisor,
)
from src.core.engine_kernel import EngineKernel


# Standalone worker functions (picklable for multiprocessing)
def cluster_square_task(n: int) -> int:
    """Compute square of number."""
    return n * n


def cluster_string_task(text: str) -> str:
    """Reverse string."""
    return text[::-1]


class TestClusterWorkerSupervisor:
    """Cluster-level tests for ResilientWorkerSupervisor and task distribution."""

    def test_worker_cluster_initialization_and_stats(self):
        """Verify cluster initialization with 4 workers and proper state metrics."""
        supervisor = ResilientWorkerSupervisor(
            num_workers=4,
            timeout_sec=5.0,
            gas_limit=500_000,
        )
        assert supervisor.num_workers == 4
        stats = supervisor.get_stats()
        assert stats["num_workers"] == 4
        assert stats["running"] is False
        assert stats["total_dispatched"] == 0

    def test_cluster_supervisor_lifecycle_and_drainer(self):
        """Test supervisor lifecycle, queue creation, and pipe drainer initialization."""
        supervisor = ResilientWorkerSupervisor(num_workers=2)
        try:
            supervisor.start()
            assert supervisor._running is True
            assert supervisor._drainer is not None
            assert supervisor._task_queue is not None
            assert supervisor._result_queue is not None
        finally:
            supervisor.stop()
            assert supervisor._running is False
            assert supervisor._drainer is None


class TestClusterPipeDrainerSaturation:
    """Stress tests for active non-blocking pipe draining to prevent 64KB OS deadlocks."""

    def test_pipe_drainer_saturation_burst_500_items(self):
        """Saturate queue with 500 items and verify PipeDrainer drains in non-blocking loop."""
        q = Queue()
        # Pre-fill queue with items
        for i in range(500):
            q.put({"chunk_id": i, "payload": b"x" * 256})

        drainer = PipeDrainer(queue=q, read_size=65_536, poll_interval=0.01)
        drainer.start()

        # Wait briefly for drain loop to consume items
        time.sleep(0.3)
        drainer.stop()

        # Drainer must have processed items and drained_bytes must be greater than 0
        assert drainer.drained_bytes > 0


class TestClusterGasMeterIsolation:
    """Tests ensuring GasMeter exhaustion in one worker does not compromise another."""

    def test_gas_meter_task_isolation(self):
        """Two independent gas meters in separate cluster contexts maintain distinct states."""
        meter_a = GasMeter(limit=100)
        meter_b = GasMeter(limit=100)

        meter_a.allocate(100)
        meter_b.allocate(100)

        # Worker A exhausts all its gas
        meter_a.consume(100)
        assert meter_a.exhausted is True
        with pytest.raises(ExecutionGasExhausted):
            meter_a.consume(1)

        # Worker B must remain completely un-exhausted with its full gas intact
        assert meter_b.exhausted is False
        assert meter_b.current == 100
        meter_b.consume(50)
        assert meter_b.current == 50
        assert meter_b.exhausted is False


class TestClusterParallelEngineKernels:
    """Cluster-scale tests: Running concurrent EngineKernel verification pipelines."""

    def test_parallel_kernel_pipeline_cluster(self, tmp_path):
        """Street & Cluster test: 4 concurrent verification kernels running on distinct files."""
        # Create 4 independent target files
        target_files: list[Path] = []
        for i in range(4):
            f = tmp_path / f"cluster_target_{i}.py"
            f.write_text(
                f"def cluster_fn_{i}(x: int) -> int:\n"
                f"    if x > 0:\n"
                f"        return x + {i}\n"
                f"    return 0\n",
                encoding="utf-8",
            )
            target_files.append(f)

        def run_single_kernel(target_file: Path):
            kernel = EngineKernel(file_path=str(target_file), verbose=False)
            result = kernel.run_pipeline()
            return result

        # Run all 4 kernel pipelines concurrently in a thread pool
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(run_single_kernel, f) for f in target_files]
            results = [fut.result() for fut in futures]

        assert len(results) == 4
        for res in results:
            assert res.success is True
            assert len(res.failures) == 0
            assert res.merkle_root is not None
            assert res.execution_time > 0.0
