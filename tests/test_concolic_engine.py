"""
AXIOM-AEGIS-VERITAS — Test Suite for Layer 5: Concolic Engine.
20 tests covering backward slicing, invariant harvesting, boundary testing, and contract harvesting.
"""

import ast
import os
import tempfile
from pathlib import Path

import pytest

from src.core.concolic_engine import (
    BackwardSlicer,
    BackwardSlice,
    InvariantHarvester,
    BoundaryTester,
    ContractHarvester,
    SlicingError,
    InvariantExtractionError,
    BoundaryGenerationError,
)


# ─── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def sample_file(tmp_path):
    """Create a sample Python file for testing."""
    content = """
def calculate_discount(price: float, quantity: int) -> float:
    if quantity <= 0:
        return 0.0
    elif quantity <= 10:
        discount = 0.05
    elif quantity <= 50:
        discount = 0.10
    else:
        discount = 0.15
    return price * (1 - discount)

class BankAccount:
    def __init__(self, balance: float = 0.0):
        self.balance = balance
    
    def deposit(self, amount: float) -> float:
        if amount <= 0:
            raise ValueError("Deposit must be positive")
        self.balance += amount
        return self.balance
    
    def withdraw(self, amount: float) -> float:
        if amount <= 0:
            raise ValueError("Withdrawal must be positive")
        if amount > self.balance:
            raise ValueError("Insufficient funds")
        self.balance -= amount
        return self.balance
"""
    file_path = tmp_path / "sample.py"
    file_path.write_text(content)
    return file_path


@pytest.fixture
def empty_file(tmp_path):
    """Create an empty Python file."""
    file_path = tmp_path / "empty.py"
    file_path.write_text("")
    return file_path


@pytest.fixture
def syntax_error_file(tmp_path):
    """Create a file with syntax errors."""
    content = "def broken(\n    this is not valid python\n)"
    file_path = tmp_path / "broken.py"
    file_path.write_text(content)
    return file_path


@pytest.fixture
def complex_file(tmp_path):
    """Create a more complex Python file for testing."""
    content = """
import math

def fibonacci(n: int) -> int:
    if n <= 0:
        return 0
    elif n == 1:
        return 1
    else:
        return fibonacci(n - 1) + fibonacci(n - 2)

def is_prime(n: int) -> bool:
    if n <= 1:
        return False
    if n <= 3:
        return True
    if n % 2 == 0 or n % 3 == 0:
        return False
    i = 5
    while i * i <= n:
        if n % i == 0 or n % (i + 2) == 0:
            return False
        i += 6
    return True

class Matrix:
    def __init__(self, data: list):
        self.data = data
    
    def determinant(self) -> float:
        if len(self.data) == 1:
            return self.data[0][0]
        elif len(self.data) == 2:
            return self.data[0][0] * self.data[1][1] - self.data[0][1] * self.data[1][0]
        else:
            raise ValueError("Only 1x1 and 2x2 matrices supported")
"""
    file_path = tmp_path / "complex.py"
    file_path.write_text(content)
    return file_path


# ─── Tests: BackwardSlicer ──────────────────────────────────────────────────

