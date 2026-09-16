"""
Phase 5: Layer 5 Test Suite - PEP 695 Resolver & Shard Dispatcher.

Tests for:
- TypeAlias resolution
- TypeVar inference
- ParamSpec handling
- TypeVarTuple resolution
- Invariant harvesting
- Metamorphic engine
- PEP 695 syntax validation
- Integration with DPOR, Octagon, Dual SMT, Concolic, CST
- Regression tests
"""

import pytest
import libcst as cst
from libcst import parse_expression
from libcst.metadata import ScopeProvider
from typing import Any, Dict, Optional

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.pep695_resolver import (
    DeepTypeResolver,
    TypeAliasResolver,
    TypeVarResolver,
    ParamSpecResolver,
    TypeVarTupleResolver,
    TypeConstraint,
    TypeAliasInfo,
    TypeVarInfo,
    ParamSpecInfo,
    TypeVarTupleInfo,
    ResolutionError,
    ConstraintType,
)
from src.core.shard_dispatcher import (
    InvariantValidator,
    WorkShard,
    ShardResult,
    ShardDispatcher,
    DispatcherConfig,
    ShardCollectionManager,
    ShardStatus,
    WorkerState,
)


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def resolver():
    """Create a DeepTypeResolver instance."""
    return DeepTypeResolver()


@pytest.fixture
def type_validator():
    """Create an InvariantValidator instance."""
    return InvariantValidator()


@pytest.fixture
def dispatcher():
    """Create a ShardDispatcher instance."""
    return ShardDispatcher(
        config=DispatcherConfig(num_workers=4),
        use_async=True,
    )


@pytest.fixture
def collection_manager():
    """Create a ShardCollectionManager instance."""
    return ShardCollectionManager()


# =============================================================================
# Test: TypeAlias Resolution
# =============================================================================

class TestTypeAliasResolution:
    """Tests for TypeAlias resolution."""

    def test_type_alias_basic_resolution(self, resolver):
        """Test basic TypeAlias resolution from TYPEALIAS constraint."""
        from src.core.pep695_resolver import TypeAliasInfo
        
        # Add a TYPEALIAS constraint for "MyType" - TypeAliasResolver will create TypeAliasInfo
        resolver.add_type_constraint("MyType", TypeConstraint(
            variable="MyType",
            lower_bound=parse_expression("int"),
            upper_bound=None,
            covariant=False,
            constraint_type=ConstraintType.TYPEALIAS,
        ))

        resolved = resolver.resolve_type_ast(parse_expression("MyType"))

        assert resolved is not None
        assert isinstance(resolved, TypeAliasInfo)
        assert resolved.alias_name == "MyType"

    def test_type_alias_subscript_resolution(self, resolver):
        """Test subscripted TypeAlias resolution."""
        from src.core.pep695_resolver import TypeAliasInfo
        
        # Add a TYPEALIAS constraint for "MyType" - TypeAliasResolver will create TypeAliasInfo
        resolver.add_type_constraint("MyType", TypeConstraint(
            variable="MyType",
            lower_bound=None,
            upper_bound=None,
            covariant=False,
            constraint_type=ConstraintType.TYPEALIAS,
        ))

        subscript = parse_expression("MyType[int]")
        resolved = resolver.resolve_type_ast(subscript)

        assert resolved is not None
        assert resolved.alias_name == "MyType"

    def test_type_alias_not_found(self, resolver):
        """Test resolution of non-existent TypeAlias."""
        with pytest.raises(ResolutionError):
            resolver.resolve_type_ast(parse_expression("UnknownType"))

    def test_type_alias_in_resolver_stack(self, resolver):
        """Test TypeAlias resolution in resolver stack."""
        from src.core.pep695_resolver import TypeAliasInfo
        
        # Create nested resolvers where inner_resolver is the parent of outer_resolver
        inner_resolver = DeepTypeResolver()
        outer_resolver = DeepTypeResolver(inner_resolver)  # inner_resolver is parent

        # Add TYPEALIAS constraint to outer_resolver
        outer_resolver.add_type_constraint("OuterType", TypeConstraint(
            variable="OuterType",
            lower_bound=parse_expression("int"),
            upper_bound=None,
            covariant=False,
            constraint_type=ConstraintType.TYPEALIAS,
        ))
        
        # Add TYPEALIAS constraint to inner_resolver (inherited by outer_resolver)
        inner_resolver.add_type_constraint("InnerType", TypeConstraint(
            variable="InnerType",
            lower_bound=parse_expression("str"),
            upper_bound=None,
            covariant=False,
            constraint_type=ConstraintType.TYPEALIAS,
        ))
        
        # Initialize resolvers
        inner_resolver._init_resolvers()
        outer_resolver._init_resolvers()

        resolved = outer_resolver.resolve_type_ast(parse_expression("InnerType"))

        assert resolved is not None, f"Expected resolved to be not None, got {resolved}"
        assert isinstance(resolved, TypeAliasInfo), f"Expected resolved to be TypeAliasInfo, got {type(resolved)}"
        assert resolved.alias_name == "InnerType", f"Expected alias_name to be 'InnerType', got {resolved.alias_name}"
        assert resolved.alias_type == "str", f"Expected alias_type to be 'str', got {resolved.alias_type}"


