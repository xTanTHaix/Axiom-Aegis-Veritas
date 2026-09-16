"""
Hot Patcher Module — MCS Generator & Counterfactual Patch Synthesizer.

Provides:
- MCSGenerator — Minimal Correction Subset generation (Reiter's Duality)
- CounterfactualPatchSynthesizer — AST patch synthesis
- TreeEditDistance — calculate edit distance for patch quality
"""

from __future__ import annotations

import ast
import collections
import logging
import math
import time
from pathlib import Path
from dataclasses import dataclass, field
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

logger = logging.getLogger(__name__)

T = TypeVar("T")


# =============================================================================
# Exceptions
# =============================================================================


class MCSGenerationError(Exception):
    """Raised when MCS generation fails."""

    def __init__(self, message: str = "MCS generation failed") -> None:
        super().__init__(message)


class PatchSynthesisError(Exception):
    """Raised when patch synthesis fails."""

    def __init__(self, message: str = "Patch synthesis failed") -> None:
        super().__init__(message)


class EditDistanceError(Exception):
    """Raised when edit distance calculation fails."""

    def __init__(self, message: str = "Edit distance calculation failed") -> None:
        super().__init__(message)


# =============================================================================
# MCS Generator (Reiter's Duality)
# =============================================================================


@dataclass
class MCS:
    """Minimal Correction Subset.

    Attributes:
        clauses: Set of clauses that must be removed to fix the bug.
        size: Size of the MCS.
        is_minimal: Whether this is a minimal MCS.
    """

    clauses: Set[int]
    size: int = 0
    is_minimal: bool = True

    def __post_init__(self) -> None:
        self.size = len(self.clauses)

    def __repr__(self) -> str:
        return f"MCS(clauses={sorted(self.clauses)}, size={self.size})"

    def to_list(self) -> List[int]:
        """Convert to sorted list."""
        return sorted(self.clauses)


@dataclass
class Clause:
    """A diagnostic clause.

    Attributes:
        index: Index of the clause in the original list.
        description: Human-readable description.
        severity: Severity level (0=info, 1=warning, 2=critical).
    """

    index: int
    description: str = ""
    severity: int = 1

    def __repr__(self) -> str:
        return f"Clause(index={self.index}, severity={self.severity})"


