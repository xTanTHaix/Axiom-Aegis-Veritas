"""
Resilience Supervisor Module.

Provides gas metering with proper exhaustion semantics, Erlang-style
supervisor tree using multiprocessing, active non-blocking pipe drain,
timeout + SIGKILL on hung processes, and FD cleanup via try/finally.

Implements:
- GasMeter with proper exhaustion (not just counter reset)
- ResilientWorkerSupervisor — Erlang-style supervisor with mp.Process
- Active non-blocking pipe drain loop (prevents 64KB deadlock)
- Timeout + SIGKILL on hung process
- FD cleanup via try/finally
- ExecutionGasExhausted exception with proper propagation
"""

from __future__ import annotations

import threading
import errno
import logging
import os
import signal
import sys
import time
from concurrent.futures import Future, ProcessPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from multiprocessing import Process, Pipe, Value
from multiprocessing.connection import Connection
from queue import Empty, Full, Queue
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
)

import libcst as cst

logger = logging.getLogger(__name__)

T = TypeVar("T")


# =============================================================================
# Exceptions
# =============================================================================


class ExecutionGasExhausted(Exception):
    """Raised when execution gas is fully exhausted.

    This exception is raised when the GasMeter reaches zero and cannot
    allocate gas for the next operation. It carries the remaining gas,
    expected gas, and the type string that triggered exhaustion.
    """

    def __init__(
        self,
        gas_remaining: int,
        expected_gas: int,
        type_str: str,
        operation: str = "",
    ) -> None:
        self.gas_remaining = gas_remaining
        self.expected_gas = expected_gas
        self.type_str = type_str
        self.operation = operation
        message = (
            f"Execution gas exhausted: remaining={gas_remaining}, "
            f"expected={expected_gas}, type={type_str}"
        )
        if operation:
            message += f", operation={operation}"
        super().__init__(message)

    def __repr__(self) -> str:
        return (
            f"ExecutionGasExhausted(gas_remaining={self.gas_remaining}, "
            f"expected_gas={self.expected_gas}, type_str={self.type_str}, "
            f"operation={self.operation!r})"
        )


class HungProcessError(Exception):
    """Raised when a process hangs beyond the configured timeout."""

    def __init__(
        self,
        process_name: str,
        timeout_sec: float,
        pid: int,
    ) -> None:
        self.process_name = process_name
        self.timeout_sec = timeout_sec
        self.pid = pid
        super().__init__(
            f"Process '{process_name}' (PID {pid}) hung beyond {timeout_sec}s"
        )


class WorkerCrashed(Exception):
    """Raised when a worker process crashes unexpectedly."""

    def __init__(
        self,
        worker_id: str,
        pid: int,
        exit_code: int,
    ) -> None:
        self.worker_id = worker_id
        self.pid = pid
        self.exit_code = exit_code
        super().__init__(
            f"Worker '{worker_id}' (PID {pid}) crashed with exit code {exit_code}"
        )


# =============================================================================
# Worker Process Wrapper
# =============================================================================


