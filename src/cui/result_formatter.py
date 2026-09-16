"""
CLI Module: Verification Result Formatter & Report Generator.

Features:
- Multiple output formats (text, JSON, XML, HTML, Markdown)
- Structured result formatting with statistics
- Report generation with detailed analysis
- Support for custom formatting options
- Color-coded output for readability
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional, TextIO, Union

import sys
from colorama import Fore, Style, init

init(autoreset=True)


@dataclass
class ResultConfig:
    """Configuration for result formatter."""

    output_format: str = "text"
    show_statistics: bool = True
    show_detailed_analysis: bool = False
    show_summary: bool = True
    show_errors: bool = True
    show_warnings: bool = True
    color_output: bool = True
    timestamp_format: str = "%Y-%m-%d %H:%M:%S"
    include_source_code: bool = False
    include_line_numbers: bool = False


class Result:
    """Represents a verification result."""

    def __init__(
        self,
        status: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        errors: Optional[List[Dict[str, Any]]] = None,
        warnings: Optional[List[Dict[str, Any]]] = None,
        statistics: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize result.

        Args:
            status: Result status (PASS, FAIL, SKIP, ERROR).
            message: Result message.
            details: Additional details.
            errors: List of errors.
            warnings: List of warnings.
            statistics: Result statistics.
        """
        self.status = status
        self.message = message
        self.details = details or {}
        self.errors = errors or []
        self.warnings = warnings or []
        self.statistics = statistics or {}

    def __str__(self) -> str:
        """String representation."""
        return f"[{self.status}] {self.message}"


class TextFormatter:
    """Text format formatter for verification results."""

    def __init__(self, config: Optional[ResultConfig] = None) -> None:
        """Initialize text formatter.

        Args:
            config: Optional result configuration.
        """
        self.config = config or ResultConfig()
        self.color_output = self.config.color_output

    def _format_status(self, status: str) -> str:
        """Format status with appropriate color.

        Args:
            status: Status string.

        Returns:
            Formatted status.
        """
        if self.color_output:
            status_map = {
                "PASS": Fore.GREEN,
                "FAIL": Fore.RED,
                "SKIP": Fore.YELLOW,
                "ERROR": Fore.MAGENTA,
            }
            return f"{status_map.get(status, Fore.WHITE)}{status}{Style.RESET_ALL}"
        return status

    def _format_error(self, error: Dict[str, Any]) -> str:
        """Format error with line numbers if available.

        Args:
            error: Error dictionary.

        Returns:
            Formatted error string.
        """
        lines = [f"{Fore.RED}[ERROR]{Style.RESET_ALL}"]

        if "line" in error and error["line"] is not None:
            lines.append(f"  Line {error['line']}: {error.get('message', '')}")

        if "file" in error:
            lines.append(f"  File: {error['file']}")

        if "column" in error and error["column"] is not None:
            lines.append(f"  Column: {error['column']}")

        if "message" in error:
            lines.append(f"  {error['message']}")

        return "\n".join(lines)

    def _format_warning(self, warning: Dict[str, Any]) -> str:
        """Format warning.

        Args:
            warning: Warning dictionary.

        Returns:
            Formatted warning string.
        """
        lines = [f"{Fore.YELLOW}[WARNING]{Style.RESET_ALL}"]

        if "line" in warning and warning["line"] is not None:
            lines.append(f"  Line {warning['line']}: {warning.get('message', '')}")

        if "file" in warning:
            lines.append(f"  File: {warning['file']}")

        if "message" in warning:
            lines.append(f"  {warning['message']}")

        return "\n".join(lines)

    def format_result(self, result: Result) -> str:
        """Format verification result.

        Args:
            result: Result to format.

        Returns:
            Formatted result string.
        """
        lines = []

        # Header
        timestamp = datetime.now(self.config.timestamp_format).strftime(self.config.timestamp_format)
        lines.append(f"{Fore.CYAN}=== VERIFICATION RESULT ==={Style.RESET_ALL}")
        lines.append(f"  Timestamp: {timestamp}")
        lines.append(f"  Status: {self._format_status(result.status)}")
        lines.append("")

        # Message
        if result.message:
            lines.append(f"  {result.message}")
            lines.append("")

        # Details
        if result.details:
            lines.append("  Details:")
            for key, value in result.details.items():
                lines.append(f"    - {key}: {value}")
            lines.append("")

        # Errors
        if self.config.show_errors and result.errors:
            lines.append(f"  {Fore.RED}Errors ({len(result.errors)}):{Style.RESET_ALL}")
            for error in result.errors:
                lines.append(self._format_error(error))
            lines.append("")

        # Warnings
        if self.config.show_warnings and result.warnings:
            lines.append(f"  {Fore.YELLOW}Warnings ({len(result.warnings)}):{Style.RESET_ALL}")
            for warning in result.warnings:
                lines.append(self._format_warning(warning))
            lines.append("")

        # Statistics
        if self.config.show_statistics and result.statistics:
            lines.append("  Statistics:")
            for stat_key, stat_value in result.statistics.items():
                lines.append(f"    - {stat_key}: {stat_value}")
            lines.append("")

        # Footer
        lines.append(f"{Fore.CYAN}=== END ==={Style.RESET_ALL}")

        return "\n".join(lines)


