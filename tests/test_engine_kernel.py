"""
AXIOM-AEGIS-VERITAS — Test Suite for Engine Kernel: Pipeline Driver & Orchestrator.
20 tests covering PipelineDriver, PipelineResult, EngineKernel, and pipeline orchestration.
"""

import tempfile
from pathlib import Path

import pytest

from src.core.engine_kernel import (
    EngineKernel,
    LayerTimeoutError,
    PipelineDriver,
    PipelineError,
    PipelineInterruptedError,
    PipelineResult,
)


# ─── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def sample_file(tmp_path):
    """Create a sample Python file for testing."""
    content = """
def hello(name: str) -> str:
    if name:
        return f"Hello, {name}!"
    else:
        return "Hello, World!"

class Calculator:
    def add(self, a: int, b: int) -> int:
        return a + b

    def subtract(self, a: int, b: int) -> int:
        return a - b
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
def nonexistent_file():
    """Return a path to a nonexistent file."""
    return Path("/tmp/nonexistent_12345.py")


# ─── Tests: PipelineResult ──────────────────────────────────────────────────

class TestPipelineResult:
    """Tests for PipelineResult class."""

    def test_result_creation(self):
        """Test PipelineResult creation with defaults."""
        result = PipelineResult(file_path="test.py")
        assert result.file_path == "test.py"
        assert result.success is True
        assert result.failures == []
        assert result.warnings == []
        assert result.execution_time == 0.0

    def test_result_add_layer_result(self):
        """Test adding a layer result."""
        result = PipelineResult(file_path="test.py")
        result.add_layer_result("L1", {"nodes": 10})
        assert result.get_layer_result("L1") == {"nodes": 10}

    def test_result_add_failure(self):
        """Test adding a failure."""
        result = PipelineResult(file_path="test.py")
        result.add_failure("L1", "Parse error")
        assert result.success is False
        assert len(result.failures) == 1
        assert "L1: Parse error" in result.failures[0]

    def test_result_add_warning(self):
        """Test adding a warning."""
        result = PipelineResult(file_path="test.py")
        result.add_warning("L2", "Slow analysis")
        assert len(result.warnings) == 1
        assert "L2: Slow analysis" in result.warnings[0]

    def test_result_repr(self):
        """Test PipelineResult representation."""
        result = PipelineResult(file_path="test.py", success=True)
        repr_str = repr(result)
        assert "test.py" in repr_str
        assert "success=True" in repr_str

    def test_result_to_dict(self):
        """Test converting to dictionary."""
        result = PipelineResult(
            file_path="test.py",
            success=True,
            failures=[],
            warnings=[],
            execution_time=1.5,
        )
        d = result.to_dict()
        assert d["file_path"] == "test.py"
        assert d["success"] is True
        assert d["execution_time"] == 1.5

    def test_result_get_layer_result_nonexistent(self):
        """Test getting a nonexistent layer result."""
        result = PipelineResult(file_path="test.py")
        assert result.get_layer_result("L99") is None

    def test_result_multiple_layer_results(self):
        """Test multiple layer results."""
        result = PipelineResult(file_path="test.py")
        result.add_layer_result("L1", {"nodes": 10})
        result.add_layer_result("L2", {"constraints": 5})
        result.add_layer_result("L3", {"status": "ok"})
        assert result.get_layer_result("L1") == {"nodes": 10}
        assert result.get_layer_result("L2") == {"constraints": 5}
        assert result.get_layer_result("L3") == {"status": "ok"}

    def test_result_multiple_failures(self):
        """Test multiple failures."""
        result = PipelineResult(file_path="test.py")
        result.add_failure("L1", "Error 1")
        result.add_failure("L2", "Error 2")
        assert len(result.failures) == 2
        assert result.success is False

    def test_result_multiple_warnings(self):
        """Test multiple warnings."""
        result = PipelineResult(file_path="test.py")
        result.add_warning("L1", "Warn 1")
        result.add_warning("L2", "Warn 2")
        assert len(result.warnings) == 2


# ─── Tests: PipelineDriver ──────────────────────────────────────────────────

class TestPipelineDriver:
    """Tests for PipelineDriver class."""

    def test_driver_creation(self, sample_file):
        """Test PipelineDriver creation."""
        driver = PipelineDriver(file_path=sample_file)
        assert driver is not None
        assert driver.file_path == sample_file

    def test_driver_run_pipeline(self, sample_file):
        """Test running the pipeline (may fail due to missing deps, but should not crash)."""
        driver = PipelineDriver(file_path=sample_file)
        result = driver.run_pipeline()
        assert result is not None
        assert result.file_path == str(sample_file)

    def test_driver_run_pipeline_nonexistent(self, nonexistent_file):
        """Test running pipeline on nonexistent file."""
        driver = PipelineDriver(file_path=nonexistent_file)
        result = driver.run_pipeline()
        assert result is not None
        assert result.success is False
        assert len(result.failures) > 0

    def test_driver_get_result(self, sample_file):
        """Test getting pipeline result."""
        driver = PipelineDriver(file_path=sample_file)
        driver.run_pipeline()
        result = driver.get_result()
        assert result is not None

    def test_driver_get_layer_result(self, sample_file):
        """Test getting a specific layer result."""
        driver = PipelineDriver(file_path=sample_file)
        driver.run_pipeline()
        result = driver.get_layer_result("L1")
        assert result is not None
        assert hasattr(result, 'merkle_root')

    def test_driver_get_failures(self, sample_file):
        """Test getting failures."""
        driver = PipelineDriver(file_path=sample_file)
        driver.run_pipeline()
        failures = driver.get_failures()
        assert isinstance(failures, list)

    def test_driver_get_warnings(self, sample_file):
        """Test getting warnings."""
        driver = PipelineDriver(file_path=sample_file)
        driver.run_pipeline()
        warnings = driver.get_warnings()
        assert isinstance(warnings, list)

    def test_driver_is_success(self, sample_file):
        """Test checking success."""
        driver = PipelineDriver(file_path=sample_file)
        driver.run_pipeline()
        assert driver.is_success() is not None  # Should return bool

    def test_driver_execution_time(self, sample_file):
        """Test execution time is recorded."""
        driver = PipelineDriver(file_path=sample_file)
        driver.run_pipeline()
        assert driver.results.execution_time >= 0.0

    def test_driver_repr(self, sample_file):
        """Test PipelineDriver representation."""
        driver = PipelineDriver(file_path=sample_file)
        repr_str = repr(driver)
        assert "PipelineDriver" in repr_str

    def test_driver_str(self, sample_file):
        """Test PipelineDriver string conversion."""
        driver = PipelineDriver(file_path=sample_file)
        str(driver)
        # Should not raise

    def test_driver_multiple_runs(self, sample_file):
        """Test running pipeline multiple times."""
        driver = PipelineDriver(file_path=sample_file)
        result1 = driver.run_pipeline()
        result2 = driver.run_pipeline()
        assert result1 is not None
        assert result2 is not None

    def test_driver_empty_file(self, empty_file):
        """Test running pipeline on empty file."""
        driver = PipelineDriver(file_path=empty_file)
        result = driver.run_pipeline()
        assert result is not None


# ─── Tests: EngineKernel ────────────────────────────────────────────────────

class TestEngineKernel:
    """Tests for EngineKernel class."""

    def test_kernel_creation(self):
        """Test EngineKernel creation."""
        kernel = EngineKernel(mode="test")
        assert kernel is not None
        assert kernel.mode == "test"

    def test_kernel_default_mode(self):
        """Test default execution mode."""
        kernel = EngineKernel()
        assert kernel.mode == "pipeline"

    def test_kernel_with_file_path(self, sample_file):
        """Test EngineKernel with file path."""
        kernel = EngineKernel(file_path=str(sample_file))
        assert kernel.file_path == sample_file

    def test_kernel_run_pipeline(self, sample_file):
        """Test running pipeline via EngineKernel."""
        kernel = EngineKernel(file_path=str(sample_file))
        result = kernel.run_pipeline()
        assert result is not None

    def test_kernel_analyze_file(self, sample_file):
        """Test analyze_file method."""
        kernel = EngineKernel(file_path=str(sample_file))
        result = kernel.analyze_file(str(sample_file))
        assert result is not None

    def test_kernel_analyze_directory(self, sample_file):
        """Test analyze_directory on a directory with files."""
        kernel = EngineKernel()
        results = kernel.analyze_directory(str(sample_file.parent))
        assert isinstance(results, dict)
        assert str(sample_file) in results

    def test_kernel_analyze_directory_empty(self, tmp_path):
        """Test analyze_directory on empty directory."""
        empty_dir = tmp_path / "empty_dir"
        empty_dir.mkdir()
        kernel = EngineKernel()
        results = kernel.analyze_directory(str(empty_dir))
        assert results == {}

    def test_kernel_analyze_directory_nonexistent(self, tmp_path):
        """Test analyze_directory on nonexistent directory."""
        kernel = EngineKernel()
        results = kernel.analyze_directory("/tmp/nonexistent_dir_xyz")
        assert results == {}

    def test_kernel_get_result(self, sample_file):
        """Test getting latest result."""
        kernel = EngineKernel(file_path=str(sample_file))
        kernel.run_pipeline()
        result = kernel.get_result()
        assert result is not None

    def test_kernel_get_result_before_run(self):
        """Test getting result before running pipeline."""
        kernel = EngineKernel()
        assert kernel.get_result() is None

    def test_kernel_get_failures(self, sample_file):
        """Test getting failures."""
        kernel = EngineKernel(file_path=str(sample_file))
        kernel.run_pipeline()
        failures = kernel.get_failures()
        assert isinstance(failures, list)

    def test_kernel_get_warnings(self, sample_file):
        """Test getting warnings."""
        kernel = EngineKernel(file_path=str(sample_file))
        kernel.run_pipeline()
        warnings = kernel.get_warnings()
        assert isinstance(warnings, list)

    def test_kernel_is_success(self, sample_file):
        """Test checking success."""
        kernel = EngineKernel(file_path=str(sample_file))
        kernel.run_pipeline()
        assert kernel.is_success() is not None

    def test_kernel_print_summary(self, sample_file):
        """Test printing summary (should not raise)."""
        kernel = EngineKernel(file_path=str(sample_file))
        kernel.run_pipeline()
        kernel.print_summary()
        # Should not raise

    def test_kernel_repr(self):
        """Test EngineKernel representation."""
        kernel = EngineKernel()
        repr_str = repr(kernel)
        assert "EngineKernel" in repr_str

    def test_kernel_str(self):
        """Test EngineKernel string conversion."""
        kernel = EngineKernel()
        str(kernel)
        # Should not raise


# ─── Tests: Exceptions ──────────────────────────────────────────────────────

class TestPipelineExceptions:
    """Tests for pipeline-related exceptions."""

    def test_pipeline_error(self):
        """Test PipelineError creation."""
        err = PipelineError("Test error")
        assert str(err) == "Test error"

    def test_pipeline_error_default(self):
        """Test PipelineError default message."""
        err = PipelineError()
        assert "Pipeline failed" in str(err)

    def test_layer_timeout_error(self):
        """Test LayerTimeoutError creation."""
        err = LayerTimeoutError("L1", 10.0)
        assert err.layer_name == "L1"
        assert err.timeout_sec == 10.0
        assert "L1" in str(err)

    def test_pipeline_interrupted_error(self):
        """Test PipelineInterruptedError creation."""
        err = PipelineInterruptedError("User cancelled")
        assert str(err) == "User cancelled"

    def test_layer_timeout_error_repr(self):
        """Test LayerTimeoutError representation."""
        err = LayerTimeoutError("L2", 30.0)
        repr_str = repr(err)
        assert "LayerTimeoutError" in repr_str


# ─── Tests: Defect Interception & Soundness ─────────────────────────────────

class TestDefectInterception:
    """Adversarial tests ensuring semantic bugs fail pipeline verification."""

    def test_pipeline_driver_fails_on_division_by_zero(self, tmp_path):
        """Ensure code containing division by zero is flagged as FAIL, not PASS."""
        buggy_file = tmp_path / "div_zero.py"
        buggy_file.write_text("def compute(x: int) -> float:\n    return x / 0\n")

        driver = PipelineDriver(file_path=buggy_file)
        result = driver.run_pipeline()

        assert result.success is False
        assert len(result.failures) > 0
        assert any("division_by_zero" in f.lower() or "division by zero" in f.lower() for f in result.failures)
        assert result.attestation_seal is not None
        assert result.attestation_seal.is_complete is False
        assert "L6" in result.attestation_seal.missing_layers

    def test_mcp_server_reports_defect_failure(self, tmp_path):
        """Ensure MCP server reports VERIFICATION_FAILED with details for buggy file."""
        from src.mcp.server import AxiomMCPServer
        buggy_file = tmp_path / "empty_cmp.py"
        buggy_file.write_text("def check(s: str) -> bool:\n    return s == ''\n")

        server = AxiomMCPServer()
        res = server.verify_file(str(buggy_file))

        assert res["success"] is False
        assert res["status"] == "VERIFICATION_FAILED"
        assert res["is_complete_7layers"] is False
        assert len(res["failures"]) > 0
        assert "L6" in res["missing_layers"]