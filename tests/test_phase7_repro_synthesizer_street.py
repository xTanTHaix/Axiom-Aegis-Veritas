"""
AXIOM-AEGIS-VERITAS — Phase 7: Layer 7 Street & Stress Test Suite.
1:1 Deep Verification for Empirical Witness Shards & Deterministic Sandbox.

Covers:
- High-volume witness generation across complex Python constructs
- Deterministic Sandbox chaos testing:
    - Rapid-fire execution bursts (50 cycles)
    - Input parameter boundary stresses
    - Execution state inspection and isolation
- CrashValidator signature extraction and classification under rapid bursts
"""

from pathlib import Path
import pytest

from src.core.repro_synthesizer import (
    CrashReport,
    CrashValidator,
    DeterministicSandbox,
    DeterministicSandboxConfig,
    ReproSynthesizer,
    SandboxExecutionResult,
    WitnessGenerator,
)


class TestPhase7WitnessGeneratorStreet:
    """Street tests for WitnessGenerator under complex multi-pattern code."""

    def test_bulk_witness_generation_complex_module(self, tmp_path):
        """Synthesize witnesses for a module containing arithmetic, collections, and conditionals."""
        src_file = tmp_path / "complex_module.py"
        src_file.write_text(
            "def calculate_balance(initial: float, transactions: list, factor: int = 1) -> float:\n"
            "    total = initial\n"
            "    for t in transactions:\n"
            "        if t < 0 and factor > 0:\n"
            "            total += t * factor\n"
            "        else:\n"
            "            total += t / factor\n"
            "    return total\n\n"
            "def lookup_item(table: dict, key: str, default: int = 0) -> int:\n"
            "    if key in table:\n"
            "        return table[key]\n"
            "    return default\n",
            encoding="utf-8",
        )

        synthesizer = ReproSynthesizer(file_path=str(src_file))
        witnesses = synthesizer.generate()
        
        # Verify synthesis output
        assert len(witnesses) > 0
        witness_report = synthesizer.get_witness_report()
        assert witness_report["witnesses_generated"] == len(witnesses)
        assert len(synthesizer.get_witnesses()) == len(witnesses)

    def test_witness_generator_octagon_and_pep695_constraints_stress(self):
        """Street test: Generate boundary witnesses from 20 simultaneous octagon and type constraints."""
        constraints = {f"var_{i}": {"lower": -100 * i, "upper": 100 * i} for i in range(1, 21)}
        types = {f"T_{i}": "int" for i in range(20)}
        
        gen = WitnessGenerator(
            seed=42,
            octagon_constraints=constraints,
            pep695_types=types,
        )
        
        witnesses = []
        for _ in range(10):
            w = gen._generate_constraint_witness()
            if w:
                witnesses.append(w)
                
        assert len(witnesses) > 0
        for w in witnesses:
            assert len(w.inputs) > 0


class TestPhase7DeterministicSandboxStreet:
    """Stress tests for DeterministicSandbox execution and resource containment."""

    def test_sandbox_rapid_execution_burst_50_cycles(self):
        """Street test: Execute 50 rapid sequential snippets in sandbox without leaks."""
        sandbox = DeterministicSandbox()
        
        for i in range(50):
            code = "result = x * 2 + y"
            inputs = {"x": i, "y": i * 10}
            res = sandbox.execute(code, inputs)
            assert res.success is True
            assert res.output == (i * 2 + i * 10)
            assert res.steps_executed > 0

    def test_sandbox_crash_trapping_zero_division(self):
        """Street test: Deliberate division by zero is safely trapped without raising uncaught host exceptions."""
        sandbox = DeterministicSandbox()
        zero_div_code = "result = 100 / 0"
        
        res = sandbox.execute(zero_div_code, {})
        assert res.success is False
        assert res.crashed is True
        assert res.stack_trace is not None
        assert "division by zero" in res.stack_trace

    def test_sandbox_state_isolation_between_runs(self):
        """Street test: Ensure variables defined in one run do not leak into subsequent runs."""
        sandbox = DeterministicSandbox()
        
        # Run 1 sets secret variable
        sandbox.execute("secret_token = 'CRITICAL_SECRET_42'\nresult = 1", {})
        
        # Run 2 attempts to access secret_token without input
        res2 = sandbox.execute("result = secret_token", {})
        assert res2.success is False
        assert res2.crashed is True
        assert "name 'secret_token' is not defined" in res2.stack_trace


class TestPhase7CrashValidatorStreet:
    """Stress tests for CrashValidator classification across boundary crash types."""

    def test_crash_validator_rapid_classification_matrix(self):
        """Street test: Validate accurate classification across standard and custom crash types."""
        validator = CrashValidator()
        
        test_matrix = [
            ("IndexError", "Traceback: list index out of range", "index_error"),
            ("TypeError", "Traceback: unsupported operand type", "type_error"),
            ("AssertionError", "Traceback: assert False", "assertion"),
            ("Timeout", "Timeout: execution exceeded deadline", "timeout"),
            ("MemoryError", "Traceback: memory allocation failed", "memory_exhausted"),
            ("ValueError", "Traceback: invalid literal for int()", "value_error"),
            ("Segmentation fault", "Process crashed with SIGSEGV", "segfault"),
            ("ArbitraryCustomError", "Traceback: unexpected chaos", "unknown"),
        ]
        
        for crash_type, stack_trace, expected_cat in test_matrix:
            report = validator.validate(
                crash_type=crash_type,
                stack_trace=stack_trace,
                execution_steps=150,
            )
            assert isinstance(report, CrashReport)
            assert report.crash_type == expected_cat
            assert report.execution_steps == 150
            
        summary = validator.get_crash_summary()
        assert summary["total"] == len(test_matrix)
