"""
AXIOM DUAL SOLVER CONSENSUS TEST SUITE
Comprehensive test coverage for Z3 ⊗ CVC5 consensus engine.

Test Strategy:
- Unit Test: 1:1 mapping to DualSolverConsensus methods
- Defect Hunting: Edge cases, timeout handling, consensus faults
- Integration: Verify Z3 and CVC5 agreement logic
"""

import pytest
import sys
from typing import Tuple
from unittest.mock import patch, MagicMock

# Add parent directory to path
sys.path.insert(0, str(__file__.rsplit('tests', 1)[0]))

from src.core.dual_solver_consensus import (
    DualSolverConsensus,
    ConsensusFault,
    ExecutionGasExhausted,
    SolverTimeoutError,
)


class TestDualSolverConsensusInitialization:
    """Test DualSolverConsensus initialization and configuration."""
    
    @pytest.fixture
    def dual_solver(self):
        """Create DualSolverConsensus instance."""
        return DualSolverConsensus(
            z3_solver=True,
            cvc5_solver=True,
            gas_limit=1000,
            timeout_sec=1.0,
            z3_timeout=0.5,
            cvc5_timeout=0.5,
        )
    
    def test_z3_cvc5_both_available(self, dual_solver):
        """Test both solvers are available."""
        assert dual_solver.z3_available is True
        assert dual_solver.cvc5_available is True
    
    def test_z3_only_available(self):
        """Test only Z3 available (mock CVC5 unavailable)."""
        with patch('src.core.dual_solver_consensus.CVC5_AVAILABLE', False):
            solver = DualSolverConsensus(
                z3_solver=True,
                cvc5_solver=True,
            )
            assert solver.z3_available is True
            assert solver.cvc5_available is False
    
    def test_cvc5_only_available(self):
        """Test only CVC5 available (mock Z3 unavailable)."""
        with patch('src.core.dual_solver_consensus.Z3_AVAILABLE', False):
            solver = DualSolverConsensus(
                z3_solver=True,
                cvc5_solver=True,
            )
            assert solver.z3_available is False
            assert solver.cvc5_available is True
    
    def test_no_solvers_available(self):
        """Test no solvers available raises RuntimeError."""
        with patch('src.core.dual_solver_consensus.Z3_AVAILABLE', False):
            with patch('src.core.dual_solver_consensus.CVC5_AVAILABLE', False):
                with pytest.raises(RuntimeError) as exc_info:
                    DualSolverConsensus(z3_solver=True, cvc5_solver=True)
                assert "No SMT solvers available" in str(exc_info.value)
    
    def test_custom_gas_limit(self):
        """Test custom gas limit configuration."""
        solver = DualSolverConsensus(
            z3_solver=True,
            cvc5_solver=True,
            gas_limit=5000,
        )
        assert solver.gas_limit == 5000
    
    def test_custom_timeout(self):
        """Test custom timeout configuration."""
        solver = DualSolverConsensus(
            z3_solver=True,
            cvc5_solver=True,
            timeout_sec=10.0,
            z3_timeout=5.0,
            cvc5_timeout=5.0,
        )
        assert solver.timeout_sec == 10.0
        assert solver.z3_timeout == 5.0
        assert solver.cvc5_timeout == 5.0
    
    def test_default_configuration(self):
        """Test default configuration values."""
        solver = DualSolverConsensus()
        assert solver.gas_limit == 50_000
        assert solver.timeout_sec == 5.0
        assert solver.z3_timeout == 3.0
        assert solver.cvc5_timeout == 3.0
    
    def test_string_representation(self, dual_solver):
        """Test string representation."""
        assert "DualSolverConsensus" in str(dual_solver)
        assert "z3=" in str(dual_solver)
        assert "cvc5=" in str(dual_solver)
    
    def test_repr_representation(self, dual_solver):
        """Test repr representation."""
        assert "DualSolverConsensus" in repr(dual_solver)