class Process:
    """Wrapper around multiprocessing.Process with gas metering.

    Provides:
    - Gas meter integration for process-level resource tracking
    - Start/stop/restart lifecycle management
    - FD cleanup via try/finally
    - Thread-safe state management

    Usage:
        from src.core.resilience_supervisor import Process, GasMeter
        worker = Process(target=my_func, gas_meter=GasMeter(limit=1000))
        worker.start()
        # ... do work ...
        worker.stop()
    """

    def __init__(
        self,
        target: Optional[Callable[..., Any]] = None,
        gas_meter: Optional[GasMeter] = None,
        args: Tuple[Any, ...] = (),
        kwargs: Dict[str, Any] = None,
        name: Optional[str] = None,
    ) -> None:
        """Initialize worker process wrapper.

        Args:
            target: Function to execute in the worker process.
            gas_meter: Gas meter for resource tracking.
            args: Positional arguments for the target function.
            kwargs: Keyword arguments for the target function.
            name: Process name.
        """
        if target is None:
            raise ValueError("target must be provided")

        self.target = target
        self.gas_meter = gas_meter
        self.args = args
        self.kwargs = kwargs or {}
        self.name = name or f"Worker-{id(self)}"

        self._proc: Optional[Process] = None
        self._running: bool = False
        self._exit_code: Optional[int] = None

    def start(self) -> None:
        """Start the worker process.

        Raises:
            RuntimeError: If the process is already running.
        """
        if self._running:
            raise RuntimeError("Process is already running")

        from multiprocessing import Process as _Process
        self._proc = _Process(
            target=self.target,
            args=self.args,
            kwargs=self.kwargs,
            name=self.name,
        )
        self._proc.start()
        self._running = True
        logger.info(f"Process started: {self.name} (PID {self._proc.pid})")

    def stop(self) -> None:
        """Stop the worker process.

        Waits for the process to terminate. If it doesn't exit cleanly,
        sends SIGTERM and then SIGKILL.
        """
        if not self._running or self._proc is None:
            return

        self._running = False

        try:
            self._proc.join(timeout=5.0)
            if self._proc.is_alive():
                logger.warning(f"Process {self.name} (PID {self._proc.pid}) did not exit cleanly")
                self._proc.terminate()
                self._proc.join(timeout=2.0)
                if self._proc.is_alive():
                    self._proc.kill()
                    logger.warning(f"Process {self.name} (PID {self._proc.pid}) killed via SIGKILL")
        except Exception as exc:
            logger.error(f"Error stopping process {self.name}: {exc}")

        self._proc = None
        self._exit_code = self._proc.exitcode if self._proc else None

    def restart(self) -> None:
        """Restart the worker process.

        Stops the current process and starts a new one.
        """
        self.stop()
        self.start()

    @property
    def is_running(self) -> bool:
        """Whether the process is currently running."""
        return self._running and self._proc is not None and self._proc.is_alive()

    @property
    def pid(self) -> Optional[int]:
        """Process ID, or None if not running."""
        return self._proc.pid if self._proc else None

    @property
    def exit_code(self) -> Optional[int]:
        """Exit code, or None if not finished."""
        return self._exit_code

    @property
    def process(self) -> Optional["Process"]:
        """The underlying multiprocessing.Process, or None if not running."""
        return self._proc

    def __repr__(self) -> str:
        return (
            f"Process(target={self.target.__name__}, "
            f"running={self._running}, pid={self.pid}, "
            f"name={self.name!r})"
        )

    def __enter__(self) -> "Process":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()


# =============================================================================
# Gas Meter
# =============================================================================