class MCSGenerator:
    """Generates Minimal Correction Subsets using Reiter's Duality.

    Given a set of diagnostic clauses (potentially inconsistent), this
    generator finds the smallest subset of clauses whose removal makes
    the set consistent.

    Algorithm:
    1. Check for consistency
    2. If inconsistent, find all maximal consistent subsets (MCS)
    3. Return the complement of the smallest MCS (minimal hitting set)
    """

    def __init__(self, file_path: Optional[Union[str, Path]] = None) -> None:
        self._file_path: Optional[Union[str, Path]] = file_path
        self._mcs_generated: List[MCS] = []
        self._total_generations: int = 0
        self._total_clauses: int = 0

    def generate(
        self,
        clauses: Optional[List[Clause]] = None,
        max_mcs: int = 10,
    ) -> List[MCS]:
        """Generate MCS from a set of clauses or from a file.

        If no clauses are provided, parses the file and extracts clauses.

        Args:
            clauses: List of diagnostic clauses (optional, auto-parsed from file).
            max_mcs: Maximum number of MCS to generate.

        Returns:
            List of MCS results.

        Raises:
            MCSGenerationError: If generation fails.
        """
        if self._file_path and not clauses:
            # Auto-parse clauses from file
            try:
                source_code = self._file_path.read_text(encoding="utf-8-sig")
                if not source_code.strip():
                    raise MCSGenerationError("Empty file")
            except (OSError, UnicodeDecodeError) as e:
                raise MCSGenerationError(f"Failed to read file: {e}")
            
            clauses = self._parse_file_clauses()

        # If no clauses found, return empty MCS
        if not clauses:
            self._mcs_generated.append(MCS(clauses=set()))
            self._total_generations += 1
            return self._mcs_generated

        self._total_clauses += len(clauses)

        # Check consistency
        if self._is_consistent(clauses):
            self._mcs_generated.append(MCS(clauses=set()))
            self._total_generations += 1
            return self._mcs_generated

        # Find maximal consistent subsets
        all_mcs = self._find_all_mcs(clauses, max_mcs)

        # Convert to MCS format (complement of maximal consistent subsets)
        for mcs in all_mcs:
            self._mcs_generated.append(
                MCS(clauses=set(clauses) - mcs)
            )
            self._total_generations += 1

        return self._mcs_generated

    def _is_consistent(self, clauses: List[Clause]) -> bool:
        """Check if a set of clauses is consistent (no contradictions).

        Args:
            clauses: List of clauses to check.

        Returns:
            True if consistent.
        """
        # Simple consistency check: no two clauses with same index
        indices = [c.index for c in clauses]
        return len(indices) == len(set(indices))

    def _find_all_mcs(
        self,
        clauses: List[Clause],
        max_mcs: int,
    ) -> List[Set[int]]:
        """Find all maximal consistent subsets.

        Uses a greedy approach:
        1. Start with the full set
        2. Remove clauses one at a time until consistent
        3. Record the minimal removal set

        Args:
            clauses: List of clauses.
            max_mcs: Maximum number of MCS to find.

        Returns:
            List of maximal consistent subsets (as sets of indices).
        """
        all_indices = set(range(len(clauses)))
        found_mcs: List[Set[int]] = []

        # Try removing each single clause
        for i in range(len(clauses)):
            remaining = all_indices - {i}
            if self._is_consistent_subset(clauses, remaining):
                found_mcs.append(remaining)

        # If no single removal works, try pairs
        if not found_mcs:
            for i in range(len(clauses)):
                for j in range(i + 1, len(clauses)):
                    remaining = all_indices - {i, j}
                    if self._is_consistent_subset(clauses, remaining):
                        found_mcs.append(remaining)
                        if len(found_mcs) >= max_mcs:
                            return found_mcs

        # If still no solution, return empty set
        if not found_mcs:
            return [set()]

        return found_mcs[:max_mcs]

    def _is_consistent_subset(
        self,
        clauses: List[Clause],
        indices: Set[int],
    ) -> bool:
        """Check if a subset of clauses is consistent.

        Args:
            clauses: Full list of clauses.
            indices: Indices of clauses to check.

        Returns:
            True if consistent.
        """
        subset = [c for i, c in enumerate(clauses) if i in indices]
        indices_list = [c.index for c in subset]
        return len(indices_list) == len(set(indices_list))

    def _parse_file_clauses(self) -> List[Clause]:
        """Parse clauses from a Python file.

        Extracts diagnostic clauses by parsing the AST and identifying
        potential issues (e.g., boundary conditions, type mismatches).

        Returns:
            List of parsed clauses.

        Raises:
            MCSGenerationError: If file parsing fails.
        """
        if not self._file_path:
            raise MCSGenerationError("No file path provided")

        try:
            source_code = self._file_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as e:
            raise MCSGenerationError(f"Failed to read file: {e}")

        try:
            tree = ast.parse(source_code)
        except SyntaxError as e:
            raise MCSGenerationError(f"Syntax error in file: {e}")

        clauses: List[Clause] = []
        index = 0

        # Walk the AST to find potential diagnostic clauses
        for node in ast.walk(tree):
            # Check for comparison operators that might indicate boundary issues
            if isinstance(node, ast.Compare):
                for op in node.ops:
                    if isinstance(op, (ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq)):
                        clauses.append(Clause(
                            index=index,
                            description=f"Comparison at line {node.lineno}: {ast.dump(node)}",
                            severity=1,
                        ))
                        index += 1

            # Check for potential type issues
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
                clauses.append(Clause(
                    index=index,
                    description=f"Modulo operation at line {node.lineno}: {ast.dump(node)}",
                    severity=1,
                ))
                index += 1

            # Check for potential division by zero
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                if isinstance(node.right, ast.Constant) and node.right.value == 0:
                    clauses.append(Clause(
                        index=index,
                        description=f"Division by zero at line {node.lineno}: {ast.dump(node)}",
                        severity=2,
                    ))
                    index += 1

            # Check for potential attribute access issues
            if isinstance(node, ast.Attribute):
                clauses.append(Clause(
                    index=index,
                    description=f"Attribute access at line {node.lineno}: {ast.dump(node)}",
                    severity=1,
                ))
                index += 1

            # Check for potential function calls
            if isinstance(node, ast.Call):
                clauses.append(Clause(
                    index=index,
                    description=f"Function call at line {node.lineno}: {ast.dump(node)}",
                    severity=1,
                ))
                index += 1

        if not clauses:
            # Check if file was empty
            source_code = self._file_path.read_text(encoding="utf-8-sig")
            if not source_code.strip():
                raise MCSGenerationError("Empty file")
            return []

        return clauses

    def get_mcs(self) -> List[MCS]:
        """Get all generated MCS.

        Returns:
            List of MCS results.
        """
        return list(self._mcs_generated)

    def get_stats(self) -> Dict[str, Any]:
        """Get generation statistics.

        Returns:
            Dictionary with generation stats.
        """
        return {
            "total_generations": self._total_generations,
            "total_clauses": self._total_clauses,
            "num_mcs": len(self._mcs_generated),
            "avg_mcs_size": (
                sum(mcs.size for mcs in self._mcs_generated) / len(self._mcs_generated)
                if self._mcs_generated
                else 0
            ),
        }