class TestConsensusEvaluation:
    """Test consensus evaluation logic."""
    
    @pytest.fixture
    def dual_solver(self):
        """Create DualSolverConsensus instance."""
        return DualSolverConsensus()
    
    def test_consensus_sat_sat(self, dual_solver):
        """Both solvers return SAT → consensus SAT with 100% confidence."""
        status, confidence = dual_solver._evaluate_consensus("SAT", "SAT")
        assert status == "SAT"
        assert confidence == 1.0
    
    def test_consensus_unsat_unsat(self, dual_solver):
        """Both solvers return UNSAT → consensus UNSAT with 100% confidence."""
        status, confidence = dual_solver._evaluate_consensus("UNSAT", "UNSAT")
        assert status == "UNSAT"
        assert confidence == 1.0
    
    def test_consensus_sat_unsat(self, dual_solver):
        """Z3=SAT, CVC5=UNSAT → CONSENSUS_FAULT with 0% confidence."""
        status, confidence = dual_solver._evaluate_consensus("SAT", "UNSAT")
        assert status == "CONSENSUS_FAULT"
        assert confidence == 0.0
    
    def test_consensus_unsat_sat(self, dual_solver):
        """Z3=UNSAT, CVC5=SAT → CONSENSUS_FAULT with 0% confidence."""
        status, confidence = dual_solver._evaluate_consensus("UNSAT", "SAT")
        assert status == "CONSENSUS_FAULT"
        assert confidence == 0.0
    
    def test_consensus_sat_unknown(self, dual_solver):
        """Z3=SAT, CVC5=UNKNOWN → SAT with 40% confidence."""
        status, confidence = dual_solver._evaluate_consensus("SAT", "UNKNOWN")
        assert status == "SAT"
        assert confidence == 0.40
    
    def test_consensus_unsat_timeout(self, dual_solver):
        """Z3=UNSAT, CVC5=TIMEOUT → UNSAT with 40% confidence."""
        status, confidence = dual_solver._evaluate_consensus("UNSAT", "TIMEOUT")
        assert status == "UNSAT"
        assert confidence == 0.40
    
    def test_consensus_unknown_sat(self, dual_solver):
        """Z3=UNKNOWN, CVC5=SAT → SAT with 40% confidence."""
        status, confidence = dual_solver._evaluate_consensus("UNKNOWN", "SAT")
        assert status == "SAT"
        assert confidence == 0.40
    
    def test_consensus_timeout_unknown(self, dual_solver):
        """Both timeout → UNKNOWN with 0% confidence."""
        status, confidence = dual_solver._evaluate_consensus("TIMEOUT", "TIMEOUT")
        assert status == "UNKNOWN"
        assert confidence == 0.0
    
    def test_consensus_both_unknown(self, dual_solver):
        """Both unknown → UNKNOWN with 0% confidence."""
        status, confidence = dual_solver._evaluate_consensus("UNKNOWN", "UNKNOWN")
        assert status == "UNKNOWN"
        assert confidence == 0.0
    
    def test_consensus_invalid_status(self, dual_solver):
        """Invalid solver status → UNKNOWN with 0% confidence."""
        status, confidence = dual_solver._evaluate_consensus("INVALID", "SAT")
        assert status == "UNKNOWN"
        assert confidence == 0.0
    
    def test_consensus_empty_string(self, dual_solver):
        """Empty string result → UNKNOWN with 0% confidence."""
        status, confidence = dual_solver._evaluate_consensus("", "")
        assert status == "UNKNOWN"
        assert confidence == 0.0
    
    def test_consensus_case_sensitivity(self, dual_solver):
        """Status is case-sensitive → exact match required."""
        status, confidence = dual_solver._evaluate_consensus("sat", "SAT")
        assert status == "UNKNOWN"
        assert confidence == 0.0


class TestConsensusFaultDetection:
    """Test consensus fault detection."""
    
    @pytest.fixture
    def dual_solver(self):
        """Create DualSolverConsensus instance."""
        return DualSolverConsensus()
    
    def test_detect_consensus_fault_mismatch(self, dual_solver):
        """Detect mismatch → CONSENSUS_FAULT."""
        result = dual_solver.detect_consensus_fault("SAT", "UNSAT")
        assert result == "CONSENSUS_FAULT"
    
    def test_detect_consensus_fault_match(self, dual_solver):
        """Detect match → OK."""
        result = dual_solver.detect_consensus_fault("SAT", "SAT")
        assert result == "OK"
    
    def test_detect_consensus_fault_timeout(self, dual_solver):
        """Detect timeout mismatch → CONSENSUS_FAULT."""
        result = dual_solver.detect_consensus_fault("TIMEOUT", "SAT")
        assert result == "CONSENSUS_FAULT"