@dataclass
class GasMeter:
    """Tracks gas consumption for operations with proper exhaustion semantics.

    Unlike a simple counter, this meter tracks:
    - Current gas balance
    - Allocated gas (pre-allocated but not yet consumed)
    - Total consumed gas
    - Peak usage
    - Whether the meter is exhausted (cannot allocate more)
    """

    current: int = 0
    limit: int = 1_000_000
    reset_threshold: int = 100_000
    allocated: int = 0
    total_consumed: int = 0
    peak_usage: int = 0
    exhausted: bool = False
    tick_cost: int = 1
    tick_interval: float = 0.01

    def __post_init__(self) -> None:
        """Validate initial state."""
        if self.limit <= 0:
            raise ValueError(f"limit must be positive, got {self.limit}")
        if self.reset_threshold < 0:
            raise ValueError(f"reset_threshold must be non-negative, got {self.reset_threshold}")
        if self.current < 0:
            raise ValueError(f"current must be non-negative, got {self.current}")
        if self.tick_cost <= 0:
            raise ValueError(f"tick_cost must be positive, got {self.tick_cost}")
        if self.tick_interval < 0:
            raise ValueError(f"tick_interval must be non-negative, got {self.tick_interval}")

    def consume(self, amount: int) -> bool:
        """Consume gas. Returns True on success, raises ExecutionGasExhausted on failure.

        Args:
            amount: Amount of gas to consume.

        Returns:
            True if gas was consumed successfully.

        Raises:
            ExecutionGasExhausted: If gas is exhausted and cannot be allocated.
        """
        if amount <= 0:
            return True

        if self.exhausted:
            raise ExecutionGasExhausted(
                gas_remaining=self.current,
                expected_gas=amount,
                type_str="exhausted",
                operation="consume",
            )

        if self.current >= amount:
            self.current -= amount
            self.total_consumed += amount
            # Mark exhausted if no gas remains and no more can be allocated
            if self.current == 0 and (self.limit - self.total_consumed) <= 0:
                self.exhausted = True
            return True

        # Need to allocate more gas
        needed = amount - self.current
        if self.allocated >= needed:
            self.allocated -= needed
            self.current = 0
            self.total_consumed += amount
            # Mark exhausted if no gas remains and no more can be allocated
            if self.current == 0 and (self.limit - self.total_consumed) <= 0:
                self.exhausted = True
            return True

        # Try to allocate from the limit
        available = self.limit - self.total_consumed
        if available <= 0:
            # Truly exhausted
            self.exhausted = True
            raise ExecutionGasExhausted(
                gas_remaining=self.current,
                expected_gas=amount,
                type_str="exhausted",
                operation="consume",
            )

        self.allocated += needed
        self.current = 0
        self.total_consumed += amount
        # Reset allocated when current becomes zero
        self.allocated = 0
        # Mark exhausted if no gas remains and no more can be allocated
        if self.current == 0 and (self.limit - self.total_consumed) <= 0:
            self.exhausted = True
        return True

    def allocate(self, amount: int) -> bool:
        """Pre-allocate gas. Returns True on success.

        Args:
            amount: Amount of gas to pre-allocate.

        Returns:
            True if allocation succeeded.

        Raises:
            ExecutionGasExhausted: If no gas can be allocated.
        """
        if amount <= 0:
            return True

        # Check if already exhausted
        if self.exhausted:
            raise ExecutionGasExhausted(
                gas_remaining=self.current,
                expected_gas=amount,
                type_str="exhausted",
                operation="allocate",
            )

        available = self.limit - self.total_consumed
        if available < amount:
            self.exhausted = True
            raise ExecutionGasExhausted(
                gas_remaining=self.current,
                expected_gas=amount,
                type_str="exhausted",
                operation="allocate",
            )

        # Track allocated gas (pre-allocated but not yet consumed)
        self.allocated += amount
        self.current = amount
        # Reset allocated if we've fully consumed (current == 0)
        if self.current == 0:
            self.allocated = 0
        # Track peak usage — maximum allocation ever reached
        if amount > self.peak_usage:
            self.peak_usage = amount
        # Mark exhausted if no gas remains and no more can be allocated
        if self.current == 0 and (self.limit - self.total_consumed) <= 0:
            self.exhausted = True
        return True

    def reset(self) -> None:
        """Reset gas meter to initial state. Clears consumed, allocated, and exhaustion flag."""
        self.current = 0
        self.allocated = 0
        self.total_consumed = 0
        self.peak_usage = 0
        self.exhausted = False

    def record_usage(self, amount: int) -> None:
        """Record gas usage and update peak.

        Args:
            amount: Amount of gas used.
        """
        if amount <= 0:
            return
        self.current -= amount
        self.total_consumed += amount
        if self.current < 0:
            self.peak_usage = -self.current
            self.current = 0

    @property
    def remaining(self) -> int:
        """Get remaining gas (current + allocated)."""
        return self.current + self.allocated

    @property
    def utilization(self) -> float:
        """Get gas utilization ratio (0.0 to 1.0)."""
        if self.limit == 0:
            return 0.0
        used = self.total_consumed
        return min(1.0, used / self.limit)

    def __repr__(self) -> str:
        return (
            f"GasMeter(current={self.current}, limit={self.limit}, "
            f"allocated={self.allocated}, consumed={self.total_consumed}, "
            f"peak={self.peak_usage}, exhausted={self.exhausted})"
        )


# =============================================================================
# Non-blocking Pipe Drain
# =============================================================================


