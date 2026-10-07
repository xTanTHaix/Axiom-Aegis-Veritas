"""
AXIOM-AEGIS-VERITAS Sovereign MCP Server.

Provides a Model Context Protocol (MCP) interface exposing formal verification tools:
1. axiom_verify_file: 8-layer formal verification with Layer 8 cryptographic seal.
2. axiom_verify_workspace: recursive workspace verification and completeness audit.
3. axiom_audit_receipt: cryptographic audit and tamper-verification of an AttestationSeal.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.attestation_oracle import AttestationOracle, AttestationVerdict
from src.core.engine_kernel import EngineKernel, PipelineDriver, PipelineResult

logger = logging.getLogger("axiom.mcp")


def configure_logging() -> None:
    """Configures dedicated stderr logger for MCP server without stdout leakage."""
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setFormatter(
            logging.Formatter("[AXIOM-MCP] %(asctime)s - %(levelname)s - %(message)s")
        )
        logger.addHandler(stderr_handler)


MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "axiom-aegis-veritas"
SERVER_VERSION = "1.0.0"

AVAILABLE_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "axiom_verify_file",
        "description": (
            "Formally verify a Python file through the 8-layer Axiom-Aegis-Veritas pipeline. "
            "Evaluates CST Merkle caching, Octagon DBM, Dual SMT Consensus, DPOR concurrency, "
            "PEP 695 typing, Semiring defect confidence, Witness generation, and synthesizes "
            "a Layer 8 cryptographic AttestationSeal (bitmask 0x7F)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute or workspace-relative path to the Python file to verify.",
                },
                "strict": {
                    "type": "boolean",
                    "description": "Whether to require bitmask 0x7F completeness (default: true).",
                    "default": True,
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "axiom_verify_workspace",
        "description": (
            "Recursively verify all Python source files in a workspace directory through the "
            "8-layer pipeline, ensuring fault isolation and per-file cryptographic attestation."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_path": {
                    "type": "string",
                    "description": "Path to workspace directory containing Python source files.",
                },
                "max_files": {
                    "type": "integer",
                    "description": "Optional maximum number of files to analyze (default: unlimited).",
                },
            },
            "required": ["workspace_path"],
        },
    },
    {
        "name": "axiom_audit_receipt",
        "description": (
            "Audit the cryptographic integrity of an existing Layer 8 AttestationSeal against "
            "the current physical source code, detecting bit-flips and tamper events."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the source file.",
                },
                "expected_seal_hash": {
                    "type": "string",
                    "description": "Expected 64-character BLAKE2b seal hash to verify against.",
                },
            },
            "required": ["file_path", "expected_seal_hash"],
        },
    },
]


class AxiomMCPServer:
    """Standard JSON-RPC 2.0 MCP Server for Axiom-Aegis-Veritas."""

    def __init__(self) -> None:
        self.kernel = EngineKernel()
        self.oracle = AttestationOracle()

    def handle_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Processes an incoming JSON-RPC 2.0 request."""
        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        # Notifications without ID
        if method == "notifications/initialized":
            logger.info("Client completed initialization handshake.")
            return None

        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {
                        "tools": {
                            "listChanged": False,
                        },
                    },
                    "serverInfo": {
                        "name": SERVER_NAME,
                        "version": SERVER_VERSION,
                    },
                },
            }

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": AVAILABLE_TOOLS,
                },
            }

        if method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})
            return self._dispatch_tool_call(req_id, tool_name, tool_args)

        # Unrecognized method
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32601,
                "message": f"Method '{method}' not found.",
            },
        }

    def _dispatch_tool_call(
        self, req_id: Any, tool_name: str, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Dispatches an MCP tool call to the corresponding implementation."""
        try:
            if tool_name == "axiom_verify_file":
                file_path = args.get("file_path")
                if not file_path:
                    return self._tool_error(req_id, "Missing 'file_path' argument.")
                result_data = self.verify_file(file_path, strict=args.get("strict", True))
                return self._tool_success(req_id, result_data)

            elif tool_name == "axiom_verify_workspace":
                workspace_path = args.get("workspace_path")
                if not workspace_path:
                    return self._tool_error(req_id, "Missing 'workspace_path' argument.")
                max_files = args.get("max_files")
                result_data = self.verify_workspace(workspace_path, max_files=max_files)
                return self._tool_success(req_id, result_data)

            elif tool_name == "axiom_audit_receipt":
                file_path = args.get("file_path")
                expected_hash = args.get("expected_seal_hash")
                if not file_path or not expected_hash:
                    return self._tool_error(req_id, "Missing 'file_path' or 'expected_seal_hash'.")
                result_data = self.audit_receipt(file_path, expected_hash)
                return self._tool_success(req_id, result_data)

            else:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32602,
                        "message": f"Unknown tool: '{tool_name}'",
                    },
                }

        except Exception as exc:
            logger.error(f"Error executing tool {tool_name}: {exc}", exc_info=True)
            return self._tool_error(req_id, f"Execution failed: {type(exc).__name__}: {str(exc)}")

    def verify_file(self, file_path_str: str, strict: bool = True) -> Dict[str, Any]:
        """Executes 8-layer verification on a single Python file."""
        target_path = Path(file_path_str).resolve()
        if not target_path.exists() or not target_path.is_file():
            return {
                "success": False,
                "error": f"Target file does not exist: {target_path}",
            }

        driver = PipelineDriver(file_path=target_path)
        res = driver.run_pipeline()

        is_sealed = False
        bitmask = 0
        seal_hash = ""
        missing_layers: List[str] = []
        failure_reasons: Dict[str, str] = {}

        if res.attestation_seal:
            is_sealed = res.attestation_seal.is_complete
            bitmask = res.attestation_seal.bitmask
            seal_hash = res.attestation_seal.seal_hash
            missing_layers = res.attestation_seal.missing_layers
            failure_reasons = res.attestation_seal.failure_reasons

        passed = res.success and (is_sealed if strict else True)

        return {
            "file": str(target_path),
            "status": "VERIFIED_SOUND" if passed else "VERIFICATION_FAILED",
            "success": passed,
            "bitmask": f"0x{bitmask:02X}",
            "is_complete_7layers": is_sealed,
            "seal_hash": seal_hash,
            "execution_time_sec": round(res.execution_time, 4),
            "missing_layers": missing_layers,
            "failure_reasons": failure_reasons,
            "layer_reports": {
                "L1_Merkle_Root": res.merkle_root,
                "L2_Octagon": res.octagon_summary,
                "L3_Consensus": res.consensus_result,
                "L4_DPOR": res.race_report,
                "L5_PEP695": res.type_report,
                "L6_Provenance": res.patch_report,
                "L7_Witness": res.witness_report,
                "L8_Attestation": res.layer8_report,
            },
        }

    def verify_workspace(
        self, workspace_path_str: str, max_files: Optional[int] = None
    ) -> Dict[str, Any]:
        """Recursively audits all Python files in the target directory."""
        ws_path = Path(workspace_path_str).resolve()
        if not ws_path.is_dir():
            return {"success": False, "error": f"Workspace directory not found: {ws_path}"}

        excluded = {".venv", "venv", "env", ".git", "__pycache__", ".pytest_cache", "build", "dist"}
        py_files = [
            p for p in sorted(ws_path.rglob("*.py"))
            if not any(part in excluded for part in p.parts)
        ]

        if max_files and max_files > 0:
            py_files = py_files[:max_files]

        total_files = len(py_files)
        passed_count = 0
        sealed_count = 0
        file_summaries: List[Dict[str, Any]] = []

        for pf in py_files:
            file_res = self.verify_file(str(pf), strict=False)
            if file_res.get("success"):
                passed_count += 1
            if file_res.get("is_complete_7layers"):
                sealed_count += 1
            file_summaries.append({
                "file": str(pf.relative_to(ws_path)),
                "status": file_res.get("status"),
                "is_sealed": file_res.get("is_complete_7layers"),
                "bitmask": file_res.get("bitmask"),
                "seal_hash": file_res.get("seal_hash"),
            })

        return {
            "workspace": str(ws_path),
            "total_files": total_files,
            "fully_sealed_files": sealed_count,
            "passed_files": passed_count,
            "completeness_rate": round((sealed_count / max(1, total_files)) * 100.0, 2),
            "all_sound": sealed_count == total_files,
            "files": file_summaries,
        }

    def audit_receipt(self, file_path_str: str, expected_seal_hash: str) -> Dict[str, Any]:
        """Verifies if the file's current attestation seal matches the expected seal."""
        verification = self.verify_file(file_path_str, strict=True)
        current_hash = verification.get("seal_hash", "")
        matches = (current_hash == expected_seal_hash) and verification.get("is_complete_7layers", False)

        return {
            "file": file_path_str,
            "expected_seal_hash": expected_seal_hash,
            "current_seal_hash": current_hash,
            "matches": matches,
            "tamper_detected": not matches,
            "verdict": "VERIFIED_AUTHENTIC" if matches else "INTEGRITY_VIOLATION",
        }

    def _tool_success(self, req_id: Any, data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(data, indent=2),
                    }
                ],
                "isError": False,
            },
        }

    def _tool_error(self, req_id: Any, message: str) -> Dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"error": message}, indent=2),
                    }
                ],
                "isError": True,
            },
        }

    def run_stdio_loop(self) -> None:
        """Runs the standard I/O JSON-RPC processing loop."""
        configure_logging()
        logger.info(f"Starting Axiom MCP Server on stdio (protocol {MCP_PROTOCOL_VERSION})...")
        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue

                request = json.loads(line)
                response = self.handle_request(request)
                if response is not None:
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()
            except json.JSONDecodeError as jde:
                logger.error(f"Malformed JSON: {jde}")
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {str(jde)}"},
                }
                sys.stdout.write(json.dumps(err_resp) + "\n")
                sys.stdout.flush()
            except Exception as e:
                logger.critical(f"Fatal stdio loop error: {e}", exc_info=True)


def main() -> None:
    """MCP entrypoint"""
    # Enforce UTF-8 on Windows console
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")

    server = AxiomMCPServer()
    server.run_stdio_loop()


if __name__ == "__main__":
    main()