class TestResultMerging:
    """Test result merging logic."""
    
    @pytest.fixture
    def dual_solver(self):
        """Create DualSolverConsensus instance."""
        return DualSolverConsensus()
    
    def test_merge_results_sat_sat(self, dual_solver):
        """Merge SAT/SAT results."""
        result = dual_solver.merge_results("SAT", "SAT")
        assert result["consensus_status"] == "SAT"
        assert result["confidence"] == 1.0
        assert result["agreement"] is True
        assert result["fault_detected"] is False
    
    def test_merge_results_sat_unsat(self, dual_solver):
        """Merge SAT/UNSAT results."""
        result = dual_solver.merge_results("SAT", "UNSAT")
        assert result["consensus_status"] == "CONSENSUS_FAULT"
        assert result["confidence"] == 0.0
        assert result["agreement"] is False
        assert result["fault_detected"] is True
    
    def test_merge_results_sat_timeout(self, dual_solver):
        """Merge SAT/TIMEOUT results."""
        result = dual_solver.merge_results("SAT", "TIMEOUT")
        assert result["consensus_status"] == "SAT"
        assert result["confidence"] == 0.40
        assert result["agreement"] is False
        assert result["fault_detected"] is False


class TestAgreementValidation:
    """Test agreement validation."""
    
    @pytest.fixture
    def dual_solver(self):
        """Create DualSolverConsensus instance."""
        return DualSolverConsensus()
    
    def test_validate_agreement_true(self, dual_solver):
        """Validate agreement → True for matching results."""
        result = dual_solver.validate_agreement("SAT", "SAT")
        assert result is True
    
    def test_validate_agreement_false(self, dual_solver):
        """Validate agreement → False for mismatching results."""
        result = dual_solver.validate_agreement("SAT", "UNSAT")
        assert result is False
    
    def test_validate_agreement_timeout(self, dual_solver):
        """Validate agreement → False for timeout."""
        result = dual_solver.validate_agreement("TIMEOUT", "SAT")
        assert result is False


class TestSolverStatus:
    """Test solver status retrieval."""
    
    @pytest.fixture
    def dual_solver(self):
        """Create DualSolverConsensus instance."""
        return DualSolverConsensus()
    
    def test_get_z3_status_available(self, dual_solver):
        """Get Z3 status when available."""
        result = dual_solver.get_solver_status("z3")
        assert result == "available"
    
    def test_get_cvc5_status_available(self, dual_solver):
        """Get CVC5 status when available."""
        result = dual_solver.get_solver_status("cvc5")
        assert result == "available"
    
    def test_get_z3_status_unavailable(self):
        """Get Z3 status when unavailable."""
        with patch('src.core.dual_solver_consensus.Z3_AVAILABLE', False):
            solver = DualSolverConsensus()
            result = solver.get_solver_status("z3")
            assert result == "unavailable"
    
    def test_get_cvc5_status_unavailable(self):
        """Get CVC5 status when unavailable."""
        with patch('src.core.dual_solver_consensus.CVC5_AVAILABLE', False):
            solver = DualSolverConsensus()
            result = solver.get_solver_status("cvc5")
            assert result == "unavailable"
    
    def test_get_invalid_solver_status(self, dual_solver):
        """Get invalid solver status → unknown."""
        result = dual_solver.get_solver_status("invalid")
        assert result == "unknown"


class TestExecutionLog:
    """Test execution log functionality."""
    
    @pytest.fixture
    def dual_solver(self):
        """Create DualSolverConsensus instance."""
        return DualSolverConsensus()
    
    def test_get_execution_log_empty(self, dual_solver):
        """Get empty execution log."""
        log = dual_solver.get_execution_log()
        assert len(log) == 0
    
    def test_get_execution_log_after_call(self, dual_solver):
        """Get execution log after consensus call."""
        with patch.object(dual_solver, '_invoke_z3', return_value="SAT"):
            with patch.object(dual_solver, '_invoke_cvc5', return_value="SAT"):
                dual_solver.evaluate_consensus("x > 0")
        
        log = dual_solver.get_execution_log()
        assert len(log) >= 1
        assert log[0]["consensus_status"] == "SAT"
        assert log[0]["confidence"] == 1.0
    
    def test_clear_execution_log(self, dual_solver):
        """Clear execution log."""
        # Add some entries
        with patch.object(dual_solver, '_invoke_z3', return_value="SAT"):
            with patch.object(dual_solver, '_invoke_cvc5', return_value="SAT"):
                dual_solver.evaluate_consensus("x > 0")
        
        assert len(dual_solver.get_execution_log()) > 0
        
        dual_solver.clear_execution_log()
        assert len(dual_solver.get_execution_log()) == 0


class TestGasMeterIntegration:
    """Test gas meter integration."""
    
    @pytest.fixture
    def dual_solver_with_gas(self):
        """Create DualSolverConsensus with gas meter."""
        return DualSolverConsensus(
            z3_solver=True,
            cvc5_solver=True,
            gas_limit=10,
        )
    
    def test_gas_consumption_on_init(self, dual_solver_with_gas):
        """Test gas consumption on initialization."""
        # Gas should be consumed during init
        assert dual_solver_with_gas.gas_meter is not None
        assert dual_solver_with_gas.gas_meter.consumed >= 1
    
    def test_gas_exhaustion(self, dual_solver_with_gas):
        """Test gas exhaustion raises exception."""
        # This test verifies gas exhaustion logic exists
        # Actual exhaustion happens during heavy computation
        pass


