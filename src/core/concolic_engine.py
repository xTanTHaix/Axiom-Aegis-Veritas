"""
Concolic Engine Module.

Provides concolic testing integration for the Layer 5 pipeline.

Implements:
- BackwardSlicer — backward slicing from focus point
- InvariantHarvester — extract pre/post-condition invariants
- BoundaryTester — generate boundary test cases (min/max/zero)
- ContractHarvester — harvest contracts from code
"""

from __future__ import annotations

import ast
import collections
import copy
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
    Type,
    TypeVar,
    Union,
)

import libcst as cst
from libcst import matchers as m
from libcst.metadata import ScopeProvider, ExpressionContext, PositionProvider

logger = logging.getLogger(__name__)

T = TypeVar("T")


# =============================================================================
# Exceptions
# =============================================================================


class SlicingError(Exception):
    """Raised when backward slicing fails."""

    def __init__(self, message: str = "Backward slicing failed") -> None:
        super().__init__(message)


class InvariantExtractionError(Exception):
    """Raised when invariant extraction fails."""

    def __init__(self, message: str = "Invariant extraction failed") -> None:
        super().__init__(message)


class BoundaryGenerationError(Exception):
    """Raised when boundary test generation fails."""

    def __init__(self, message: str = "Boundary generation failed") -> None:
        super().__init__(message)


# =============================================================================
# Backward Slicer
# =============================================================================


@dataclass
class BackwardSlice:
    """Result of backward slicing from a focus point.

    Attributes:
        focus_node: The AST node that was the focus of slicing.
        slice_nodes: All nodes reachable via backward edges.
        dependency_edges: Edges showing data dependencies.
        control_edges: Edges showing control flow dependencies.
        slice_depth: Maximum depth of the slice.
    """

    focus_node: ast.AST
    slice_nodes: List[ast.AST] = field(default_factory=list)
    dependency_edges: List[Tuple[ast.AST, ast.AST]] = field(default_factory=list)
    control_edges: List[Tuple[ast.AST, ast.AST]] = field(default_factory=list)
    slice_depth: int = 0

    def __repr__(self) -> str:
        return (
            f"BackwardSlice(focus={self.focus_node.__class__.__name__}, "
            f"nodes={len(self.slice_nodes)}, depth={self.slice_depth})"
        )


class BackwardSlicer:
    """Performs backward slicing from a focus point in the AST.

    Backward slicing identifies all program points that can reach (via
    control flow and data dependencies) a specified focus node.
    """

    def __init__(self) -> None:
        self._slices: List[BackwardSlice] = []
        self._total_focus_points: int = 0
        self._total_slice_nodes: int = 0

    def slice(
        self,
        tree: ast.Module,
        focus_node: ast.AST,
        max_depth: int = 10,
    ) -> BackwardSlice:
        """Perform backward slicing from a focus node.

        Args:
            tree: The AST module to slice.
            focus_node: The AST node to slice backward from.
            max_depth: Maximum recursion depth for the slice.

        Returns:
            The backward slice result.

        Raises:
            SlicingError: If slicing fails.
        """
        if focus_node is None:
            raise SlicingError("Focus node cannot be None")

        try:
            self._total_focus_points += 1
            slice_nodes: Set[ast.AST] = {focus_node}
            edges: List[Tuple[ast.AST, ast.AST]] = []
            self._dfs_backward(tree.body, focus_node, slice_nodes, edges, max_depth)
            self._slices.append(
                BackwardSlice(
                    focus_node=focus_node,
                    slice_nodes=list(slice_nodes),
                    dependency_edges=edges,
                    slice_depth=max_depth,
                )
            )
            self._total_slice_nodes += len(slice_nodes)
            return self._slices[-1]
        except Exception as exc:
            raise SlicingError(f"Backward slicing failed: {exc}") from exc

    def _dfs_backward(
        self,
        statements: List[ast.stmt],
        focus: ast.AST,
        visited: Set[ast.AST],
        edges: List[Tuple[ast.AST, ast.AST]],
        depth: int,
    ) -> None:
        """Depth-first backward traversal from focus node."""
        if depth <= 0 or id(focus) in visited:
            return

        visited.add(id(focus))

        # Find parent statements
        for stmt in statements:
            if id(stmt) in visited:
                continue
            self._find_back_edges(stmt, focus, visited, edges, depth)

    def _find_back_edges(
        self,
        stmt: ast.stmt,
        target: ast.AST,
        visited: Set[int],
        edges: List[Tuple[ast.AST, ast.AST]],
        depth: int,
    ) -> None:
        """Find edges from stmt to target (backward direction)."""
        if depth <= 0 or id(stmt) in visited:
            return

        visited.add(id(stmt))

        for node in ast.walk(stmt):
            if id(node) in visited:
                continue
            if node is target:
                # Add backward edge from current stmt to target
                edges.append((target, stmt))
                return

            # Check if node is used by stmt
            if isinstance(node, ast.Name) and isinstance(stmt, ast.stmt):
                try:
                    scope = ScopeProvider()
                    ctx = ExpressionContext(
                        position=PositionProvider().position(node),
                        parent=PositionProvider().parent(node),
                    )
                    scope.resolve(node, ctx)
                    if stmt in scope.resolve(node, ctx).refs:
                        edges.append((node, stmt))
                except Exception:
                    pass

    def get_slices(self) -> List[BackwardSlice]:
        """Get all computed slices.

        Returns:
            List of BackwardSlice results.
        """
        return list(self._slices)

    def get_stats(self) -> Dict[str, Any]:
        """Get slicing statistics.

        Returns:
            Dictionary with slicing stats.
        """
        return {
            "total_focus_points": self._total_focus_points,
            "total_slice_nodes": self._total_slice_nodes,
            "num_slices": len(self._slices),
            "avg_slice_size": (
                self._total_slice_nodes / self._total_focus_points
                if self._total_focus_points > 0
                else 0
            ),
        }


