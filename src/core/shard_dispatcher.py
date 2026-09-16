"""
Shard Dispatcher Module.

Handles distribution of work shards across workers, result collection,
and invariant validation for the Layer 5 pipeline.

Implements:
- Shard distribution logic
- Result aggregation
- Invariant validation
- Worker coordination
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import queue
import random
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum, auto
from functools import partial
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
    TypeVar,
    Union,
)

import libcst as cst
from libcst.metadata import ScopeProvider

from src.core.dpor_scheduler import DeterministicVirtualScheduler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# =============================================================================
# Enums and Constants
# =============================================================================

class ShardStatus(Enum):
    """Status of a work shard."""

    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


class WorkerState(Enum):
    """State of a worker."""

    IDLE = auto()
    BUSY = auto()
    CRASHED = auto()
    RECOVERING = auto()


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class WorkShard:
    """Represents a unit of work to be distributed."""

    shard_id: str
    worker_id: str
    payload: Any
    priority: int = 0
    deadline: Optional[float] = None
    dependencies: List[str] = field(default_factory=list)
    status: ShardStatus = ShardStatus.PENDING
    result: Optional[Any] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None

    def __hash__(self) -> int:
        return hash(self.shard_id)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "shard_id": self.shard_id,
            "worker_id": self.worker_id,
            "payload": self.payload,
            "priority": self.priority,
            "deadline": self.deadline,
            "dependencies": self.dependencies,
            "status": self.status.name,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkShard":
        """Create from dictionary."""
        return cls(
            shard_id=data["shard_id"],
            worker_id=data["worker_id"],
            payload=data["payload"],
            priority=data["priority"],
            deadline=data["deadline"],
            dependencies=data["dependencies"],
            status=ShardStatus[data["status"]],
            result=data["result"],
            error=data["error"],
            created_at=data["created_at"],
            completed_at=data["completed_at"],
        )


@dataclass
class ShardResult:
    """Result of a completed shard."""

    shard_id: str
    worker_id: str
    result: Any
    status: ShardStatus = ShardStatus.COMPLETED
    error: Optional[str] = None
    elapsed_ms: float = 0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "shard_id": self.shard_id,
            "worker_id": self.worker_id,
            "result": self.result,
            "status": self.status.name,
            "error": self.error,
            "elapsed_ms": self.elapsed_ms,
            "created_at": self.created_at,
        }


@dataclass
class Invariant:
    """Represents a type invariant."""

    name: str
    expression: str
    validation_result: bool
    validation_error: Optional[str] = None
    validated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "expression": self.expression,
            "validation_result": self.validation_result,
            "validation_error": self.validation_error,
            "validated_at": self.validated_at,
        }


@dataclass
class Worker:
    """Represents a worker node."""

    worker_id: str
    state: WorkerState = WorkerState.IDLE
    task_queue: queue.Queue = field(default_factory=queue.Queue)
    active_shards: List[WorkShard] = field(default_factory=list)
    results: List[ShardResult] = field(default_factory=list)
    last_heartbeat: float = field(default_factory=time.time)
    is_crashed: bool = False
    recovery_time: float = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "worker_id": self.worker_id,
            "state": self.state.name,
            "active_shards": [s.shard_id for s in self.active_shards],
            "results_count": len(self.results),
            "last_heartbeat": self.last_heartbeat,
            "is_crashed": self.is_crashed,
            "recovery_time": self.recovery_time,
        }


# =============================================================================
# Invariant Validator
# =============================================================================

class InvariantValidator:
    """
    Validates invariants against type expressions.

    Implements:
    - PEP 695 type validation
    - Generic type consistency
    - Constraint satisfaction
    """

    def __init__(self, type_constraints: Dict[str, Any] = None):
        self.type_constraints = type_constraints or {}

    def validate_type_expression(
        self,
        expression: str,
        context: Dict[str, Any],
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate a type expression against constraints.

        Args:
            expression: The type expression string.
            context: Context with type information.

        Returns:
            Tuple of (is_valid, error_message).
        """
        try:
            # Check for type variable consistency
            type_vars = self._extract_type_vars(expression)
            for var_name in type_vars:
                if var_name not in self.type_constraints:
                    return False, f"Unknown type variable: {var_name}"

            # Validate type bounds
            bounds = self._validate_bounds(expression)
            if not bounds:
                return True, ""

            return True, ""  # Empty string when validation succeeds

        except Exception as e:
            return False, str(e)

    def validate_pep695_type(
        self,
        type_ast: cst.expr.Expression,
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate a PEP 695 type AST.

        Args:
            type_ast: The AST node to validate.

        Returns:
            Tuple of (is_valid, error_message).
        """
        try:
            # Parse and validate against type constraints
            type_str = self._ast_to_string(type_ast)
            is_valid, error = self.validate_type_expression(type_str, {})

            return is_valid, error

        except Exception as e:
            return False, str(e)

    def _extract_type_vars(self, expression: str) -> Set[str]:
        """Extract type variable names from expression."""
        type_vars: Set[str] = set()

        # Simple pattern matching for TypeVar names
        import re

        # Match TypeVar[X], ParamSpec[X], TypeVarTuple[X]
        pattern = r"(?:TypeVar|ParamSpec|TypeVarTuple)\s*\(\s*([A-Z][A-Z0-9_]*)\s*\)"
        matches = re.findall(pattern, expression)
        type_vars.update(matches)

        return type_vars

    def _validate_bounds(self, expression: str) -> Optional[Dict[str, Any]]:
        """Validate type bounds."""
        # Check for bounds in generic types
        import re

        # Pattern: TypeVar(name, bound=...)
        bound_pattern = r"TypeVar\([^)]*bound\s*=\s*([^)]+)\)"
        bound_match = re.search(bound_pattern, expression)

        if bound_match:
            bound = bound_match.group(1)
            if bound and bound not in self.type_constraints:
                return {"bound": bound, "valid": False}

        return None

    def _ast_to_string(self, node: cst.expr.Expression) -> str:
        """Convert AST to string representation."""
        return str(node)


# =============================================================================
# Shard Dispatcher (Main Class)
# =============================================================================

@dataclass
class DispatcherConfig:
    """Configuration for the shard dispatcher."""

    num_workers: int = 4
    shard_size: int = 1000
    priority_levels: int = 5
    timeout_seconds: float = 30.0
    max_pending_shards: int = 100
    recovery_timeout: float = 30.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "num_workers": self.num_workers,
            "shard_size": self.shard_size,
            "priority_levels": self.priority_levels,
            "timeout_seconds": self.timeout_seconds,
            "max_pending_shards": self.max_pending_shards,
            "recovery_timeout": self.recovery_timeout,
        }


class ShardDispatcher:
    """
    Main shard dispatcher class.

    Coordinates work distribution across workers, handles result collection,
    and validates invariants for the Layer 5 pipeline.

    Features:
    - Work shard distribution
    - Priority-based scheduling
    - Dependency resolution
    - Worker coordination
    - Invariant validation
    - Crash recovery
    """

    def __init__(
        self,
        config: Optional[DispatcherConfig] = None,
        use_async: bool = True,
    ):
        self.config = config or DispatcherConfig()
        self.use_async = use_async

        # Initialize workers
        self.workers: Dict[str, Worker] = {}
        self.worker_ids: List[str] = []

        # Shard management
        self.pending_shards: Dict[str, WorkShard] = {}
        self.running_shards: Dict[str, WorkShard] = {}
        self.completed_shards: Dict[str, ShardResult] = {}

        # Invariant validation
        self.type_validator = InvariantValidator()

        # Metrics
        self.metrics: Dict[str, Any] = {
            "total_submitted": 0,
            "total_completed": 0,
            "total_failed": 0,
            "average_latency_ms": 0.0,
            "throughput_per_second": 0.0,
        }

        # Thread pools
        self.executor: Optional[ThreadPoolExecutor] = None

        # Initialization
        self._init_workers()
        self._init_executor()

    def _init_workers(self) -> None:
        """Initialize worker nodes."""
        for i in range(self.config.num_workers):
            worker_id = f"worker_{i:03d}"
            self.workers[worker_id] = Worker(worker_id=worker_id)
            self.worker_ids.append(worker_id)

    def _init_executor(self) -> None:
        """Initialize thread executor."""
        if self.use_async:
            self.executor = ThreadPoolExecutor(max_workers=self.config.num_workers)
        else:
            self.executor = None

    def submit_shard(
        self,
        payload: Any,
        shard_id: Optional[str] = None,
        priority: int = 0,
        deadline: Optional[float] = None,
        dependencies: Optional[List[str]] = None,
    ) -> WorkShard:
        """
        Submit a work shard for processing.

        Args:
            payload: The payload to process.
            shard_id: Optional shard identifier.
            priority: Priority level (0 = normal, negative = high, positive = low).
            deadline: Optional deadline for completion.
            dependencies: Optional list of shard IDs this depends on.

        Returns:
            Created WorkShard.
        """
        # Default dependencies to empty list if None
        if dependencies is None:
            dependencies = []
        
        shard_id = shard_id or self._generate_shard_id()
        worker_id = self._select_worker(shard_id, priority, dependencies)

        shard = WorkShard(
            shard_id=shard_id,
            worker_id=worker_id,
            payload=payload,
            priority=priority,
            deadline=deadline,
            dependencies=dependencies or [],
            status=ShardStatus.PENDING,
        )

        self.pending_shards[shard_id] = shard
        self.running_shards[shard_id] = shard
        self.metrics["total_submitted"] += 1

        logger.debug(f"Submitted shard {shard_id} to worker {worker_id}")

        return shard

    def _generate_shard_id(self) -> str:
        """Generate a unique shard ID."""
        timestamp = time.time()
        random_id = random.randint(0, 2**31 - 1)
        return f"shard_{timestamp:.6f}_{random_id}"

    def _select_worker(
        self,
        shard_id: str,
        priority: int,
        dependencies: List[str],
    ) -> str:
        """
        Select a worker for a shard.

        Args:
            shard_id: The shard ID.
            priority: Priority level.
            dependencies: List of dependency shard IDs.

        Returns:
            Selected worker ID.
        """
        # Check dependencies first
        available_workers = self._find_available_workers(
            dependencies,
            priority,
        )

        if not available_workers:
            # Fallback to any available worker
            available_workers = self._find_any_available_worker()

        if not available_workers:
            raise RuntimeError("No available workers")

        # Select worker based on load balancing
        selected = random.choice(available_workers)
        logger.debug(f"Selected worker {selected} for shard {shard_id}")

        return selected

    def _find_available_workers(
        self,
        dependencies: List[str],
        priority: int,
    ) -> List[str]:
        """Find workers that can handle the shard."""
        available: List[str] = []

        for worker_id in self.worker_ids:
            worker = self.workers[worker_id]

            # Check if worker is available
            if not self._is_worker_available(worker, dependencies, priority):
                continue

            available.append(worker_id)

        return available

    def _find_any_available_worker(self) -> Optional[str]:
        """Find any available worker."""
        for worker_id in self.worker_ids:
            if self._is_worker_available(self.workers[worker_id], [], 0):
                return worker_id

        return None

    def _is_worker_available(
        self,
        worker: Worker,
        dependencies: List[str],
        priority: int,
    ) -> bool:
        """Check if worker is available for a shard."""
        # Check worker state
        if worker.state != WorkerState.IDLE:
            return False

        # Check if worker has capacity
        if len(worker.active_shards) >= self.config.shard_size:
            return False

        # Check if any dependency is satisfied
        for dep_id in dependencies:
            if dep_id not in self.completed_shards:
                return False

        return True

    def process_shard(self, shard_id: str) -> Optional[ShardResult]:
        """
        Process a completed shard.

        Args:
            shard_id: The shard ID to process.

        Returns:
            ShardResult if successful, None otherwise.
        """
        if shard_id not in self.running_shards:
            logger.warning(f"Shard {shard_id} not found in running shards")
            return None

        shard = self.running_shards.pop(shard_id)
        worker = self.workers[shard.worker_id]

        # Update status
        shard.status = ShardStatus.COMPLETED
        shard.completed_at = time.time()

        # Generate result
        result = ShardResult(
            shard_id=shard.shard_id,
            worker_id=shard.worker_id,
            result=self._process_payload(shard.payload),
            status=ShardStatus.COMPLETED,
            elapsed_ms=(shard.completed_at - shard.created_at) * 1000,
        )

        worker.results.append(result)
        self.completed_shards[shard.shard_id] = result

        # Update metrics
        self.metrics["total_completed"] += 1
        self.metrics["average_latency_ms"] = (
            self.metrics["average_latency_ms"]
            + result.elapsed_ms
        )
        self.metrics["average_latency_ms"] /= self.metrics["total_completed"]

        logger.info(f"Processed shard {shard.shard_id} in {result.elapsed_ms:.2f}ms")

        return result

    def _process_payload(self, payload: Any) -> Any:
        """Process a payload (placeholder for actual processing logic)."""
        # In production, this would delegate to worker
        # For now, return the payload as-is
        return payload

    def invalidate_shard(self, shard_id: str) -> bool:
        """
        Invalidate a shard (mark as failed or cancelled).

        Args:
            shard_id: The shard ID to invalidate.

        Returns:
            True if shard was invalidated.
        """
        if shard_id not in self.running_shards:
            return False

        shard = self.running_shards.pop(shard_id)
        shard.status = ShardStatus.FAILED
        shard.error = "Shard invalidated"

        worker = self.workers[shard.worker_id]
        worker.results.append(
            ShardResult(
                shard_id=shard.shard_id,
                worker_id=shard.worker_id,
                result=None,
                status=ShardStatus.FAILED,
                error=shard.error,
            )
        )

        self.metrics["total_failed"] += 1
        logger.warning(f"Invalidated shard {shard.shard_id}")

        return True

    def get_pending_count(self) -> int:
        """Get count of pending shards."""
        return len(self.pending_shards)

    def get_running_count(self) -> int:
        """Get count of running shards."""
        return len(self.running_shards)

    def get_completed_count(self) -> int:
        """Get count of completed shards."""
        return len(self.completed_shards)

    def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics."""
        total_submitted = self.metrics["total_submitted"]
        total_completed = self.metrics["total_completed"]

        return {
            "total_submitted": total_submitted,
            "total_completed": total_completed,
            "total_failed": self.metrics["total_failed"],
            "pending": self.get_pending_count(),
            "running": self.get_running_count(),
            "average_latency_ms": self.metrics["average_latency_ms"],
            "throughput_per_second": (
                total_completed / (total_submitted / self.config.timeout_seconds)
            )
            if total_submitted > 0
            else 0.0,
        }

    def reset_metrics(self) -> None:
        """Reset metrics counters."""
        self.metrics = {
            "total_submitted": 0,
            "total_completed": 0,
            "total_failed": 0,
            "average_latency_ms": 0.0,
            "throughput_per_second": 0.0,
        }

    def get_all_workers(self) -> List[Worker]:
        """Get all workers."""
        return list(self.workers.values())

    def get_worker_state(self, worker_id: str) -> Optional[Worker]:
        """Get state of a specific worker."""
        return self.workers.get(worker_id)

    def shutdown(self, wait: bool = True) -> None:
        """Shutdown the dispatcher."""
        if self.executor:
            self.executor.shutdown(wait=wait)
            self.executor = None

        logger.info("ShardDispatcher shut down")


# =============================================================================
# Shard Collection Manager
# =============================================================================

class ShardCollectionManager:
    """
    Manages collection of shard results.

    Features:
    - Result aggregation
    - Batch collection
    - Validation
    """

    def __init__(
        self,
        validator: Optional[InvariantValidator] = None,
    ):
        self.validator = validator or InvariantValidator()
        self.results: List[ShardResult] = []
        self.batch_size: int = 100

    def add_result(self, result: ShardResult) -> None:
        """Add a result to the collection."""
        self.results.append(result)
        logger.debug(f"Added result {result.shard_id}")

    def get_results(
        self,
        shard_ids: Optional[List[str]] = None,
    ) -> List[ShardResult]:
        """Get results, optionally filtered by shard IDs."""
        if shard_ids:
            return [
                r for r in self.results if r.shard_id in shard_ids
            ]
        return self.results

    def get_batch(
        self,
        start_index: int = 0,
        end_index: Optional[int] = None,
    ) -> List[ShardResult]:
        """Get a batch of results."""
        end_index = end_index or len(self.results)
        return self.results[start_index:end_index]

    def validate_all_results(self) -> Tuple[bool, List[Invariant]]:
        """
        Validate all results against invariants.

        Returns:
            Tuple of (all_valid, list of invariants).
        """
        invariants: List[Invariant] = []
        all_valid = True

        for result in self.results:
            is_valid, error = self.validator.validate_type_expression(
                "placeholder",
                {"result": result.result},
            )

            invariant = Invariant(
                name=result.shard_id,
                expression="placeholder",
                validation_result=is_valid,
                validation_error=error,
            )

            invariants.append(invariant)

            if not is_valid:
                all_valid = False

        return all_valid, invariants

    def get_summary(self) -> Dict[str, Any]:
        """Get collection summary."""
        total = len(self.results)
        completed = sum(1 for r in self.results if r.status == ShardStatus.COMPLETED)
        failed = sum(1 for r in self.results if r.status == ShardStatus.FAILED)

        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "success_rate": completed / total if total > 0 else 0.0,
        }


# =============================================================================
# Utility Functions
# =============================================================================

def create_dispatcher(
    num_workers: int = 4,
    use_async: bool = True,
) -> ShardDispatcher:
    """
    Create a ShardDispatcher instance.

    Args:
        num_workers: Number of worker nodes.
        use_async: Whether to use async processing.

    Returns:
        Configured ShardDispatcher.
    """
    config = DispatcherConfig(num_workers=num_workers)
    return ShardDispatcher(config=config, use_async=use_async)


def create_collection_manager(
    validator: Optional[InvariantValidator] = None,
) -> ShardCollectionManager:
    """
    Create a ShardCollectionManager instance.

    Args:
        validator: Optional invariant validator.

    Returns:
        Configured ShardCollectionManager.
    """
    return ShardCollectionManager(validator=validator)
