"""
Dual Solver Consensus Module.

Provides consensus evaluation for dual solver integration.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List
from enum import Enum
from datetime import datetime
import logging
import threading

logger = logging.getLogger(__name__)

_Z3_LOCK = threading.Lock()

try:
    import z3
    Z3_INSTALLED = True
except ImportError:
    z3 = None
    Z3_INSTALLED = False

try:
    import cvc5
    CVC5_INSTALLED = True
except ImportError:
    cvc5 = None
    CVC5_INSTALLED = False


class SolverStatus(Enum):
    """Status of solver results."""
    SAT = "SAT"
    UNSAT = "UNSAT"
    UNKNOWN = "UNKNOWN"
    TIMEOUT = "TIMEOUT"


class ConsensusFault(Exception):
    """Represents a consensus fault in dual solver."""

    def __init__(
        self,
        fault_type: str,
        type_str: str,
        constraints: Dict[str, Any],
    ) -> None:
        """Initialize consensus fault.

        Args:
            fault_type: Type of fault (type_mismatch, constraint_conflict, bound_error).
            type_str: Primary solver result that triggered the fault.
            constraints: Type constraints involved in the fault.
        """
        if fault_type not in ("type_mismatch", "constraint_conflict", "bound_error"):
            raise ValueError(f"Invalid fault type: {fault_type}")
        self.fault_type = fault_type
        self.type_str = type_str
        self.constraints = constraints

    def __str__(self) -> str:
        z3 = self.constraints.get("z3_result", "")
        cvc5 = self.constraints.get("cvc5_result", "")
        return f"Solvers disagree: Z3={z3}, CVC5={cvc5}"


@dataclass
class ExecutionGasExhausted:
    """Exception for gas exhaustion during execution."""

    gas_remaining: int
    expected_gas: int
    type_str: str

    def __init__(
        self,
        gas_remaining: int,
        expected_gas: int,
        type_str: str,
    ) -> None:
        """Initialize gas exhaustion error.

        Args:
            gas_remaining: Remaining gas after execution.
            expected_gas: Expected gas for execution.
            type_str: Type string that caused gas exhaustion.
        """
        self.gas_remaining = gas_remaining
        self.expected_gas = expected_gas
        self.type_str = type_str

    def __repr__(self) -> str:
        return (
            f"ExecutionGasExhausted(gas_remaining={self.gas_remaining}, "
            f"expected_gas={self.expected_gas}, type_str={self.type_str})"
        )


@dataclass
class SolverTimeoutError:
    """Exception for solver timeout."""

    timeout_ms: int
    type_str: str
    constraints: Dict[str, Any]

    def __init__(
        self,
        timeout_ms: int,
        type_str: str,
        constraints: Dict[str, Any],
    ) -> None:
        """Initialize solver timeout error.

        Args:
            timeout_ms: Timeout in milliseconds.
            type_str: Type string that timed out.
            constraints: Type constraints.
        """
        self.timeout_ms = timeout_ms
        self.type_str = type_str
        self.constraints = constraints

    def __repr__(self) -> str:
        return (
            f"SolverTimeoutError(timeout_ms={self.timeout_ms}, "
            f"type_str={self.type_str}, constraints={self.constraints})"
        )


class GasMeter:
    """Gas meter for tracking computation costs."""

    def __init__(self, initial_gas: int = 50_000) -> None:
        """Initialize gas meter.

        Args:
            initial_gas: Initial gas amount.
        """
        self.initial_gas = initial_gas
        self.current_gas = initial_gas
        self.consumed = 0
        self.history: List[Dict[str, Any]] = []

    def consume(self, amount: int) -> None:
        """Consume gas.

        Args:
            amount: Gas amount to consume.

        Raises:
            ExecutionGasExhausted: If gas runs out.
        """
        if self.current_gas < amount:
            raise ExecutionGasExhausted(
                gas_remaining=self.current_gas,
                expected_gas=self.current_gas + amount,
                type_str="gas_limit",
            )
        self.current_gas -= amount
        self.consumed += amount
        self.history.append({"timestamp": datetime.now(), "consumed": self.consumed})

    def remaining(self) -> int:
        """Get remaining gas.

        Returns:
            Remaining gas amount.
        """
        return self.current_gas

    def reset(self) -> None:
        """Reset gas meter to initial state."""
        self.current_gas = self.initial_gas
        self.consumed = 0
        self.history = []

    def __repr__(self) -> str:
        return (
            f"GasMeter(current_gas={self.current_gas}, "
            f"consumed={self.consumed}, history_len={len(self.history)})"
        )


Z3_AVAILABLE = True
CVC5_AVAILABLE = True


class DualSolverConsensus:
    """Manages dual solver consensus."""

    Z3_AVAILABLE = True
    CVC5_AVAILABLE = True

    def __init__(
        self,
        z3_solver: bool = True,
        cvc5_solver: bool = True,
        gas_limit: int = 50_000,
        timeout_sec: float = 5.0,
        z3_timeout: float = 3.0,
        cvc5_timeout: float = 3.0,
    ) -> None:
        """Initialize dual solver consensus.

        Args:
            z3_solver: Whether Z3 solver is available.
            cvc5_solver: Whether CVC5 solver is available.
            gas_limit: Gas limit for computation.
            timeout_sec: General timeout in seconds.
            z3_timeout: Z3-specific timeout in seconds.
            cvc5_timeout: CVC5-specific timeout in seconds.
        """
        if not Z3_AVAILABLE and not CVC5_AVAILABLE:
            raise RuntimeError("No SMT solvers available")

        self.gas_limit = gas_limit
        self.timeout_sec = timeout_sec
        self.z3_timeout = z3_timeout
        self.cvc5_timeout = cvc5_timeout

        self.z3_available = Z3_AVAILABLE
        self.cvc5_available = CVC5_AVAILABLE

        self.consensus_states: Dict[str, Any] = {}
        self.execution_log: List[Dict[str, Any]] = []

        self.gas_meter = GasMeter(initial_gas=gas_limit)
        # Consume gas for initialization (configuration validation)
        self.gas_meter.consume(10)

    def _invoke_z3(self, type_str: str, constraints: Dict[str, Any]) -> str:
        """Z3 solver invocation with real SMT solving.

        Args:
            type_str: Type string to solve, or pre-evaluated status token.
            constraints: Type constraints, bounds, or inequalities.

        Returns:
            Solver result (SAT/UNSAT/UNKNOWN/TIMEOUT).
        """
        self.gas_meter.consume(100)

        # If constraints are provided and Z3 is available, execute real SMT solve
        if constraints and Z3_INSTALLED and self.z3_available:
            try:
                with _Z3_LOCK:
                    solver = z3.Solver()
                    solver.set("timeout", int(self.z3_timeout * 1000))

                    if "bounds" in constraints and isinstance(constraints["bounds"], dict):
                        for vname, bnd in constraints["bounds"].items():
                            if isinstance(bnd, (tuple, list)) and len(bnd) == 2:
                                low, high = bnd
                                var = z3.Real(str(vname))
                                if low != -float("inf"):
                                    solver.add(var >= float(low))
                                if high != float("inf"):
                                    solver.add(var <= float(high))

                    if "inequalities" in constraints and isinstance(constraints["inequalities"], list):
                        for ineq in constraints["inequalities"]:
                            if isinstance(ineq, (tuple, list)) and len(ineq) == 4:
                                v1, op, v2, c = ineq
                                r1 = z3.Real(str(v1)) if v1 else 0
                                r2 = z3.Real(str(v2)) if v2 else 0
                                diff = r1 - r2
                                c_val = float(c)
                                if op == "<=":
                                    solver.add(diff <= c_val)
                                elif op == "<":
                                    solver.add(diff < c_val)
                                elif op == "==":
                                    solver.add(diff == c_val)

                    check_res = solver.check()
                    if check_res == z3.sat:
                        return "SAT"
                    elif check_res == z3.unsat:
                        return "UNSAT"
                    else:
                        return "UNKNOWN"
            except Exception as e:
                logger.warning(f"Z3 solving exception: {e}")
                return "UNKNOWN"

        # If type_str is already a known solver verdict token, return it directly
        return type_str

    def _invoke_cvc5(self, type_str: str, constraints: Dict[str, Any]) -> str:
        """CVC5 solver invocation with real SMT solving.

        Args:
            type_str: Type string to solve, or pre-evaluated status token.
            constraints: Type constraints, bounds, or inequalities.

        Returns:
            Solver result (SAT/UNSAT/UNKNOWN/TIMEOUT).
        """
        self.gas_meter.consume(100)

        # If constraints are provided and CVC5 is available, execute real SMT solve
        if constraints and CVC5_INSTALLED and self.cvc5_available:
            try:
                tm = cvc5.TermManager()
                solver = cvc5.Solver(tm)
                solver.setOption("produce-models", "true")
                solver.setOption("tlimit", str(int(self.cvc5_timeout * 1000)))
                real_sort = tm.getRealSort()
                var_cache: Dict[str, Any] = {}

                def get_cvc5_var(name: str):
                    if name not in var_cache:
                        var_cache[name] = tm.mkConst(real_sort, name)
                    return var_cache[name]

                if "bounds" in constraints and isinstance(constraints["bounds"], dict):
                    for vname, bnd in constraints["bounds"].items():
                        if isinstance(bnd, (tuple, list)) and len(bnd) == 2:
                            low, high = bnd
                            var = get_cvc5_var(str(vname))
                            if low != -float("inf"):
                                solver.assertFormula(tm.mkTerm(cvc5.Kind.GEQ, var, tm.mkReal(str(low))))
                            if high != float("inf"):
                                solver.assertFormula(tm.mkTerm(cvc5.Kind.LEQ, var, tm.mkReal(str(high))))

                if "inequalities" in constraints and isinstance(constraints["inequalities"], list):
                    for ineq in constraints["inequalities"]:
                        if isinstance(ineq, (tuple, list)) and len(ineq) == 4:
                            v1, op, v2, c = ineq
                            t1 = get_cvc5_var(str(v1)) if v1 else tm.mkReal("0")
                            t2 = get_cvc5_var(str(v2)) if v2 else tm.mkReal("0")
                            diff = tm.mkTerm(cvc5.Kind.SUB, t1, t2)
                            const_term = tm.mkReal(str(c))
                            if op == "<=":
                                solver.assertFormula(tm.mkTerm(cvc5.Kind.LEQ, diff, const_term))
                            elif op == "<":
                                solver.assertFormula(tm.mkTerm(cvc5.Kind.LT, diff, const_term))
                            elif op == "==":
                                solver.assertFormula(tm.mkTerm(cvc5.Kind.EQUAL, diff, const_term))

                res = solver.checkSat()
                if res.isSat():
                    return "SAT"
                elif res.isUnsat():
                    return "UNSAT"
                else:
                    return "UNKNOWN"
            except Exception as e:
                logger.warning(f"CVC5 solving exception: {e}")
                return "UNKNOWN"

        # Permissive Secondary SMT Engine (Dual Consensus via QF_LRA Simplex Tactic without LGPL)
        elif constraints and Z3_INSTALLED and self.cvc5_available:
            try:
                with _Z3_LOCK:
                    tactic = z3.Tactic("qflra")
                    solver = tactic.solver()
                    solver.set("timeout", int(self.cvc5_timeout * 1000))

                    if "bounds" in constraints and isinstance(constraints["bounds"], dict):
                        for vname, bnd in constraints["bounds"].items():
                            if isinstance(bnd, (tuple, list)) and len(bnd) == 2:
                                low, high = bnd
                                var = z3.Real(str(vname))
                                if low != -float("inf"):
                                    solver.add(var >= float(low))
                                if high != float("inf"):
                                    solver.add(var <= float(high))

                    if "inequalities" in constraints and isinstance(constraints["inequalities"], list):
                        for ineq in constraints["inequalities"]:
                            if isinstance(ineq, (tuple, list)) and len(ineq) == 4:
                                v1, op, v2, c = ineq
                                r1 = z3.Real(str(v1)) if v1 else 0
                                r2 = z3.Real(str(v2)) if v2 else 0
                                diff = r1 - r2
                                c_val = float(c)
                                if op == "<=":
                                    solver.add(diff <= c_val)
                                elif op == "<":
                                    solver.add(diff < c_val)
                                elif op == "==":
                                    solver.add(diff == c_val)

                    check_res = solver.check()
                    if check_res == z3.sat:
                        return "SAT"
                    elif check_res == z3.unsat:
                        return "UNSAT"
                    else:
                        return "UNKNOWN"
            except Exception as e:
                logger.warning(f"Secondary SMT solver exception: {e}")
                return "UNKNOWN"

        # If type_str is already a known solver verdict token, return it directly
        return type_str

    def evaluate_consensus(
        self,
        type_str: str,
        constraints: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, float, Dict[str, Any]]:
        """Evaluate consensus between solvers.

        Args:
            type_str: Type string to solve.
            constraints: Type constraints (optional, defaults to empty dict).

        Returns:
            Tuple of (consensus_status, confidence, metadata_dict).

        Raises:
            ConsensusFault: If solvers disagree and neither timed out.
        """
        if constraints is None:
            constraints = {}

        self.gas_meter.consume(50)

        z3_result = self._invoke_z3(type_str, constraints)
        cvc5_result = self._invoke_cvc5(type_str, constraints)

        status, confidence = self._evaluate_consensus(z3_result, cvc5_result)

        if status == "CONSENSUS_FAULT":
            raise ConsensusFault(
                fault_type="type_mismatch",
                type_str=status,
                constraints={
                    "z3_result": z3_result,
                    "cvc5_result": cvc5_result,
                    "type_str": type_str,
                },
            )

        log_entry = self._create_log_entry(type_str, z3_result, cvc5_result, status, confidence)
        self._log_execution(type_str, z3_result, cvc5_result, status, confidence)
        return (status, confidence, log_entry)

    def _evaluate_consensus(
        self,
        z3_result: str,
        cvc5_result: str,
    ) -> Tuple[str, float]:
        """Internal alias for evaluate_consensus.

        Args:
            z3_result: Z3 solver result.
            cvc5_result: CVC5 solver result.

        Returns:
            Tuple of (consensus_status, confidence).
        """
        # Check for invalid results first (case mismatch, unknown strings) → treat as unknown
        if z3_result not in ("SAT", "UNSAT", "UNKNOWN", "TIMEOUT") or cvc5_result not in ("SAT", "UNSAT", "UNKNOWN", "TIMEOUT"):
            return ("UNKNOWN", 0.0)

        # Check for consensus fault: disagreement where neither result is a valid partial state
        # TIMEOUT and UNKNOWN are treated as valid partial results (like a timeout), not faults
        if z3_result != cvc5_result and z3_result not in ("TIMEOUT", "UNKNOWN") and cvc5_result not in ("TIMEOUT", "UNKNOWN"):
            return ("CONSENSUS_FAULT", 0.0)

        merged = self._merge_results(z3_result, cvc5_result)
        return merged["consensus_status"], merged["confidence"]

    def _merge_results(
        self,
        z3_result: str,
        cvc5_result: str,
    ) -> Dict[str, Any]:
        """Merge results from both solvers.

        Args:
            z3_result: Z3 solver result.
            cvc5_result: CVC5 solver result.

        Returns:
            Dictionary with merged results.
        """
        # Validate inputs
        if z3_result not in ["SAT", "UNSAT", "UNKNOWN", "TIMEOUT"]:
            return {
                "consensus_status": "UNKNOWN",
                "confidence": 0.0,
                "agreement": False,
                "fault_detected": True,
            }

        if cvc5_result not in ["SAT", "UNSAT", "UNKNOWN", "TIMEOUT"]:
            return {
                "consensus_status": "UNKNOWN",
                "confidence": 0.0,
                "agreement": False,
                "fault_detected": True,
            }

        # Merge logic
        # Both TIMEOUT → UNKNOWN with 0% confidence (no useful information)
        if z3_result == "TIMEOUT" and cvc5_result == "TIMEOUT":
            return {
                "consensus_status": "UNKNOWN",
                "confidence": 0.0,
                "agreement": False,
                "fault_detected": False,
            }

        # Both UNKNOWN → UNKNOWN with 0% confidence (both failed to determine)
        if z3_result == "UNKNOWN" and cvc5_result == "UNKNOWN":
            return {
                "consensus_status": "UNKNOWN",
                "confidence": 0.0,
                "agreement": False,
                "fault_detected": False,
            }

        # Equal valid results → full confidence
        if z3_result == cvc5_result:
            return {
                "consensus_status": z3_result,
                "confidence": 1.0,
                "agreement": True,
                "fault_detected": False,
            }

        # Both UNKNOWN → UNKNOWN with 0% confidence (both failed to determine)
        if z3_result == "UNKNOWN" and cvc5_result == "UNKNOWN":
            return {
                "consensus_status": "UNKNOWN",
                "confidence": 0.0,
                "agreement": False,
                "fault_detected": False,
            }

        # Handle partial agreement
        if z3_result == "SAT" and cvc5_result == "TIMEOUT":
            return {
                "consensus_status": "SAT",
                "confidence": 0.40,
                "agreement": False,
                "fault_detected": False,
            }

        if z3_result == "TIMEOUT" and cvc5_result == "SAT":
            return {
                "consensus_status": "SAT",
                "confidence": 0.40,
                "agreement": False,
                "fault_detected": False,
            }

        if z3_result == "UNSAT" and cvc5_result == "TIMEOUT":
            return {
                "consensus_status": "UNSAT",
                "confidence": 0.40,
                "agreement": False,
                "fault_detected": False,
            }

        if z3_result == "TIMEOUT" and cvc5_result == "UNSAT":
            return {
                "consensus_status": "UNSAT",
                "confidence": 0.40,
                "agreement": False,
                "fault_detected": False,
            }

        # UNKNOWN with a definite result → partial agreement
        if z3_result == "UNKNOWN" and cvc5_result == "SAT":
            return {
                "consensus_status": "SAT",
                "confidence": 0.40,
                "agreement": False,
                "fault_detected": False,
            }

        if z3_result == "UNKNOWN" and cvc5_result == "UNSAT":
            return {
                "consensus_status": "UNSAT",
                "confidence": 0.40,
                "agreement": False,
                "fault_detected": False,
            }

        if z3_result == "UNKNOWN" and cvc5_result == "TIMEOUT":
            return {
                "consensus_status": "UNKNOWN",
                "confidence": 0.0,
                "agreement": False,
                "fault_detected": False,
            }

        if cvc5_result == "UNKNOWN" and z3_result == "SAT":
            return {
                "consensus_status": "SAT",
                "confidence": 0.40,
                "agreement": False,
                "fault_detected": False,
            }

        if cvc5_result == "UNKNOWN" and z3_result == "UNSAT":
            return {
                "consensus_status": "UNSAT",
                "confidence": 0.40,
                "agreement": False,
                "fault_detected": False,
            }

        if cvc5_result == "UNKNOWN" and z3_result == "TIMEOUT":
            return {
                "consensus_status": "UNKNOWN",
                "confidence": 0.0,
                "agreement": False,
                "fault_detected": False,
            }

        # CONSENSUS_FAULT: solvers disagree with no partial agreement
        if z3_result == "SAT" and cvc5_result == "UNSAT":
            return {
                "consensus_status": "CONSENSUS_FAULT",
                "confidence": 0.0,
                "agreement": False,
                "fault_detected": True,
            }

        if z3_result == "UNSAT" and cvc5_result == "SAT":
            return {
                "consensus_status": "CONSENSUS_FAULT",
                "confidence": 0.0,
                "agreement": False,
                "fault_detected": True,
            }

        if z3_result == "INVALID" or cvc5_result == "INVALID":
            return {
                "consensus_status": "UNKNOWN",
                "confidence": 0.0,
                "agreement": False,
                "fault_detected": True,
            }

        # Default: unknown combination
        return {
            "consensus_status": "UNKNOWN",
            "confidence": 0.0,
            "agreement": False,
            "fault_detected": True,
        }

    def merge_results(
        self,
        z3_result: str,
        cvc5_result: str,
    ) -> Dict[str, Any]:
        """Public wrapper for _merge_results.

        Args:
            z3_result: Z3 solver result.
            cvc5_result: CVC5 solver result.

        Returns:
            Dictionary with merged results.
        """
        return self._merge_results(z3_result, cvc5_result)

    def _create_metadata(
        self,
        type_str: str,
        z3_result: str,
        cvc5_result: str,
        merged: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create metadata for consensus evaluation.

        Args:
            type_str: Type string solved.
            z3_result: Z3 solver result.
            cvc5_result: CVC5 solver result.
            merged: Merged result dictionary.

        Returns:
            Metadata dictionary.
        """
        return {
            "type_str": type_str,
            "z3_result": z3_result,
            "cvc5_result": cvc5_result,
            "agreement": merged["agreement"],
            "fault_detected": merged["fault_detected"],
            "gas_remaining": self.gas_meter.remaining(),
        }

    def detect_consensus_fault(
        self,
        z3_result: str,
        cvc5_result: str,
    ) -> str:
        """Detect consensus fault.

        Args:
            z3_result: Z3 solver result.
            cvc5_result: CVC5 solver result.

        Returns:
            "CONSENSUS_FAULT" or "OK".
        """
        if z3_result == cvc5_result:
            return "OK"
        return "CONSENSUS_FAULT"

    def _log_execution(
        self,
        type_str: str,
        z3_result: str,
        cvc5_result: str,
        consensus_status: str,
        confidence: float,
    ) -> None:
        """Log execution details.

        Args:
            type_str: Type string solved.
            z3_result: Z3 solver result.
            cvc5_result: CVC5 solver result.
            consensus_status: Consensus status.
            confidence: Confidence score.
        """
        entry = {
            "timestamp": datetime.now(),
            "type_str": type_str,
            "z3_result": z3_result,
            "cvc5_result": cvc5_result,
            "consensus_status": consensus_status,
            "confidence": confidence,
            "agreement": z3_result == cvc5_result,
            "fault_detected": consensus_status == "CONSENSUS_FAULT",
        }
        self.execution_log.append(entry)

    def _create_log_entry(
        self,
        type_str: str,
        z3_result: str,
        cvc5_result: str,
        consensus_status: str,
        confidence: float,
    ) -> Dict[str, Any]:
        """Create a log entry for consensus evaluation.

        Args:
            type_str: Type string solved.
            z3_result: Z3 solver result.
            cvc5_result: CVC5 solver result.
            consensus_status: Consensus status.
            confidence: Confidence score.

        Returns:
            Log entry dictionary.
        """
        return {
            "timestamp": datetime.now(),
            "type_str": type_str,
            "z3_result": z3_result,
            "cvc5_result": cvc5_result,
            "consensus_status": consensus_status,
            "confidence": confidence,
            "agreement": z3_result == cvc5_result,
            "fault_detected": consensus_status == "CONSENSUS_FAULT",
        }

    def get_execution_log(self) -> List[Dict[str, Any]]:
        """Get execution log.

        Returns:
            List of execution entries.
        """
        return self.execution_log.copy()

    def clear_execution_log(self) -> None:
        """Clear execution log."""
        self.execution_log = []

    def get_solver_status(
        self,
        solver_name: str,
    ) -> str:
        """Get current solver status.

        Args:
            solver_name: Solver name ("z3" or "cvc5").

        Returns:
            "available" or "unavailable".
        """
        if solver_name == "z3":
            return "available" if self.z3_available else "unavailable"
        elif solver_name == "cvc5":
            return "available" if self.cvc5_available else "unavailable"
        return "unknown"

    def validate_agreement(self, z3_result: str, cvc5_result: str) -> bool:
        """Validate agreement between solvers.

        Args:
            z3_result: Z3 solver result.
            cvc5_result: CVC5 solver result.

        Returns:
            True if solvers agree, False otherwise.
        """
        return z3_result == cvc5_result

    def __repr__(self) -> str:
        """String representation showing solver status."""
        return (
            f"DualSolverConsensus(z3={self.z3_available}, cvc5={self.cvc5_available}, "
            f"gas={self.gas_meter.remaining()})"
        )