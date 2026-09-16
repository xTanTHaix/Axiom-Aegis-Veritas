"""
AXIOM-AEGIS-VERITAS — Test Suite for Layer 2: Octagon Domain (DBM)
28 tests covering DBM, Widening, Narrowing, Dominator Tree, and edge cases.
"""

import os
import tempfile
from pathlib import Path

import pytest

from src.core.octagon_domain import DBM, OctagonConstraint, OctagonDomain
from src.core.ssa_dominator_tree import (
    DominatorTree,
    DominatorTreeBuilder,
    SSAVariable,
    SparseSSABuilder,
    BackedgeDetector,
)


# ─── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def sample_file(tmp_path):
    """Create a sample Python file for testing"""
    content = """
x = 10
y = 20
z = x + y
w = z - x
if w > 5:
    result = w * 2
else:
    result = w + 1
"""
    file_path = tmp_path / "sample.py"
    file_path.write_text(content)
    return file_path


@pytest.fixture
def simple_assignment_file(tmp_path):
    """Create a file with simple assignments"""
    content = """
a = 5
b = 10
c = a + b
"""
    file_path = tmp_path / "simple.py"
    file_path.write_text(content)
    return file_path


@pytest.fixture
def loop_file(tmp_path):
    """Create a file with a loop"""
    content = """
i = 0
while i < 10:
    i = i + 1
"""
    file_path = tmp_path / "loop.py"
    file_path.write_text(content)
    return file_path


@pytest.fixture
def empty_file(tmp_path):
    """Create an empty Python file"""
    file_path = tmp_path / "empty.py"
    file_path.write_text("")
    return file_path


@pytest.fixture
def syntax_error_file(tmp_path):
    """Create a file with syntax errors"""
    content = "def broken(\n    this is not valid\n)\nimport\n"
    file_path = tmp_path / "broken.py"
    file_path.write_text(content)
    return file_path


@pytest.fixture
def real_syntax_error_file(tmp_path):
    """Create a file with actual syntax errors"""
    content = "def broken(\n    this is not valid python syntax at all\n)"
    file_path = tmp_path / "real_broken.py"
    file_path.write_text(content)
    return file_path


@pytest.fixture
def guaranteed_syntax_error_file(tmp_path):
    """Create a file with guaranteed syntax errors (Python 3.12+)"""
    content = "def broken(\n    this is not valid\n)\nimport\n"
    file_path = tmp_path / "guaranteed_broken.py"
    file_path.write_text(content)
    return file_path


# ─── Tests: DBM ─────────────────────────────────────────────────────────────