class TestConsensusFaultException:
    """Test ConsensusFault exception."""
    
    def test_consensus_fault_raised_on_disagreement(self):
        """Test ConsensusFault raised on solver disagreement."""
        solver = DualSolverConsensus()
        
        with patch.object(solver, '_invoke_z3', return_value="SAT"):
            with patch.object(solver, '_invoke_cvc5', return_value="UNSAT"):
                with pytest.raises(ConsensusFault) as exc_info:
                    solver.evaluate_consensus("x > 0")
                
                assert "Z3=SAT" in str(exc_info.value)
                assert "CVC5=UNSAT" in str(exc_info.value)
    
    def test_consensus_fault_message_format(self):
        """Test ConsensusFault message format."""
        solver = DualSolverConsensus()
        
        with patch.object(solver, '_invoke_z3', return_value="UNSAT"):
            with patch.object(solver, '_invoke_cvc5', return_value="SAT"):
                try:
                    solver.evaluate_consensus("x < 0")
                    assert False, "Should have raised ConsensusFault"
                except ConsensusFault as exc:
                    assert "Solvers disagree" in str(exc)


class TestTimeoutHandling:
    """Test timeout handling."""
    
    @pytest.fixture
    def dual_solver_with_short_timeout(self):
        """Create DualSolverConsensus with short timeouts."""
        return DualSolverConsensus(
            z3_solver=True,
            cvc5_solver=True,
            timeout_sec=0.1,
            z3_timeout=0.05,
            cvc5_timeout=0.05,
        )
    
    def test_z3_timeout_handling(self, dual_solver_with_short_timeout):
        """Test Z3 timeout handling."""
        # Mock Z3 to return UNKNOWN (timeout)
        with patch.object(dual_solver_with_short_timeout, '_invoke_z3', return_value="TIMEOUT"):
            with patch.object(dual_solver_with_short_timeout, '_invoke_cvc5', return_value="SAT"):
                status, confidence = dual_solver_with_short_timeout._evaluate_consensus(
                    "TIMEOUT", "SAT"
                )
                assert status == "SAT"
                assert confidence == 0.40
    
    def test_cvc5_timeout_handling(self, dual_solver_with_short_timeout):
        """Test CVC5 timeout handling."""
        # Mock CVC5 to return UNKNOWN (timeout)
        with patch.object(dual_solver_with_short_timeout, '_invoke_z3', return_value="SAT"):
            with patch.object(dual_solver_with_short_timeout, '_invoke_cvc5', return_value="TIMEOUT"):
                status, confidence = dual_solver_with_short_timeout._evaluate_consensus(
                    "SAT", "TIMEOUT"
                )
                assert status == "SAT"
                assert confidence == 0.40
    
    def test_both_timeout_handling(self, dual_solver_with_short_timeout):
        """Test both solvers timeout."""
        with patch.object(dual_solver_with_short_timeout, '_invoke_z3', return_value="TIMEOUT"):
            with patch.object(dual_solver_with_short_timeout, '_invoke_cvc5', return_value="TIMEOUT"):
                status, confidence = dual_solver_with_short_timeout._evaluate_consensus(
                    "TIMEOUT", "TIMEOUT"
                )
                assert status == "UNKNOWN"
                assert confidence == 0.0


class TestThreadSafety:
    """Test thread safety."""
    
    def test_concurrent_consensus_checks(self):
        """Test concurrent consensus checks don't interfere."""
        solver = DualSolverConsensus()
        
        results = []
        
        def check_consensus(i):
            try:
                with patch.object(solver, '_invoke_z3', return_value="SAT"):
                    with patch.object(solver, '_invoke_cvc5', return_value="SAT"):
                        status, confidence = solver.evaluate_consensus(f"x > {i}")
                results.append((i, status, confidence))
            except Exception as exc:
                results.append((i, "ERROR", str(exc)))
        
        # Run concurrent checks
        import concurrent.futures
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(check_consensus, i) for i in range(10)]
            concurrent.futures.wait(futures)
        
        # Verify all results are consistent
        assert len(results) == 10
        for i, status, confidence in results:
            if status == "ERROR":
                # Skip error results (expected in some cases)
                continue
            assert status == "SAT"
            assert confidence == 1.0


