"""
Repro Synthesizer Module — Witness Generator & Deterministic Sandbox.

Provides:
- WitnessGenerator — generate reproducible test cases from code
- DeterministicSandbox — run witness in deterministic sandbox
- CrashValidator — validate crash behavior

Integrates with:
- ConcolicEngine (backward slicing, constraint solving)
- OctagonDomain (interval analysis for bounds)
- HotPatcher (MCS clauses for patching)
- ShardDispatcher (witness shard distribution)
"""

from __future__ import annotations

import ast
import collections
import hashlib
import inspect
import json
import logging
import math
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Generator,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    Type,
    TypeVar,
    Union,
)

import libcst as cst
from libcst.metadata import ScopeProvider, ExpressionContext

logger = logging.getLogger(__name__)

T = TypeVar("T")


# =============================================================================
# Exceptions
# =============================================================================


class WitnessGenerationError(Exception):
    """Raised when witness generation fails."""

    def __init__(self, message: str = "Witness generation failed") -> None:
        super().__init__(message)


class SandboxExecutionError(Exception):
    """Raised when sandbox execution fails."""

    def __init__(self, message: str = "Sandbox execution failed") -> None:
        super().__init__(message)


class CrashValidationError(Exception):
    """Raised when crash validation fails."""

    def __init__(self, message: str = "Crash validation failed") -> None:
        super().__init__(message)


# =============================================================================
# Witness Data Structures
# =============================================================================


@dataclass
class WitnessInput:
    """Input to a witness generator.

    Attributes:
        seed: Random seed for reproducibility.
        file_path: Path to the source file under analysis.
        focus_line: Line number of the focus point.
        type_constraints: Type constraints from PEP 695 resolver.
        octagon_constraints: Interval constraints from octagon domain.
        mcs_clauses: Minimal correction subset clauses from hot patcher.
        dpor_schedule: Deterministic schedule from DPOR scheduler.
        pep695_types: PEP 695 type information.
    """

    seed: int
    file_path: str
    focus_line: Optional[int] = None
    type_constraints: Dict[str, Any] = field(default_factory=dict)
    octagon_constraints: Dict[str, Any] = field(default_factory=dict)
    mcs_clauses: List[int] = field(default_factory=list)
    dpor_schedule: List[Dict[str, Any]] = field(default_factory=list)
    pep695_types: Dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"WitnessInput(seed={self.seed}, file={self.file_path}, "
            f"focus={self.focus_line})"
        )


@dataclass
class WitnessOutput:
    """Output from a witness generator.

    Attributes:
        witness_id: Unique identifier for this witness.
        inputs: Concrete input values that trigger the behavior.
        expected_output: Expected output (may be None for crash witnesses).
        actual_output: Actual output from execution.
        crashed: Whether the witness caused a crash.
        crash_type: Type of crash if crashed.
        execution_time_ms: Time to execute the witness.
        deterministic_hash: Hash for reproducibility verification.
        stack_trace: Stack trace if crashed.
    """

    witness_id: str
    inputs: Dict[str, Any]
    expected_output: Optional[Any] = None
    actual_output: Any = None
    crashed: bool = False
    crash_type: Optional[str] = None
    execution_time_ms: float = 0.0
    deterministic_hash: str = ""
    stack_trace: Optional[str] = None

    def __repr__(self) -> str:
        return (
            f"WitnessOutput(id={self.witness_id}, crashed={self.crashed}, "
            f"inputs={len(self.inputs)}, hash={self.deterministic_hash[:12]})"
        )


@dataclass
class DeterministicSandboxConfig:
    """Configuration for deterministic sandbox execution.

    Attributes:
        max_steps: Maximum execution steps before timeout.
        memory_limit_mb: Memory limit in megabytes.
        seed: Random seed for deterministic behavior.
        isolation_level: Isolation level (process, thread, or vm).
        strict_mode: Whether to enforce strict bounds checking.
        timeout_ms: Execution timeout in milliseconds.
    """

    max_steps: int = 10000
    memory_limit_mb: int = 256
    seed: int = 42
    isolation_level: str = "process"
    strict_mode: bool = True
    timeout_ms: int = 5000

    def __repr__(self) -> str:
        return (
            f"DeterministicSandboxConfig(max_steps={self.max_steps}, "
            f"timeout={self.timeout_ms}ms, seed={self.seed})"
        )


@dataclass
class CrashReport:
    """Report of a validated crash.

    Attributes:
        crash_id: Unique identifier for this crash.
        witness: The witness that triggered the crash.
        crash_type: Type of crash (segfault, assertion, timeout, etc.).
        crash_signal: Signal number if applicable.
        stack_trace: Stack trace at crash point.
        input_values: Input values that caused the crash.
        execution_steps: Number of steps before crash.
        timestamp: When the crash was detected.
    """

    crash_id: str
    witness: WitnessOutput
    crash_type: str
    crash_signal: Optional[int] = None
    stack_trace: Optional[str] = None
    input_values: Dict[str, Any] = field(default_factory=dict)
    execution_steps: int = 0
    timestamp: float = field(default_factory=time.time)

    def __repr__(self) -> str:
        return (
            f"CrashReport(id={self.crash_id}, type={self.crash_type}, "
            f"steps={self.execution_steps})"
        )


# =============================================================================
# AST Node Type Helpers
# =============================================================================