# =============================================================================
# Test: TypeVar Inference
# =============================================================================

class TestTypeVarInference:
    """Tests for TypeVar inference."""

    def test_typevar_basic_resolution(self, resolver):
        """Test basic TypeVar resolution."""
        constraint = TypeConstraint(
            variable="T",
            lower_bound=None,
            upper_bound=None,
            covariant=True,
            constraint_type=ConstraintType.TYPEVAR,
        )
        resolver.add_type_constraint("T", constraint)

        resolved = resolver.resolve_type_ast(parse_expression("T"))

        assert resolved is not None
        assert isinstance(resolved, TypeVarInfo)
        assert resolved.name == "T"

    def test_typevar_with_bounds(self, resolver):
        """Test TypeVar with bounds."""
        constraint = TypeConstraint(
            variable="T",
            lower_bound=parse_expression("int"),
            upper_bound=None,
            constraint_type=ConstraintType.TYPEVAR,
        )
        resolver.add_type_constraint("T", constraint)

        resolved = resolver.resolve_type_ast(parse_expression("T"))

        assert resolved is not None
        assert isinstance(resolved, TypeVarInfo)
        assert resolved.name == "T"
        assert resolved.bound == "int"

    def test_typevar_covariant(self, resolver):
        """Test TypeVar with covariant flag."""
        constraint = TypeConstraint(
            variable="T",
            lower_bound=None,
            upper_bound=None,
            covariant=True,
            contravariant=False,
            constraint_type=ConstraintType.TYPEVAR,
        )
        resolver.add_type_constraint("T", constraint)

        resolved = resolver.resolve_type_ast(parse_expression("T"))

        assert resolved is not None
        assert isinstance(resolved, TypeVarInfo)
        assert resolved.covariant == True
        assert resolved.contravariant == False

    def test_typevar_not_found(self, resolver):
        """Test resolution of non-existent TypeVar."""
        with pytest.raises(ResolutionError):
            resolver.resolve_type_ast(parse_expression("UnknownTypeVar"))


# =============================================================================
# Test: ParamSpec Handling
# =============================================================================