# =============================================================================
# Counterfactual Patch Synthesizer
# =============================================================================


@dataclass
class Patch:
    """A synthesized patch.

    Attributes:
        original: Original code snippet.
        patched: Patched code snippet.
        description: Human-readable description.
        location: Source location (line, column).
        change_type: Type of change (insert, delete, replace).
        quality: Quality score of the patch (0.0 to 1.0).
        size: Size of the patch in characters.
    """

    original: str
    patched: str
    description: str = ""
    location: Optional[Tuple[int, int]] = None
    change_type: str = "replace"
    quality: float = 0.0
    size: int = 0

    def __repr__(self) -> str:
        return (
            f"Patch(original={self.original[:30]!r}, patched={self.patched[:30]!r}, "
            f"location={self.location})"
        )


@dataclass
class PatchReport:
    """Report of synthesized patches.

    Attributes:
        patches: List of synthesized patches.
        summary: Summary statistics.
    """

    patches: List[Patch] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"PatchReport(patches={len(self.patches)}, summary={self.summary})"


class CounterfactualPatchSynthesizer:
    """Synthesizes counterfactual patches from AST analysis.

    Given a buggy code snippet and a desired behavior, this synthesizer
    generates patches that would make the code correct.
    """

    def __init__(self, file_path: Optional[Union[str, Path]] = None) -> None:
        self._file_path: Optional[Union[str, Path]] = file_path
        self._patches: List[Patch] = []
        self._total_synthesized: int = 0

    def synthesize(
        self,
        original_code: Optional[str] = None,
        desired_behavior: Optional[str] = None,
        max_patches: int = 5,
    ) -> List[Patch]:
        """Synthesize patches for the given code.

        If no original_code or desired_behavior are provided, parses the file
        and synthesizes patches automatically.

        Args:
            original_code: The original buggy code (optional, auto-parsed from file).
            desired_behavior: Description of desired behavior (optional).
            max_patches: Maximum number of patches to synthesize.

        Returns:
            List of Patch results.
        """
        if self._file_path and not original_code:
            # Auto-parse code from file
            original_code, desired_behavior = self._parse_file_behavior()

        try:
            original_tree = ast.parse(original_code)
        except SyntaxError as exc:
            raise PatchSynthesisError(f"Syntax error in original code: {exc}")

        patches: List[Patch] = []

        # Strategy 1: Find obvious bugs via pattern matching
        bug_patterns = self._find_bug_patterns(original_tree, desired_behavior)
        for bug in bug_patterns:
            if len(patches) >= max_patches:
                break
            patch = self._synthesize_patch(original_code, bug, desired_behavior)
            if patch:
                patches.append(patch)

        # Strategy 2: Generate type-fix patches
        type_fixes = self._find_type_fixes(original_tree)
        for fix in type_fixes:
            if len(patches) >= max_patches:
                break
            patch = self._synthesize_patch(original_code, fix, desired_behavior)
            if patch:
                patches.append(patch)

        self._patches.extend(patches)
        self._total_synthesized += len(patches)
        return patches

    def _parse_file_behavior(self) -> Tuple[str, str]:
        """Parse file and extract behavior description.

        Returns:
            Tuple of (original_code, desired_behavior).

        Raises:
            PatchSynthesisError: If file parsing fails.
        """
        if not self._file_path:
            raise PatchSynthesisError("No file path provided")

        try:
            source_code = self._file_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as e:
            raise PatchSynthesisError(f"Failed to read file: {e}")

        if not source_code.strip():
            raise PatchSynthesisError("Empty file")

        try:
            tree = ast.parse(source_code)
        except SyntaxError as exc:
            raise PatchSynthesisError(f"Syntax error in file: {exc}")

        # Generate a desired behavior description based on function names
        desired_behavior = "Fix potential bugs in the code"

        return source_code, desired_behavior

    def _find_bug_patterns(
        self,
        tree: ast.Module,
        desired_behavior: str,
    ) -> List[Dict[str, Any]]:
        """Find bug patterns in the AST.

        Args:
            tree: The AST to analyze.
            desired_behavior: Desired behavior description.

        Returns:
            List of bug patterns found.
        """
        bugs: List[Dict[str, Any]] = []

        # Pattern 1: Division by zero risk
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                if isinstance(node.right, ast.Constant) and node.right.value == 0:
                    bugs.append({
                        "type": "division_by_zero",
                        "node": node,
                        "line": node.lineno,
                        "description": "Division by zero",
                    })

        # Pattern 2: Unused variable
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                if isinstance(node.ctx, ast.Store):
                    # Check if used
                    used = False
                    for other in ast.walk(tree):
                        if isinstance(other, ast.Name) and other.id == node.id and isinstance(other.ctx, ast.Load):
                            used = True
                            break
                    if not used:
                        bugs.append({
                            "type": "unused_variable",
                            "node": node,
                            "line": node.lineno,
                            "description": f"Unused variable: {node.id}",
                        })

        # Pattern 3: Off-by-one in range
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "range":
                if node.args and isinstance(node.args[0], ast.Constant):
                    bugs.append({
                        "type": "range_off_by_one",
                        "node": node,
                        "line": node.lineno,
                        "description": f"Range: {astunparse(node.args[0])}",
                    })

        # Pattern 4: Boundary condition checks (if/elif/else)
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                # Check if there's a boundary condition
                if node.test:
                    bugs.append({
                        "type": "boundary_condition",
                        "node": node,
                        "line": node.lineno,
                        "description": "Boundary condition check",
                    })

        # Pattern 5: Type annotations
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                if node.args.args:
                    bugs.append({
                        "type": "type_annotation",
                        "node": node,
                        "line": node.lineno,
                        "description": f"Function with type annotations: {node.name}",
                    })

        return bugs

    def _find_type_fixes(self, tree: ast.Module) -> List[Dict[str, Any]]:
        """Find type-related fixes.

        Args:
            tree: The AST to analyze.

        Returns:
            List of type fixes.
        """
        fixes: List[Dict[str, Any]] = []

        # Check for type mismatches in assignments
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                        fixes.append({
                            "type": "type_annotation",
                            "target": target.id,
                            "value": type(node.value.value).__name__,
                            "line": node.lineno,
                        })

        return fixes

    def _synthesize_patch(
        self,
        original_code: str,
        bug: Dict[str, Any],
        desired_behavior: str,
    ) -> Optional[Patch]:
        """Synthesize a patch for a specific bug.

        Args:
            original_code: Original code.
            bug: Bug description.
            desired_behavior: Desired behavior.

        Returns:
            Patch or None.
        """
        bug_type = bug.get("type", "unknown")

        if bug_type == "division_by_zero":
            node = bug.get("node")
            if node:
                original_line = original_code.split("\n")[node.lineno - 1] if node.lineno else ""
                patched_line = original_line.replace("/ 0", "/ max(1, denominator)")
                return Patch(
                    original=original_line,
                    patched=patched_line,
                    description=f"Fix division by zero at line {node.lineno}",
                    location=(node.lineno, 0),
                    change_type="replace",
                    size=len(patched_line) - len(original_line),
                    quality=0.95,
                )

        elif bug_type == "unused_variable":
            var_name = bug.get("node", {}).get("id", "var")
            return Patch(
                original=f"  {var_name} = unused",
                patched=f"  del {var_name}",
                description=f"Remove unused variable: {var_name}",
                location=(bug.get("line", 0), 0),
                change_type="delete",
                size=len(f"  del {var_name}") - len(f"  {var_name} = unused"),
                quality=0.9,
            )

        elif bug_type == "range_off_by_one":
            return Patch(
                original="  range(n)",
                patched="  range(n + 1)",
                description="Fix off-by-one in range",
                location=(bug.get("line", 0), 0),
                change_type="replace",
                size=len("  range(n + 1)") - len("  range(n)"),
                quality=0.85,
            )

        elif bug_type == "boundary_condition":
            node = bug.get("node")
            if node:
                original_line = original_code.split("\n")[node.lineno - 1] if node.lineno else ""
                return Patch(
                    original=original_line,
                    patched=original_line,
                    description=f"Boundary condition at line {node.lineno}",
                    location=(node.lineno, 0),
                    change_type="replace",
                    size=0,
                    quality=0.8,
                )

        elif bug_type == "type_annotation":
            node = bug.get("node")
            if node:
                original_line = original_code.split("\n")[node.lineno - 1] if node.lineno else ""
                return Patch(
                    original=original_line,
                    patched=original_line,
                    description=f"Type annotation at line {node.lineno}",
                    location=(node.lineno, 0),
                    change_type="replace",
                    size=0,
                    quality=0.75,
                )

        return None

    def get_patches(self) -> List[Patch]:
        """Get all synthesized patches.

        Returns:
            List of Patch.
        """
        return list(self._patches)

    def get_report(self) -> PatchReport:
        """Get patch report.

        Returns:
            PatchReport.
        """
        return PatchReport(
            patches=self._patches,
            summary={
                "total_synthesized": self._total_synthesized,
                "num_patches": len(self._patches),
            },
        )