class JSONFormatter:
    """JSON format formatter for verification results."""

    def format_result(self, result: Result) -> str:
        """Format verification result as JSON.

        Args:
            result: Result to format.

        Returns:
            JSON string.
        """
        return json.dumps({
            "timestamp": datetime.now().isoformat(),
            "status": result.status,
            "message": result.message,
            "details": result.details,
            "errors": result.errors,
            "warnings": result.warnings,
            "statistics": result.statistics,
        }, indent=2)


class XMLFormatter:
    """XML format formatter for verification results."""

    def format_result(self, result: Result) -> str:
        """Format verification result as XML.

        Args:
            result: Result to format.

        Returns:
            XML string.
        """
        from xml.etree.ElementTree import Element, SubElement, tostring

        root = Element("Result")
        ET = ElementTree
        ET.SubElement(root, "Timestamp").text = datetime.now().isoformat()
        ET.SubElement(root, "Status").text = result.status
        ET.SubElement(root, "Message").text = result.message

        if result.details:
            for key, value in result.details.items():
                ET.SubElement(root, f"Detail_{key}").text = str(value)

        if result.errors:
            for error in result.errors:
                error_elem = ET.SubElement(root, "Error")
                if "line" in error:
                    ET.SubElement(error_elem, "Line").text = str(error["line"])
                if "file" in error:
                    ET.SubElement(error_elem, "File").text = error["file"]
                if "message" in error:
                    ET.SubElement(error_elem, "Message").text = error["message"]

        if result.warnings:
            for warning in result.warnings:
                warning_elem = ET.SubElement(root, "Warning")
                if "line" in warning:
                    ET.SubElement(warning_elem, "Line").text = str(warning["line"])
                if "file" in warning:
                    ET.SubElement(warning_elem, "File").text = warning["file"]
                if "message" in warning:
                    ET.SubElement(warning_elem, "Message").text = warning["message"]

        if result.statistics:
            for stat_key, stat_value in result.statistics.items():
                ET.SubElement(root, f"Statistic_{stat_key}").text = str(stat_value)

        return ET.tostring(root, encoding="unicode")