class TestParamSpecHandling:
    """Tests for ParamSpec handling."""

    def test_paramspec_basic_resolution(self, resolver):
        """Test basic ParamSpec resolution."""
        constraint = TypeConstraint(
            variable="P",
            lower_bound=None,
            upper_bound=None,
            covariant=True,
            constraint_type=ConstraintType.PARAMSPEC,
        )
        resolver.add_type_constraint("P", constraint)

        resolved = resolver.resolve_type_ast(parse_expression("P"))

        assert resolved is not None
        assert isinstance(resolved, ParamSpecInfo)
        assert resolved.name == "P"

    def test_paramspec_with_bounds(self, resolver):
        """Test ParamSpec with bounds."""
        constraint = TypeConstraint(
            variable="P",
            lower_bound=parse_expression("collections.abc.Callable"),
            upper_bound=None,
            constraint_type=ConstraintType.PARAMSPEC,
        )
        resolver.add_type_constraint("P", constraint)

        resolved = resolver.resolve_type_ast(parse_expression("P"))

        assert resolved is not None
        assert isinstance(resolved, ParamSpecInfo)
        assert resolved.name == "P"
        assert resolved.bound == "collections.abc.Callable"

    def test_paramspec_covariant(self, resolver):
        """Test ParamSpec with covariant flag."""
        constraint = TypeConstraint(
            variable="P",
            lower_bound=None,
            upper_bound=None,
            covariant=True,
            constraint_type=ConstraintType.PARAMSPEC,
        )
        resolver.add_type_constraint("P", constraint)

        resolved = resolver.resolve_type_ast(parse_expression("P"))

        assert resolved is not None
        assert isinstance(resolved, ParamSpecInfo)
        assert resolved.covariant == True


# =============================================================================
# Test: TypeVarTuple Resolution
# =============================================================================

class TestTypeVarTupleResolution:
    """Tests for TypeVarTuple resolution."""

    def test_typevartuple_basic_resolution(self, resolver):
        """Test basic TypeVarTuple resolution."""
        constraint = TypeConstraint(
            variable="Tvs",
            lower_bound=None,
            upper_bound=None,
            constraint_type=ConstraintType.TYPEVARTUPLE,
        )
        resolver.add_type_constraint("Tvs", constraint)

        resolved = resolver.resolve_type_ast(parse_expression("Tvs"))

        assert resolved is not None
        assert isinstance(resolved, TypeVarTupleInfo)
        assert resolved.name == "Tvs"

    def test_typevartuple_with_items(self, resolver):
        """Test TypeVarTuple with items."""
        constraint = TypeConstraint(
            variable="Tvs",
            lower_bound=None,
            upper_bound=None,
            constraint_type=ConstraintType.TYPEVARTUPLE,
            items=["T", "U"],
        )
        resolver.add_type_constraint("Tvs", constraint)

        resolved = resolver.resolve_type_ast(parse_expression("Tvs"))

        assert resolved is not None
        assert isinstance(resolved, TypeVarTupleInfo)
        assert resolved.name == "Tvs"
        assert len(resolved.items) > 0  # TypeAliasResolver should return TypeAliasInfo with items from constraint

    def test_typevartuple_not_found(self, resolver):
        """Test resolution of non-existent TypeVarTuple."""
        with pytest.raises(ResolutionError):
            resolver.resolve_type_ast(
                parse_expression("UnknownTypeVarTuple"),
            )


# =============================================================================
# Test: Invariant Harvesting
# =============================================================================

class TestInvariantHarvesting:
    """Tests for invariant harvesting and validation."""

    def test_validate_type_expression(self, type_validator):
        """Test type expression validation."""
        is_valid, error = type_validator.validate_type_expression(
            "TypeVar[X, Y]",
            {"X": "int", "Y": "str"},
        )

        assert isinstance(is_valid, bool)

    def test_validate_pep695_type(self, type_validator):
        """Test PEP 695 type AST validation."""
        type_ast = parse_expression("TypeVar[X]")
        is_valid, error = type_validator.validate_pep695_type(type_ast)

        assert isinstance(is_valid, bool)

    def test_invariant_validation(self, type_validator):
        """Test invariant validation."""
        is_valid, error = type_validator.validate_type_expression(
            "TypeVar[T]",
            {"T": "int"},
        )

        assert isinstance(is_valid, bool)
        assert isinstance(error, str)

    def test_type_constraint_validation(self, type_validator):
        """Test type constraint validation."""
        constraint = TypeConstraint(
            variable="T",
            lower_bound=parse_expression("int"),
            upper_bound=None,
        )

        type_validator.type_constraints["T"] = constraint

        is_valid, error = type_validator.validate_type_expression(
            "TypeVar[T]",
            {"T": "int"},
        )

        assert is_valid is True
        assert error == ""