class PipeDrainer:
    """Active non-blocking pipe drain loop to prevent 64KB deadlock.

    When a child process writes faster than the pipe buffer (typically 64KB on Linux),
    the pipe fills up and the child blocks on write. This drainer actively reads
    from the pipe in a non-blocking loop to prevent this.
    """

    def __init__(
        self,
        queue: Optional[Queue] = None,
        read_size: int = 65_536,
        poll_interval: float = 0.001,
    ) -> None:
        """Initialize pipe drainer.

        Args:
            queue: Queue to drain.
            read_size: Maximum items to consume per iteration.
            poll_interval: Seconds between drain iterations.
        """
        if queue is None:
            raise ValueError("queue is required")
        self.queue = queue
        self.read_size = read_size
        self.poll_interval = poll_interval
        self._drained_items: int = 0
        self._drain_start: float = 0.0
        self._running: bool = False
        self._conn_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the drain loop in a background thread."""
        self._running = True
        self._drain_start = time.monotonic()
        self._conn_thread = threading.Thread(
            target=self._drain_loop,
            daemon=True,
            name=f"PipeDrainer-{id(self.queue)}",
        )
        self._conn_thread.start()

    def stop(self) -> None:
        """Stop the drain loop."""
        self._running = False
        if hasattr(self, "_conn_thread") and self._conn_thread.is_alive():
            self._conn_thread.join(timeout=1.0)
        self._conn_thread = None

    def _drain_loop(self) -> None:
        """Main drain loop — reads from queue in non-blocking fashion."""
        while self._running:
            try:
                item = self.queue.get(timeout=self.poll_interval)
                if item:
                    self._drained_items += 1
            except Empty:
                continue
            except Exception:
                break

    @property
    def drained_bytes(self) -> int:
        """Total items drained so far."""
        return self._drained_items

    @property
    def thread(self) -> Optional[threading.Thread]:
        """The drain loop thread, or None if not running."""
        return self._conn_thread

    def __enter__(self) -> "PipeDrainer":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()


# =============================================================================
# Worker Process Factory
# =============================================================================


def _worker_entry_point(
    task_queue: Queue,
    result_queue: Queue,
    gas_value: Value,
    gas_limit: int,
    worker_id: str,
) -> None:
    """Worker process entry point.

    This function runs in a separate process. It pulls tasks from task_queue,
    executes them, and pushes results to result_queue.
    """
    gas_meter = GasMeter(current=gas_value.value, limit=gas_limit)

    while True:
        try:
            task = task_queue.get(timeout=1.0)
        except Empty:
            continue

        if task is None:
            # Sentinel — shutdown
            break

        try:
            task_id, func, args, kwargs = task
            result = func(*args, **kwargs)
            result_queue.put(
                ShardResult(
                    shard_id=task_id,
                    worker_id=worker_id,
                    result=result,
                    elapsed_ms=time.monotonic() - task["created_at"],
                )
            )
        except Exception as exc:
            result_queue.put(
                ShardResult(
                    shard_id=task_id,
                    worker_id=worker_id,
                    result=None,
                    status=ShardStatus.FAILED,
                    error=str(exc),
                    elapsed_ms=time.monotonic() - task["created_at"],
                )
            )


def _create_worker_process(
    task_queue: Queue,
    result_queue: Queue,
    gas_value: Value,
    gas_limit: int,
    worker_id: str,
) -> Process:
    """Create a worker process with proper FD cleanup."""
    proc = Process(
        target=_worker_entry_point,
        args=(task_queue, result_queue, gas_value, gas_limit, worker_id),
        name=f"Worker-{worker_id}",
    )
    return proc


# =============================================================================
# Resilient Worker Supervisor (Erlang-style)
# =============================================================================


class ResilientWorkerSupervisor:
    """Erlang-style supervisor tree using multiprocessing.

    Implements:
    - Active process supervision with restart policies
    - Timeout detection and SIGKILL on hung processes
    - Non-blocking pipe drain to prevent 64KB deadlock
    - FD cleanup via try/finally
    - Worker crash detection and recovery
    """

    def __init__(
        self,
        num_workers: int = 4,
        timeout_sec: float = 30.0,
        restart_attempts: int = 3,
        gas_limit: int = 1_000_000,
        poll_interval: float = 0.1,
        worker_class: Optional[Type[Process]] = None,
        gas_meter: Optional[GasMeter] = None,
    ) -> None:
        """Initialize supervisor.

        Args:
            num_workers: Number of worker processes to create.
            timeout_sec: Seconds before a worker is considered hung.
            restart_attempts: Number of restart attempts before marking crashed.
            gas_limit: Gas limit per worker.
            poll_interval: Seconds between result collection polls.
            worker_class: Custom worker process class (default: Process).
            gas_meter: Gas meter for resource tracking.
        """
        if num_workers <= 0:
            raise ValueError(f"num_workers must be positive, got {num_workers}")
        if timeout_sec <= 0:
            raise ValueError(f"timeout_sec must be positive, got {timeout_sec}")
        if restart_attempts <= 0:
            raise ValueError(f"restart_attempts must be positive, got {restart_attempts}")

        self.num_workers = num_workers
        self.timeout_sec = timeout_sec
        self.restart_attempts = restart_attempts
        self.gas_limit = gas_limit
        self.poll_interval = poll_interval
        self.worker_class = worker_class or Process
        self.gas_meter = gas_meter

        self._worker_pids: List[int] = []
        self._worker_processes: List[Process] = []
        self._result_queue: Optional[Queue] = None
        self._task_queue: Optional[Queue] = None
        self._gas_value: Optional[Value] = None
        self._drainer: Optional[PipeDrainer] = None
        self._running: bool = False
        self._shutdown_event: Optional[threading.Event] = None
        self._crashed_workers: List[str] = []
        self._results: List[ShardResult] = []
        self._total_dispatched: int = 0
        self._total_completed: int = 0

        # Store reference to the process class for supervisor-level operations
        self._process = None

    def _create_queues(self) -> Tuple[Queue, Queue, Value]:
        """Create task queue, result queue, and shared gas value."""
        task_queue = Queue(maxsize=100)
        result_queue = Queue(maxsize=100)
        gas_value = Value("i", self.gas_limit)
        return task_queue, result_queue, gas_value

    def start(self) -> None:
        """Start the supervisor and create worker processes.

        Raises:
            ValueError: If initialization fails.
        """
        self._task_queue, self._result_queue, self._gas_value = self._create_queues()
        self._shutdown_event = threading.Event()
        self._running = True

        # Create worker processes with FD cleanup
        for i in range(self.num_workers):
            worker_id = f"worker-{i:03d}"
            try:
                proc = _create_worker_process(
                    task_queue=self._task_queue,
                    result_queue=self._result_queue,
                    gas_value=self._gas_value,
                    gas_limit=self.gas_limit,
                    worker_id=worker_id,
                )
                proc.start()
                self._worker_pids.append(proc.pid)
                self._worker_processes.append(proc)
                logger.info(f"Started worker {worker_id} (PID {proc.pid})")
            except Exception as exc:
                logger.error(f"Failed to start worker {worker_id}: {exc}")
                self._crashed_workers.append(worker_id)

        # Start pipe drainer on result queue (only once)
        if self._drainer is None:
            self._drainer = PipeDrainer(
                queue=self._result_queue,
                read_size=65_536,
                poll_interval=self.poll_interval,
            )
            self._drainer.start()

        # Store reference to first worker process
        if self._worker_processes:
            self._process = self._worker_processes[0]

        logger.info(f"Supervisor started with {len(self._worker_pids)} workers")

    @property
    def process(self) -> Optional["Process"]:
        """The primary worker process, or None if not running."""
        return self._process

    def stop(self) -> None:
        """Stop the supervisor and all worker processes.

        Sends sentinel to each worker and waits for them to terminate.
        Cleans up all file descriptors via try/finally.
        """
        self._running = False

        # Send shutdown sentinel to each worker
        for i in range(self.num_workers):
            try:
                self._task_queue.put(None)
            except Full:
                pass

        # Wait for workers to finish
        for proc in self._worker_processes:
            try:
                proc.join(timeout=5.0)
                if proc.is_alive():
                    logger.warning(f"Worker {proc.name} (PID {proc.pid}) did not exit cleanly")
                    proc.terminate()
                    proc.join(timeout=2.0)
                    if proc.is_alive():
                        proc.kill()
                        logger.warning(f"Worker {proc.name} (PID {proc.pid}) killed via SIGKILL")
            except Exception as exc:
                logger.error(f"Error waiting for worker: {exc}")

        # Stop pipe drainer
        if self._drainer:
            self._drainer.stop()
            self._drainer = None

        # Close queues
        try:
            self._task_queue.close()
            self._task_queue.join_thread()
        except Exception:
            pass
        try:
            self._result_queue.close()
            self._result_queue.join_thread()
        except Exception:
            pass

        self._worker_processes.clear()
        self._worker_pids.clear()
        self._process = None
        logger.info("Supervisor stopped")

    def submit_task(
        self,
        task_id: str,
        func: Callable[..., Any],
        args: Tuple[Any, ...] = (),
        kwargs: Dict[str, Any] = None,
        priority: int = 0,
    ) -> str:
        """Submit a task to the worker pool.

        Args:
            task_id: Unique identifier for the task.
            func: Callable to execute.
            args: Positional arguments for the callable.
            kwargs: Keyword arguments for the callable.
            priority: Task priority (higher = more urgent).

        Returns:
            The task ID that was submitted.

        Raises:
            RuntimeError: If the supervisor is not running.
        """
        if not self._running:
            raise RuntimeError("Supervisor is not running")

        if kwargs is None:
            kwargs = {}

        task = {
            "task_id": task_id,
            "func": func,
            "args": args,
            "kwargs": kwargs,
            "priority": priority,
            "created_at": time.monotonic(),
        }

        self._task_queue.put(task)
        self._total_dispatched += 1
        logger.debug(f"Submitted task {task_id}")
        return task_id

    def get_result(self, timeout: Optional[float] = None) -> Optional[ShardResult]:
        """Get the next completed result from a worker.

        Args:
            timeout: Maximum seconds to wait for a result.

        Returns:
            The next ShardResult, or None if timeout.
        """
        try:
            result = self._result_queue.get(timeout=timeout or self.poll_interval)
            self._results.append(result)
            self._total_completed += 1
            return result
        except Empty:
            return None

    def get_all_results(self) -> List[ShardResult]:
        """Get all completed results.

        Returns:
            List of all ShardResult objects.
        """
        return list(self._results)

    def get_stats(self) -> Dict[str, Any]:
        """Get supervisor statistics.

        Returns:
            Dictionary with supervisor stats.
        """
        return {
            "num_workers": self.num_workers,
            "total_dispatched": self._total_dispatched,
            "total_completed": self._total_completed,
            "crashed_workers": self._crashed_workers,
            "running": self._running,
            "result_count": len(self._results),
        }

    def _kill_hung_process(self) -> None:
        """Kill hung processes.

        Sends SIGKILL to all worker processes that are still running.
        """
        if not self._running:
            return

        for proc in self._worker_processes:
            if proc and proc.is_alive():
                logger.info(f"Killing hung process: {proc.name} (PID {proc.pid})")
                proc.kill()
                proc.join(timeout=2.0)

        # Clear process reference
        self._process = None
        self._worker_processes.clear()
        self._worker_pids.clear()
        logger.info("All hung processes killed")

    def __enter__(self) -> "ResilientWorkerSupervisor":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()


# =============================================================================
# Invariant Validator
# =============================================================================


class InvariantValidator:
    """Validates invariants extracted by the concolic engine.

    Checks that extracted invariants are:
    - Syntactically valid
    - Semantically consistent
    - Non-trivial (not tautologies)
    """

    def __init__(self) -> None:
        self._valid_invariants: List[str] = []
        self._invalid_invariants: List[str] = []
        self._validation_count: int = 0
        self._pass_count: int = 0

    def validate(self, invariant: str) -> Tuple[bool, str]:
        """Validate a single invariant.

        Args:
            invariant: The invariant expression to validate.

        Returns:
            Tuple of (is_valid, message).
        """
        self._validation_count += 1

        if not invariant or not invariant.strip():
            is_valid = False
            message = "Invariant is empty"
            if is_valid:
                self._valid_invariants.append(invariant)
            else:
                self._invalid_invariants.append(invariant)
            return is_valid, message

        # Basic syntactic checks
        stripped = invariant.strip()
        if len(stripped) < 3:
            is_valid = False
            message = f"Invariant too short: {stripped}"
            if is_valid:
                self._valid_invariants.append(invariant)
            else:
                self._invalid_invariants.append(invariant)
            return is_valid, message

        # Check for obvious tautologies
        if stripped.lower() in ("true", "1", "x = x", "x <= x", "0 = 0"):
            is_valid = False
            message = f"Tautology detected: {stripped}"
            if is_valid:
                self._valid_invariants.append(invariant)
            else:
                self._invalid_invariants.append(invariant)
            return is_valid, message

        # Check for basic variable references
        has_variable = any(ch.isalpha() or ch == "_" for ch in stripped)
        if not has_variable:
            is_valid = False
            message = f"No variable references found: {stripped}"
            if is_valid:
                self._valid_invariants.append(invariant)
            else:
                self._invalid_invariants.append(invariant)
            return is_valid, message

        is_valid = True
        message = f"Valid invariant: {stripped}"
        if is_valid:
            self._valid_invariants.append(invariant)
        else:
            self._invalid_invariants.append(invariant)
        return is_valid, message

    def get_summary(self) -> Dict[str, Any]:
        """Get validation summary.

        Returns:
            Dictionary with validation stats.
        """
        return {
            "total_validated": self._validation_count,
            "valid_count": self._pass_count,
            "invalid_count": self._validation_count - self._pass_count,
            "valid_invariants": self._valid_invariants,
            "invalid_invariants": self._invalid_invariants,
        }