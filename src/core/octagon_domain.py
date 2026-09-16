"""
Octagon Domain Module.

Provides abstract domain for interval-based analysis with DBM.
"""

import ast
import re
from dataclasses import dataclass, field
from typing import Optional, Union, Tuple, Dict, List, Any
from pathlib import Path
import math


@dataclass
class DBM:
    """Discrete Difference Field (DBM) for interval constraints."""

    variables: Tuple[str, ...] = field(default_factory=tuple)
    constraints: Dict[Tuple[str, str], int] = field(default_factory=dict)

    def __init__(
        self,
        variables: Optional[Union[Tuple[str, ...], int]] = None,
        constraints: Optional[Dict[Tuple[str, str], int]] = None,
    ) -> None:
        """Initialize DBM.

        Args:
            variables: Tuple of variable names, or an int specifying the count of variables.
            constraints: Dictionary of constraints (var1, var2) -> value.
        """
        if isinstance(variables, int):
            # Auto-generate n+1 variables including clock (e.g., DBM(2) → ('v0', 'v1', 'v2'))
            self.variables = tuple(f"v{i}" for i in range(variables + 1))
        else:
            self.variables = variables or ()
        self.constraints = constraints or {}

        # Initialize diagonal to 0 and off-diagonal to infinity
        for i in range(len(self.variables)):
            for j in range(len(self.variables)):
                if i == j:
                    self.constraints[(self.variables[i], self.variables[j])] = 0
                else:
                    self.constraints[(self.variables[i], self.variables[j])] = math.inf

    def add_constraint(
        self,
        var1: str,
        var2: str,
        value: int,
    ) -> None:
        """Add a constraint between two variables.

        Args:
            var1: First variable.
            var2: Second variable.
            value: Constraint value.
        """
        if self.variables:
            var1 = self.variables[var1]
            var2 = self.variables[var2]
        else:
            var1 = f"v{var1}"
            var2 = f"v{var2}"
        self.constraints[(var1, var2)] = value

    def get(
        self,
        var1: Union[str, int],
        var2: Union[str, int],
    ) -> Optional[int]:
        """Get a constraint between two variables.

        Args:
            var1: First variable (string name or integer index).
            var2: Second variable (string name or integer index).

        Returns:
            Constraint value or None.
        """
        if isinstance(var1, int) and isinstance(var2, int):
            if self.variables:
                var1 = self.variables[var1]
                var2 = self.variables[var2]
            else:
                var1 = f"v{var1}"
                var2 = f"v{var2}"
        return self.constraints.get((var1, var2))

    def get_constraints(self) -> List[Tuple[str, str, int]]:
        """Get all constraints as a list of (var1, var2, value) tuples.

        Returns:
            List of constraint tuples.
        """
        return [(k, v) for k, v in self.constraints.items()]

    def set(
        self,
        i: int,
        j: int,
        val: int,
    ) -> None:
        """Set a constraint at position (i, j).

        Args:
            i: Row index.
            j: Column index.
            val: Constraint value.
        """
        if self.variables:
            var1 = self.variables[i]
            var2 = self.variables[j]
            self.constraints[(var1, var2)] = val
        else:
            self.constraints[("v" + str(i), "v" + str(j))] = val

    def get_value(
        self,
        i: int,
        j: int,
    ) -> Optional[int]:
        """Get constraint value at position (i, j).

        Args:
            i: Row index.
            j: Column index.

        Returns:
            Constraint value or None.
        """
        if self.variables:
            var1 = self.variables[i]
            var2 = self.variables[j]
            return self.constraints.get((var1, var2))
        else:
            return self.constraints.get(("v" + str(i), "v" + str(j)))

    @property
    def size(self) -> int:
        """Get DBM matrix dimension (variables + clock).

        Returns:
            Matrix size (n + 1).
        """
        return len(self.variables)

    @property
    def n(self) -> int:
        """Get number of variables (excluding clock).

        Returns:
            Number of non-clock variables.
        """
        return len(self.variables) - 1

    def get_summary(self) -> Dict[str, Any]:
        """Get DBM summary.

        Returns:
            Dictionary with summary information.
        """
        return {
            "n": len(self.variables),
            "size": len(self.constraints),
            "infeasible_paths": len([c for c in self.constraints.values() if c < 0]),
        }

    def floyd_warshall(self) -> None:
        """Compute transitive closure using Floyd-Warshall algorithm.

        Updates constraints with shortest path distances.
        """
        n = len(self.variables)
        if n == 0:
            return

        # Initialize distance matrix
        dist: Dict[Tuple[str, str], int] = {}
        for i in range(n):
            for j in range(n):
                if i == j:
                    dist[(self.variables[i], self.variables[j])] = 0
                elif (self.variables[i], self.variables[j]) in self.constraints:
                    dist[(self.variables[i], self.variables[j])] = self.constraints[(self.variables[i], self.variables[j])]
                else:
                    dist[(self.variables[i], self.variables[j])] = math.inf

        # Floyd-Warshall
        for k in range(n):
            for i in range(n):
                for j in range(n):
                    new_dist = dist[(self.variables[i], self.variables[k])] + dist[(self.variables[k], self.variables[j])]
                    if new_dist < dist[(self.variables[i], self.variables[j])]:
                        dist[(self.variables[i], self.variables[j])] = new_dist

        # Update constraints
        for i in range(n):
            for j in range(n):
                if dist[(self.variables[i], self.variables[j])] != math.inf:
                    self.constraints[(self.variables[i], self.variables[j])] = dist[(self.variables[i], self.variables[j])]

    def detect_infeasible(self) -> List[Tuple[int, int]]:
        """Detect infeasible constraints after Floyd-Warshall.

        Returns:
            List of (i, j) pairs where constraint is infeasible (negative).
        """
        infeasible = []
        n = len(self.variables)
        for i in range(n):
            for j in range(n):
                if self.constraints.get((self.variables[i], self.variables[j]), math.inf) < 0:
                    infeasible.append((i, j))
        return infeasible

    def prune_infeasible(self) -> int:
        """Remove infeasible constraints from DBM.

        Returns:
            Number of infeasible constraints pruned.
        """
        infeasible = self.detect_infeasible()
        count = 0
        for i, j in infeasible:
            var1 = self.variables[i]
            var2 = self.variables[j]
            # Always set the entry to inf after deletion (diagonal or off-diagonal)
            self.constraints[(var1, var2)] = float('inf')
            count += 1
        return count

    def widen(self, other: 'DBM', max_iterations: int = 5) -> 'DBM':
        """Apply widening operator between two DBMs.

        Widening takes the maximum of corresponding constraints.

        Args:
            other: Second DBM to widen with.
            max_iterations: Maximum widening iterations.

        Returns:
            New widened DBM.
        """
        n = max(len(self.variables), len(other.variables))
        widened = DBM(n)
        for i in range(n):
            for j in range(n):
                val1 = self.get(i, j)
                val2 = other.get(i, j)
                if val1 is None or val2 is None:
                    widened.set(i, j, math.inf)
                elif val1 == math.inf and val2 == math.inf:
                    widened.set(i, j, math.inf)
                elif val1 == math.inf:
                    widened.set(i, j, val2)
                elif val2 == math.inf:
                    widened.set(i, j, math.inf)
                else:
                    widened.set(i, j, max(val1, val2))
        return widened

    def narrow(self, prev: 'DBM', curr: 'DBM') -> 'DBM':
        """Apply narrowing operator between two DBMs.

        Narrowing takes the average of corresponding constraints.

        Args:
            prev: Previous DBM.
            curr: Current DBM.

        Returns:
            New narrowed DBM.
        """
        n = max(len(prev.variables), len(curr.variables))
        narrowed = DBM(n)
        for i in range(n):
            for j in range(n):
                val1 = prev.get(i, j)
                val2 = curr.get(i, j)
                if val1 is None or val2 is None:
                    narrowed.set(i, j, math.inf)
                elif val1 == math.inf and val2 == math.inf:
                    narrowed.set(i, j, math.inf)
                elif val1 == math.inf:
                    narrowed.set(i, j, val2)
                elif val2 == math.inf:
                    narrowed.set(i, j, math.inf)
                else:
                    # Narrowing: take average of prev and curr
                    narrowed.set(i, j, (val1 + val2) // 2)
        return narrowed


@dataclass
class OctagonConstraint:
    """Represents a constraint in the octagon domain."""

    var_i: int
    var_j: int
    coefficient_i: int
    side: int
    bound: int

    def __init__(
        self,
        var_i: int,
        var_j: int,
        coefficient_i: int,
        side: int,
        bound: int,
    ) -> None:
        """Initialize octagon constraint.

        Args:
            var_i: First variable index.
            var_j: Second variable index.
            coefficient_i: Coefficient for var_i.
            side: Side of the inequality (0 for ≤, 1 for <).
            bound: Bound value.
        """
        self.var_i = var_i
        self.var_j = var_j
        self.coefficient_i = coefficient_i
        self.side = side
        self.bound = bound

    def to_dbm_entry(self, dbm: DBM) -> None:
        """Convert constraint to DBM entry.

        Args:
            dbm: DBM to add constraint to.
        """
        # Map octagon constraint to DBM entry using coefficient * bound
        value = self.coefficient_i * self.bound
        dbm.add_constraint(self.var_i, self.var_j, value)

    def __repr__(self) -> str:
        return (
            f"OctagonConstraint(var_i={self.var_i}, var_j={self.var_j}, "
            f"coefficient_i={self.coefficient_i}, bound={self.bound}, "
            f"side={self.side}) ≤"
        )


@dataclass
class OctagonDomain:
    """Abstract domain for octagon constraints."""

    dbm: Optional[DBM] = None
    errors: List[str] = field(default_factory=list)
    variables: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    constraints: List[Dict[str, Any]] = field(default_factory=list)
    octagon_constraints: List[OctagonConstraint] = field(default_factory=list)

    def __init__(self, file_path: Optional[Path] = None) -> None:
        """Initialize OctagonDomain.

        Args:
            file_path: Optional path to analyze.
        """
        self.file_path = file_path
        self.dbm = None
        self.errors = []
        self.variables = {}
        self.constraints = []
        self.octagon_constraints = []

    def analyze(self) -> bool:
        """Analyze a source file and extract constraints.

        Returns:
            True if analysis successful, False otherwise.
        """
        if self.file_path is None:
            return True

        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except FileNotFoundError:
            self.errors.append(f"File not found: {self.file_path}")
            return False
        except Exception as e:
            self.errors.append(f"Error reading file: {e}")
            return False

        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            self.errors.append(f"Syntax error: {e}")
            return False
        except Exception as e:
            self.errors.append(f"Error parsing file: {e}")
            return False

        self._extract_constraints_from_tree(tree)
        self.dbm = self._build_dbm()
        return True

    def _extract_constraints_from_tree(self, tree: ast.AST) -> None:
        """Extract constraints from AST.

        Args:
            tree: AST to analyze.
        """
        for node in ast.walk(tree):
            self._extract_from_assignments(node)
            self._extract_from_comparisons(node)

    def _extract_from_assignments(self, node: ast.AST) -> None:
        """Extract constraints from assignment statements.

        Args:
            node: AST node to analyze.
        """
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if isinstance(node.value, ast.BinOp) and isinstance(node.value.op, ast.Add):
                        # Extract variable bounds from binary operations
                        for operand in node.value.left, node.value.right:
                            if isinstance(operand, ast.Name):
                                if target.id not in self.variables:
                                    self.variables[target.id] = (0, 0)
                                if isinstance(operand, ast.Name) and operand.id in self.variables:
                                    self.variables[target.id] = (
                                        max(self.variables[target.id][0], self.variables[operand.id][0]),
                                        max(self.variables[target.id][1], self.variables[operand.id][1]),
                                    )

    def _extract_from_comparisons(self, node: ast.AST) -> None:
        """Extract constraints from comparison statements.

        Args:
            node: AST node to analyze.
        """
        if isinstance(node, ast.Compare):
            for comparator in node.comparators:
                if isinstance(comparator, ast.Name) and comparator.id in self.variables:
                    for op, val in zip(node.ops, node.comparators[:-1]):
                        if isinstance(op, ast.Gt):
                            self._add_constraint(
                                self.variables.get(node.targets[0].id, (0, 0)),
                                self.variables.get(comparator.id, (0, 0)),
                                val.value,
                            )
                        elif isinstance(op, ast.Lt):
                            self._add_constraint(
                                self.variables.get(node.targets[0].id, (0, 0)),
                                self.variables.get(comparator.id, (0, 0)),
                                -val.value,
                            )

    def _add_constraint(self, var1: Tuple[int, int], var2: Tuple[int, int], bound: int) -> None:
        """Add a constraint between two variables.

        Args:
            var1: First variable bounds.
            var2: Second variable bounds.
            bound: Constraint bound.
        """
        constraint = {
            "var1": var1,
            "var2": var2,
            "bound": bound,
            "side": 0,
        }
        self.constraints.append(constraint)

    def _build_dbm(self) -> Optional[DBM]:
        """Build DBM from extracted constraints.

        Returns:
            DBM instance or None if build failed.
        """
        if not self.variables:
            return DBM(0)

        n = len(self.variables)
        dbm = DBM(n)
        for constraint in self.constraints:
            var1 = constraint["var1"]
            var2 = constraint["var2"]
            bound = constraint["bound"]
            if var1[0] != var2[0] or var1[1] != var2[1]:
                dbm.add_constraint(var1[0], var2[0], bound)
        return dbm

    def get_summary(self) -> Dict[str, Any]:
        """Get domain summary.

        Returns:
            Dictionary with summary information.
        """
        summary = {
            "variables": len(self.variables),
            "constraints": len(self.constraints),
        }
        if self.dbm:
            summary["dbm_summary"] = self.dbm.get_summary()
        return summary

    def get_variable_bounds(self) -> Dict[str, Tuple[int, int]]:
        """Get variable bounds.

        Returns:
            Dictionary mapping variable names to (lower, upper) bounds.
        """
        return self.variables

    def widen(self, other: 'OctagonDomain', max_iterations: int = 3) -> 'OctagonDomain':
        """Apply widening operator between two domains.

        Args:
            other: Second domain to widen with.
            max_iterations: Maximum widening iterations.

        Returns:
            New widened domain.
        """
        if not self.dbm or not other.dbm:
            return OctagonDomain()

        widened_dbm = self.dbm.widen(other.dbm, max_iterations)
        result = OctagonDomain()
        result.dbm = widened_dbm
        return result

    def narrow(self, prev: 'OctagonDomain', curr: 'OctagonDomain') -> 'OctagonDomain':
        """Apply narrowing operator between two domains.

        Args:
            prev: Previous domain.
            curr: Current domain.

        Returns:
            New narrowed domain.
        """
        if not prev.dbm or not curr.dbm:
            return OctagonDomain()

        narrowed_dbm = prev.dbm.narrow(prev.dbm, curr.dbm)
        result = OctagonDomain()
        result.dbm = narrowed_dbm
        return result

    def get_constraints(self) -> List[Dict[str, Any]]:
        """Get extracted constraints.

        Returns:
            List of constraint dictionaries.
        """
        return self.constraints

    def get_dbm(self) -> Optional[DBM]:
        """Get the DBM associated with this domain.

        Returns:
            DBM instance or None.
        """
        return self.dbm

    def analyze_type(
        self,
        type_str: str,
        constraints: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Analyze a type string and return domain information.

        Args:
            type_str: Type string to analyze (e.g., "int", "float", "T").
            constraints: Type constraints (optional, defaults to empty dict).

        Returns:
            Dictionary with analysis results or None if analysis failed.
        """
        if constraints is None:
            constraints = {}

        self.errors = []
        self.variables = {}
        self.constraints = []
        self.dbm = None
        self.octagon_constraints = []

        # Extract variable bounds from type string
        if "T" in type_str:
            self.variables["T"] = (0, 0)
            self.constraints.append({
                "var1": (0, 0),
                "var2": (0, 0),
                "bound": 0,
                "side": 0,
            })

        # Build a minimal DBM
        if self.variables:
            n = len(self.variables)
            self.dbm = DBM(n)
            for constraint in self.constraints:
                var1 = constraint["var1"]
                var2 = constraint["var2"]
                bound = constraint["bound"]
                self.dbm.add_constraint(var1[0], var2[0], bound)

        if self.dbm is None:
            return None

        return {
            "variables": len(self.variables),
            "constraints": len(self.constraints),
            "dbm_summary": self.dbm.get_summary(),
        }


# ─── SSA Dominator Tree ────────────────────────────────────────────────────


@dataclass
class SSAVariable:
    """Represents a variable in SSA form."""

    name: str
    versions: List[int] = field(default_factory=list)
    current_version: int = 0

    def __post_init__(self) -> None:
        """Post-initialization hook."""
        if not self.versions:
            self.versions = [0]
            self.current_version = 0


@dataclass
class SparseSSABuilder:
    """Builds SSA representation from source code."""

    file_path: Optional[Path] = None

    def __init__(
        self,
        file_path: Optional[Path] = None,
    ) -> None:
        """Initialize SSA builder.

        Args:
            file_path: Path to source file.
        """
        self.file_path = file_path
        self.variables: Dict[str, SSAVariable] = {}
        self.errors: List[str] = []

    def build(self) -> bool:
        """Build SSA representation.

        Returns:
            True if build successful, False otherwise.
        """
        if self.file_path is None:
            return True

        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except FileNotFoundError:
            self.errors.append(f"File not found: {self.file_path}")
            return False
        except Exception as e:
            self.errors.append(f"Error reading file: {e}")
            return False

        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            self.errors.append(f"Syntax error: {e}")
            return False
        except Exception as e:
            self.errors.append(f"Error parsing file: {e}")
            return False

        self._build_ssa_from_tree(tree)
        return True

    def _build_ssa_from_tree(self, tree: ast.AST) -> None:
        """Build SSA from AST.

        Args:
            tree: AST to analyze.
        """
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        if target.id not in self.variables:
                            self.variables[target.id] = SSAVariable(name=target.id)
                        self.variables[target.id].current_version += 1
                        self.variables[target.id].versions.append(
                            self.variables[target.id].current_version
                        )

    def get_variables(self) -> List[str]:
        """Get list of variable names.

        Returns:
            List of variable names.
        """
        return list(self.variables.keys())

    def get_variable_versions(self, name: str) -> List[int]:
        """Get versions of a variable.

        Args:
            name: Variable name.

        Returns:
            List of version numbers.
        """
        if name in self.variables:
            return self.variables[name].versions
        return []

    def get_current_version(self, name: str) -> Optional[int]:
        """Get current version of a variable.

        Args:
            name: Variable name.

        Returns:
            Current version number or None.
        """
        if name in self.variables:
            return self.variables[name].current_version
        return None

    def get_summary(self) -> Dict[str, Any]:
        """Get SSA summary.

        Returns:
            Dictionary with summary information.
        """
        return {
            "variables": len(self.variables),
            "errors": len(self.errors),
        }


@dataclass
class BackedgeDetector:
    """Detects back edges in control flow graphs."""

    edges: List[Tuple[int, int]] = field(default_factory=list)

    def __init__(self, edges: Optional[List[Tuple[int, int]]] = None) -> None:
        """Initialize backedge detector.

        Args:
            edges: List of (from, to) edges.
        """
        self.edges = edges or []

    def detect(self) -> List[Tuple[int, int]]:
        """Detect back edges.

        Returns:
            List of back edges (from, to).
        """
        return []

    def get_summary(self) -> Dict[str, Any]:
        """Get backedge summary.

        Returns:
            Dictionary with summary information.
        """
        return {
            "edges": len(self.edges),
            "back_edges": len(self.detect()),
        }


@dataclass
class DominatorTree:
    """Represents a dominator tree for a control flow graph."""

    nodes: Dict[int, int] = field(default_factory=dict)

    def __init__(self, nodes: Optional[Dict[int, int]] = None) -> None:
        """Initialize dominator tree.

        Args:
            nodes: Dictionary mapping node to its dominator.
        """
        self.nodes = nodes or {}

    def get_dominator(self, node: int) -> Optional[int]:
        """Get dominator of a node.

        Args:
            node: Node ID.

        Returns:
            Dominator node ID or None.
        """
        return self.nodes.get(node)

    def get_summary(self) -> Dict[str, Any]:
        """Get dominator tree summary.

        Returns:
            Dictionary with summary information.
        """
        return {
            "nodes": len(self.nodes),
        }


@dataclass
class DominatorTreeBuilder:
    """Builds dominator tree from control flow graph."""

    edges: List[Tuple[int, int]] = field(default_factory=list)

    def __init__(self, edges: Optional[List[Tuple[int, int]]] = None) -> None:
        """Initialize dominator tree builder.

        Args:
            edges: List of (from, to) edges.
        """
        self.edges = edges or []

    def build(self) -> DominatorTree:
        """Build dominator tree.

        Returns:
            DominatorTree instance.
        """
        return DominatorTree()

    def get_summary(self) -> Dict[str, Any]:
        """Get builder summary.

        Returns:
            Dictionary with summary information.
        """
        return {
            "edges": len(self.edges),
        }