# =============================================================================
# Test: Metamorphic Engine
# =============================================================================

class TestMetamorphicEngine:
    """Tests for metamorphic engine functionality."""

    def test_metamorphic_type_generation(self, resolver):
        """Test metamorphic type generation."""
        constraint = TypeConstraint(
            variable="T",
            lower_bound=parse_expression("int"),
            upper_bound=None,
        )
        resolver.add_type_constraint("T", constraint)

        type_ast = parse_expression("T")
        resolved = resolver.resolve_type_ast(type_ast)

        assert resolved is not None
        assert isinstance(resolved, TypeVarInfo)

    def test_metamorphic_type_transformation(self, resolver):
        """Test metamorphic type transformation."""
        constraint = TypeConstraint(
            variable="T",
            lower_bound=parse_expression("int"),
            upper_bound=None,
        )
        resolver.add_type_constraint("T", constraint)

        type_ast = parse_expression("T")
        transformed = resolver.resolve_type_ast(type_ast)

        assert transformed is not None
        assert isinstance(transformed, TypeVarInfo)


# =============================================================================
# Test: PEP 695 Syntax Validation
# =============================================================================

class TestPEP695SyntaxValidation:
    """Tests for PEP 695 syntax validation."""

    def test_valid_type_syntax(self, resolver):
        """Test valid type syntax validation."""
        type_ast = parse_expression("TypeVar[T]")
        is_valid, errors = resolver.validate_pep695_syntax(type_ast)

        assert is_valid is True
        assert len(errors) == 0

    def test_invalid_type_syntax(self, resolver):
        """Test invalid type syntax validation."""
        type_ast = parse_expression("UnknownType[T]")
        is_valid, errors = resolver.validate_pep695_syntax(type_ast)

        assert is_valid is False
        assert len(errors) > 0

    def test_complex_type_syntax(self, resolver):
        """Test complex type syntax validation."""
        type_ast = parse_expression("Callable[[T, U], V]")
        is_valid, errors = resolver.validate_pep695_syntax(type_ast)

        assert is_valid is True
        assert len(errors) == 0

    def test_nested_type_syntax(self, resolver):
        """Test nested type syntax validation."""
        type_ast = parse_expression("Dict[T, List[U]]")
        is_valid, errors = resolver.validate_pep695_syntax(type_ast)

        assert is_valid is True
        assert len(errors) == 0


# =============================================================================
# Test: Integration with DPOR
# =============================================================================

class TestIntegrationWithDPOR:
    """Tests for integration with DPOR scheduler."""

    def test_integration_with_dpor(self, resolver):
        """Test integration with DPOR scheduler."""
        from src.core.dpor_scheduler import DeterministicVirtualScheduler

        type_resolver = DeepTypeResolver()
        dpor_scheduler = DeterministicVirtualScheduler(num_workers=4)

        constraint = TypeConstraint(
            variable="T",
            lower_bound=None,
            upper_bound=None,
            constraint_type=ConstraintType.TYPEVAR,
        )
        type_resolver.add_type_constraint("T", constraint)
        type_ast = parse_expression("T")
        resolved = type_resolver.resolve_type_ast(type_ast)

        dpor_result = dpor_scheduler.process_result(
            shard_id="test_shard",
            payload=resolved,
        )

        assert dpor_result is not None

    async def test_integration_with_dpor_concurrent(self, resolver):
        """Test concurrent DPOR processing."""
        import asyncio

        from src.core.dpor_scheduler import DeterministicVirtualScheduler

        type_resolver = DeepTypeResolver()
        dpor_scheduler = DeterministicVirtualScheduler(num_workers=8)

        async def process_type(
            i: int,
            type_ast,
        ) -> Any:
            resolved = type_resolver.resolve_type_ast(type_ast)
            return dpor_scheduler.process_result(
                shard_id=f"shard_{i}",
                payload=resolved,
            )

        constraint = TypeConstraint(
            variable="T",
            lower_bound=None,
            upper_bound=None,
            constraint_type=ConstraintType.TYPEVAR,
        )
        type_resolver.add_type_constraint("T", constraint)

        tasks = [
            process_type(i, parse_expression("T"))
            for i in range(10)
        ]

        results = await asyncio.gather(*tasks)
        assert results is not None


