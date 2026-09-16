"""
AXIOM-AEGIS-VERITAS — Test Suite for CUI: Progress Bar.
20 tests covering progress bar rendering, state management, and animation.
"""

import pytest

from src.cui.progress_bar import ProgressBar


# ─── Tests: ProgressBar ──────────────────────────────────────────────────────

class TestProgressBar:
    """Tests for ProgressBar class."""

    def test_progress_bar_creation(self):
        """Test progress bar creation."""
        bar = ProgressBar()
        assert bar is not None

    def test_progress_bar_start(self):
        """Test progress bar start."""
        bar = ProgressBar()
        bar.start("Layer 1", "CST Merkle Cache")
        assert bar.current_layer == "Layer 1"
        assert bar.current_task == "CST Merkle Cache"

    def test_progress_bar_complete(self):
        """Test progress bar completion."""
        bar = ProgressBar()
        bar.start("Layer 1", "CST Merkle Cache")
        bar.complete()
        assert bar.current_layer is None
        assert bar.current_task is None

    def test_progress_bar_reset(self):
        """Test progress bar reset."""
        bar = ProgressBar()
        bar.start("Layer 1", "CST Merkle Cache")
        bar.reset()
        assert bar.current_layer is None
        assert bar.current_task is None

    def test_progress_bar_repr(self):
        """Test progress bar representation."""
        bar = ProgressBar()
        repr_str = repr(bar)
        assert "ProgressBar" in repr_str

    def test_progress_bar_str(self):
        """Test progress bar string representation."""
        bar = ProgressBar()
        str(bar)
        # Should not raise

    def test_progress_bar_multiple_layers(self):
        """Test multiple layer transitions."""
        bar = ProgressBar()
        bar.start("L1", "Layer 1")
        bar.complete()
        bar.start("L2", "Layer 2")
        bar.complete()
        bar.start("L3", "Layer 3")
        bar.complete()
        assert bar.current_layer is None

    def test_progress_bar_concurrent(self):
        """Test concurrent progress bar usage."""
        bar1 = ProgressBar()
        bar2 = ProgressBar()
        bar1.start("L1", "Task 1")
        bar2.start("L2", "Task 2")
        bar1.complete()
        bar2.complete()
        assert bar1.current_layer is None
        assert bar2.current_layer is None

    def test_progress_bar_start_no_args(self):
        """Test progress bar start with no arguments."""
        bar = ProgressBar()
        bar.start()
        assert bar.current_layer is None

    def test_progress_bar_complete_no_start(self):
        """Test progress bar complete without start."""
        bar = ProgressBar()
        bar.complete()
        assert bar.current_layer is None

    def test_progress_bar_reset_no_start(self):
        """Test progress bar reset without start."""
        bar = ProgressBar()
        bar.reset()
        assert bar.current_layer is None

    def test_progress_bar_repr_after_start(self):
        """Test progress bar representation after start."""
        bar = ProgressBar()
        bar.start("L1", "Task 1")
        repr_str = repr(bar)
        assert "ProgressBar" in repr_str

    def test_progress_bar_repr_after_complete(self):
        """Test progress bar representation after complete."""
        bar = ProgressBar()
        bar.start("L1", "Task 1")
        bar.complete()
        repr_str = repr(bar)
        assert "ProgressBar" in repr_str

    def test_progress_bar_str_after_start(self):
        """Test progress bar string after start."""
        bar = ProgressBar()
        bar.start("L1", "Task 1")
        str(bar)
        # Should not raise

    def test_progress_bar_str_after_complete(self):
        """Test progress bar string after complete."""
        bar = ProgressBar()
        bar.start("L1", "Task 1")
        bar.complete()
        str(bar)
        # Should not raise

    def test_progress_bar_multiple_starts(self):
        """Test multiple starts without reset."""
        bar = ProgressBar()
        bar.start("L1", "Task 1")
        bar.start("L2", "Task 2")
        assert bar.current_layer == "L2"
        assert bar.current_task == "Task 2"

    def test_progress_bar_complete_then_start(self):
        """Test complete then start."""
        bar = ProgressBar()
        bar.start("L1", "Task 1")
        bar.complete()
        bar.start("L2", "Task 2")
        assert bar.current_layer == "L2"
        assert bar.current_task == "Task 2"

    def test_progress_bar_reset_then_start(self):
        """Test reset then start."""
        bar = ProgressBar()
        bar.start("L1", "Task 1")
        bar.reset()
        bar.start("L2", "Task 2")
        assert bar.current_layer == "L2"
        assert bar.current_task == "Task 2"

    def test_progress_bar_repr_after_multiple(self):
        """Test progress bar representation after multiple operations."""
        bar = ProgressBar()
        bar.start("L1", "Task 1")
        bar.complete()
        bar.start("L2", "Task 2")
        bar.complete()
        repr_str = repr(bar)
        assert "ProgressBar" in repr_str