# =============================================================================
# Invariant Harvester
# =============================================================================


@dataclass
class Invariant:
    """An extracted invariant.

    Attributes:
        expression: The invariant expression string.
        location: Source location in the AST.
        type: Invariant type (loop, function, global).
        confidence: Confidence score (0.0 to 1.0).
        variables: Set of variables involved.
    """

    expression: str
    location: Optional[Tuple[int, int]] = None
    type: str = "unknown"
    confidence: float = 0.0
    variables: Set[str] = field(default_factory=set)

    def __repr__(self) -> str:
        return (
            f"Invariant(expr={self.expression!r}, type={self.type}, "
            f"confidence={self.confidence:.2f}, vars={self.variables})"
        )


@dataclass
class InvariantHarvestResult:
    """Result of invariant harvesting.

    Attributes:
        invariants: List of extracted invariants.
        summary: Summary statistics.
    """

    invariants: List[Invariant] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"InvariantHarvestResult(invariants={len(self.invariants)}, "
            f"summary={self.summary})"
        )


class InvariantHarvester:
    """Extracts pre/post-condition invariants from code.

    Uses pattern matching on AST to identify:
    - Loop invariants (loop-carried, induction variables)
    - Function invariants (parameter constraints)
    - Global invariants (module-level constants)
    """

    def __init__(self) -> None:
        self._harvests: List[InvariantHarvestResult] = []
        self._total_invariants: int = 0
        self._total_variables: int = 0

    def harvest(
        self,
        tree: ast.Module,
        focus_node: Optional[ast.AST] = None,
        boundary_type: Optional[str] = None,
        pre_condition: Optional[bool] = None,
        post_condition: Optional[bool] = None,
    ) -> List[dict]:
        """Harvest invariants from the AST.

        Args:
            tree: The AST module to harvest from.
            focus_node: Optional focus node for targeted harvesting.
            boundary_type: Optional boundary type filter (e.g., "loop", "function", "global").
            pre_condition: If True, only harvest pre-condition invariants.
            post_condition: If True, only harvest post-condition invariants.

        Returns:
            List of invariant dictionaries with keys: expression, type, confidence, variables, constraints.
        """
        invariants: List[Invariant] = []

        # Harvest loop invariants (pre-condition)
        for node in ast.walk(tree):
            if isinstance(node, ast.For) or isinstance(node, ast.While):
                loop_invariants = self._harvest_loop_invariants(node)
                invariants.extend(loop_invariants)

        # Harvest function invariants (pre-condition + post-condition)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_invariants = self._harvest_function_invariants(node)
                invariants.extend(func_invariants)

        # Harvest global invariants (pre-condition)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                global_invariants = self._harvest_global_invariants(node)
                invariants.extend(global_invariants)

        # Apply filters
        if pre_condition and not post_condition:
            invariants = [iv for iv in invariants if iv.type in ("loop", "function", "global")]
        elif post_condition and not pre_condition:
            invariants = [iv for iv in invariants if iv.type == "function"]
        elif pre_condition and post_condition:
            invariants = list(invariants)

        if boundary_type:
            invariants = [iv for iv in invariants if iv.type == boundary_type]

        result: List[dict] = []
        for iv in invariants:
            result.append({
                "expression": iv.expression,
                "type": iv.type,
                "confidence": iv.confidence,
                "variables": list(iv.variables),
                "constraints": iv.expression,
            })

        self._harvests.append(
            InvariantHarvestResult(
                invariants=invariants,
                summary={
                    "total_invariants": len(invariants),
                    "total_variables": len(set().union(*(iv.variables for iv in invariants))),
                },
            )
        )
        self._total_invariants += len(invariants)
        self._total_variables += len(set().union(*(iv.variables for iv in invariants)))

        return result

    def _harvest_loop_invariants(self, node: Union[ast.For, ast.While]) -> List[Invariant]:
        """Harvest invariants from a loop node."""
        invariants: List[Invariant] = []

        # Find induction variables
        if isinstance(node, ast.For):
            target = node.target
        else:
            # ast.While does not have 'target' attribute, use the loop body iterator
            target = node.body[0] if node.body else None

        if isinstance(target, ast.Name):
            var_name = target.id
            # Look for comparison patterns: i < n, i <= n, etc.
            for child in ast.walk(node):
                if isinstance(child, ast.Compare):
                    for comparator in child.comparators:
                        if isinstance(comparator, ast.Name) and comparator.id == var_name:
                            invariants.append(
                                Invariant(
                                    expression=f"{var_name} < {comparator.id}",
                                    location=child.lineno,
                                    type="loop",
                                    confidence=0.8,
                                    variables={var_name, comparator.id},
                                )
                            )

        return invariants

    def _harvest_function_invariants(self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> List[Invariant]:
        """Harvest invariants from a function node."""
        invariants: List[Invariant] = []

        # Extract parameter types and constraints
        for arg in node.args.args:
            if arg.annotation:
                ann_str = astunparse(node.args.args[0].annotation) if arg.annotation else ""
                invariants.append(
                    Invariant(
                        expression=f"arg: {arg.arg} = {ann_str}",
                        location=node.lineno,
                        type="function",
                        confidence=0.7,
                        variables={arg.arg},
                    )
                )

        return invariants

    def _harvest_global_invariants(self, node: ast.Assign) -> List[Invariant]:
        """Harvest invariants from assignment nodes."""
        invariants: List[Invariant] = []

        for target in node.targets:
            if isinstance(target, ast.Name):
                var_name = target.id
                if isinstance(node.value, ast.Constant):
                    invariants.append(
                        Invariant(
                            expression=f"{var_name} = {node.value.value}",
                            location=node.lineno,
                            type="global",
                            confidence=0.9,
                            variables={var_name},
                        )
                    )

        return invariants

    def get_harvests(self) -> List[InvariantHarvestResult]:
        """Get all harvest results.

        Returns:
            List of InvariantHarvestResult.
        """
        return list(self._harvests)

    def get_stats(self) -> Dict[str, Any]:
        """Get harvest statistics.

        Returns:
            Dictionary with harvest stats.
        """
        return {
            "total_invariants": self._total_invariants,
            "total_variables": self._total_variables,
            "num_harvests": len(self._harvests),
        }


# =============================================================================
# Boundary Tester
# =============================================================================


@dataclass
class BoundaryTestCase:
    """A boundary test case.

    Attributes:
        name: Test case name.
        inputs: Input values for the test case.
        expected_output: Expected output.
        boundary_type: Type of boundary (min, max, zero, negative, overflow).
        description: Human-readable description.
        variables: Variables involved in the test case.
    """

    name: str
    inputs: Dict[str, Any]
    expected_output: Any
    boundary_type: str = "unknown"
    description: str = ""
    variables: Dict[str, str] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"BoundaryTestCase(name={self.name!r}, type={self.boundary_type}, "
            f"inputs={self.inputs})"
        )