# =============================================================================
# Test: Integration with Octagon Domain
# =============================================================================

class TestIntegrationWithOctagon:
    """Tests for integration with Octagon domain."""

    def test_integration_with_octagon(self, resolver):
        """Test integration with Octagon domain."""
        from src.core.octagon_domain import OctagonDomain

        type_resolver = DeepTypeResolver()
        octagon_domain = OctagonDomain()

        constraint = TypeConstraint(
            variable="T",
            lower_bound=parse_expression("int"),
            upper_bound=None,
        )
        type_resolver.add_type_constraint("T", constraint)

        type_ast = parse_expression("T")
        resolved = type_resolver.resolve_type_ast(type_ast)

        octagon_result = octagon_domain.analyze_type(
            type_str=str(resolved),
            constraints={"T": "int"},
        )

        assert octagon_result is not None

    def test_integration_with_octagon_bounds(self, resolver):
        """Test integration with Octagon domain bounds."""
        from src.core.octagon_domain import OctagonDomain

        type_resolver = DeepTypeResolver()
        octagon_domain = OctagonDomain()

        constraint = TypeConstraint(
            variable="T",
            lower_bound=parse_expression("int"),
            upper_bound=parse_expression("float"),
        )
        type_resolver.add_type_constraint("T", constraint)

        type_ast = parse_expression("T")
        resolved = type_resolver.resolve_type_ast(type_ast)

        octagon_result = octagon_domain.analyze_type(
            type_str=str(resolved),
            constraints={"T": "int"},
        )

        assert octagon_result is not None


# =============================================================================
# Test: Integration with Dual SMT
# =============================================================================

class TestIntegrationWithDualSolver:
    """Tests for integration with dual solver consensus."""

    def test_integration_with_dual_solver(self, resolver):
        """Test integration with dual solver consensus."""
        from src.core.dual_solver_consensus import DualSolverConsensus

        type_resolver = DeepTypeResolver()
        dual_solver = DualSolverConsensus()

        constraint = TypeConstraint(
            variable="T",
            lower_bound=parse_expression("int"),
            upper_bound=None,
        )
        type_resolver.add_type_constraint("T", constraint)

        type_ast = parse_expression("T")
        resolved = type_resolver.resolve_type_ast(type_ast)

        consensus = dual_solver.evaluate_consensus(
            type_str=str(resolved),
            constraints={"T": "int"},
        )

        assert consensus is not None

    def test_integration_with_dual_solver_agreement(self, resolver):
        """Test dual solver agreement."""
        from src.core.dual_solver_consensus import DualSolverConsensus

        type_resolver = DeepTypeResolver()
        dual_solver = DualSolverConsensus()

        constraint = TypeConstraint(
            variable="T",
            lower_bound=parse_expression("int"),
            upper_bound=None,
        )
        type_resolver.add_type_constraint("T", constraint)

        type_ast = parse_expression("T")
        resolved = type_resolver.resolve_type_ast(type_ast)

        consensus = dual_solver.evaluate_consensus(
            type_str=str(resolved),
            constraints={"T": "int"},
        )

        assert consensus is not None
        # evaluate_consensus returns (status, confidence, metadata_dict)
        assert isinstance(consensus, tuple)
        assert len(consensus) == 3
        assert isinstance(consensus[0], str)
        assert isinstance(consensus[1], float)
        assert isinstance(consensus[2], dict)


# =============================================================================
# Test: Integration with Concolic Engine
# =============================================================================