class TestDBM:
    """Tests for DBM (Difference Bound Matrix) class"""

    def test_initialization(self):
        """Test DBM initialization with n=2"""
        dbm = DBM(2)
        assert dbm.n == 2
        assert dbm.size == 3  # 2 variables + clock

    def test_diagonal_zero(self):
        """Test that diagonal elements are 0"""
        dbm = DBM(3)
        for i in range(dbm.size):
            assert dbm.get(i, i) == 0

    def test_off_diagonal_infinity(self):
        """Test that off-diagonal elements are infinity"""
        dbm = DBM(2)
        assert dbm.get(0, 1) == float('inf')
        assert dbm.get(1, 0) == float('inf')

    def test_set_and_get(self):
        """Test setting and getting values"""
        dbm = DBM(2)
        dbm.set(0, 1, 10)
        assert dbm.get(0, 1) == 10

    def test_floyd_warshall(self):
        """Test Floyd-Warshall closure"""
        dbm = DBM(2)
        dbm.set(0, 1, 5)
        dbm.set(1, 2, 3)
        dbm.floyd_warshall()
        # After closure: DBM[0][2] should be 8
        assert dbm.get(0, 2) == 8

    def test_detect_infeasible(self):
        """Test infeasible path detection"""
        dbm = DBM(1)
        dbm.set(0, 0, -1)  # Negative self-loop
        infeasible = dbm.detect_infeasible()
        assert len(infeasible) == 1
        assert (0, 0) in infeasible

    def test_prune_infeasible(self):
        """Test pruning infeasible paths"""
        dbm = DBM(1)
        dbm.set(0, 0, -1)
        count = dbm.prune_infeasible()
        assert count == 1
        assert dbm.get(0, 0) == float('inf')

    def test_widen_operator(self):
        """Test widening operator"""
        dbm1 = DBM(2)
        dbm1.set(0, 1, 10)
        dbm2 = DBM(2)
        dbm2.set(0, 1, 20)
        widened = dbm1.widen(dbm2, max_iterations=3)
        assert widened.get(0, 1) == 20

    def test_narrow_operator(self):
        """Test narrowing operator"""
        prev = DBM(2)
        prev.set(0, 1, 20)
        curr = DBM(2)
        curr.set(0, 1, 15)
        narrowed = prev.narrow(prev, curr)
        assert narrowed.get(0, 1) == 17  # (20-15)//2 + 15 = 17

    def test_get_constraints(self):
        """Test extracting constraints"""
        dbm = DBM(2)
        dbm.set(0, 1, 10)
        constraints = dbm.get_constraints()
        assert len(constraints) > 0

    def test_get_summary(self):
        """Test getting DBM summary"""
        dbm = DBM(2)
        dbm.set(0, 1, 10)
        summary = dbm.get_summary()
        assert "n" in summary
        assert "size" in summary
        assert "infeasible_paths" in summary


# ─── Tests: OctagonConstraint ──────────────────────────────────────────────

class TestOctagonConstraint:
    """Tests for OctagonConstraint class"""

    def test_basic_constraint(self):
        """Test basic constraint creation"""
        constraint = OctagonConstraint(0, 1, 1, 1, 10)
        assert constraint.var_i == 0
        assert constraint.var_j == 1
        assert constraint.coefficient_i == 1
        assert constraint.bound == 10

    def test_to_dbm_entry(self):
        """Test adding constraint to DBM"""
        dbm = DBM(2)
        constraint = OctagonConstraint(0, 1, 1, 1, 10)
        constraint.to_dbm_entry(dbm)
        assert dbm.get(0, 1) == 10

    def test_negative_coefficient(self):
        """Test constraint with negative coefficient"""
        dbm = DBM(2)
        constraint = OctagonConstraint(0, 1, -1, 1, 10)
        constraint.to_dbm_entry(dbm)
        assert dbm.get(0, 1) == -10

    def test_repr(self):
        """Test string representation"""
        constraint = OctagonConstraint(0, 1, 1, 1, 10)
        repr_str = repr(constraint)
        assert "≤" in repr_str


# ─── Tests: OctagonDomain ──────────────────────────────────────────────────