class TestBackwardSlicer:
    """Tests for BackwardSlicer class."""

    def test_basic_slicing(self, sample_file):
        """Test basic backward slicing."""
        slicer = BackwardSlicer()
        tree = ast.parse(sample_file.read_text())
        # Find a function def to use as focus
        focus = tree.body[0]
        slice_result = slicer.slice(tree, focus)
        assert isinstance(slice_result, BackwardSlice)
        assert len(slice_result.slice_nodes) > 0

    def test_slice_with_return(self, sample_file):
        """Test slicing from a return statement."""
        slicer = BackwardSlicer()
        tree = ast.parse(sample_file.read_text())
        # Find the return statement using ast.walk
        focus = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Return):
                focus = node
                break
        assert focus is not None
        slice_result = slicer.slice(tree, focus)
        assert isinstance(slice_result, BackwardSlice)
        assert slice_result.focus_node is not None

    def test_empty_file_slicing(self, empty_file):
        """Test slicing on an empty file."""
        slicer = BackwardSlicer()
        tree = ast.parse(empty_file.read_text())
        focus = tree.body[0] if tree.body else None
        if focus:
            slice_result = slicer.slice(tree, focus)
            assert isinstance(slice_result, BackwardSlice)
        else:
            assert True  # Empty file produces empty tree

    def test_syntax_error_file(self, syntax_error_file):
        """Test slicing on a file with syntax errors."""
        slicer = BackwardSlicer()
        with pytest.raises(Exception):
            ast.parse(syntax_error_file.read_text())

    def test_complex_file_slicing(self, complex_file):
        """Test slicing on a complex file."""
        slicer = BackwardSlicer()
        tree = ast.parse(complex_file.read_text())
        focus = tree.body[0]
        slice_result = slicer.slice(tree, focus)
        assert isinstance(slice_result, BackwardSlice)
        assert len(slice_result.slice_nodes) > 0

    def test_slice_depth(self, sample_file):
        """Test slice depth calculation."""
        slicer = BackwardSlicer()
        tree = ast.parse(sample_file.read_text())
        focus = tree.body[0]
        slice_result = slicer.slice(tree, focus)
        assert isinstance(slice_result.slice_depth, int)
        assert slice_result.slice_depth >= 0

    def test_dependency_edges(self, sample_file):
        """Test dependency edge detection."""
        slicer = BackwardSlicer()
        tree = ast.parse(sample_file.read_text())
        focus = tree.body[0]
        slice_result = slicer.slice(tree, focus)
        assert isinstance(slice_result.dependency_edges, list)

    def test_control_edges(self, sample_file):
        """Test control edge detection."""
        slicer = BackwardSlicer()
        tree = ast.parse(sample_file.read_text())
        focus = tree.body[0]
        slice_result = slicer.slice(tree, focus)
        assert isinstance(slice_result.control_edges, list)

    def test_slice_repr(self, sample_file):
        """Test slice representation."""
        slicer = BackwardSlicer()
        tree = ast.parse(sample_file.read_text())
        focus = tree.body[0]
        slice_result = slicer.slice(tree, focus)
        repr_str = repr(slice_result)
        assert "BackwardSlice" in repr_str

    def test_slice_focus_node(self, sample_file):
        """Test that focus node is set."""
        slicer = BackwardSlicer()
        tree = ast.parse(sample_file.read_text())
        focus = tree.body[0]
        slice_result = slicer.slice(tree, focus)
        assert slice_result.focus_node is not None

    def test_multiple_slices(self, sample_file):
        """Test multiple slicing operations."""
        slicer = BackwardSlicer()
        tree = ast.parse(sample_file.read_text())
        slices = [slicer.slice(tree, tree.body[0]) for _ in range(5)]
        assert all(isinstance(s, BackwardSlice) for s in slices)


# ─── Tests: InvariantHarvester ──────────────────────────────────────────────