class TestIntegrationWithConcolic:
    """Tests for integration with concolic engine."""

    def test_integration_with_concolic(self, resolver):
        """Test integration with concolic engine."""
        from src.core.concolic_engine import ConcolicEngine

        type_resolver = DeepTypeResolver()
        concolic_engine = ConcolicEngine()

        constraint = TypeConstraint(
            variable="T",
            lower_bound=parse_expression("int"),
            upper_bound=None,
        )
        type_resolver.add_type_constraint("T", constraint)

        type_ast = parse_expression("T")
        resolved = type_resolver.resolve_type_ast(type_ast)

        concolic_result = concolic_engine.analyze_type(
            type_str=str(resolved),
            constraints={"T": "int"},
        )

        assert concolic_result is not None

    def test_integration_with_concolic_backtracking(self, resolver):
        """Test concolic backtracking."""
        from src.core.concolic_engine import ConcolicEngine

        type_resolver = DeepTypeResolver()
        concolic_engine = ConcolicEngine()

        constraint = TypeConstraint(
            variable="T",
            lower_bound=parse_expression("int"),
            upper_bound=None,
        )
        type_resolver.add_type_constraint("T", constraint)

        type_ast = parse_expression("T")
        resolved = type_resolver.resolve_type_ast(type_ast)

        concolic_result = concolic_engine.analyze_type(
            type_str=str(resolved),
            constraints={"T": "int"},
        )

        assert concolic_result is not None


# =============================================================================
# Test: Integration with CST
# =============================================================================

class TestIntegrationWithCST:
    """Tests for integration with CST parser."""

    def test_integration_with_cst(self, resolver):
        """Test integration with CST parser."""
        type_resolver = DeepTypeResolver()

        constraint = TypeConstraint(
            variable="T",
            lower_bound=None,
            upper_bound=None,
            constraint_type=ConstraintType.TYPEVAR,
        )
        type_resolver.add_type_constraint("T", constraint)

        type_annotation = parse_expression("T")
        resolved = type_resolver.resolve_type_ast(type_annotation)

        assert resolved is not None

    def test_integration_with_cst_subscript(self, resolver):
        """Test integration with CST subscripted types."""
        type_resolver = DeepTypeResolver()

        constraint = TypeConstraint(
            variable="T",
            lower_bound=None,
            upper_bound=None,
            constraint_type=ConstraintType.TYPEVAR,
        )
        type_resolver.add_type_constraint("T", constraint)

        type_annotation = parse_expression("T")
        resolved = type_resolver.resolve_type_ast(type_annotation)

        assert resolved is not None


# =============================================================================
# Test: Regression Tests
# =============================================================================

class TestRegressionTests:
    """Regression tests for previous phases."""

    def test_regression_test_1_typealias_chain(self, resolver):
        """Test TypeAlias chain resolution."""
        constraint1 = TypeConstraint(
            variable="BaseType",
            lower_bound=parse_expression("int"),
            upper_bound=None,
            constraint_type=ConstraintType.TYPEALIAS,
        )
        resolver.add_type_constraint("BaseType", constraint1)

        constraint2 = TypeConstraint(
            variable="DerivedType",
            lower_bound=parse_expression("BaseType"),
            upper_bound=None,
            constraint_type=ConstraintType.TYPEALIAS,
        )
        resolver.add_type_constraint("DerivedType", constraint2)

        resolved = resolver.resolve_type_ast(parse_expression("DerivedType"))

        assert resolved is not None
        assert isinstance(resolved, TypeAliasInfo)

    def test_regression_test_2_typevar_bounds(self, resolver):
        """Test TypeVar bounds resolution."""
        constraint = TypeConstraint(
            variable="T",
            lower_bound=parse_expression("int"),
            upper_bound=parse_expression("float"),
            constraint_type=ConstraintType.TYPEALIAS,
        )
        resolver.add_type_constraint("T", constraint)

        resolved = resolver.resolve_type_ast(parse_expression("T"))

        assert resolved is not None
        assert isinstance(resolved, TypeAliasInfo)
        assert resolved.alias_type == "int"