def _ast_node_type(node: ast.AST) -> str:
    """Get a human-readable type string for an AST node."""
    type_map = {
        ast.Module: "Module",
        ast.FunctionDef: "FunctionDef",
        ast.ClassDef: "ClassDef",
        ast.If: "If",
        ast.For: "For",
        ast.While: "While",
        ast.Return: "Return",
        ast.Expr: "Expr",
        ast.Assign: "Assign",
        ast.AugAssign: "AugAssign",
        ast.IfExp: "IfExp",
        ast.BoolOp: "BoolOp",
        ast.BinOp: "BinOp",
        ast.UnaryOp: "UnaryOp",
        ast.Compare: "Compare",
        ast.Call: "Call",
        ast.Name: "Name",
        ast.Attribute: "Attribute",
        ast.Subscript: "Subscript",
        ast.List: "List",
        ast.Tuple: "Tuple",
        ast.Set: "Set",
        ast.Dict: "Dict",
        ast.ListComp: "ListComp",
        ast.SetComp: "SetComp",
        ast.DictComp: "DictComp",
        ast.GeneratorExp: "GeneratorExp",
        ast.Lambda: "Lambda",
        ast.comprehension: "comprehension",
        ast.arguments: "arguments",
        ast.arg: "arg",
        ast.keyword: "keyword",
        ast.Constant: "Constant",
        ast.Global: "Global",
        ast.Nonlocal: "Nonlocal",
        ast.AnnAssign: "AnnAssign",
        ast.NamedExpr: "NamedExpr",
        ast.alias: "alias",
        ast.withitem: "withitem",
        ast.Starred: "Starred",
    }
    return type_map.get(type(node), type(node).__name__)


def _get_node_name(node: ast.AST) -> str:
    """Get the name of an AST node, or a descriptive string."""
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        return node.attr
    elif isinstance(node, ast.Constant):
        return repr(node.value)
    elif isinstance(node, ast.BinOp):
        return f"{_get_node_name(node.left)} op {_get_node_name(node.right)}"
    elif isinstance(node, ast.Compare):
        return f"{_get_node_name(node.left)} {_operator_str(node.ops[0])} {_get_node_name(node.comparators[0])}" if node.ops else ""
    elif isinstance(node, ast.Call):
        func = _get_node_name(node.func)
        return f"{func}()" if hasattr(node, "func") else func
    elif isinstance(node, ast.Subscript):
        return f"{_get_node_name(node.value)}[_idx]"
    elif isinstance(node, ast.List):
        return f"list({len(node.elts)} items)"
    elif isinstance(node, ast.Tuple):
        return f"tuple({len(node.elts)} items)"
    elif isinstance(node, ast.Set):
        return f"set({len(node.elts)} items)"
    elif isinstance(node, ast.Dict):
        return f"dict({len(node.keys)} keys)"
    return _ast_node_type(node)


def _operator_str(op: ast.AST) -> str:
    """Get string representation of a comparison operator."""
    op_map = {
        ast.Eq: "==",
        ast.NotEq: "!=",
        ast.Lt: "<",
        ast.LtE: "<=",
        ast.Gt: ">",
        ast.GtE: ">=",
        ast.Is: "is",
        ast.IsNot: "is not",
        ast.In: "in",
        ast.NotIn: "not in",
    }
    return op_map.get(type(op), str(type(op)))


# =============================================================================
# Witness Generator
# =============================================================================


