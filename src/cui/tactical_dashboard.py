"""
AXIOM-AEGIS-VERITAS — Tactical Terminal CUI Dashboard v1.1.0.

High-Density Visual Console Scanner & Process Telemetry Dashboard.
Features:
- ANSI Escape Code width compensation (visible_len / pad_visible) ensuring zero border drift.
- Real-time Process Telemetry: Live CPU Sparkline, RSS Memory (MB), Worker Threads.
- Left Pane: Dynamic Python AST Buffer with scanning laser indicator (▶▶).
- Right Pane: Codebase profile metrics and resource gauges.
- Bottom Feed: Live streaming event log with status spinners and Layer 8 attestation seals.
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import sys
import time
import unicodedata
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None
    PSUTIL_AVAILABLE = False


# Tactical visual glyphs & activity indicators
SPINNERS = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
BAR_CHARS = [" ", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
ANSI_REGEX = re.compile(r"\x1b\[[0-9;]*m")

DEFAULT_CODE_SNIPPET = [
    "def audit_ast_node(node: ast.AST, ctx: ScanContext) -> list[Issue]:",
    "    issues = []",
    "    if isinstance(node, ast.Call):",
    "        if is_unsafe_eval(node.func):",
    "            issues.append(Issue.critical('DYN_EXEC', node.lineno))",
    "    elif isinstance(node, ast.ImportFrom):",
    "        if node.module in BLACKLISTED_DEPS:",
    "            issues.append(Issue.high('INSECURE_DEP', node.lineno))",
    "    for child in ast.iter_child_nodes(node):",
    "        issues.extend(audit_ast_node(child, ctx))",
    "    return issues",
]

STANDBY_SNIPPET = [
    "# AXIOM-AEGIS-VERITAS v1.1.0 — Interactive Standby Mode",
    "# ------------------------------------------------------",
    "# Type or paste file/folder path below to begin scan.",
    "# Example: src, tests, cli.py, or any project path.",
    "#",
    "# 8 Formal Verification Layers Enforced:",
    "# • L1: CST Merkle Hash    • L5: PEP 695 Generics",
    "# • L2: Octagon DBM Bounds • L6: Semiring Confidence",
    "# • L3: Dual SMT Consensus • L7: Witness Sandbox",
    "# • L4: DPOR Virtual Clocks• L8: Attestation Seal (0x7F)",
    "#",
    "# Type 'q' or 'exit' in the prompt below to exit.",
]


class ProcessMonitor:
    """Monitors live host process resource consumption with history sparkline."""

    def __init__(self) -> None:
        self.pid = os.getpid()
        self.process = psutil.Process(self.pid) if (PSUTIL_AVAILABLE and psutil) else None
        if self.process:
            try:
                self.process.cpu_percent(interval=None)
            except Exception:
                pass
        self.cpu_history: deque[float] = deque([0.0] * 12, maxlen=12)

        # Win32 ctypes fallback structures for Windows
        self._is_windows = os.name == "nt"
        self._win32_ready = False
        if self._is_windows:
            try:
                import ctypes
                from ctypes import wintypes

                class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
                    _fields_ = [
                        ("cb", wintypes.DWORD),
                        ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t),
                        ("PrivateUsage", ctypes.c_size_t),
                    ]

                class FILETIME(ctypes.Structure):
                    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

                self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                self._psapi = ctypes.WinDLL("psapi", use_last_error=True)
                self._PMC = PROCESS_MEMORY_COUNTERS_EX
                self._FT = FILETIME
                self._psapi.GetProcessMemoryInfo.argtypes = [
                    wintypes.HANDLE,
                    ctypes.POINTER(self._PMC),
                    wintypes.DWORD,
                ]
                self._psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

                self._kernel32.GetProcessTimes.argtypes = [
                    wintypes.HANDLE,
                    ctypes.POINTER(self._FT),
                    ctypes.POINTER(self._FT),
                    ctypes.POINTER(self._FT),
                    ctypes.POINTER(self._FT),
                ]
                self._kernel32.GetProcessTimes.restype = wintypes.BOOL
                self._proc_handle = self._kernel32.GetCurrentProcess()
                self._last_time = time.time()
                self._last_cpu_time = self._get_win32_cpu_time()
                self._win32_ready = True
            except Exception:
                self._win32_ready = False

    def _get_win32_cpu_time(self) -> float:
        if not self._win32_ready:
            return 0.0
        import ctypes
        c, e, k, u = self._FT(), self._FT(), self._FT(), self._FT()
        if self._kernel32.GetProcessTimes(
            self._proc_handle,
            ctypes.byref(c),
            ctypes.byref(e),
            ctypes.byref(k),
            ctypes.byref(u),
        ):
            k_val = (k.dwHighDateTime << 32) | k.dwLowDateTime
            u_val = (u.dwHighDateTime << 32) | u.dwLowDateTime
            return (k_val + u_val) / 1e7
        return 0.0

    def sample(self) -> Dict[str, Any]:
        """Sample current CPU, RSS memory, and active threads."""
        cpu = 0.0
        rss_mb = 0.0
        threads = 1

        if self.process:
            try:
                cpu = float(self.process.cpu_percent(interval=None))
                mem = self.process.memory_info()
                rss_mb = float(mem.rss) / (1024.0 * 1024.0)
                threads = int(self.process.num_threads())
            except Exception:
                pass

        # If psutil is missing or returns zero on Windows, invoke Win32 direct API
        if rss_mb <= 0.0 and self._win32_ready:
            try:
                import ctypes
                counters = self._PMC()
                counters.cb = ctypes.sizeof(self._PMC)
                if self._psapi.GetProcessMemoryInfo(self._proc_handle, ctypes.byref(counters), counters.cb):
                    rss_mb = float(counters.WorkingSetSize) / (1024.0 * 1024.0)
            except Exception:
                pass

        if cpu <= 0.0 and self._win32_ready:
            try:
                now = time.time()
                cpu_time = self._get_win32_cpu_time()
                dt = max(0.001, now - self._last_time)
                dcpu = max(0.0, cpu_time - self._last_cpu_time)
                calculated_cpu = (dcpu / dt) * 100.0
                self._last_time = now
                self._last_cpu_time = cpu_time
                if calculated_cpu > 0.0:
                    cpu = min(100.0, calculated_cpu)
            except Exception:
                pass

        # Fallback for Linux / procfs
        if rss_mb <= 0.0 and os.path.exists("/proc/self/status"):
            try:
                with open("/proc/self/status", "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            parts = line.split()
                            rss_mb = float(parts[1]) / 1024.0
                            break
            except Exception:
                pass

        self.cpu_history.append(cpu)
        return {
            "pid": self.pid,
            "cpu": cpu,
            "rss_mb": rss_mb,
            "threads": threads,
            "history": list(self.cpu_history),
        }


def visible_len(text: str) -> int:
    """Calculates visible character terminal display width, ignoring ANSI escape codes."""
    clean = ANSI_REGEX.sub("", text)
    width = 0
    for ch in clean:
        if unicodedata.east_asian_width(ch) in ("F", "W"):
            width += 2
        else:
            width += 1
    return width


def pad_visible(text: str, width: int) -> str:
    """Pads text to ensure exact column alignment regardless of ANSI colors."""
    diff = width - visible_len(text)
    return text + (" " * diff) if diff > 0 else text


def build_sparkline(history: List[float]) -> str:
    """Builds unicode micro-bar graph from CPU percentage history."""
    chars: List[str] = []
    for val in history:
        idx = min(int((val / 100.0) * len(BAR_CHARS)), len(BAR_CHARS) - 1)
        chars.append(BAR_CHARS[max(0, idx)])
    return "".join(chars)


class TacticalDashboard:
    """Interactive Full-Screen Terminal CUI Dashboard for Axiom-Aegis-Veritas."""

    def __init__(self) -> None:
        self.monitor = ProcessMonitor()
        self.tick = 0
        self.feed_events: deque[str] = deque(maxlen=4)
        self.feed_events.append("Kernel-Scanner initialized. Ready for static AST audit.")

    def add_feed_event(self, text: str) -> None:
        """Add an event message to the bottom feed log."""
        timestamp = time.strftime("%H:%M:%S")
        self.feed_events.append(f"[{timestamp}] {text}")

    def render(
        self,
        current_target: str,
        done_files: int,
        total_files: int,
        total_lines: int,
        scan_rate: float,
        code_snippet: Optional[List[str]] = None,
        scan_line_idx: int = 0,
        status_label: str = "LIVE",
        status_summary: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Renders one complete frame of the tactical dashboard with responsive terminal width."""
        self.tick += 1
        stats = self.monitor.sample()
        spinner = SPINNERS[self.tick % len(SPINNERS)]
        sparkline = build_sparkline(stats["history"])

        # Determine terminal width (clamp between 80 and 120 cols)
        term_cols = shutil.get_terminal_size((100, 30)).columns
        W = max(80, min(120, term_cols))
        inner_W = W - 2

        # Two-column widths for middle split
        left_col = (W - 3) // 2
        right_col = (W - 3) - left_col

        display_total_files = max(1, total_files) if total_files > 0 else 0
        progress_pct = (done_files / display_total_files) * 100.0 if display_total_files > 0 else 0.0
        snippet = code_snippet or DEFAULT_CODE_SNIPPET
        avg_lines = int(total_lines / total_files) if total_files > 0 else 0

        out: List[str] = []
        # Cursor home
        out.append("\033[H")

        # Top border
        full_title = "◈ KERNEL-SCANNER // PYTHON AST AUDITOR v1.1.0"
        short_title = "◈ KERNEL-SCANNER v1.1.0"
        title = full_title if W >= 95 else short_title
        prog_txt = f"{progress_pct:4.1f}% {done_files}/{total_files} FILES"
        header_l = f"╔═[ {title} ]"
        header_r = f"[ {prog_txt} ]═╗"

        dashes_count = W - visible_len(header_l) - visible_len(header_r)
        if dashes_count < 2:
            header_l = f"╔═[ {short_title} ]"
            dashes_count = W - visible_len(header_l) - visible_len(header_r)
        dashes = "═" * max(2, dashes_count)
        out.append(f"\033[36m{header_l}{dashes}{header_r}\033[0m\n")

        # Target banner
        status_color = "\033[32m" if status_label in ("LIVE", "READY") else "\033[33m"
        max_target_len = max(15, W - 52)
        if len(current_target) <= max_target_len:
            target_display = current_target
        else:
            target_display = "..." + current_target[-(max_target_len - 3):]

        banner_text = (
            f" TARGET: {target_display:<{max_target_len}}  "
            f"{status_color}[STATUS: {status_label}]\033[0m  "
            f"\033[33m[PROGRESS: {progress_pct:4.1f}%]\033[0m"
        )
        out.append(f"\033[36m║\033[0m{pad_visible(banner_text, inner_W)}\033[36m║\033[0m\n")

        # Two-column divider
        out.append(f"\033[36m╠{'═' * left_col}╦{'═' * right_col}╣\033[0m\n")

        # Telemetry rows (Right Pane)
        snippet_width = max(20, left_col - 10)
        telemetry_rows = [
            f"\033[1;37mPROCESS TELEMETRY (LIVE PID: {stats['pid']})\033[0m",
            "",
            f"  \033[90mCPU USAGE            ACTIVE THREADS\033[0m",
            f"  [\033[32m {stats['cpu']:5.1f}% \033[0m] \033[35m{sparkline:<10}\033[0m  \033[33m{stats['threads']}\033[0m Workers",
            "",
            f"  \033[90mRESIDENT MEMORY (RSS) TOTAL CODE\033[0m",
            f"  [\033[32m {stats['rss_mb']:5.1f} MB \033[0m]       \033[36m{total_lines:,}\033[0m Lines",
            "",
            f"  \033[90mCODEBASE PROFILE (PURE PYTHON)\033[0m",
            f"  • \033[33mFiles\033[0m: {total_files} py      • \033[32mRate\033[0m: {scan_rate:4.1f} f/s",
            f"  • \033[37mAvg\033[0m  : ~{avg_lines} lines/file",
            "",
        ]

        max_lines = max(len(snippet), len(telemetry_rows))

        for i in range(max_lines):
            # Left pane: Source AST snippet
            if i < len(snippet):
                code_line = snippet[i]
                truncated_code = code_line[:snippet_width]
                if i == scan_line_idx:
                    raw_left = f"\033[1;31m▶▶ {i+1:02d} │ \033[7m{truncated_code}\033[0m"
                else:
                    raw_left = f"   \033[90m{i+1:02d} │\033[0m \033[37m{truncated_code}\033[0m"
            else:
                raw_left = ""

            left_side = pad_visible(raw_left, left_col)
            right_raw = telemetry_rows[i] if i < len(telemetry_rows) else ""
            right_side = pad_visible(f"  {right_raw}", right_col)

            out.append(f"\033[36m║\033[0m{left_side}\033[36m║\033[0m{right_side}\033[36m║\033[0m\n")

        # Bottom Pane: Live Feed Divider
        out.append(f"\033[36m╠{'═' * left_col}╩{'═' * right_col}╣\033[0m\n")

        latest_event = self.feed_events[-1] if self.feed_events else "Idle."
        prev_event = self.feed_events[-2] if len(self.feed_events) >= 2 else ""
        feed_max_len = max(40, inner_W - 14)

        line_1 = pad_visible(f"  \033[33mFEED ❯\033[0m {spinner} {latest_event[:feed_max_len]}", inner_W)
        out.append(f"\033[36m║\033[0m{line_1}\033[36m║\033[0m\n")

        if prev_event:
            line_2 = pad_visible(f"       \033[90m◈\033[0m {prev_event[:feed_max_len]}", inner_W)
            out.append(f"\033[36m║\033[0m{line_2}\033[36m║\033[0m\n")

        # Pytest-style Colorful Result Summary Bar
        if status_summary:
            passed = status_summary.get("passed", 0)
            failed = status_summary.get("failed", 0)
            tot = status_summary.get("total", total_files)
            elapsed = status_summary.get("elapsed", 0.0)

            p_part = f"\033[1;32m✔ {passed} PASSED\033[0m"
            f_part = f"\033[1;31m✖ {failed} FAILED\033[0m" if failed > 0 else "\033[90m0 FAILED\033[0m"
            t_part = f"\033[1;37m{tot} FILES [{elapsed:.2f}s]\033[0m"
            raw_summary = f" {p_part}   {f_part}   {t_part} "

            summary_vis_len = visible_len(raw_summary)
            side_len = max(2, (inner_W - summary_vis_len) // 2)
            left_bar = "=" * side_len
            right_bar = "=" * (inner_W - summary_vis_len - side_len)
            bar_color = "\033[1;31m" if failed > 0 else "\033[1;32m"
            summary_content = f"{bar_color}{left_bar}\033[0m{raw_summary}{bar_color}{right_bar}\033[0m"

            out.append(f"\033[36m╠{'═' * inner_W}╣\033[0m\n")
            out.append(f"\033[36m║\033[0m{pad_visible(summary_content, inner_W)}\033[36m║\033[0m\n")

            # Layer 8 Attestation Breakdown (Shows specific verification layer failures)
            failed_details = status_summary.get("failed_details", [])
            if failed_details:
                out.append(f"\033[36m╠{'═' * inner_W}╣\033[0m\n")
                header_line = pad_visible("  \033[1;33m◈ LAYER 8 ATTESTATION BREAKDOWN (FAILED VERIFICATION LAYERS):\033[0m", inner_W)
                out.append(f"\033[36m║\033[0m{header_line}\033[36m║\033[0m\n")

                # Show up to 4 failed files to maintain screen fit, or summarize if more
                max_show = 4
                for item in failed_details[:max_show]:
                    fname = item.get("file", "unknown")
                    missing = item.get("missing_layers", [])
                    missing_str = ", ".join(missing) if missing else "Unknown"
                    # Format: ✖ file_name.py ❯ Failed: [L6]
                    detail_raw = f"   \033[1;31m✖\033[0m \033[1;37m{fname[:42]:<42}\033[0m \033[90m❯\033[0m \033[1;31mFailed: [{missing_str}]\033[0m"
                    out.append(f"\033[36m║\033[0m{pad_visible(detail_raw, inner_W)}\033[36m║\033[0m\n")

                if len(failed_details) > max_show:
                    more_cnt = len(failed_details) - max_show
                    more_raw = f"   \033[90m... and {more_cnt} more failed file(s)\033[0m"
                    out.append(f"\033[36m║\033[0m{pad_visible(more_raw, inner_W)}\033[36m║\033[0m\n")

        out.append(f"\033[36m╚{'═' * inner_W}╝\033[0m\n")

        return "".join(out)

    def scan_target(self, target_path: Path) -> Dict[str, Any]:
        """Executes full live directory scan with tactical dashboard animation."""
        import logging
        from src.core.engine_kernel import EngineKernel

        target = Path(target_path)
        if target.is_file():
            py_files = [target]
        else:
            excluded_dirs = {".venv", "venv", "env", ".git", "__pycache__", ".pytest_cache", "build", "dist"}
            py_files = [
                p for p in sorted(target.rglob("*.py"))
                if not any(part in excluded_dirs for part in p.parts)
            ]

        if not py_files:
            self.add_feed_event(f"No Python (.py) files found in: {target}")
            return {}

        total_files = len(py_files)
        total_lines = 0
        for pf in py_files:
            try:
                total_lines += len(pf.read_text(encoding="utf-8", errors="ignore").splitlines())
            except Exception:
                pass
        self._last_scanned_lines = total_lines

        kernel = EngineKernel()
        results: Dict[str, Any] = {}
        passed_count = 0
        failed_count = 0
        failed_details: List[Dict[str, Any]] = []

        # Mute root and module loggers to prevent stdout text pollution during CUI rendering
        old_root_level = logging.root.level
        logging.root.setLevel(logging.CRITICAL)

        start_time = time.time()
        try:
            for idx, file_path in enumerate(py_files, 1):
                # Read sample lines for the left pane
                snippet = DEFAULT_CODE_SNIPPET
                try:
                    lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
                    if lines:
                        snippet = [line.strip() for line in lines[:11]]
                except Exception:
                    pass

                self.add_feed_event(f"Auditing file: {file_path.name} through 8-layer pipeline...")

                # Animate frames before execution
                for frame in range(2):
                    elapsed = max(0.001, time.time() - start_time)
                    rate = idx / elapsed
                    frame_text = self.render(
                        current_target=str(file_path),
                        done_files=idx - 1,
                        total_files=total_files,
                        total_lines=total_lines,
                        scan_rate=rate,
                        code_snippet=snippet,
                        scan_line_idx=frame % len(snippet),
                        status_label="SCANNING",
                        status_summary={
                            "passed": passed_count,
                            "failed": failed_count,
                            "total": total_files,
                            "elapsed": elapsed,
                            "failed_details": failed_details,
                        },
                    )
                    sys.stdout.write(frame_text)
                    sys.stdout.flush()
                    time.sleep(0.02)

                # Run actual pipeline
                pipe_res = kernel.run_pipeline(str(file_path))
                results[str(file_path)] = pipe_res

                # Check pass/fail status
                is_ok = pipe_res.success and (
                    pipe_res.attestation_seal.is_complete if pipe_res.attestation_seal else False
                )
                if is_ok:
                    passed_count += 1
                    self.add_feed_event(
                        f"Layer 8 SEAL VERIFIED for {file_path.name} [Mask=0x7F, Hash={pipe_res.attestation_seal.seal_hash[:12]}...]"
                    )
                else:
                    failed_count += 1
                    missing = pipe_res.attestation_seal.missing_layers if pipe_res.attestation_seal else ["L8"]
                    reasons = pipe_res.attestation_seal.failure_reasons if pipe_res.attestation_seal else {}
                    failed_details.append({
                        "file": file_path.name,
                        "missing_layers": missing,
                        "reasons": reasons,
                    })
                    self.add_feed_event(
                        f"Layer 8 ATTESTATION INCOMPLETE for {file_path.name}: Failed {missing}"
                    )

                # Render completed state for this file
                elapsed = max(0.001, time.time() - start_time)
                rate = idx / elapsed
                frame_text = self.render(
                    current_target=str(file_path),
                    done_files=idx,
                    total_files=total_files,
                    total_lines=total_lines,
                    scan_rate=rate,
                    code_snippet=snippet,
                    scan_line_idx=min(len(snippet) - 1, 4),
                    status_label="LIVE",
                    status_summary={
                        "passed": passed_count,
                        "failed": failed_count,
                        "total": total_files,
                        "elapsed": elapsed,
                        "failed_details": failed_details,
                    },
                )
                sys.stdout.write(frame_text)
                sys.stdout.flush()
                time.sleep(0.02)
        finally:
            logging.root.setLevel(old_root_level)

        # Hold final frame summary in feed and render Pytest-style summary bar
        total_elapsed = max(0.001, time.time() - start_time)
        final_summary = {
            "passed": passed_count,
            "failed": failed_count,
            "total": total_files,
            "elapsed": total_elapsed,
            "failed_details": failed_details,
        }
        self.add_feed_event(
            f"Completed scan of {total_files} files in {total_elapsed:.2f}s ({passed_count} passed, {failed_count} failed)."
        )
        frame_text = self.render(
            current_target=f"SCAN COMPLETE: {target.name}",
            done_files=total_files,
            total_files=total_files,
            total_lines=total_lines,
            scan_rate=total_files / total_elapsed,
            status_label="READY",
            status_summary=final_summary,
        )
        sys.stdout.write(frame_text)
        sys.stdout.flush()

        return results

    def run_live_scan(self, target_path: Path) -> Dict[str, Any]:
        """Backward-compatible single run method."""
        sys.stdout.write("\033[?1049h\033[?25l")
        sys.stdout.flush()
        try:
            return self.scan_target(target_path)
        finally:
            sys.stdout.write("\033[?25h\033[?1049l")
            sys.stdout.flush()

    def run_interactive_session(self, initial_target: Optional[Path] = None) -> None:
        """Runs the interactive tactical session, prompting for targets in a continuous loop."""
        # Enter alternate buffer and hide cursor
        sys.stdout.write("\033[?1049h\033[?25l")
        sys.stdout.flush()

        try:
            last_summary: Optional[Dict[str, Any]] = None
            last_total_lines: int = 0
            last_total_files: int = 0

            if initial_target and Path(initial_target).exists():
                results = self.scan_target(Path(initial_target))
                if results:
                    last_total_files = len(results)
                    passed = sum(1 for r in results.values() if r.success and (r.attestation_seal and r.attestation_seal.is_complete))
                    failed = len(results) - passed
                    cur_failed_details: List[Dict[str, Any]] = []
                    for fpath_str, res in results.items():
                        if not (res.success and (res.attestation_seal and res.attestation_seal.is_complete)):
                            seal = res.attestation_seal
                            cur_failed_details.append({
                                "file": Path(fpath_str).name,
                                "missing_layers": seal.missing_layers if seal else ["L8"],
                                "reasons": seal.failure_reasons if seal else {},
                            })
                    last_summary = {
                        "passed": passed,
                        "failed": failed,
                        "total": len(results),
                        "elapsed": 0.0,
                        "failed_details": cur_failed_details,
                    }
                    last_total_lines = getattr(self, "_last_scanned_lines", 0)

            while True:
                # Render standby frame
                frame_text = self.render(
                    current_target="AWAITING TARGET PATH",
                    done_files=last_total_files,
                    total_files=last_total_files,
                    total_lines=last_total_lines,
                    scan_rate=0.0,
                    code_snippet=STANDBY_SNIPPET,
                    scan_line_idx=-1,
                    status_label="STANDBY",
                    status_summary=last_summary,
                )
                term_cols = shutil.get_terminal_size((100, 30)).columns
                cmd_dashes = "─" * max(10, term_cols - 24)
                prompt_line = (
                    f"\033[36m───[ COMMAND INTERFACE ]{cmd_dashes}\033[0m\n"
                    " \033[1;32m❯ Enter target path\033[0m (file/folder, or 'q' to exit): "
                )
                sys.stdout.write(frame_text + prompt_line)
                sys.stdout.write("\033[?25h")  # Show cursor for user typing
                sys.stdout.flush()

                try:
                    user_input = input().strip()
                except (EOFError, KeyboardInterrupt):
                    break

                sys.stdout.write("\033[?25l")  # Hide cursor during processing
                sys.stdout.flush()

                # Clean quotes from drag-and-drop or Windows copy path
                cleaned_input = user_input.strip('"\'')
                if not cleaned_input:
                    continue

                if cleaned_input.lower() in ("q", "quit", "exit"):
                    break

                target_path = Path(cleaned_input)
                if not target_path.exists():
                    self.add_feed_event(f"Path not found: '{cleaned_input}'. Please check and try again.")
                    continue

                # Execute scan on target and stay open
                res = self.scan_target(target_path)
                if res:
                    last_total_files = len(res)
                    passed = sum(1 for r in res.values() if r.success and (r.attestation_seal and r.attestation_seal.is_complete))
                    failed = len(res) - passed
                    cur_failed_details: List[Dict[str, Any]] = []
                    for fpath_str, r_item in res.items():
                        if not (r_item.success and (r_item.attestation_seal and r_item.attestation_seal.is_complete)):
                            seal = r_item.attestation_seal
                            cur_failed_details.append({
                                "file": Path(fpath_str).name,
                                "missing_layers": seal.missing_layers if seal else ["L8"],
                                "reasons": seal.failure_reasons if seal else {},
                            })
                    last_summary = {
                        "passed": passed,
                        "failed": failed,
                        "total": len(res),
                        "elapsed": 0.0,
                        "failed_details": cur_failed_details,
                    }
                    last_total_lines = getattr(self, "_last_scanned_lines", 0)

        finally:
            # Restore cursor and normal screen buffer
            sys.stdout.write("\033[?25h\033[?1049l")
            sys.stdout.flush()


def run_standalone_demo() -> None:
    """Runs a standalone demonstration loop of the tactical dashboard."""
    dashboard = TacticalDashboard()
    sys.stdout.write("\033[?1049h\033[?25l")
    try:
        scan_idx = 0
        total_files = 58
        total_lines = 24850
        start = time.time()
        for step in range(50):
            done = min(58, int((step / 50.0) * 58))
            rate = 42.0
            frame = dashboard.render(
                current_target="src/core/attestation_oracle.py",
                done_files=done,
                total_files=total_files,
                total_lines=total_lines,
                scan_rate=rate,
                scan_line_idx=scan_idx,
            )
            sys.stdout.write(frame)
            sys.stdout.flush()
            time.sleep(0.08)
            scan_idx = (scan_idx + 1) % len(DEFAULT_CODE_SNIPPET)
            if step == 10:
                dashboard.add_feed_event("Traversing ast.Call nodes in target module...")
            elif step == 25:
                dashboard.add_feed_event("Layer 8 Seal synthesized: Bitmask=0x7F, Verdict=VERIFIED_COMPLETE")
            elif step == 40:
                dashboard.add_feed_event("Audit Chain persistence verified across block #42")
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\033[?25h\033[?1049l")
        sys.stdout.flush()


if __name__ == "__main__":
    run_standalone_demo()