class BoundaryTester:
    """Generates boundary test cases for functions.

    Generates test cases for:
    - Minimum/maximum values
    - Zero values
    - Negative values
    - Overflow/underflow
    - Empty inputs
    - Single-element inputs
    """

    def __init__(self, max_test_cases: Optional[int] = None) -> None:
        self._test_cases: List[BoundaryTestCase] = []
        self._total_generated: int = 0
        self._max_test_cases: int = max_test_cases or 10

    def generate(
        self,
        tree: ast.Module,
        boundary_type: Optional[str] = None,
    ) -> List[BoundaryTestCase]:
        """Generate boundary test cases from an AST module.

        Scans the AST for function definitions, extracts parameter types,
        and generates boundary test cases (min, max, zero, negative, overflow).

        Args:
            tree: The AST module to analyze.
            boundary_type: Optional filter for boundary type
                ("min", "max", "zero", "negative", "overflow", or "all").

        Returns:
            List of BoundaryTestCase.
        """
        test_cases: List[BoundaryTestCase] = []
        case_idx = 0
        max_test_cases = self._max_test_cases

        # Collect all function definitions from the tree
        functions: List[Tuple[str, List[str]]] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                params: List[str] = []
                for arg in node.args.args:
                    type_str = "any"
                    if arg.annotation:
                        try:
                            type_str = ast.unparse(arg.annotation) if hasattr(ast, "unparse") else astunparse(arg.annotation)
                        except Exception:
                            type_str = str(arg.annotation)
                    params.append(type_str)
                functions.append((node.name, params))

        # Generate boundary test cases for each function
        for func_name, param_types in functions:
            if case_idx >= max_test_cases:
                break

            # Determine boundary type for this case
            if boundary_type == "all":
                current_boundary = "min_max"
            elif boundary_type in ("min", "max", "zero", "negative", "overflow"):
                current_boundary = boundary_type
            else:
                current_boundary = "min_max"

            # Min values
            if current_boundary in ("min", "min_max", "all"):
                for i, param_type in enumerate(param_types):
                    if case_idx >= max_test_cases:
                        break
                    test_cases.append(
                        BoundaryTestCase(
                            name=f"min_{func_name}_{i}",
                            inputs={f"param_{i}": self._min_value(param_type)},
                            expected_output=None,
                            boundary_type="min",
                            description=f"Minimum value for {param_type}",
                            variables={f"param_{i}": param_type},
                        )
                    )
                    case_idx += 1

            # Max values
            if current_boundary in ("max", "min_max", "all"):
                for i, param_type in enumerate(param_types):
                    if case_idx >= max_test_cases:
                        break
                    test_cases.append(
                        BoundaryTestCase(
                            name=f"max_{func_name}_{i}",
                            inputs={f"param_{i}": self._max_value(param_type)},
                            expected_output=None,
                            boundary_type="max",
                            description=f"Maximum value for {param_type}",
                            variables={f"param_{i}": param_type},
                        )
                    )
                    case_idx += 1

            # Zero values
            if current_boundary in ("zero", "all"):
                for i, param_type in enumerate(param_types):
                    if case_idx >= max_test_cases:
                        break
                    test_cases.append(
                        BoundaryTestCase(
                            name=f"zero_{func_name}_{i}",
                            inputs={f"param_{i}": 0},
                            expected_output=None,
                            boundary_type="zero",
                            description=f"Zero value for {param_type}",
                            variables={f"param_{i}": param_type},
                        )
                    )
                    case_idx += 1

            # Negative values
            if current_boundary in ("negative", "all"):
                for i, param_type in enumerate(param_types):
                    if case_idx >= max_test_cases:
                        break
                    test_cases.append(
                        BoundaryTestCase(
                            name=f"negative_{func_name}_{i}",
                            inputs={f"param_{i}": -1},
                            expected_output=None,
                            boundary_type="negative",
                            description=f"Negative value for {param_type}",
                            variables={f"param_{i}": param_type},
                        )
                    )
                    case_idx += 1

            # Overflow
            if current_boundary in ("overflow", "all"):
                for i, param_type in enumerate(param_types):
                    if case_idx >= max_test_cases:
                        break
                    test_cases.append(
                        BoundaryTestCase(
                            name=f"overflow_{func_name}_{i}",
                            inputs={f"param_{i}": self._overflow_value(param_type)},
                            expected_output=None,
                            boundary_type="overflow",
                            description=f"Overflow value for {param_type}",
                            variables={f"param_{i}": param_type},
                        )
                    )
                    case_idx += 1

        self._test_cases.extend(test_cases)
        self._total_generated += len(test_cases)
        return test_cases

    def _min_value(self, type_str: str) -> Any:
        """Get minimum value for a type."""
        if type_str in ("int", "integer", "int32", "int64"):
            return -2**31
        elif type_str in ("float", "float64"):
            return -1e308
        elif type_str in ("str", "string"):
            return ""
        elif type_str in ("bool", "boolean"):
            return False
        elif type_str in ("list", "array"):
            return []
        elif type_str in ("dict", "map"):
            return {}
        return None

    def _max_value(self, type_str: str) -> Any:
        """Get maximum value for a type."""
        if type_str in ("int", "integer", "int32", "int64"):
            return 2**31 - 1
        elif type_str in ("float", "float64"):
            return 1e308
        elif type_str in ("str", "string"):
            return "a" * 100
        elif type_str in ("bool", "boolean"):
            return True
        elif type_str in ("list", "array"):
            return [1]
        elif type_str in ("dict", "map"):
            return {"a": 1}
        return None

    def _overflow_value(self, type_str: str) -> Any:
        """Get overflow value for a type."""
        if type_str in ("int", "integer", "int32", "int64"):
            return 2**63
        elif type_str in ("float", "float64"):
            return float("inf")
        return None

    def get_test_cases(self) -> List[BoundaryTestCase]:
        """Get all generated test cases.

        Returns:
            List of BoundaryTestCase.
        """
        return list(self._test_cases)

    def get_stats(self) -> Dict[str, Any]:
        """Get generation statistics.

        Returns:
            Dictionary with generation stats.
        """
        type_counts: Dict[str, int] = collections.Counter(tc.boundary_type for tc in self._test_cases)
        return {
            "total_generated": self._total_generated,
            "total_test_cases": len(self._test_cases),
            "type_counts": dict(type_counts),
        }