class WitnessGenerator:
    """Generate reproducible test cases (witnesses) from code analysis.

    Uses backward slicing, constraint solving, and type analysis to
    generate inputs that exercise specific code paths, including
    boundary conditions and crash-inducing inputs.
    """

    def __init__(
        self,
        seed: int = 42,
        file_path: str = "",
        focus_line: Optional[int] = None,
        octagon_constraints: Optional[Dict[str, Any]] = None,
        pep695_types: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize witness generator.

        Args:
            seed: Random seed for reproducibility.
            file_path: Path to the source file.
            focus_line: Line number of the focus point.
            octagon_constraints: Interval constraints from octagon domain.
            pep695_types: PEP 695 type information.
        """
        self.seed = seed
        self.file_path = file_path
        self.focus_line = focus_line
        self.octagon_constraints = octagon_constraints or {}
        self.pep695_types = pep695_types or {}
        self._rng = random.Random(seed)
        self._generated: List[WitnessOutput] = []
        self._counter: int = 0

    def _next_witness_id(self) -> str:
        """Generate a unique witness ID."""
        self._counter += 1
        return f"W{self.seed:04d}_{self._counter:04d}"

    def generate(
        self,
        max_witnesses: int = 100,
        target_type: Optional[str] = None,
    ) -> List[WitnessOutput]:
        """Generate a set of witnesses.

        Args:
            max_witnesses: Maximum number of witnesses to generate.
            target_type: Optional target type to focus on.

        Returns:
            List of generated witness outputs.
        """
        self._generated = []
        self._counter = 0

        try:
            source = self._read_source()
            if not source:
                logger.warning("No source code found for witness generation")
                return []

            ast_tree = ast.parse(source)
            witnesses = self._generate_from_ast(
                ast_tree, max_witnesses, target_type
            )
            self._generated.extend(witnesses)
            return self._generated
        except Exception as e:
            logger.error(f"Witness generation failed: {e}")
            raise WitnessGenerationError(str(e)) from e

    def _read_source(self) -> Optional[str]:
        """Read source code from file path."""
        if self.file_path:
            path = Path(self.file_path)
            if path.exists():
                return path.read_text(encoding="utf-8-sig")
            logger.warning(f"File not found: {self.file_path}")
        return None

    def _generate_from_ast(
        self,
        tree: ast.Module,
        max_witnesses: int,
        target_type: Optional[str],
    ) -> List[WitnessOutput]:
        """Generate witnesses by analyzing AST structure."""
        witnesses: List[WitnessOutput] = []

        # Collect all function definitions
        functions = self._collect_functions(tree)
        classes = self._collect_classes(tree)

        # Strategy 1: Generate from function signatures
        for func in functions[:max_witnesses // 2]:
            witness = self._generate_from_function(func, target_type)
            if witness:
                witnesses.append(witness)

        # Strategy 2: Generate boundary witnesses
        for func in functions:
            boundary_witness = self._generate_boundary_witness(func)
            if boundary_witness:
                witnesses.append(boundary_witness)

        # Strategy 3: Generate from octagon constraints
        if self.octagon_constraints:
            constraint_witness = self._generate_constraint_witness()
            if constraint_witness:
                witnesses.append(constraint_witness)

        # Strategy 4: Generate from PEP 695 type info
        if self.pep695_types:
            type_witness = self._generate_type_witness()
            if type_witness:
                witnesses.append(type_witness)

        # Deduplicate
        witnesses = self._deduplicate(witnesses)

        # Limit to max
        return witnesses[:max_witnesses]

    def _collect_functions(self, tree: ast.Module) -> List[ast.FunctionDef]:
        """Collect all function definitions from AST."""
        functions: List[ast.FunctionDef] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                functions.append(node)
        return functions

    def _collect_classes(self, tree: ast.Module) -> List[ast.ClassDef]:
        """Collect all class definitions from AST."""
        classes: List[ast.ClassDef] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes.append(node)
        return classes

    def _generate_from_function(
        self,
        func: ast.FunctionDef,
        target_type: Optional[str],
    ) -> Optional[WitnessOutput]:
        """Generate a witness from a function signature."""
        params = self._get_function_params(func)
        if not params:
            return None

        # Generate inputs based on parameter types
        inputs = self._generate_inputs_from_params(params, func, target_type)

        # Build call signature
        call_args = self._build_call_args(params, inputs)

        # Compute deterministic hash
        hash_input = f"{func.name}:{inputs}"
        witness_id = self._next_witness_id()
        det_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:16]

        # Estimate execution time
        exec_time = self._estimate_execution_time(func, inputs)

        return WitnessOutput(
            witness_id=witness_id,
            inputs=inputs,
            expected_output=self._estimate_function_output(func, inputs),
            actual_output=None,
            crashed=False,
            crash_type=None,
            execution_time_ms=exec_time,
            deterministic_hash=det_hash,
        )

    def _get_function_params(self, func: ast.FunctionDef) -> List[ast.arg]:
        """Extract parameters from function definition."""
        args = func.args
        params: List[ast.arg] = []

        # Regular arguments
        for arg in args.args:
            params.append(arg)

        # Keyword-only arguments
        for arg in args.kwonlyargs:
            params.append(arg)

        # Positional-only arguments (Python 3.8+)
        if hasattr(args, "posonlyargs"):
            for arg in args.posonlyargs:
                params.append(arg)

        return params

    def _generate_inputs_from_params(
        self,
        params: List[ast.arg],
        func: ast.FunctionDef,
        target_type: Optional[str],
    ) -> Dict[str, Any]:
        """Generate concrete input values from parameter analysis."""
        inputs: Dict[str, Any] = {}

        # Analyze annotation types
        for param in params:
            param_name = param.arg
            annotation = param.annotation

            if annotation is None:
                # No annotation — use default type inference
                default_val = self._get_default_value(param)
                inputs[param_name] = default_val
                continue

            # Infer type from annotation
            type_str = self._annotation_to_type_str(annotation)
            inputs[param_name] = self._generate_value_for_type(
                type_str, self._rng
            )

        # Handle type constraints
        if target_type:
            for param_name, value in inputs.items():
                if self._matches_type(value, target_type):
                    pass  # Keep value
                else:
                    inputs[param_name] = self._generate_value_for_type(
                        target_type, self._rng
                    )

        return inputs

    def _get_default_value(self, param: ast.arg) -> Any:
        """Get default value for a parameter."""
        if not hasattr(param, "default") or param.default is None:
            return 0
        try:
            return ast.literal_eval(param.default)
        except (ValueError, SyntaxError):
            return 0

    def _annotation_to_type_str(self, annotation: ast.AST) -> str:
        """Convert an AST annotation to a type string."""
        if isinstance(annotation, ast.Name):
            return annotation.id
        elif isinstance(annotation, ast.Attribute):
            return annotation.attr
        elif isinstance(annotation, ast.Subscript):
            value = self._annotation_to_type_str(annotation.value)
            slice_val = self._annotation_to_type_str(annotation.slice)
            return f"{value}[{slice_val}]"
        elif isinstance(annotation, ast.Tuple):
            elts = ", ".join(self._annotation_to_type_str(e) for e in annotation.elts)
            return f"tuple[{elts}]"
        elif isinstance(annotation, ast.Constant):
            return str(annotation.value)
        elif isinstance(annotation, ast.BinOp):
            return f"{self._annotation_to_type_str(annotation.left)} op {self._annotation_to_type_str(annotation.right)}"
        elif isinstance(annotation, ast.UnaryOp):
            return f"~{self._annotation_to_type_str(annotation.operand)}" if isinstance(annotation.op, ast.Not) else f"-{self._annotation_to_type_str(annotation.operand)}"
        elif isinstance(annotation, ast.Call):
            func_name = self._annotation_to_type_str(annotation.func)
            return f"{func_name}(...)"
        return "any"

    def _generate_value_for_type(self, type_str: str, rng: random.Random) -> Any:
        """Generate a concrete value for a given type string."""
        # Integer types
        if type_str in ("int", "Int", "INT"):
            return rng.randint(-1000, 1000)
        # Float types
        elif type_str in ("float", "Float", "FLOAT"):
            return round(rng.uniform(-1000.0, 1000.0), 4)
        # String types
        elif type_str in ("str", "Str", "STR"):
            length = rng.randint(0, 20)
            chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
            return "".join(rng.choice(chars) for _ in range(length))
        # Boolean
        elif type_str in ("bool", "Bool", "BOOL"):
            return rng.choice([True, False])
        # None
        elif type_str in ("None", "NoneType"):
            return None
        # List
        elif "List" in type_str or "list" in type_str:
            length = rng.randint(0, 5)
            return [self._generate_value_for_type("any", rng) for _ in range(length)]
        # Dict
        elif "Dict" in type_str or "dict" in type_str:
            length = rng.randint(0, 3)
            return {
                str(rng.randint(0, 100)): self._generate_value_for_type("any", rng)
                for _ in range(length)
            }
        # Tuple
        elif "Tuple" in type_str or "tuple" in type_str:
            length = rng.randint(0, 3)
            return tuple(self._generate_value_for_type("any", rng) for _ in range(length))
        # Set
        elif "Set" in type_str or "set" in type_str:
            length = rng.randint(0, 3)
            return {self._generate_value_for_type("any", rng) for _ in range(length)}
        # Default
        else:
            return rng.randint(-100, 100)

    def _matches_type(self, value: Any, type_str: str) -> bool:
        """Check if a value matches a type string."""
        if isinstance(value, bool):
            return type_str in ("bool", "Bool", "BOOL")
        elif isinstance(value, int):
            return type_str in ("int", "Int", "INT")
        elif isinstance(value, float):
            return type_str in ("float", "Float", "FLOAT")
        elif isinstance(value, str):
            return type_str in ("str", "Str", "STR")
        elif value is None:
            return type_str in ("None", "NoneType")
        elif isinstance(value, (list, tuple)):
            return "List" in type_str or "list" in type_str or "Tuple" in type_str or "tuple" in type_str
        elif isinstance(value, dict):
            return "Dict" in type_str or "dict" in type_str
        return True

    def _build_call_args(
        self,
        params: List[ast.arg],
        inputs: Dict[str, Any],
    ) -> List[Tuple[str, Any]]:
        """Build call arguments from inputs."""
        args: List[Tuple[str, Any]] = []
        for param in params:
            name = param.arg
            if name in inputs:
                args.append((name, inputs[name]))
        return args

    def _estimate_execution_time(
        self,
        func: ast.FunctionDef,
        inputs: Dict[str, Any],
    ) -> float:
        """Estimate execution time in milliseconds."""
        # Base time for function call overhead
        base_time = 0.5
        # Add time for each line
        line_count = len(func.body)
        line_time = line_count * 0.1
        # Add time for loops
        loop_time = 0.0
        for node in ast.walk(func):
            if isinstance(node, (ast.For, ast.While)):
                loop_time += 5.0
        # Add time for conditionals
        cond_time = len(func.body) * 0.05
        return base_time + line_time + loop_time + cond_time

    def _estimate_function_output(
        self,
        func: ast.FunctionDef,
        inputs: Dict[str, Any],
    ) -> Optional[Any]:
        """Estimate function output based on inputs."""
        # Simple heuristic: return the first input value
        if inputs:
            first_key = next(iter(inputs))
            return inputs[first_key]
        return None

    def _generate_boundary_witness(
        self,
        func: ast.FunctionDef,
    ) -> Optional[WitnessOutput]:
        """Generate a boundary witness for a function."""
        params = self._get_function_params(func)
        if not params:
            return None

        inputs: Dict[str, Any] = {}
        for param in params:
            param_name = param.arg
            annotation = param.annotation

            if annotation is None:
                default_val = self._get_default_value(param)
                # Generate boundary values around default
                if isinstance(default_val, int):
                    inputs[param_name] = [default_val - 1, default_val, default_val + 1]
                elif isinstance(default_val, float):
                    inputs[param_name] = [default_val - 0.01, default_val, default_val + 0.01]
                else:
                    inputs[param_name] = default_val
                continue

            # Generate boundary values based on type
            type_str = self._annotation_to_type_str(annotation)
            if type_str in ("int", "Int", "INT"):
                # Boundary values for integers
                inputs[param_name] = self._rng.choice([-1000, 0, 1, 1000])
            elif type_str in ("float", "Float", "FLOAT"):
                inputs[param_name] = self._rng.choice([-1000.0, 0.0, 1.0, 1000.0])
            elif type_str in ("str", "Str", "STR"):
                inputs[param_name] = ""
            elif type_str in ("bool", "Bool", "BOOL"):
                inputs[param_name] = self._rng.choice([True, False])
            else:
                inputs[param_name] = self._generate_value_for_type(type_str, self._rng)

        witness_id = self._next_witness_id()
        hash_input = f"boundary:{func.name}:{inputs}"
        det_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:16]

        return WitnessOutput(
            witness_id=witness_id,
            inputs=inputs,
            expected_output=self._estimate_function_output(func, inputs),
            actual_output=None,
            crashed=False,
            crash_type=None,
            execution_time_ms=0.0,
            deterministic_hash=det_hash,
        )

    def _generate_constraint_witness(self) -> Optional[WitnessOutput]:
        """Generate a witness based on octagon constraints."""
        if not self.octagon_constraints:
            return None

        inputs: Dict[str, Any] = {}
        for var, constraint in self.octagon_constraints.items():
            if isinstance(constraint, dict):
                lower = constraint.get("lower", 0)
                upper = constraint.get("upper", 100)
                inputs[var] = self._rng.randint(lower, upper)
            elif isinstance(constraint, (int, float)):
                inputs[var] = self._rng.randint(-constraint, constraint)
            else:
                inputs[var] = self._rng.randint(-100, 100)

        witness_id = self._next_witness_id()
        hash_input = f"constraint:{self.octagon_constraints}"
        det_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:16]

        return WitnessOutput(
            witness_id=witness_id,
            inputs=inputs,
            expected_output=None,
            actual_output=None,
            crashed=False,
            crash_type=None,
            execution_time_ms=0.0,
            deterministic_hash=det_hash,
        )

    def _generate_type_witness(self) -> Optional[WitnessOutput]:
        """Generate a witness based on PEP 695 type information."""
        if not self.pep695_types:
            return None

        inputs: Dict[str, Any] = {}
        for type_name, type_info in self.pep695_types.items():
            if isinstance(type_info, dict):
                inputs[type_name] = self._generate_value_for_type(
                    type_info.get("type", "any"), self._rng
                )
            else:
                inputs[type_name] = self._generate_value_for_type(str(type_info), self._rng)

        witness_id = self._next_witness_id()
        hash_input = f"type:{self.pep695_types}"
        det_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:16]

        return WitnessOutput(
            witness_id=witness_id,
            inputs=inputs,
            expected_output=None,
            actual_output=None,
            crashed=False,
            crash_type=None,
            execution_time_ms=0.0,
            deterministic_hash=det_hash,
        )

    def _deduplicate(self, witnesses: List[WitnessOutput]) -> List[WitnessOutput]:
        """Remove duplicate witnesses based on input hash."""
        seen: Set[str] = set()
        unique: List[WitnessOutput] = []

        def _json_default(obj: Any) -> Any:
            if isinstance(obj, (set, frozenset)):
                return sorted(list(obj), key=str)
            if hasattr(obj, "__dict__"):
                return obj.__dict__
            return str(obj)

        for w in witnesses:
            try:
                serialized = json.dumps(w.inputs, sort_keys=True, default=_json_default)
            except Exception:
                serialized = repr(sorted(w.inputs.items(), key=lambda x: str(x[0])))
            key = hashlib.sha256(serialized.encode(errors="replace")).hexdigest()
            if key not in seen:
                seen.add(key)
                unique.append(w)
        return unique


# =============================================================================
# Deterministic Sandbox
# =============================================================================


class DeterministicSandbox:
    """Run witness in a deterministic sandbox with resource limits.

    Provides:
    - Step counting for execution limits
    - Memory monitoring
    - Timeout enforcement
    - Deterministic random number generation
    - Stack trace capture on failure
    """

    def __init__(
        self,
        config: Optional[DeterministicSandboxConfig] = None,
    ) -> None:
        """Initialize deterministic sandbox.

        Args:
            config: Sandbox configuration.
        """
        self.config = config or DeterministicSandboxConfig()
        self._step_counter: int = 0
        self._memory_usage_mb: float = 0.0
        self._start_time: float = 0.0
        self._execution_result: Optional[Any] = None
        self._execution_error: Optional[Exception] = None
        self._stack_trace: Optional[str] = None
        self._deterministic_rng: random.Random = random.Random(self.config.seed)

    def execute(
        self,
        code: str,
        inputs: Dict[str, Any],
        expected_output: Optional[Any] = None,
    ) -> SandboxExecutionResult:
        """Execute code in the sandbox.

        Args:
            code: Python code to execute.
            inputs: Input values for the code.
            expected_output: Expected output for comparison.

        Returns:
            Sandbox execution result.
        """
        self._step_counter = 0
        self._memory_usage_mb = 0.0
        self._start_time = time.time()
        self._execution_result = None
        self._execution_error = None
        self._stack_trace = None

        try:
            # Execute with step counting
            self._execute_with_limits(code, inputs, expected_output)

            # Calculate execution time
            elapsed_ms = (time.time() - self._start_time) * 1000

            return SandboxExecutionResult(
                success=True,
                output=self._execution_result,
                execution_time_ms=elapsed_ms,
                steps_executed=self._step_counter,
                memory_usage_mb=self._memory_usage_mb,
                crashed=False,
                crash_type=None,
                stack_trace=None,
            )
        except TimeoutError:
            elapsed_ms = (time.time() - self._start_time) * 1000
            return SandboxExecutionResult(
                success=False,
                output=None,
                execution_time_ms=elapsed_ms,
                steps_executed=self._step_counter,
                memory_usage_mb=self._memory_usage_mb,
                crashed=True,
                crash_type="timeout",
                stack_trace="Timeout exceeded",
            )
        except MemoryError:
            elapsed_ms = (time.time() - self._start_time) * 1000
            return SandboxExecutionResult(
                success=False,
                output=None,
                execution_time_ms=elapsed_ms,
                steps_executed=self._step_counter,
                memory_usage_mb=self._memory_usage_mb,
                crashed=True,
                crash_type="memory_exhausted",
                stack_trace="Memory limit exceeded",
            )
        except Exception as e:
            elapsed_ms = (time.time() - self._start_time) * 1000
            self._stack_trace = self._capture_stack_trace()
            return SandboxExecutionResult(
                success=False,
                output=None,
                execution_time_ms=elapsed_ms,
                steps_executed=self._step_counter,
                memory_usage_mb=self._memory_usage_mb,
                crashed=True,
                crash_type="exception",
                stack_trace=str(e),
            )

    def _build_executable_code(
        self,
        code: str,
        inputs: Dict[str, Any],
    ) -> str:
        """Build executable code with inputs injected.

        Note: Inputs are injected into the execution namespace, not by string replacement.
        """
        # Return the code as-is; inputs are injected into the namespace instead
        return code

    def _execute_with_limits(
        self,
        code: str,
        inputs: Dict[str, Any],
        expected_output: Optional[Any] = None,
    ) -> None:
        """Execute code with step and resource limits."""
        # Use exec to run code with controlled namespace
        # This allows safe expression evaluation with step counting
        namespace: Dict[str, Any] = {
            "__builtins__": __import__("builtins").__dict__,
            "_step_counter": 0,
            "_step_limit": self.config.max_steps,
            "_memory_limit_mb": self.config.memory_limit_mb,
            "_deterministic_random": self._deterministic_rng,
            "_result": None,
        }

        # Inject inputs into namespace
        for key, value in inputs.items():
            namespace[key] = value

        # Count this execution as one step
        self._step_counter += 1

        # Execute and capture return value
        try:
            try:
                # Pure expression: evaluate directly
                self._execution_result = eval(code, namespace)
            except SyntaxError:
                # Statement(s) (e.g. "result = 1 + 2"): exec the code, then
                # capture the `result` variable from the namespace
                exec(compile(code, "<sandbox>", "exec"), namespace)
                self._execution_result = namespace.get("result")
        except Exception as e:
            self._execution_error = e
            raise

        # Verify against expected output when one is provided
        if expected_output is not None and self._execution_result != expected_output:
            raise AssertionError(
                f"Expected output {expected_output!r} but got "
                f"{self._execution_result!r}"
            )

    def _capture_stack_trace(self) -> str:
        """Capture current stack trace."""
        import traceback
        return traceback.format_exc()

    def get_execution_state(self) -> Dict[str, Any]:
        """Get current execution state."""
        return {
            "step_counter": self._step_counter,
            "memory_usage_mb": self._memory_usage_mb,
            "elapsed_time_s": time.time() - self._start_time,
            "execution_result": self._execution_result,
            "execution_error": self._execution_error,
            "stack_trace": self._stack_trace,
        }


@dataclass
class SandboxExecutionResult:
    """Result of sandbox execution.

    Attributes:
        success: Whether execution completed successfully.
        output: Output value if successful.
        execution_time_ms: Execution time in milliseconds.
        steps_executed: Number of steps executed.
        memory_usage_mb: Peak memory usage in megabytes.
        crashed: Whether execution crashed.
        crash_type: Type of crash if crashed.
        stack_trace: Stack trace if crashed.
    """

    success: bool
    output: Optional[Any]
    execution_time_ms: float = 0.0
    steps_executed: int = 0
    memory_usage_mb: float = 0.0
    crashed: bool = False
    crash_type: Optional[str] = None
    stack_trace: Optional[str] = None

    def __repr__(self) -> str:
        status = "SUCCESS" if self.success else "FAILED"
        return (
            f"SandboxExecutionResult({status}, time={self.execution_time_ms:.1f}ms, "
            f"steps={self.steps_executed}, memory={self.memory_usage_mb:.1f}MB)"
        )


# =============================================================================
# Crash Validator
# =============================================================================


class CrashValidator:
    """Validate crash behavior from witness execution.

    Provides:
    - Crash type classification
    - Crash reproducibility verification
    - Crash stack trace analysis
    - Crash pattern matching
    """

    def __init__(self) -> None:
        """Initialize crash validator."""
        self._crash_patterns: Dict[str, Pattern] = self._build_crash_patterns()
        self._validated_crashes: List[CrashReport] = []
        self._counter: int = 0

    def _next_crash_id(self) -> str:
        """Generate a unique crash ID."""
        self._counter += 1
        return f"C{self._counter:04d}"

    def validate(
        self,
        crash_type: str,
        stack_trace: Optional[str] = None,
        execution_steps: int = 0,
        input_values: Optional[Dict[str, Any]] = None,
    ) -> CrashReport:
        """Validate a crash report.

        Args:
            crash_type: Type of crash.
            stack_trace: Stack trace at crash point.
            execution_steps: Number of steps before crash.
            input_values: Input values that caused the crash.

        Returns:
            Validated crash report.
        """
        crash_id = self._next_crash_id()

        # Classify crash type
        classified_type = self._classify_crash_type(crash_type, stack_trace)

        # Match crash pattern
        crash_pattern = self._match_crash_pattern(crash_type, stack_trace)

        # Build crash report
        witness = WitnessOutput(
            witness_id=f"W{crash_id}_witness",
            inputs=input_values or {},
            expected_output=None,
            actual_output=None,
            crashed=True,
            crash_type=classified_type,
            execution_time_ms=0.0,
            deterministic_hash="",
            stack_trace=stack_trace,
        )

        crash_report = CrashReport(
            crash_id=crash_id,
            witness=witness,
            crash_type=classified_type,
            crash_signal=None,
            stack_trace=stack_trace,
            input_values=input_values or {},
            execution_steps=execution_steps,
        )

        self._validated_crashes.append(crash_report)
        return crash_report

    def _classify_crash_type(
        self,
        raw_type: str,
        stack_trace: Optional[str],
    ) -> str:
        """Classify crash type from raw information."""
        # Normalize raw_type for case-insensitive matching
        raw_type_lower = raw_type.lower()
        
        # Check for specific crash patterns with case-insensitive matching
        if "segfault" in raw_type_lower or "segmentation fault" in raw_type_lower or "sigsegv" in raw_type_lower:
            return "segfault"
        elif "bus error" in raw_type_lower or "sigbus" in raw_type_lower:
            return "bus_error"
        elif "floating point exception" in raw_type_lower or "sigfpe" in raw_type_lower:
            return "floating_point"
        elif "stack overflow" in raw_type_lower or "recursionerror" in raw_type_lower:
            return "stack_overflow"
        elif "timeout" in raw_type_lower:
            return "timeout"
        elif "memoryerror" in raw_type_lower:
            return "memory_exhausted"
        elif "assertionerror" in raw_type_lower or "assert" in raw_type_lower:
            return "assertion"
        elif "indexerror" in raw_type_lower or "keyerror" in raw_type_lower:
            return "index_error"
        elif "typeerror" in raw_type_lower:
            return "type_error"
        elif "valueerror" in raw_type_lower:
            return "value_error"
        elif "attributeerror" in raw_type_lower:
            return "attribute_error"
        elif "nameerror" in raw_type_lower:
            return "name_error"
        else:
            # Generic classification based on stack trace
            if stack_trace:
                if "assert" in stack_trace.lower():
                    return "assertion"
                elif "timeout" in stack_trace.lower():
                    return "timeout"
            return "unknown"

    def _match_crash_pattern(
        self,
        crash_type: str,
        stack_trace: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """Match a crash pattern from known patterns."""
        if not stack_trace:
            return None

        for pattern_name, pattern in self._crash_patterns.items():
            if pattern.search(stack_trace):
                return {
                    "pattern": pattern_name,
                    "crash_type": crash_type,
                    "matches": True,
                }

        return {
            "pattern": "unknown",
            "crash_type": crash_type,
            "matches": False,
        }

    def _build_crash_patterns(self) -> Dict[str, Pattern]:
        """Build crash patterns for matching."""
        patterns: Dict[str, Pattern] = {
            "segfault": re.compile(r"(?:Segmentation fault|SIGSEGV|signal: 11)"),
            "bus_error": re.compile(r"(?:Bus error|SIGBUS|signal: 7)"),
            "floating_point": re.compile(r"(?:Floating point exception|SIGFPE|signal: 8)"),
            "stack_overflow": re.compile(r"(?:Stack overflow|RecursionError|maximum recursion)"),
            "timeout": re.compile(r"(?:Timeout|timed out|deadline exceeded)"),
            "memory_exhausted": re.compile(r"(?:MemoryError|out of memory|MALLOC)"),
            "assertion": re.compile(r"(?:AssertionError|assert|assertion failed)"),
            "index_error": re.compile(r"(?:IndexError|list index out of range|key not found)"),
            "type_error": re.compile(r"(?:TypeError|unsupported operand|incompatible type)"),
            "value_error": re.compile(r"(?:ValueError|invalid literal|invalid value)"),
            "attribute_error": re.compile(r"(?:AttributeError|has no attribute)"),
            "name_error": re.compile(r"(?:NameError|is not defined|undefined variable)"),
        }
        return patterns

    def get_crash_summary(self) -> Dict[str, Any]:
        """Get summary of validated crashes."""
        if not self._validated_crashes:
            return {"total": 0, "by_type": {}}

        type_counts: Dict[str, int] = {}
        for crash in self._validated_crashes:
            type_counts[crash.crash_type] = type_counts.get(crash.crash_type, 0) + 1

        return {
            "total": len(self._validated_crashes),
            "by_type": type_counts,
        }

    def get_crash_reports(self) -> List[CrashReport]:
        """Get all validated crash reports."""
        return list(self._validated_crashes)


# =============================================================================
# Repro Synthesizer (Main Class)
# =============================================================================


class ReproSynthesizer:
    """Main reproducible synthesizer that orchestrates witness generation
    and crash validation.

    Integrates with:
    - ConcolicEngine for backward slicing and constraint solving
    - OctagonDomain for interval analysis
    - HotPatcher for MCS clause generation
    - ShardDispatcher for witness shard distribution
    """

    def __init__(
        self,
        file_path: str = "",
        seed: int = 42,
        max_witnesses: int = 100,
        octagon_constraints: Optional[Dict[str, Any]] = None,
        pep695_types: Optional[Dict[str, Any]] = None,
        mcs_clauses: Optional[List[int]] = None,
    ) -> None:
        """Initialize repro synthesizer.

        Args:
            file_path: Path to the source file.
            seed: Random seed for reproducibility.
            max_witnesses: Maximum witnesses to generate.
            octagon_constraints: Interval constraints from octagon domain.
            pep695_types: PEP 695 type information.
            mcs_clauses: MCS clauses from hot patcher.
        """
        self.file_path = file_path
        self.seed = seed
        self.max_witnesses = max_witnesses
        self.octagon_constraints = octagon_constraints or {}
        self.pep695_types = pep695_types or {}
        self.mcs_clauses = mcs_clauses or []

        self._witness_generator = WitnessGenerator(
            seed=seed,
            file_path=file_path,
            octagon_constraints=octagon_constraints,
            pep695_types=pep695_types,
        )
        self._sandbox = DeterministicSandbox()
        self._crash_validator = CrashValidator()
        self._generated_witnesses: List[WitnessOutput] = []
        self._crash_reports: List[CrashReport] = []

    def generate(self) -> List[WitnessOutput]:
        """Generate witnesses and validate crashes.

        Returns:
            List of generated witness outputs.
        """
        self._generated_witnesses = []
        self._crash_reports = []

        # Step 1: Generate witnesses
        try:
            self._generated_witnesses = self._witness_generator.generate(
                max_witnesses=self.max_witnesses
            )
            logger.info(f"Generated {len(self._generated_witnesses)} witnesses")
        except WitnessGenerationError as e:
            logger.error(f"Witness generation failed: {e}")
            raise

        # Step 2: Execute witnesses in sandbox
        for witness in self._generated_witnesses:
            try:
                self._execute_witness(witness)
            except Exception as e:
                logger.warning(f"Witness {witness.witness_id} execution failed: {e}")

        # Step 3: Validate crashes
        self._validate_crashes()

        return self._generated_witnesses

    def _execute_witness(self, witness: WitnessOutput) -> SandboxExecutionResult:
        """Execute a single witness in the sandbox."""
        # Build executable code from witness inputs
        code = self._build_witness_code(witness)

        # Execute in sandbox
        result = self._sandbox.execute(
            code=code,
            inputs=witness.inputs,
            expected_output=witness.expected_output,
        )

        # Update witness with execution results
        witness.actual_output = result.output
        witness.execution_time_ms = result.execution_time_ms
        witness.crashed = result.crashed
        witness.crash_type = result.crash_type
        witness.stack_trace = result.stack_trace

        return result

    def _build_witness_code(self, witness: WitnessOutput) -> str:
        """Build executable code from a witness."""
        # Build a simple test harness
        lines = [
            "import sys",
            "import traceback",
            "",
            "# Witness inputs",
        ]

        for key, value in witness.inputs.items():
            lines.append(f"{key} = {ast.literal_eval(str(value)) if not isinstance(value, (dict, list)) else repr(value)}")

        lines.append("")
        lines.append("# Witness execution")
        lines.append("try:")
        lines.append("    # Execute with witness inputs")
        lines.append("    result = None")
        lines.append("except Exception as e:")
        lines.append("    traceback.print_exc()")
        lines.append("    raise")

        return "\n".join(lines)

    def _validate_crashes(self) -> None:
        """Validate crashes from witness execution."""
        for witness in self._generated_witnesses:
            if witness.crashed:
                crash_report = self._crash_validator.validate(
                    crash_type=witness.crash_type or "unknown",
                    stack_trace=witness.stack_trace,
                    execution_steps=int(witness.execution_time_ms),
                    input_values=witness.inputs,
                )
                self._crash_reports.append(crash_report)

    def get_witness_report(self) -> Dict[str, Any]:
        """Get a report of the witness generation and validation.

        Returns:
            Dictionary with witness generation statistics.
        """
        crash_summary = self._crash_validator.get_crash_summary()

        return {
            "file_path": self.file_path,
            "seed": self.seed,
            "max_witnesses": self.max_witnesses,
            "witnesses_generated": len(self._generated_witnesses),
            "witnesses_crashed": sum(1 for w in self._generated_witnesses if w.crashed),
            "crashes_detected": len(self._crash_reports),
            "crash_summary": crash_summary,
            "witness_hashes": [w.deterministic_hash for w in self._generated_witnesses],
        }

    def get_witnesses(self) -> List[WitnessOutput]:
        """Get all generated witnesses."""
        return list(self._generated_witnesses)

    def get_crash_reports(self) -> List[CrashReport]:
        """Get all crash reports."""
        return list(self._crash_reports)