class TestOctagonDomain:
    """Tests for OctagonDomain class"""

    def test_analyze_valid_file(self, sample_file):
        """Test analyzing a valid file"""
        domain = OctagonDomain(sample_file)
        assert domain.analyze() is True
        assert domain.dbm is not None

    def test_analyze_empty_file(self, empty_file):
        """Test analyzing an empty file"""
        domain = OctagonDomain(empty_file)
        assert domain.analyze() is True

    def test_analyze_syntax_error(self, syntax_error_file):
        """Test analyzing a file with syntax errors"""
        domain = OctagonDomain(syntax_error_file)
        assert domain.analyze() is False
        assert len(domain.errors) > 0

    def test_get_summary(self, sample_file):
        """Test getting domain summary"""
        domain = OctagonDomain(sample_file)
        domain.analyze()
        summary = domain.get_summary()
        assert "variables" in summary
        assert "constraints" in summary

    def test_get_variable_bounds(self, sample_file):
        """Test getting variable bounds"""
        domain = OctagonDomain(sample_file)
        domain.analyze()
        bounds = domain.get_variable_bounds()
        assert isinstance(bounds, dict)

    def test_widen_operator(self, sample_file):
        """Test widening operator"""
        domain1 = OctagonDomain(sample_file)
        domain1.analyze()

        domain2 = OctagonDomain(sample_file)
        domain2.analyze()

        widened = domain1.widen(domain2, max_iterations=3)
        assert widened.dbm is not None

    def test_narrow_operator(self, sample_file):
        """Test narrowing operator"""
        domain1 = OctagonDomain(sample_file)
        domain1.analyze()

        domain2 = OctagonDomain(sample_file)
        domain2.analyze()

        narrowed = domain1.narrow(domain1, domain2)
        assert narrowed.dbm is not None

    def test_get_constraints(self, sample_file):
        """Test getting extracted constraints"""
        domain = OctagonDomain(sample_file)
        domain.analyze()
        constraints = domain.get_constraints()
        assert isinstance(constraints, list)

    def test_analyze_nonexistent_file(self, tmp_path):
        """Test analyzing a nonexistent file"""
        domain = OctagonDomain(tmp_path / "nonexistent.py")
        assert domain.analyze() is False


# ─── Tests: SSA Builder ────────────────────────────────────────────────────

class TestSparseSSABuilder:
    """Tests for SparseSSABuilder class"""

    def test_build_valid_file(self, simple_assignment_file):
        """Test building SSA from valid file"""
        builder = SparseSSABuilder(simple_assignment_file)
        assert builder.build() is True
        assert len(builder.get_variables()) > 0

    def test_build_empty_file(self, empty_file):
        """Test building SSA from empty file"""
        builder = SparseSSABuilder(empty_file)
        assert builder.build() is True

    def test_build_syntax_error(self, syntax_error_file):
        """Test building SSA from file with syntax errors"""
        builder = SparseSSABuilder(syntax_error_file)
        assert builder.build() is False

    def test_get_variable_versions(self, simple_assignment_file):
        """Test getting variable versions"""
        builder = SparseSSABuilder(simple_assignment_file)
        builder.build()
        versions = builder.get_variable_versions("a")
        assert len(versions) > 0

    def test_get_current_version(self, simple_assignment_file):
        """Test getting current version"""
        builder = SparseSSABuilder(simple_assignment_file)
        builder.build()
        version = builder.get_current_version("a")
        assert version is not None

    def test_get_summary(self, simple_assignment_file):
        """Test getting SSA summary"""
        builder = SparseSSABuilder(simple_assignment_file)
        builder.build()
        summary = builder.get_summary()
        assert "unique_variables" in summary
        assert "total_versions" in summary


# ─── Tests: Dominator Tree ─────────────────────────────────────────────────

class TestDominatorTree:
    """Tests for DominatorTree class"""

    def test_initialization(self):
        """Test dominator tree initialization"""
        entries = [0]
        dominators = {0: None, 1: 0, 2: 0, 3: 1}
        tree = DominatorTree(entries, dominators)
        assert tree.get_root() == 0

    def test_get_ancestors(self):
        """Test getting ancestors"""
        entries = [0]
        dominators = {0: None, 1: 0, 2: 1, 3: 2}
        tree = DominatorTree(entries, dominators)
        ancestors = tree.get_ancestors(3)
        assert 0 in ancestors
        assert 1 in ancestors
        assert 2 in ancestors
        assert 3 in ancestors

    def test_get_immediate_dominator(self):
        """Test getting immediate dominator"""
        entries = [0]
        dominators = {0: None, 1: 0, 2: 1}
        tree = DominatorTree(entries, dominators)
        dom = tree.get_immediate_dominator(2)
        assert dom == 1

    def test_get_children(self):
        """Test getting children"""
        entries = [0]
        dominators = {0: None, 1: 0, 2: 0, 3: 1}
        tree = DominatorTree(entries, dominators)
        children = tree.get_children(0)
        assert 1 in children
        assert 2 in children

    def test_get_summary(self):
        """Test getting dominator tree summary"""
        entries = [0]
        dominators = {0: None, 1: 0, 2: 0}
        tree = DominatorTree(entries, dominators)
        summary = tree.get_summary()
        assert "root" in summary
        assert "nodes" in summary