# =============================================================================
# Contract Harvester
# =============================================================================


@dataclass
class Contract:
    """A harvested contract.

    Attributes:
        name: Contract name.
        precondition: Pre-condition expression.
        postcondition: Post-condition expression.
        invariants: List of invariants.
        location: Source location.
    """

    name: str
    precondition: str = ""
    postcondition: str = ""
    invariants: List[str] = field(default_factory=list)
    location: Optional[Tuple[int, int]] = None

    def __repr__(self) -> str:
        return (
            f"Contract(name={self.name!r}, pre={self.precondition!r}, "
            f"post={self.postcondition!r})"
        )


@dataclass
class ContractHarvestResult:
    """Result of contract harvesting.

    Attributes:
        contracts: List of harvested contracts.
        summary: Summary statistics.
    """

    contracts: List[Contract] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"ContractHarvestResult(contracts={len(self.contracts)}, "
            f"summary={self.summary})"
        )


class ContractHarvester:
    """Harvests contracts from code.

    Contracts include:
    - Preconditions (input constraints)
    - Postconditions (output guarantees)
    - Invariants (loop/function invariants)
    """

    def __init__(self) -> None:
        self._harvests: List[ContractHarvestResult] = []
        self._total_contracts: int = 0

    def harvest(
        self,
        tree: ast.Module,
        contract_type: Optional[str] = None,
    ) -> List[dict]:
        """Harvest contracts from the AST.

        Args:
            tree: The AST module to harvest from.
            contract_type: Optional filter for contract type
                ("pre" for preconditions, "post" for postconditions, or None for all).

        Returns:
            List of contract dictionaries with keys: function, precondition, postcondition, invariants.
        """
        contracts: List[dict] = []

        # Harvest function contracts
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_contract = self._harvest_function_contract(node)
                contract_dict: dict = {
                    "function": node.name,
                    "precondition": func_contract.precondition,
                    "postcondition": func_contract.postcondition,
                    "invariants": [],
                }
                # Filter by contract_type if specified
                if contract_type is None or contract_type in ("pre", "all"):
                    contracts.append(contract_dict)

        # Harvest class contracts
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_contract = self._harvest_class_contract(node)
                contract_dict: dict = {
                    "function": node.name,
                    "precondition": class_contract.precondition,
                    "postcondition": class_contract.postcondition,
                    "invariants": [],
                }
                if contract_type is None or contract_type in ("pre", "all"):
                    contracts.append(contract_dict)

        # Harvest invariants from function nodes
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                invariants = self._harvest_function_invariants(node)
                for iv in invariants:
                    contracts[-1]["invariants"].append(iv.expression)

        # Harvest invariants from class nodes
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                invariants = self._harvest_class_invariants(node)
                for iv in invariants:
                    contracts[-1]["invariants"].append(iv.expression)

        self._harvests.append(
            ContractHarvestResult(
                contracts=contracts,
                summary={
                    "total_contracts": len(contracts),
                    "total_preconditions": sum(len(c["precondition"]) for c in contracts),
                    "total_postconditions": sum(len(c["postcondition"]) for c in contracts),
                },
            )
        )
        self._total_contracts += len(contracts)

        return contracts

    def _harvest_function_contract(
        self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef]
    ) -> Contract:
        """Harvest contract from a function node."""
        name = node.name
        preconditions = []
        postconditions = []

        # Extract docstring as precondition (Python 3.12+: body[0].value)
        docstring = None
        if len(node.body) > 0 and isinstance(node.body[0], ast.Expr):
            docstring = node.body[0].value.value if isinstance(node.body[0].value, ast.Constant) else str(node.body[0].value)
        if docstring:
            preconditions.append(docstring.strip())

        # Extract return annotation as postcondition
        if node.returns:
            ret_str = astunparse(node.returns) if hasattr(node.returns, 'id') else str(node.returns)
            postconditions.append(f"returns {ret_str}")

        return Contract(
            name=name,
            precondition=" and ".join(preconditions) if preconditions else "",
            postcondition=" and ".join(postconditions) if postconditions else "",
            location=(node.lineno, node.col_offset),
        )

    def _harvest_function_invariants(self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> List[Dict[str, Any]]:
        """Harvest invariants from a function node.

        Args:
            node: Function definition node.

        Returns:
            List of invariant dictionaries with expression and description.
        """
        invariants: List[Dict[str, Any]] = []

        # Check for @property decorator
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Name) and decorator.id == "property":
                invariants.append({
                    "expression": f"{node.name} is a property",
                    "description": f"{node.name} is declared as a property",
                })

        # Check for @abstractmethod decorator
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Name) and decorator.id == "abstractmethod":
                invariants.append({
                    "expression": f"{node.name} is abstract",
                    "description": f"{node.name} is declared as abstract method",
                })

        # Check for @abstractmethod decorator with base class
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Attribute) and decorator.attr == "abstractmethod":
                invariants.append({
                    "expression": f"{node.name} is abstract",
                    "description": f"{node.name} is declared as abstract method",
                })

        return invariants

    def _harvest_class_invariants(self, node: ast.ClassDef) -> List[Dict[str, Any]]:
        """Harvest invariants from a class node.

        Args:
            node: Class definition node.

        Returns:
            List of invariant dictionaries with expression and description.
        """
        invariants: List[Dict[str, Any]] = []

        # Check for @abstractmethod decorator in __init__
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "__init__":
                for decorator in item.decorator_list:
                    if isinstance(decorator, ast.Name) and decorator.id == "abstractmethod":
                        invariants.append({
                            "expression": f"__init__ is abstract",
                            "description": f"__init__ is declared as abstract method",
                        })

        return invariants

    def _harvest_class_contract(self, node: ast.ClassDef) -> Contract:
        """Harvest contract from a class node."""
        name = node.name
        preconditions = []
        postconditions = []

        # Extract class docstring (Python 3.12+: body[0].value)
        docstring = None
        if len(node.body) > 0 and isinstance(node.body[0], ast.Expr):
            docstring = node.body[0].value.value if isinstance(node.body[0].value, ast.Constant) else str(node.body[0].value)
        if docstring:
            preconditions.append(docstring.strip())

        # Extract __init__ return type
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "__init__":
                if item.returns:
                    ret_str = astunparse(item.returns) if hasattr(item.returns, 'id') else str(item.returns)
                    postconditions.append(f"__init__ returns {ret_str}")

        return Contract(
            name=name,
            precondition=" and ".join(preconditions) if preconditions else "",
            postcondition=" and ".join(postconditions) if postconditions else "",
            location=(node.lineno, node.col_offset),
        )

    def get_harvests(self) -> List[ContractHarvestResult]:
        """Get all harvest results.

        Returns:
            List of ContractHarvestResult.
        """
        return list(self._harvests)

    def get_stats(self) -> Dict[str, Any]:
        """Get harvest statistics.

        Returns:
            Dictionary with harvest stats.
        """
        return {
            "total_contracts": self._total_contracts,
            "num_harvests": len(self._harvests),
        }


