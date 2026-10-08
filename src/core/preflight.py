"""
AXIOM-AEGIS-VERITAS — Pre-flight Dependency & Runtime Verification Gate.

Enforces zero-silent-failure dependency validation before pipeline ignition.
Verifies critical AST/CST, SMT, and system telemetry primitives, emitting
structured actionable resolution paths rather than cascaded layer panics.
"""

from __future__ import annotations

import importlib.util
import sys
from typing import Dict, List, NamedTuple


class DependencyDescriptor(NamedTuple):
    package_name: str
    import_name: str
    affected_layers: str
    purpose: str
    install_command: str


CRITICAL_DEPENDENCIES: List[DependencyDescriptor] = [
    DependencyDescriptor(
        package_name="libcst",
        import_name="libcst",
        affected_layers="Layer 1 (CST Merkle), Layer 5 (PEP 695), Layer 7 (Witness Repro)",
        purpose="Concrete Syntax Tree parsing, trivia preservation, and CST Merkle hashing",
        install_command="pip install libcst>=1.0.0",
    ),
    DependencyDescriptor(
        package_name="z3-solver",
        import_name="z3",
        affected_layers="Layer 3 (Dual SMT Consensus)",
        purpose="SMT solver integration for algebraic invariants and type contract consensus",
        install_command="pip install z3-solver>=5.0.0",
    ),
    DependencyDescriptor(
        package_name="colorama",
        import_name="colorama",
        affected_layers="Terminal CUI & Progress Telemetry",
        purpose="Cross-platform ANSI color code sequencing and Windows VT-100 emulation",
        install_command="pip install colorama>=0.4.6",
    ),
    DependencyDescriptor(
        package_name="psutil",
        import_name="psutil",
        affected_layers="System Telemetry & Hardware Resource Guard",
        purpose="Deterministic virtual memory, CPU affinity, and worker scheduler monitoring",
        install_command="pip install psutil>=5.9.0",
    ),
]


def check_runtime_dependencies() -> List[DependencyDescriptor]:
    """Check availability of all critical production dependencies.

    Returns:
        List of DependencyDescriptor instances that are currently missing.
    """
    missing: List[DependencyDescriptor] = []
    for dep in CRITICAL_DEPENDENCIES:
        if importlib.util.find_spec(dep.import_name) is None:
            missing.append(dep)
    return missing


def render_preflight_failure_banner(missing: List[DependencyDescriptor]) -> str:
    """Renders a high-visibility terminal banner instructing the operator how to remediate."""
    bar = "═" * 78
    lines = [
        "",
        bar,
        "  ❌ AXIOM-AEGIS-VERITAS PRE-FLIGHT DEPENDENCY CHECK FAILED",
        bar,
        "  The formal verification engine requires native production dependencies",
        "  that are currently missing in the active Python environment.",
        "",
        f"  Active Python Binary: {sys.executable}",
        "",
        "  Missing Component(s):",
    ]
    for dep in missing:
        lines.append(f"    • {dep.package_name:<14} ➔ Affected: {dep.affected_layers}")
        lines.append(f"      Purpose:       {dep.purpose}")
        lines.append(f"      Direct Fix:    {dep.install_command}")
        lines.append("")

    lines.extend([
        bar,
        "  ⚡ RECOMMENDED RESOLUTION COMMANDS (Choose one):",
        "",
        "    1. Install full production requirements:",
        "       pip install -r requirements.txt",
        "",
        "    2. Install directly via project metadata:",
        "       pip install -e .",
        bar,
        "",
    ])
    return "\n".join(lines)


def ensure_runtime_ready(fail_fast: bool = True) -> bool:
    """Guarantees runtime readiness, optionally terminating execution immediately.

    Args:
        fail_fast: If True, prints diagnostic banner and calls sys.exit(3).

    Returns:
        True if all dependencies are satisfied, False otherwise.
    """
    missing = check_runtime_dependencies()
    if not missing:
        return True

    banner = render_preflight_failure_banner(missing)
    sys.stderr.write(banner)
    sys.stderr.flush()

    if fail_fast:
        sys.exit(3)

    return False