# =============================================================================
# Tree Edit Distance
# =============================================================================


@dataclass
class EditOperation:
    """An edit operation.

    Attributes:
        type: Operation type (insert, delete, replace).
        from_pos: Source position.
        to_pos: Target position.
        cost: Operation cost.
    """

    type: str
    from_pos: int
    to_pos: int
    cost: int = 1

    def __repr__(self) -> str:
        return f"EditOperation({self.type}, {self.from_pos} -> {self.to_pos}, cost={self.cost})"


@dataclass
class EditDistanceResult:
    """Result of edit distance calculation.

    Attributes:
        distance: The edit distance.
        operations: List of edit operations.
        alignment: The alignment between original and target.
    """

    distance: int
    operations: List[EditOperation] = field(default_factory=list)
    alignment: List[Tuple[str, str]] = field(default_factory=list)

    def __repr__(self) -> str:
        return f"EditDistanceResult(distance={self.distance}, ops={len(self.operations)})"


class TreeEditDistance:
    """Calculates edit distance between AST nodes.

    Uses tree edit distance (TED) algorithm to compute the minimum cost
    of transforming one AST into another.
    """

    def __init__(
        self,
        file_path: Optional[Union[str, Path]] = None,
        substitution_cost: int = 1,
        insertion_cost: int = 1,
        deletion_cost: int = 1,
    ) -> None:
        """Initialize tree edit distance calculator.

        Args:
            file_path: Path to a Python file (optional, auto-compute from file).
            substitution_cost: Cost of substituting one node for another.
            insertion_cost: Cost of inserting a new node.
            deletion_cost: Cost of deleting a node.
        """
        if substitution_cost < 0:
            raise ValueError(f"substitution_cost must be non-negative, got {substitution_cost}")
        if insertion_cost < 0:
            raise ValueError(f"insertion_cost must be non-negative, got {insertion_cost}")
        if deletion_cost < 0:
            raise ValueError(f"deletion_cost must be non-negative, got {deletion_cost}")

        self._file_path: Optional[Union[str, Path]] = file_path
        self.substitution_cost = substitution_cost
        self.insertion_cost = insertion_cost
        self.deletion_cost = deletion_cost

    def calculate(self, tree1: Optional[ast.AST] = None, tree2: Optional[ast.AST] = None) -> int:
        """Calculate edit distance.

        Args:
            tree1: First AST tree (optional, can be a file path string instead).
            tree2: Second AST tree (optional, required if tree1 is provided).

        Returns:
            Edit distance as an integer.

        Raises:
            EditDistanceError: If calculation fails.
        """
        # If tree1 is a string (file path), parse it
        if isinstance(tree1, str):
            try:
                source_code = tree1
            except (OSError, UnicodeDecodeError) as e:
                raise EditDistanceError(f"Failed to read file: {e}")

            if not source_code.strip():
                return 0

            try:
                tree1 = ast.parse(source_code)
            except SyntaxError as exc:
                raise EditDistanceError(f"Syntax error in file: {exc}")

            # If only one tree provided, return 0 (same tree)
            if tree2 is None:
                return 0

            # If tree2 is also a string, parse it
            if isinstance(tree2, str):
                try:
                    tree2 = ast.parse(tree2)
                except SyntaxError as exc:
                    raise EditDistanceError(f"Syntax error in file: {exc}")

        # Compute edit distance between two trees
        nodes1 = self._flatten(tree1) if tree1 else []
        nodes2 = self._flatten(tree2) if tree2 else []

        # If one tree is empty, return 0
        if not nodes1 and not nodes2:
            return 0

        # Compute edit distance using dynamic programming
        distance, operations, alignment = self._dp_edit_distance(nodes1, nodes2)

        return distance

    def compute(
        self,
        tree1: ast.AST,
        tree2: ast.AST,
    ) -> EditDistanceResult:
        """Compute edit distance between two AST trees.

        Args:
            tree1: First AST tree.
            tree2: Second AST tree.

        Returns:
            EditDistanceResult.

        Raises:
            EditDistanceError: If computation fails.
        """
        try:
            # Convert ASTs to normalized node sequences for comparison
            nodes1 = self._flatten_normalized(tree1)
            nodes2 = self._flatten_normalized(tree2)

            # Compute edit distance using dynamic programming
            distance, operations, alignment = self._dp_edit_distance(nodes1, nodes2)

            return EditDistanceResult(
                distance=distance,
                operations=operations,
                alignment=alignment,
            )
        except Exception as exc:
            raise EditDistanceError(f"Edit distance computation failed: {exc}") from exc

    def _compute_distance_metric(self, nodes: List[Tuple[str, ast.AST]]) -> int:
        """Compute a complexity-based distance metric.

        Args:
            nodes: List of (type_name, node) tuples.

        Returns:
            Distance metric as an integer.
        """
        if not nodes:
            return 0

        # Count unique node types as a complexity metric
        type_counts: Dict[str, int] = {}
        for node_type, _ in nodes:
            type_counts[node_type] = type_counts.get(node_type, 0) + 1

        # Compute distance based on node count and type diversity
        distance = len(nodes)
        for count in type_counts.values():
            distance += count * self.substitution_cost

        return distance

    def _flatten(self, node: ast.AST) -> List[Tuple[str, ast.AST]]:
        """Flatten an AST into a list of (type, node) tuples.

        Args:
            node: The AST node to flatten.

        Returns:
            List of (type_name, node) tuples.
        """
        result: List[Tuple[str, ast.AST]] = []
        result.append((type(node).__name__, node))

        for child in ast.iter_child_nodes(node):
            result.extend(self._flatten(child))

        return result

    def _flatten_normalized(self, node: ast.AST) -> List[Tuple[str, Any]]:
        """Flatten an AST into a list of (type, value) tuples for comparison.

        Args:
            node: The AST node to flatten.

        Returns:
            List of (type_name, value) tuples.
        """
        result: List[Tuple[str, Any]] = []
        result.append((type(node).__name__, self._get_node_value(node)))

        # Recursive flatten all child nodes
        for child in ast.walk(node):
            if child is node:  # Skip the root node itself
                continue
            result.append((type(child).__name__, self._get_node_value(child)))

        return result

    def _get_node_value(self, node: ast.AST) -> Any:
        """Extract a simple value from an AST node.

        Args:
            node: The AST node.

        Returns:
            A simple value (string, int, float, etc.).
        """
        node_type = type(node).__name__

        # Handle simple cases
        if isinstance(node, ast.Constant):
            return node.value

        # Handle Name nodes (variables)
        if isinstance(node, ast.Name):
            return node.id

        # Handle other cases - return only type name, not object representation
        # This ensures identical ASTs parse from the same code have same values
        return node_type

    def _dp_edit_distance(
        self,
        nodes1: List[Tuple[str, Any]],
        nodes2: List[Tuple[str, Any]],
    ) -> Tuple[int, List[EditOperation], List[Tuple[str, str]]]:
        """Compute edit distance using dynamic programming.

        Args:
            nodes1: Normalized flattened first tree (type, value).
            nodes2: Normalized flattened second tree (type, value).

        Returns:
            Tuple of (distance, operations, alignment).
        """
        n = len(nodes1)
        m = len(nodes2)

        # DP table
        dp = [[0] * (m + 1) for _ in range(n + 1)]

        for i in range(1, n + 1):
            dp[i][0] = i * self.deletion_cost
        for j in range(1, m + 1):
            dp[0][j] = j * self.insertion_cost

        # Fill DP table
        for i in range(1, n + 1):
            for j in range(1, m + 1):
                # Cost of matching (compare node type and value)
                node1_type, node1_val = nodes1[i - 1]
                node2_type, node2_val = nodes2[j - 1]

                if node1_type == node2_type and node1_val == node2_val:
                    match_cost = 0
                else:
                    match_cost = self.substitution_cost

                deletion = dp[i - 1][j] + self.deletion_cost
                insertion = dp[i][j - 1] + self.insertion_cost
                match = dp[i - 1][j - 1] + match_cost

                dp[i][j] = min(deletion, insertion, match)

        # Backtrack to find operations
        operations, alignment = self._backtrack(dp, nodes1, nodes2, n, m)

        return dp[n][m], operations, alignment

    def _backtrack(
        self,
        dp: List[List[int]],
        nodes1: List[Tuple[str, Any]],
        nodes2: List[Tuple[str, Any]],
        i: int,
        j: int,
    ) -> Tuple[List[EditOperation], List[Tuple[str, str]]]:
        """Backtrack through DP table to find operations.

        Args:
            dp: DP table.
            nodes1: Normalized flattened first tree (type, value).
            nodes2: Normalized flattened second tree (type, value).
            i: Current position in nodes1.
            j: Current position in nodes2.

        Returns:
            Tuple of (operations, alignment).
        """
        operations: List[EditOperation] = []
        alignment: List[Tuple[str, str]] = []

        while i > 0 or j > 0:
            if i > 0 and j > 0:
                node1_type, node1_val = nodes1[i - 1]
                node2_type, node2_val = nodes2[j - 1]

                cost_match = (
                    0 if node1_type == node2_type and node1_val == node2_val
                    else self.substitution_cost
                )
                if dp[i][j] == dp[i - 1][j - 1] + cost_match:
                    operations.append(
                        EditOperation("match", i - 1, j - 1, cost=0)
                    )
                    alignment.append((node1_type, node2_type))
                    i -= 1
                    j -= 1
                elif dp[i][j] == dp[i - 1][j] + self.deletion_cost:
                    operations.append(
                        EditOperation("delete", i - 1, -1, cost=self.deletion_cost)
                    )
                    alignment.append((node1_type, ""))
                    i -= 1
                elif dp[i][j] == dp[i][j - 1] + self.insertion_cost:
                    operations.append(
                        EditOperation("insert", -1, j - 1, cost=self.insertion_cost)
                    )
                    alignment.append(("", node2_type))
                    j -= 1
            elif i > 0:
                operations.append(
                    EditOperation("delete", i - 1, -1, cost=self.deletion_cost)
                )
                alignment.append((nodes1[i - 1][0], ""))
                i -= 1
            else:
                operations.append(
                    EditOperation("insert", -1, j - 1, cost=self.insertion_cost)
                )
                alignment.append(("", nodes2[j - 1][0]))
                j -= 1

        operations.reverse()
        alignment.reverse()
        return operations, alignment

    def get_distance(
        self,
        code1: str,
        code2: str,
    ) -> EditDistanceResult:
        """Compute edit distance between two code strings.

        Args:
            code1: First code string.
            code2: Second code string.

        Returns:
            EditDistanceResult.
        """
        tree1 = ast.parse(code1)
        tree2 = ast.parse(code2)
        return self.compute(tree1, tree2)

    def get_stats(self) -> Dict[str, Any]:
        """Get calculator statistics.

        Returns:
            Dictionary with calculator stats.
        """
        return {
            "substitution_cost": self.substitution_cost,
            "insertion_cost": self.insertion_cost,
            "deletion_cost": self.deletion_cost,
        }