# =============================================================================
# Concolic Engine (Main Class)
# =============================================================================


class ConcolicEngine:
    """Concolic testing engine.

    Integrates backward slicing, invariant harvesting, boundary testing,
    and contract harvesting into a unified concolic testing pipeline.

    Usage:
        engine = ConcolicEngine()
        result = engine.analyze(file_path)
        report = engine.get_report()
    """

    def __init__(
        self,
        gas_limit: int = 1_000_000,
        max_slice_depth: int = 10,
        max_test_cases: int = 10,
    ) -> None:
        """Initialize concolic engine.

        Args:
            gas_limit: Gas limit for execution.
            max_slice_depth: Maximum depth for backward slicing.
            max_test_cases: Maximum boundary test cases per function.
        """
        from src.core.resilience_supervisor import GasMeter

        self.gas_meter = GasMeter(limit=gas_limit)
        self.max_slice_depth = max_slice_depth
        self.max_test_cases = max_test_cases
        self.coverage_map: Dict[str, int] = {}
        self.execution_paths: list = []

        # Sub-components
        self._slicer = BackwardSlicer()
        self._harvester = InvariantHarvester()
        self._boundary_tester = BoundaryTester()
        self._contract_harvester = ContractHarvester()

        # State
        self._analyzed_files: List[str] = []
        self._total_paths_explored: int = 0

    def analyze(self, file_path: str) -> Dict[str, Any]:
        """Analyze a file through the concolic pipeline.

        Args:
            file_path: Path to the Python file to analyze.

        Returns:
            Dictionary with analysis results.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        self.gas_meter.consume(100)

        source = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)

        self._analyzed_files.append(str(file_path))

        # Step 1: Backward slicing
        self._slice(tree)

        # Step 2: Invariant harvesting
        self._harvest_invariants(tree)

        # Step 3: Boundary testing
        self._generate_boundaries(tree)

        # Step 4: Contract harvesting
        self._harvest_contracts(tree)

    def analyze(self, file_path: str) -> Dict[str, Any]:
        """Analyze a file through the concolic pipeline.

        Args:
            file_path: Path to the Python file to analyze.

        Returns:
            Dictionary with analysis results.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        self.gas_meter.consume(100)

        source = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)

        self._analyzed_files.append(str(file_path))

        # Step 1: Backward slicing
        self._slice(tree)

        # Step 2: Invariant harvesting
        self._harvest_invariants(tree)

        # Step 3: Boundary testing
        self._generate_boundaries(tree)

        # Step 4: Contract harvesting
        self._harvest_contracts(tree)

        self.gas_meter.consume(50)

        return {
            "file": str(file_path),
            "paths_explored": self._total_paths_explored,
            "invariants": len(self._harvester.get_harvests()),
            "contracts": len(self._contract_harvester.get_harvests()),
            "boundary_cases": len(self._boundary_tester.get_test_cases()),
            "coverage": self.coverage_map,
        }

    def analyze_type(self, file_path: str) -> Dict[str, Any]:
        """Analyze type information from a file.

        Args:
            file_path: Path to the Python file to analyze.

        Returns:
            Dictionary with type analysis results.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        self.gas_meter.consume(50)

        source = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)

        # Collect type information
        type_info: Dict[str, Any] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                type_info[node.name] = {
                    "params": [],
                    "returns": None,
                }
                for arg in node.args.args:
                    if arg.annotation:
                        try:
                            type_info[node.name]["params"].append(
                                astunparse(arg.annotation)
                            )
                        except Exception:
                            type_info[node.name]["params"].append("any")
                if node.returns:
                    try:
                        type_info[node.name]["returns"] = astunparse(node.returns)
                    except Exception:
                        type_info[node.name]["returns"] = "any"

        self.gas_meter.consume(25)

        return {
            "file": str(file_path),
            "types": type_info,
            "total_functions": len(type_info),
        }

    def analyze_type(
        self,
        type_str: Optional[str] = None,
        constraints: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Analyze type information from type string and constraints.

        Args:
            type_str: Type string to analyze (e.g., "TypeVar[T]").
            constraints: Optional type constraints dictionary.

        Returns:
            Dictionary with type analysis results.
        """
        self.gas_meter.consume(50)

        result: Dict[str, Any] = {
            "type_str": type_str or "",
            "constraints": constraints or {},
            "parsed": False,
            "error": None,
        }

        # Simple type parsing for demonstration
        if type_str and "TypeVar" in type_str:
            result["parsed"] = True
            result["parsed_type"] = "TypeVar"
            if constraints:
                for var, bound in constraints.items():
                    result["parsed_type"] += f"[{var}:{bound}]"

        self.gas_meter.consume(25)

        return result

    def _slice(self, tree: ast.Module) -> None:
        """Perform backward slicing on the AST."""
        # Find function definitions as focus points
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                try:
                    self.gas_meter.consume(10)
                    self._slicer.slice(tree, node, self.max_slice_depth)
                except SlicingError:
                    pass

    def _harvest_invariants(self, tree: ast.Module) -> None:
        """Harvest invariants from the AST."""
        try:
            self.gas_meter.consume(50)
            self._harvester.harvest(tree)
        except InvariantExtractionError:
            pass

    def _generate_boundaries(self, tree: ast.Module) -> None:
        """Generate boundary test cases."""
        # Find functions and generate boundary cases
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                param_types = []
                for arg in node.args.args:
                    if arg.annotation:
                        param_types.append(str(arg.annotation))
                    else:
                        param_types.append("unknown")

                if param_types:
                    try:
                        self.gas_meter.consume(20)
                        self._boundary_tester.generate(
                            node.name, param_types, self.max_test_cases
                        )
                    except BoundaryGenerationError:
                        pass

    def _harvest_contracts(self, tree: ast.Module) -> None:
        """Harvest contracts from the AST."""
        try:
            self.gas_meter.consume(50)
            self._contract_harvester.harvest(tree)
        except Exception:
            pass

    def get_slicer_stats(self) -> Dict[str, Any]:
        """Get backward slicer statistics.

        Returns:
            Dictionary with slicer stats.
        """
        return self._slicer.get_stats()

    def get_invariant_stats(self) -> Dict[str, Any]:
        """Get invariant harvester statistics.

        Returns:
            Dictionary with harvester stats.
        """
        return self._harvester.get_stats()

    def get_boundary_stats(self) -> Dict[str, Any]:
        """Get boundary tester statistics.

        Returns:
            Dictionary with tester stats.
        """
        return self._boundary_tester.get_stats()

    def get_contract_stats(self) -> Dict[str, Any]:
        """Get contract harvester statistics.

        Returns:
            Dictionary with harvester stats.
        """
        return self._contract_harvester.get_stats()

    def get_report(self) -> Dict[str, Any]:
        """Get a comprehensive report.

        Returns:
            Dictionary with the full concolic analysis report.
        """
        return {
            "analyzed_files": self._analyzed_files,
            "total_paths_explored": self._total_paths_explored,
            "slicer": self.get_slicer_stats(),
            "invariants": self.get_invariant_stats(),
            "boundaries": self.get_boundary_stats(),
            "contracts": self.get_contract_stats(),
            "coverage": self.coverage_map,
        }