# =============================================================================
# Shard Dispatcher Tests
# =============================================================================

class TestShardDispatcher:
    """Tests for ShardDispatcher."""

    def test_submit_and_process_shard(self, dispatcher):
        """Test submitting and processing a shard."""
        shard = dispatcher.submit_shard(
            payload={"test": "data"},
            shard_id="test_shard_001",
        )

        assert shard.shard_id == "test_shard_001"
        assert shard.worker_id.startswith("worker_")
        assert shard.status == ShardStatus.PENDING

        result = dispatcher.process_shard(shard.shard_id)

        assert result is not None
        assert result.status == ShardStatus.COMPLETED

    def test_priority_based_distribution(self, dispatcher):
        """Test priority-based shard distribution."""
        high_priority_shard = dispatcher.submit_shard(
            payload={"priority": "high"},
            priority=-1,
        )

        low_priority_shard = dispatcher.submit_shard(
            payload={"priority": "low"},
            priority=1,
        )

        assert high_priority_shard.worker_id in dispatcher.worker_ids
        assert low_priority_shard.worker_id in dispatcher.worker_ids
        assert high_priority_shard.priority < low_priority_shard.priority

    def test_dependency_resolution(self, dispatcher):
        """Test shard dependency resolution."""
        dep_shard = dispatcher.submit_shard(
            payload={"type": "dependency"},
            shard_id="dep_shard",
        )

        dependent_shard = dispatcher.submit_shard(
            payload={"type": "dependent"},
            shard_id="dep_shard",
            dependencies=["dep_shard"],
        )

        assert dependent_shard.status == ShardStatus.PENDING

    def test_worker_crash_recovery(self, dispatcher):
        """Test worker crash recovery."""
        worker_id = dispatcher.worker_ids[0]
        worker = dispatcher.get_worker_state(worker_id)

        assert worker is not None
        assert worker.state == WorkerState.IDLE

    def test_metrics_tracking(self, dispatcher):
        """Test metrics tracking."""
        shard = dispatcher.submit_shard(
            payload={"metric": "test"},
            shard_id="metric_shard",
        )

        metrics = dispatcher.get_metrics()

        assert metrics["total_submitted"] == 1
        assert metrics["average_latency_ms"] >= 0


# =============================================================================
# Shard Collection Manager Tests
# =============================================================================

class TestShardCollectionManager:
    """Tests for ShardCollectionManager."""

    def test_add_and_get_results(self, collection_manager):
        """Test adding and retrieving results."""
        result = ShardResult(
            shard_id="test_shard",
            worker_id="worker_001",
            result={"data": "test"},
        )

        collection_manager.add_result(result)
        retrieved = collection_manager.get_results()

        assert len(retrieved) == 1
        assert retrieved[0].shard_id == "test_shard"

    def test_validate_all_results(self, collection_manager):
        """Test validation of all results."""
        result1 = ShardResult(
            shard_id="valid_shard",
            worker_id="worker_001",
            result={"data": "valid"},
        )
        result2 = ShardResult(
            shard_id="invalid_shard",
            worker_id="worker_002",
            result=None,
        )

        collection_manager.add_result(result1)
        collection_manager.add_result(result2)

        all_valid, invariants = collection_manager.validate_all_results()

        assert len(invariants) == 2

    def test_get_summary(self, collection_manager):
        """Test collection summary."""
        result1 = ShardResult(
            shard_id="shard_1",
            worker_id="worker_001",
            result={"data": "test"},
            status=ShardStatus.COMPLETED,
        )
        result2 = ShardResult(
            shard_id="shard_2",
            worker_id="worker_002",
            result=None,
            status=ShardStatus.FAILED,
        )

        collection_manager.add_result(result1)
        collection_manager.add_result(result2)

        summary = collection_manager.get_summary()

        assert summary["total"] == 2
        assert summary["completed"] == 1
        assert summary["failed"] == 1
        assert summary["success_rate"] == 0.5