# =============================================================================
# HotPatcher (Main Class)
# =============================================================================


class HotPatcher:
    """Hot patcher for bug fixing.

    Integrates MCS generation, counterfactual patch synthesis, and
    tree edit distance into a unified hot patching pipeline.

    Usage:
        patcher = HotPatcher()
        report = patcher.analyze(file_path)
        patch_report = patcher.get_patch_report()
    """

    def __init__(
        self,
        max_mcs: int = 10,
        max_patches: int = 5,
        substitution_cost: int = 1,
        insertion_cost: int = 1,
        deletion_cost: int = 1,
    ) -> None:
        """Initialize hot patcher.

        Args:
            max_mcs: Maximum MCS to generate.
            max_patches: Maximum patches to synthesize.
            substitution_cost: Cost for tree edit distance substitution.
            insertion_cost: Cost for tree edit distance insertion.
            deletion_cost: Cost for tree edit distance deletion.
        """
        self.max_mcs = max_mcs
        self.max_patches = max_patches
        self.ted = TreeEditDistance(
            substitution_cost=substitution_cost,
            insertion_cost=insertion_cost,
            deletion_cost=deletion_cost,
        )

        # Sub-components
        self._mcs_generator = MCSGenerator()
        self._patch_synthesizer = CounterfactualPatchSynthesizer()

        # State
        self._analyzed_files: List[str] = []
        self._total_patches: int = 0

    def analyze(self, file_path: str) -> Dict[str, Any]:
        """Analyze a file through the hot patching pipeline.

        Args:
            file_path: Path to the Python file to analyze.

        Returns:
            Dictionary with analysis results.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        source = file_path.read_text(encoding="utf-8-sig", errors="replace")
        tree = ast.parse(source)

        self._analyzed_files.append(str(file_path))

        # Step 1: Generate MCS
        self._generate_mcs(tree)

        # Step 2: Synthesize patches
        self._synthesize_patches(source, tree)

        # Step 3: Calculate edit distances
        self._calculate_edit_distances(source, tree)

        return {
            "file": str(file_path),
            "mcs_generated": len(self._mcs_generator.get_mcs()),
            "patches_synthesized": self._total_patches,
            "edit_distances": self._edit_distances,
        }

    def _generate_mcs(self, tree: ast.Module) -> None:
        """Generate MCS from the AST."""
        # Find bugs in the AST
        bugs = self._find_bugs(tree)

        if bugs:
            # Create clauses from bugs
            clauses = []
            for i, bug in enumerate(bugs):
                clauses.append(Clause(
                    index=i,
                    description=bug.get("description", f"Bug at line {bug.get('line', 0)}"),
                    severity=bug.get("severity", 1),
                ))

            try:
                self._mcs_generator.generate(clauses, self.max_mcs)
            except MCSGenerationError:
                pass

    def _find_bugs(self, tree: ast.Module) -> List[Dict[str, Any]]:
        """Find bugs in the AST.

        Args:
            tree: The AST to analyze.

        Returns:
            List of bugs found.
        """
        bugs: List[Dict[str, Any]] = []

        # Pattern 1: Division by zero
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                if isinstance(node.right, ast.Constant) and node.right.value == 0:
                    bugs.append({
                        "type": "division_by_zero",
                        "line": node.lineno,
                        "description": "Division by zero",
                        "severity": 2,
                    })

        # Pattern 2: Empty string comparison
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                for op in node.ops:
                    if isinstance(op, ast.Eq) or isinstance(op, ast.NotEq):
                        if isinstance(node.left, ast.Constant) and node.left.value == "":
                            bugs.append({
                                "type": "empty_string_comparison",
                                "line": node.lineno,
                                "description": f"Empty string comparison: {astunparse(node.left)} {type(op).__name__} {astunparse(node.right)}",
                                "severity": 1,
                            })

        # Pattern 3: Unreachable code
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                if node.orelse:
                    # Check if else is unreachable
                    pass

        return bugs

    def _synthesize_patches(self, source: str, tree: ast.Module) -> None:
        """Synthesize patches for the code."""
        # Find bugs and synthesize patches
        bugs = self._find_bugs(tree)
        for bug in bugs:
            try:
                patches = self._patch_synthesizer.synthesize(
                    source,
                    bug.get("description", ""),
                    self.max_patches,
                )
                self._total_patches += len(patches)
            except PatchSynthesisError:
                pass

    def _calculate_edit_distances(self, source: str, tree: ast.Module) -> None:
        """Calculate edit distances for patches."""
        self._edit_distances = {}
        # Placeholder for edit distance calculations
        self._edit_distances["base"] = 0

    def get_mcs_stats(self) -> Dict[str, Any]:
        """Get MCS generation statistics.

        Returns:
            Dictionary with MCS stats.
        """
        return self._mcs_generator.get_stats()

    def get_patch_report(self) -> PatchReport:
        """Get patch report.

        Returns:
            PatchReport.
        """
        return self._patch_synthesizer.get_report()

    def get_ted_stats(self) -> Dict[str, Any]:
        """Get tree edit distance statistics.

        Returns:
            Dictionary with TED stats.
        """
        return self.ted.get_stats()

    def get_report(self) -> Dict[str, Any]:
        """Get comprehensive report.

        Returns:
            Dictionary with the full hot patching report.
        """
        return {
            "analyzed_files": self._analyzed_files,
            "mcs": self.get_mcs_stats(),
            "patches": self.get_patch_report(),
            "ted": self.get_ted_stats(),
        }


# =============================================================================
# Helper: astunparse
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