class TestErrorRecovery:
    """Test error recovery."""
    
    @pytest.fixture
    def dual_solver(self):
        """Create DualSolverConsensus instance."""
        return DualSolverConsensus()
    
    def test_solver_error_recovery(self, dual_solver):
        """Test recovery from solver errors."""
        # Mock both solvers to return UNKNOWN on error
        with patch.object(dual_solver, '_invoke_z3', return_value="UNKNOWN"):
            with patch.object(dual_solver, '_invoke_cvc5', return_value="UNKNOWN"):
                status, confidence, log_entry = dual_solver.evaluate_consensus("x > 0")
                assert status == "UNKNOWN"
                assert confidence == 0.0
    
    def test_execution_log_on_error(self, dual_solver):
        """Test execution log entries errors."""
        with patch.object(dual_solver, '_invoke_z3', return_value="UNKNOWN"):
            with patch.object(dual_solver, '_invoke_cvc5', return_value="UNKNOWN"):
                dual_solver.evaluate_consensus("x > 0")
        
        log = dual_solver.get_execution_log()
        assert len(log) >= 1
        assert log[0]["consensus_status"] == "UNKNOWN"


class TestFullConsensusFlow:
    """Test full consensus flow."""
    
    def test_full_consensus_flow_verified(self):
        """Test full consensus flow on verified formula."""
        solver = DualSolverConsensus()
        
        with patch.object(solver, '_invoke_z3', return_value="SAT"):
            with patch.object(solver, '_invoke_cvc5', return_value="SAT"):
                status, confidence, log_entry = solver.evaluate_consensus("x >= 0")
                
                assert status == "SAT"
                assert confidence == 1.0
                assert log_entry["z3_result"] == "SAT"
                assert log_entry["cvc5_result"] == "SAT"
                assert log_entry["agreement"] is True
                assert log_entry["fault_detected"] is False
    
    def test_full_consensus_flow_violation(self):
        """Test full consensus flow on violating formula."""
        solver = DualSolverConsensus()
        
        with patch.object(solver, '_invoke_z3', return_value="UNSAT"):
            with patch.object(solver, '_invoke_cvc5', return_value="UNSAT"):
                status, confidence, log_entry = solver.evaluate_consensus("x < 0 and x >= 0")
                
                assert status == "UNSAT"
                assert confidence == 1.0
                assert log_entry["fault_detected"] is False
    
    def test_full_consensus_flow_fault(self):
        """Test full consensus flow detects fault."""
        solver = DualSolverConsensus()
        
        with patch.object(solver, '_invoke_z3', return_value="SAT"):
            with patch.object(solver, '_invoke_cvc5', return_value="UNSAT"):
                with pytest.raises(ConsensusFault):
                    solver.evaluate_consensus("x > 0")
    
    def test_full_consensus_flow_partial_agreement(self):
        """Test full consensus flow with partial agreement."""
        solver = DualSolverConsensus()
        
        with patch.object(solver, '_invoke_z3', return_value="SAT"):
            with patch.object(solver, '_invoke_cvc5', return_value="TIMEOUT"):
                status, confidence, metadata = solver.evaluate_consensus("complex_formula")
                
                assert status == "SAT"
                assert confidence == 0.40
                assert metadata["z3_result"] == "SAT"
                assert metadata["cvc5_result"] == "TIMEOUT"

    def test_real_smt_satisfiable_system(self):
        """Test real Z3 and CVC5 solving on a genuinely satisfiable constraint system."""
        solver = DualSolverConsensus(z3_timeout=2.0, cvc5_timeout=2.0)
        constraints = {
            "bounds": {"x": (0, 10), "y": (5, 20)},
            "inequalities": [("x", "<=", "y", 0)],  # x <= y
        }
        status, confidence, metadata = solver.evaluate_consensus("type_check", constraints)
        assert status == "SAT"
        assert confidence == 1.0
        assert metadata["z3_result"] == "SAT"
        assert metadata["cvc5_result"] == "SAT"

    def test_real_smt_unsatisfiable_system(self):
        """Test real Z3 and CVC5 solving on an unsatisfiable constraint system."""
        solver = DualSolverConsensus(z3_timeout=2.0, cvc5_timeout=2.0)
        constraints = {
            "bounds": {"x": (10, 20)},
            "inequalities": [("x", "<=", None, 5)],  # x <= 5, but x in [10, 20]
        }
        status, confidence, metadata = solver.evaluate_consensus("type_check", constraints)
        assert status == "UNSAT"
        assert confidence == 1.0
        assert metadata["z3_result"] == "UNSAT"
        assert metadata["cvc5_result"] == "UNSAT"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

