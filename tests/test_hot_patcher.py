"""
AXIOM-AEGIS-VERITAS — Test Suite for Layer 6: Hot Patcher.
20 tests covering MCS generation, counterfactual patching, and tree edit distance.
"""

import ast
import os
import tempfile
from pathlib import Path

import pytest

from src.core.hot_patcher import (
    MCSGenerator,
    MCS,
    Clause,
    CounterfactualPatchSynthesizer,
    TreeEditDistance,
    MCSGenerationError,
    PatchSynthesisError,
    EditDistanceError,
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


# ─── Tests: MCSGenerator ───────────────────────────────────────────────────

class TestMCSGenerator:
    """Tests for MCSGenerator class."""

    def test_basic_mcs_generation(self, sample_file):
        """Test basic MCS generation."""
        generator = MCSGenerator(sample_file)
        mcs = generator.generate()
        assert isinstance(mcs, list)
        assert len(mcs) > 0

    def test_mcs_clauses(self, sample_file):
        """Test MCS clause generation."""
        generator = MCSGenerator(sample_file)
        mcs = generator.generate()
        # Verify each item is an MCS object
        assert all(isinstance(mcs_item, MCS) for mcs_item in mcs)

    def test_mcs_size(self, sample_file):
        """Test MCS size calculation."""
        generator = MCSGenerator(sample_file)
        mcs = generator.generate()
        # Verify each MCS has valid size
        assert all(mcs_item.size >= 0 for mcs_item in mcs)

    def test_mcs_empty_file(self, empty_file):
        """Test MCS generation on empty file."""
        generator = MCSGenerator(empty_file)
        with pytest.raises(MCSGenerationError):
            generator.generate()

    def test_mcs_syntax_error_file(self, syntax_error_file):
        """Test MCS generation on file with syntax errors."""
        generator = MCSGenerator(syntax_error_file)
        with pytest.raises(MCSGenerationError):
            generator.generate()

    def test_mcs_complex_file(self, complex_file):
        """Test MCS generation on complex file."""
        generator = MCSGenerator(complex_file)
        mcs = generator.generate()
        assert isinstance(mcs, list)
        assert len(mcs) > 0
        # Verify each MCS has clauses attribute
        assert all(hasattr(mcs_item, 'clauses') for mcs_item in mcs)

    def test_mcs_to_list(self, sample_file):
        """Test MCS to list conversion."""
        generator = MCSGenerator(sample_file)
        mcs = generator.generate()
        assert len(mcs) > 0
        # Convert each MCS to list and verify
        for mcs_item in mcs:
            clause_list = mcs_item.to_list()
            assert isinstance(clause_list, list)
            assert clause_list == sorted(clause_list)

    def test_mcs_repr(self, sample_file):
        """Test MCS representation."""
        generator = MCSGenerator(sample_file)
        mcs = generator.generate()
        assert len(mcs) > 0
        # Verify repr contains expected elements
        repr_str = repr(mcs[0])
        assert "MCS" in repr_str
        assert "clauses" in repr_str

    def test_mcs_count(self, sample_file):
        """Test MCS count."""
        generator = MCSGenerator(sample_file)
        mcs = generator.generate()
        assert len(mcs) >= 1

    def test_multiple_generations(self, sample_file):
        """Test multiple MCS generation operations."""
        generator = MCSGenerator(sample_file)
        mcs_list = [generator.generate() for _ in range(5)]
        assert all(isinstance(m, list) for m in mcs_list)


# ─── Tests: CounterfactualPatchSynthesizer ─────────────────────────────────

class TestCounterfactualPatchSynthesizer:
    """Tests for CounterfactualPatchSynthesizer class."""

    def test_basic_patch_synthesis(self, sample_file):
        """Test basic patch synthesis."""
        synthesizer = CounterfactualPatchSynthesizer(sample_file)
        patches = synthesizer.synthesize()
        assert isinstance(patches, list)
        assert len(patches) > 0

    def test_patch_quality(self, sample_file):
        """Test patch quality calculation."""
        synthesizer = CounterfactualPatchSynthesizer(sample_file)
        patches = synthesizer.synthesize()
        assert all(hasattr(p, "quality") for p in patches)

    def test_patch_size(self, sample_file):
        """Test patch size calculation."""
        synthesizer = CounterfactualPatchSynthesizer(sample_file)
        patches = synthesizer.synthesize()
        assert all(hasattr(p, "size") for p in patches)

    def test_empty_file_patches(self, empty_file):
        """Test patch synthesis on empty file."""
        synthesizer = CounterfactualPatchSynthesizer(empty_file)
        with pytest.raises(PatchSynthesisError):
            synthesizer.synthesize()

    def test_syntax_error_file_patches(self, syntax_error_file):
        """Test patch synthesis on file with syntax errors."""
        synthesizer = CounterfactualPatchSynthesizer(syntax_error_file)
        with pytest.raises(PatchSynthesisError):
            synthesizer.synthesize()

    def test_complex_file_patches(self, complex_file):
        """Test patch synthesis on complex file."""
        synthesizer = CounterfactualPatchSynthesizer(complex_file)
        patches = synthesizer.synthesize()
        assert isinstance(patches, list)
        assert len(patches) > 0

    def test_patch_count(self, sample_file):
        """Test patch count."""
        synthesizer = CounterfactualPatchSynthesizer(sample_file)
        patches = synthesizer.synthesize()
        assert len(patches) >= 1

    def test_patch_repr(self, sample_file):
        """Test patch representation."""
        synthesizer = CounterfactualPatchSynthesizer(sample_file)
        patches = synthesizer.synthesize()
        assert len(patches) > 0
        # Verify repr contains expected elements
        repr_str = repr(patches[0])
        assert "Patch" in repr_str


# ─── Tests: TreeEditDistance ───────────────────────────────────────────────

class TestTreeEditDistance:
    """Tests for TreeEditDistance class."""

    def test_empty_trees(self):
        """Test edit distance between empty trees."""
        distance = TreeEditDistance()
        result = distance.calculate("", "")
        assert result == 0

    def test_identical_trees(self):
        """Test edit distance between identical trees."""
        distance = TreeEditDistance()
        code1 = "x = 1\ny = 2"
        code2 = "x = 1\ny = 2"
        result = distance.compute(ast.parse(code1), ast.parse(code2))
        assert result.distance == 0

    def test_different_trees(self):
        """Test edit distance between different trees."""
        distance = TreeEditDistance()
        code1 = "x = 1"
        code2 = "x = 2"
        result = distance.compute(ast.parse(code1), ast.parse(code2))
        assert result.distance > 0

    def test_empty_vs_nonempty(self):
        """Test edit distance between empty and non-empty trees."""
        distance = TreeEditDistance()
        result = distance.compute(ast.parse(""), ast.parse("x = 1"))
        assert result.distance > 0


# ─── Tests: TreeEditDistanceError ──────────────────────────────────────────

class TestEditDistanceError:
    """Tests for EditDistanceError class."""

    def test_error_raised_on_invalid_input(self):
        """Test that error is raised on invalid input."""
        distance = TreeEditDistance()
        with pytest.raises(EditDistanceError):
            distance.compute(None, ast.parse("x = 1"))