# ─── Tests: Backedge Detector ──────────────────────────────────────────────

class TestBackedgeDetector:
    """Tests for BackedgeDetector class"""

    def test_no_backedges(self):
        """Test detecting no backedges in acyclic graph"""
        entries = [0]
        dominators = {0: None, 1: 0, 2: 1}
        tree = DominatorTree(entries, dominators)
        edges = [(0, 1), (1, 2)]
        detector = BackedgeDetector(tree, edges)
        backedges = detector.get_backedges()
        assert len(backedges) == 0

    def test_with_backedge(self):
        """Test detecting backedge in cyclic graph"""
        entries = [0]
        dominators = {0: None, 1: 0, 2: 0, 3: 1}
        tree = DominatorTree(entries, dominators)
        edges = [(0, 1), (1, 2), (2, 3), (3, 1)]  # Backedge: 3→1
        detector = BackedgeDetector(tree, edges)
        backedges = detector.get_backedges()
        assert len(backedges) > 0

    def test_get_loops(self):
        """Test extracting loops from backedges"""
        entries = [0]
        dominators = {0: None, 1: 0, 2: 0, 3: 1}
        tree = DominatorTree(entries, dominators)
        edges = [(0, 1), (1, 2), (2, 3), (3, 1)]
        detector = BackedgeDetector(tree, edges)
        loops = detector.get_loops()
        assert len(loops) > 0


# ─── Tests: DominatorTreeBuilder ───────────────────────────────────────────

class TestDominatorTreeBuilder:
    """Tests for DominatorTreeBuilder class"""

    def test_build_valid_file(self, simple_assignment_file):
        """Test building dominator tree from valid file"""
        builder = DominatorTreeBuilder(simple_assignment_file)
        assert builder.build() is True
        assert builder.get_dominator_tree() is not None

    def test_build_empty_file(self, empty_file):
        """Test building dominator tree from empty file"""
        builder = DominatorTreeBuilder(empty_file)
        assert builder.build() is True

    def test_build_syntax_error(self, syntax_error_file):
        """Test building dominator tree from file with syntax errors"""
        builder = DominatorTreeBuilder(syntax_error_file)
        assert builder.build() is False

    def test_get_summary(self, simple_assignment_file):
        """Test getting dominator tree builder summary"""
        builder = DominatorTreeBuilder(simple_assignment_file)
        builder.build()
        summary = builder.get_summary()
        assert "dominator_tree" in summary


# ─── Tests: Integration ─────────────────────────────────────────────────────

class TestIntegration:
    """Integration tests for Octagon Domain and SSA"""

    def test_full_pipeline(self, sample_file):
        """Test full analysis pipeline"""
        domain = OctagonDomain(sample_file)
        assert domain.analyze() is True
        assert domain.dbm is not None
        summary = domain.get_summary()
        assert "variables" in summary

    def test_ssa_and_dominator(self, simple_assignment_file):
        """Test SSA construction and dominator tree"""
        builder = SparseSSABuilder(simple_assignment_file)
        assert builder.build() is True
        assert len(builder.get_variables()) > 0

    def test_complex_file(self, tmp_path):
        """Test with a more complex file"""
        content = """
def calculate(a, b, c):
    x = a + b
    y = x * c
    z = y - a
    if z > 0:
        return z
    else:
        return 0
"""
        file_path = tmp_path / "complex.py"
        file_path.write_text(content)

        domain = OctagonDomain(file_path)
        assert domain.analyze() is True
        assert domain.dbm is not None