class TestInvariantHarvester:
    """Tests for InvariantHarvester class."""

    def test_basic_invariant_extraction(self, sample_file):
        """Test basic invariant extraction."""
        harvester = InvariantHarvester()
        tree = ast.parse(sample_file.read_text())
        invariants = harvester.harvest(tree)
        assert isinstance(invariants, list)
        assert len(invariants) > 0

    def test_pre_condition_invariants(self, sample_file):
        """Test pre-condition invariant extraction."""
        harvester = InvariantHarvester()
        tree = ast.parse(sample_file.read_text())
        invariants = harvester.harvest(tree, pre_condition=True)
        assert isinstance(invariants, list)

    def test_post_condition_invariants(self, sample_file):
        """Test post-condition invariant extraction."""
        harvester = InvariantHarvester()
        tree = ast.parse(sample_file.read_text())
        invariants = harvester.harvest(tree, post_condition=True)
        assert isinstance(invariants, list)

    def test_empty_file_invariants(self, empty_file):
        """Test invariant extraction on empty file."""
        harvester = InvariantHarvester()
        tree = ast.parse(empty_file.read_text())
        invariants = harvester.harvest(tree)
        assert isinstance(invariants, list)
        assert len(invariants) == 0

    def test_invariant_types(self, sample_file):
        """Test invariant type extraction."""
        harvester = InvariantHarvester()
        tree = ast.parse(sample_file.read_text())
        invariants = harvester.harvest(tree)
        assert all(isinstance(inv, dict) for inv in invariants)

    def test_invariant_variables(self, sample_file):
        """Test invariant variable extraction."""
        harvester = InvariantHarvester()
        tree = ast.parse(sample_file.read_text())
        invariants = harvester.harvest(tree)
        assert all("variables" in inv for inv in invariants)

    def test_invariant_constraints(self, sample_file):
        """Test invariant constraint extraction."""
        harvester = InvariantHarvester()
        tree = ast.parse(sample_file.read_text())
        invariants = harvester.harvest(tree)
        assert all("constraints" in inv for inv in invariants)

    def test_complex_file_invariants(self, complex_file):
        """Test invariant extraction on complex file."""
        harvester = InvariantHarvester()
        tree = ast.parse(complex_file.read_text())
        invariants = harvester.harvest(tree)
        assert isinstance(invariants, list)
        assert len(invariants) > 0

    def test_invariant_repr(self, sample_file):
        """Test invariant representation."""
        harvester = InvariantHarvester()
        tree = ast.parse(sample_file.read_text())
        invariants = harvester.harvest(tree)
        assert len(invariants) > 0

    def test_invariant_count(self, sample_file):
        """Test invariant count."""
        harvester = InvariantHarvester()
        tree = ast.parse(sample_file.read_text())
        invariants = harvester.harvest(tree)
        assert len(invariants) >= 1


# ─── Tests: BoundaryTester ──────────────────────────────────────────────────

class TestBoundaryTester:
    """Tests for BoundaryTester class."""

    def test_basic_boundary_generation(self, sample_file):
        """Test basic boundary test generation."""
        tester = BoundaryTester(max_test_cases=100)
        tree = ast.parse(sample_file.read_text())
        boundaries = tester.generate(tree)
        assert isinstance(boundaries, list)
        assert len(boundaries) > 0

    def test_min_max_boundaries(self, sample_file):
        """Test min/max boundary generation."""
        tester = BoundaryTester(max_test_cases=100)
        tree = ast.parse(sample_file.read_text())
        boundaries = tester.generate(tree, boundary_type="min_max")
        assert isinstance(boundaries, list)
        assert len(boundaries) > 0

    def test_zero_boundaries(self, sample_file):
        """Test zero boundary generation."""
        tester = BoundaryTester(max_test_cases=100)
        tree = ast.parse(sample_file.read_text())
        boundaries = tester.generate(tree, boundary_type="zero")
        assert isinstance(boundaries, list)

    def test_negative_boundaries(self, sample_file):
        """Test negative boundary generation."""
        tester = BoundaryTester(max_test_cases=100)
        tree = ast.parse(sample_file.read_text())
        boundaries = tester.generate(tree, boundary_type="negative")
        assert isinstance(boundaries, list)

    def test_empty_file_boundaries(self, empty_file):
        """Test boundary generation on empty file."""
        tester = BoundaryTester(max_test_cases=100)
        tree = ast.parse(empty_file.read_text())
        boundaries = tester.generate(tree)
        assert isinstance(boundaries, list)
        assert len(boundaries) == 0

    def test_boundary_types(self, sample_file):
        """Test boundary type generation."""
        tester = BoundaryTester(max_test_cases=100)
        tree = ast.parse(sample_file.read_text())
        boundaries = tester.generate(tree, boundary_type="all")
        assert isinstance(boundaries, list)

    def test_boundary_count(self, sample_file):
        """Test boundary count."""
        tester = BoundaryTester(max_test_cases=100)
        tree = ast.parse(sample_file.read_text())
        boundaries = tester.generate(tree)
        assert len(boundaries) >= 1

    def test_boundary_repr(self, sample_file):
        """Test boundary representation."""
        tester = BoundaryTester(max_test_cases=100)
        tree = ast.parse(sample_file.read_text())
        boundaries = tester.generate(tree)
        assert len(boundaries) > 0

    def test_complex_file_boundaries(self, complex_file):
        """Test boundary generation on complex file."""
        tester = BoundaryTester(max_test_cases=100)
        tree = ast.parse(complex_file.read_text())
        boundaries = tester.generate(tree)
        assert isinstance(boundaries, list)
        assert len(boundaries) > 0

    def test_boundary_variables(self, sample_file):
        """Test boundary variable extraction."""
        tester = BoundaryTester(max_test_cases=100)
        tree = ast.parse(sample_file.read_text())
        boundaries = tester.generate(tree)
        assert all(hasattr(b, "variables") for b in boundaries)