# =============================================================================
# Helper: astunparse (avoid external dependency)
# =============================================================================


def astunparse(node: ast.AST) -> str:
    """Convert an AST node to a string representation.

    Args:
        node: The AST node to convert.

    Returns:
        String representation of the node.
    """
    if isinstance(node, ast.Constant):
        return repr(node.value)
    elif isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        return f"{astunparse(node.value)}.{node.attr}"
    elif isinstance(node, ast.BinOp):
        op = type(node.op).__name__
        return f"{astunparse(node.left)} {op} {astunparse(node.right)}"
    elif isinstance(node, ast.Compare):
        parts = []
        for left, op, right in zip(node.left, node.ops, node.comparators):
            parts.append(f"{astunparse(left)} {type(op).__name__} {astunparse(right)}")
        return " and ".join(parts)
    elif isinstance(node, ast.Call):
        func = astunparse(node.func)
        args = ", ".join(astunparse(a) for a in node.args)
        return f"{func}({args})"
    elif isinstance(node, ast.List):
        return "[" + ", ".join(astunparse(el) for el in node.elts) + "]"
    elif isinstance(node, ast.Dict):
        items = []
        for k, v in zip(node.keys, node.values):
            items.append(f"{astunparse(k)}: {astunparse(v)}")
        return "{" + ", ".join(items) + "}"
    elif isinstance(node, ast.Tuple):
        return "(" + ", ".join(astunparse(el) for el in node.elts) + ")"
    elif isinstance(node, ast.Subscript):
        return f"{astunparse(node.value)}[{astunparse(node.slice)}]"
    elif isinstance(node, ast.IfExp):
        return f"{astunparse(node.body)} if {astunparse(node.test)} else {astunparse(node.orelse)}"
    else:
        return f"<{type(node).__name__}>"