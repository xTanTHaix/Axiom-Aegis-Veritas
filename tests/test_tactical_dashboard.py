"""
Tests for Tactical Terminal CUI Dashboard v1.1.0.

Validates:
- ProcessMonitor resource telemetry sampling.
- ANSI escape width calculation and visual padding alignment.
- Sparkline generator accuracy.
- Frame layout rendering invariants.
- Event feed queue handling.
"""

from __future__ import annotations

import re
from src.cui.tactical_dashboard import (
    ProcessMonitor,
    TacticalDashboard,
    build_sparkline,
    pad_visible,
    visible_len,
)


def test_process_monitor_sample() -> None:
    """Verify that ProcessMonitor samples real or fallback resource metrics."""
    monitor = ProcessMonitor()
    sample = monitor.sample()

    assert "pid" in sample
    assert "cpu" in sample
    assert "rss_mb" in sample
    assert "threads" in sample
    assert "history" in sample
    assert isinstance(sample["history"], list)
    assert len(sample["history"]) >= 1


def test_visible_len_ansi_stripping() -> None:
    """Verify that ANSI color codes are ignored when measuring string length."""
    colored_text = "\033[36m[STATUS: LIVE]\033[0m"
    clean_text = "[STATUS: LIVE]"

    assert visible_len(colored_text) == len(clean_text)
    assert visible_len(colored_text) == 14


def test_pad_visible_alignment() -> None:
    """Verify that pad_visible pads characters correctly based on visible width."""
    colored_text = "\033[32mPASS\033[0m"  # Visible length is 4 ("PASS")
    padded = pad_visible(colored_text, 10)

    # Visible length of padded text should be exactly 10
    assert visible_len(padded) == 10
    # Should end with 6 spaces
    assert padded.endswith(" " * 6)


def test_build_sparkline() -> None:
    """Verify sparkline rendering from numerical values."""
    history = [0.0, 25.0, 50.0, 75.0, 100.0]
    sparkline = build_sparkline(history)

    assert len(sparkline) == len(history)
    assert sparkline[0] == " "
    assert sparkline[-1] == "█"


def test_tactical_dashboard_render_frame() -> None:
    """Verify that render produces the complete tactical frame."""
    dashboard = TacticalDashboard()
    dashboard.add_feed_event("Unit test audit event.")

    frame = dashboard.render(
        current_target="src/core/test.py",
        done_files=5,
        total_files=10,
        total_lines=1200,
        scan_rate=15.5,
        scan_line_idx=1,
        status_label="TEST_MODE",
    )

    assert "KERNEL-SCANNER // PYTHON AST AUDITOR v1.1.0" in frame
    assert "PROCESS TELEMETRY" in frame
    assert "Unit test audit event." in frame
    assert "src/core/test.py" in frame
    assert "50.0% 5/10 FILES" in frame


def test_tactical_dashboard_standby_mode() -> None:
    """Verify that standby frame renders instruction snippet and STANDBY status."""
    from src.cui.tactical_dashboard import STANDBY_SNIPPET
    dashboard = TacticalDashboard()

    frame = dashboard.render(
        current_target="AWAITING TARGET PATH",
        done_files=0,
        total_files=0,
        total_lines=0,
        scan_rate=0.0,
        code_snippet=STANDBY_SNIPPET,
        scan_line_idx=-1,
        status_label="STANDBY",
    )

    assert "STATUS: STANDBY" in frame
    assert "AWAITING TARGET PATH" in frame
    assert "AXIOM-AEGIS-VERITAS v1.1.0" in frame


def test_tactical_dashboard_pytest_summary_bar() -> None:
    """Verify that render produces a pytest-style colorful summary bar when provided."""
    dashboard = TacticalDashboard()

    frame = dashboard.render(
        current_target="SCAN COMPLETE: src",
        done_files=10,
        total_files=10,
        total_lines=1500,
        scan_rate=20.0,
        status_label="READY",
        status_summary={
            "passed": 9,
            "failed": 1,
            "total": 10,
            "elapsed": 1.25,
        },
    )

    assert "9 PASSED" in frame
    assert "1 FAILED" in frame
    assert "10 FILES [1.25s]" in frame


def test_tactical_dashboard_layer8_breakdown() -> None:
    """Verify that render displays the Layer 8 Attestation Breakdown when failures occur."""
    dashboard = TacticalDashboard()

    failed_details = [
        {"file": "test_thread_pool.py", "missing_layers": ["L6"], "reasons": {"L6": "Race condition detected"}},
        {"file": "bad_syntax.py", "missing_layers": ["L1", "L3"], "reasons": {}},
    ]

    frame = dashboard.render(
        current_target="SCAN COMPLETE: tests",
        done_files=10,
        total_files=10,
        total_lines=1500,
        scan_rate=20.0,
        status_label="READY",
        status_summary={
            "passed": 8,
            "failed": 2,
            "total": 10,
            "elapsed": 1.50,
            "failed_details": failed_details,
        },
    )

    assert "LAYER 8 ATTESTATION BREAKDOWN (FAILED VERIFICATION LAYERS):" in frame
    assert "test_thread_pool.py" in frame
    assert "Failed: [L6]" in frame
    assert "bad_syntax.py" in frame
    assert "Failed: [L1, L3]" in frame