class HTMLFormatter:
    """HTML format formatter for verification results."""

    def format_result(self, result: Result) -> str:
        """Format verification result as HTML.

        Args:
            result: Result to format.

        Returns:
            HTML string.
        """
        colors = {
            "PASS": "green",
            "FAIL": "red",
            "SKIP": "yellow",
            "ERROR": "purple",
        }

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Verification Result</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .result {{ border: 1px solid #ccc; padding: 15px; margin: 10px 0; }}
                .status {{ font-weight: bold; }}
                .pass {{ color: green; }}
                .fail {{ color: red; }}
                .skip {{ color: yellow; }}
                .error {{ color: purple; }}
                .warning {{ color: orange; }}
                .stat {{ background: #f5f5f5; padding: 5px; margin: 5px 0; }}
            </style>
        </head>
        <body>
            <h1>Verification Result</h1>
            <div class="result">
                <p><span class="status {colors.get(result.status, '')}">{result.status}</span>
                <span class="message">{result.message}</span></p>
            </div>
        </body>
        </html>
        """
        return html


class MarkdownFormatter:
    """Markdown format formatter for verification results."""

    def format_result(self, result: Result) -> str:
        """Format verification result as Markdown.

        Args:
            result: Result to format.

        Returns:
            Markdown string.
        """
        lines = []

        # Header
        lines.append(f"## {result.status} - {result.message}")

        # Details
        if result.details:
            lines.append("### Details")
            for key, value in result.details.items():
                lines.append(f"- **{key}**: {value}")
            lines.append("")

        # Errors
        if result.errors:
            lines.append(f"### Errors ({len(result.errors)})")
            for error in result.errors:
                lines.append(f"- **{error.get('message', '')}**")
                if "line" in error and error["line"] is not None:
                    lines.append(f"  - Line: {error['line']}")
                if "file" in error:
                    lines.append(f"  - File: {error['file']}")
            lines.append("")

        # Warnings
        if result.warnings:
            lines.append(f"### Warnings ({len(result.warnings)})")
            for warning in result.warnings:
                lines.append(f"- **{warning.get('message', '')}**")
            lines.append("")

        # Statistics
        if result.statistics:
            lines.append("### Statistics")
            for stat_key, stat_value in result.statistics.items():
                lines.append(f"- {stat_key}: {stat_value}")
            lines.append("")

        return "\n".join(lines)


class ResultFormatter:
    """Verification result formatter with multiple output options."""

    def __init__(
        self,
        config: Optional[ResultConfig] = None,
    ) -> None:
        """Initialize result formatter.

        Args:
            config: Optional result configuration.
        """
        self.config = config or ResultConfig()
        self.text_formatter = TextFormatter(self.config)
        self.json_formatter = JSONFormatter()
        self.xml_formatter = XMLFormatter()
        self.html_formatter = HTMLFormatter()
        self.markdown_formatter = MarkdownFormatter()

    def format_result(self, result: Result, output_format: Optional[str] = None) -> str:
        """Format verification result.

        Args:
            result: Result to format.
            output_format: Output format (overrides config if provided).

        Returns:
            Formatted result string.
        """
        if output_format:
            if output_format == "json":
                return self.json_formatter.format_result(result)
            elif output_format == "xml":
                return self.xml_formatter.format_result(result)
            elif output_format == "html":
                return self.html_formatter.format_result(result)
            elif output_format == "markdown":
                return self.markdown_formatter.format_result(result)
            else:
                return self.text_formatter.format_result(result)
        else:
            return self.text_formatter.format_result(result)

    def format_results(
        self,
        results: List[Result],
        output_format: Optional[str] = None,
    ) -> str:
        """Format multiple verification results.

        Args:
            results: List of results to format.
            output_format: Output format.

        Returns:
            Formatted results string.
        """
        formatted = []
        for result in results:
            formatted.append(self.format_result(result, output_format))

        return "\n\n".join(formatted)

    def write_to_file(
        self,
        results: List[Result],
        output_path: str,
        output_format: Optional[str] = None,
    ) -> None:
        """Write formatted results to file.

        Args:
            results: Results to write.
            output_path: Output file path.
            output_format: Output format.
        """
        formatted = self.format_results(results, output_format)
        Path(output_path).write_text(formatted, encoding="utf-8")

    def write_to_console(
        self,
        results: List[Result],
        output_format: Optional[str] = None,
    ) -> None:
        """Write formatted results to console.

        Args:
            results: Results to write.
            output_format: Output format.
        """
        formatted = self.format_results(results, output_format)
        print(formatted)


class ReportGenerator:
    """Verification report generator with multiple formats."""

    def __init__(
        self,
        title: str = "Verification Report",
        config: Optional[ResultConfig] = None,
    ) -> None:
        """Initialize report generator.

        Args:
            title: Report title.
            config: Optional result configuration.
        """
        self.title = title
        self.config = config or ResultConfig()
        self.formatter = ResultFormatter(self.config)

    def generate_report(
        self,
        results: List[Result],
        output_format: Optional[str] = None,
    ) -> str:
        """Generate verification report.

        Args:
            results: Results to include.
            output_format: Output format.

        Returns:
            Report string.
        """
        formatted = self.formatter.format_results(results, output_format)

        # Add report header and footer
        header = f"""
---
# {self.title}
Generated: {datetime.now().strftime(self.config.timestamp_format)}

---
"""
        footer = f"""
---
*This report was automatically generated by the verification engine.*
---
"""

        return header + formatted + footer

    def generate_summary(
        self,
        results: List[Result],
    ) -> Dict[str, int]:
        """Generate summary statistics.

        Args:
            results: Results to summarize.

        Returns:
            Summary dictionary with counts.
        """
        summary = {
            "total": len(results),
            "pass": 0,
            "fail": 0,
            "skip": 0,
            "error": 0,
            "warnings": 0,
        }

        for result in results:
            if result.status == "PASS":
                summary["pass"] += 1
            elif result.status == "FAIL":
                summary["fail"] += 1
            elif result.status == "SKIP":
                summary["skip"] += 1
            elif result.status == "ERROR":
                summary["error"] += 1
            summary["warnings"] += len(result.warnings)

        return summary