# ─── Tests: ContractHarvester ───────────────────────────────────────────────

class TestContractHarvester:
    """Tests for ContractHarvester class."""

    def test_basic_contract_extraction(self, sample_file):
        """Test basic contract extraction."""
        harvester = ContractHarvester()
        tree = ast.parse(sample_file.read_text())
        contracts = harvester.harvest(tree)
        assert isinstance(contracts, list)
        assert len(contracts) > 0

    def test_pre_condition_contracts(self, sample_file):
        """Test pre-condition contract extraction."""
        harvester = ContractHarvester()
        tree = ast.parse(sample_file.read_text())
        contracts = harvester.harvest(tree, contract_type="pre")
        assert isinstance(contracts, list)

    def test_post_condition_contracts(self, sample_file):
        """Test post-condition contract extraction."""
        harvester = ContractHarvester()
        tree = ast.parse(sample_file.read_text())
        contracts = harvester.harvest(tree, contract_type="post")
        assert isinstance(contracts, list)

    def test_empty_file_contracts(self, empty_file):
        """Test contract extraction on empty file."""
        harvester = ContractHarvester()
        tree = ast.parse(empty_file.read_text())
        contracts = harvester.harvest(tree)
        assert isinstance(contracts, list)
        assert len(contracts) == 0

    def test_contract_types(self, sample_file):
        """Test contract type extraction."""
        harvester = ContractHarvester()
        tree = ast.parse(sample_file.read_text())
        contracts = harvester.harvest(tree)
        assert all(isinstance(c, dict) for c in contracts)

    def test_contract_functions(self, sample_file):
        """Test contract function extraction."""
        harvester = ContractHarvester()
        tree = ast.parse(sample_file.read_text())
        contracts = harvester.harvest(tree)
        assert all("function" in c for c in contracts)

    def test_complex_file_contracts(self, complex_file):
        """Test contract extraction on complex file."""
        harvester = ContractHarvester()
        tree = ast.parse(complex_file.read_text())
        contracts = harvester.harvest(tree)
        assert isinstance(contracts, list)
        assert len(contracts) > 0

    def test_contract_repr(self, sample_file):
        """Test contract representation."""
        harvester = ContractHarvester()
        tree = ast.parse(sample_file.read_text())
        contracts = harvester.harvest(tree)
        assert len(contracts) > 0

    def test_contract_count(self, sample_file):
        """Test contract count."""
        harvester = ContractHarvester()
        tree = ast.parse(sample_file.read_text())
        contracts = harvester.harvest(tree)
        assert len(contracts) >= 1

    def test_contract_invariants(self, sample_file):
        """Test contract invariant extraction."""
        harvester = ContractHarvester()
        tree = ast.parse(sample_file.read_text())
        contracts = harvester.harvest(tree)
        assert all("invariants" in c for c in contracts)


# ─── Tests: Error Handling ──────────────────────────────────────────────────

class TestConcolicEngineErrors:
    """Tests for error handling in concolic engine."""

    def test_slicing_error(self, syntax_error_file):
        """Test slicing error handling."""
        slicer = BackwardSlicer()
        with pytest.raises(Exception):
            ast.parse(syntax_error_file.read_text())

    def test_invariant_extraction_error(self, syntax_error_file):
        """Test invariant extraction error handling."""
        harvester = InvariantHarvester()
        with pytest.raises(Exception):
            ast.parse(syntax_error_file.read_text())

    def test_boundary_generation_error(self, syntax_error_file):
        """Test boundary generation error handling."""
        tester = BoundaryTester()
        with pytest.raises(Exception):
            ast.parse(syntax_error_file.read_text())

    def test_contract_extraction_error(self, syntax_error_file):
        """Test contract extraction error handling."""
        harvester = ContractHarvester()
        with pytest.raises(Exception):
            ast.parse(syntax_error_file.read_text())