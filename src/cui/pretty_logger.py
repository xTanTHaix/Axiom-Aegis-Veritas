"""
CLI Module: Structured Telemetry Logger with Multiple Output Formats.

Features:
- Text, JSON, XML, HTML, Markdown output formats
- Color-coded log levels
- Timestamp formatting
- Log rotation
- Support for multiple output destinations
- Thread-safe logging
"""

from __future__ import annotations

import json
import os
import sys
import time
import threading
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional, TextIO, Union

import sys
from colorama import Fore, Style, init

init(autoreset=True)


class LogFormatter:
    """Base class for log formatters."""

    def __init__(self, config: Optional[LogConfig] = None) -> None:
        self.config = config or LogConfig()

    def format(self, record: Any) -> str:
        """Format log record.

        Args:
            record: Log record to format.

        Returns:
            Formatted string.
        """
        raise NotImplementedError


@dataclass
class LogConfig:
    """Configuration for PrettyLogger."""

    level: str = "INFO"
    format_str: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    use_colors: bool = True
    timestamp_format: str = "%Y-%m-%d %H:%M:%S"
    output_file: Optional[str] = None
    output_format: str = "text"
    max_size_mb: int = 10
    backup_count: int = 5
    console_output: bool = True
    file_output: bool = True


class TextFormatter(LogFormatter):
    """Text format formatter with optional colors."""

    def __init__(self, config: Optional[LogConfig] = None) -> None:
        """Initialize text formatter.

        Args:
            config: Optional log configuration.
        """
        self.config = config or LogConfig()
        self.use_colors = self.config.use_colors

    def format(self, record: Any) -> str:
        """Format log record.

        Args:
            record: Log record to format.

        Returns:
            Formatted string.
        """
        timestamp = datetime.now().strftime(self.config.timestamp_format)
        level = record.levelname
        name = record.name
        message = record.getMessage()

        if self.use_colors:
            level_colors = {
                "DEBUG": Fore.CYAN,
                "INFO": Fore.GREEN,
                "WARNING": Fore.YELLOW,
                "ERROR": Fore.RED,
                "CRITICAL": Fore.MAGENTA,
            }
            level_str = f"{level_colors.get(level, Fore.WHITE)}{level}{Style.RESET_ALL}"
        else:
            level_str = level

        formatted = f"{timestamp} - {name} - {level_str} - {message}"
        return formatted


class JSONFormatter(LogFormatter):
    """JSON format formatter."""

    def format(self, record: Any) -> str:
        """Format log record.

        Args:
            record: Log record to format.

        Returns:
            JSON string.
        """
        timestamp = datetime.now().strftime(self.config.timestamp_format)
        level = record.levelname
        name = record.name
        message = record.getMessage()

        log_entry = {
            "timestamp": timestamp,
            "level": level,
            "name": name,
            "message": message,
        }

        if record.exc_info:
            log_entry["exception"] = str(record.exc_info[1])

        return json.dumps(log_entry, indent=2)


class XMLFormatter(LogFormatter):
    """XML format formatter."""

    def format(self, record: Any) -> str:
        """Format log record.

        Args:
            record: Log record to format.

        Returns:
            XML string.
        """
        timestamp = datetime.now().strftime(self.config.timestamp_format)
        level = record.levelname
        name = record.name
        message = record.getMessage()

        root = ET.Element("Log")
        ET.SubElement(root, "Timestamp").text = timestamp
        ET.SubElement(root, "Level").text = level
        ET.SubElement(root, "Name").text = name
        ET.SubElement(root, "Message").text = message

        if record.exc_info:
            ET.SubElement(root, "Exception").text = str(record.exc_info[1])

        return ET.tostring(root, encoding="unicode")


class HTMLFormatter(LogFormatter):
    """HTML format formatter."""

    def format(self, record: Any) -> str:
        """Format log record.

        Args:
            record: Log record to format.

        Returns:
            HTML string.
        """
        timestamp = datetime.now().strftime(self.config.timestamp_format)
        level = record.levelname
        name = record.name
        message = record.getMessage()

        colors = {
            "DEBUG": "#888",
            "INFO": "#000",
            "WARNING": "#FF8800",
            "ERROR": "#FF0000",
            "CRITICAL": "#FF0000",
        }

        html = f"""
        <div class="log-entry">
            <span class="timestamp">{timestamp}</span>
            <span class="level {level.lower()}">{level}</span>
            <span class="name">{name}</span>
            <span class="message">{message}</span>
        </div>
        """
        return html


class MarkdownFormatter(LogFormatter):
    """Markdown format formatter."""

    def format(self, record: Any) -> str:
        """Format log record.

        Args:
            record: Log record to format.

        Returns:
            Markdown string.
        """
        timestamp = datetime.now().strftime(self.config.timestamp_format)
        level = record.levelname
        name = record.name
        message = record.getMessage()

        return f"- **{timestamp}** | {name} | {level} | {message}\n"


class PrettyLogger:
    """Structured telemetry logger with multiple output formats."""

    def __init__(
        self,
        name: str = "AXIOM",
        config: Optional[LogConfig] = None,
    ) -> None:
        """Initialize PrettyLogger.

        Args:
            name: Logger name.
            config: Optional log configuration.
        """
        self.name = name
        self.config = config or LogConfig()
        self._handlers: List[Any] = []
        self._lock = threading.Lock()
        self._initialized = False

        # Create formatters
        self._text_formatter = TextFormatter(self.config)
        self._json_formatter = JSONFormatter(self.config)
        self._xml_formatter = XMLFormatter(self.config)
        self._html_formatter = HTMLFormatter(self.config)
        self._markdown_formatter = MarkdownFormatter(self.config)

    def _get_formatter(self, output_format: str) -> LogFormatter:
        """Get formatter for specified output format.

        Args:
            output_format: Output format name.

        Returns:
            Appropriate formatter instance.
        """
        formatters = {
            "text": self._text_formatter,
            "json": self._json_formatter,
            "xml": self._xml_formatter,
            "html": self._html_formatter,
            "markdown": self._markdown_formatter,
        }
        return formatters.get(output_format, self._text_formatter)

    def _format_message(self, record: Any) -> str:
        """Format log record message.

        Args:
            record: Log record to format.

        Returns:
            Formatted message string.
        """
        formatter = self._get_formatter(self.config.output_format)
        return formatter.format(record)

    def _should_log(self, level: str) -> bool:
        """Check if log level should be processed.

        Args:
            level: Log level to check.

        Returns:
            True if should log.
        """
        levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
        return levels.get(self.config.level, 20) <= levels.get(level, 20)

    def _add_handler(self, handler: Any) -> None:
        """Add log handler.

        Args:
            handler: Handler to add.
        """
        self._handlers.append(handler)

    def _write_to_console(self, message: str) -> None:
        """Write message to console.

        Args:
            message: Message to write.
        """
        if not self.config.console_output:
            return

        print(message, file=sys.stdout, flush=True)

    def _write_to_file(self, message: str) -> None:
        """Write message to file.

        Args:
            message: Message to write.
        """
        if not self.config.file_output:
            return

        try:
            Path(self.config.output_file).write_text(message, encoding="utf-8")
        except Exception as e:
            print(f"Error writing to file: {e}", file=sys.stderr)

    def log(self, level: str, message: str, **kwargs: Any) -> None:
        """Log a message.

        Args:
            level: Log level.
            message: Message to log.
            **kwargs: Additional keyword arguments.
        """
        if not self._should_log(level):
            return

        if not self._initialized:
            self._initialized = True

        # Create log record
        record = LogRecord(
            name=self.name,
            level=level,
            message=message,
            **kwargs,
        )

        # Format message
        formatted = self._format_message(record)

        # Write to handlers
        with self._lock:
            for handler in self._handlers:
                if hasattr(handler, "handle"):
                    try:
                        handler.handle(record)
                    except Exception as e:
                        print(f"Error handling log: {e}", file=sys.stderr)

    def debug(self, message: str, **kwargs: Any) -> None:
        """Log debug message.

        Args:
            message: Message to log.
            **kwargs: Additional keyword arguments.
        """
        self.log("DEBUG", message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        """Log info message.

        Args:
            message: Message to log.
            **kwargs: Additional keyword arguments.
        """
        self.log("INFO", message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log warning message.

        Args:
            message: Message to log.
            **kwargs: Additional keyword arguments.
        """
        self.log("WARNING", message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        """Log error message.

        Args:
            message: Message to log.
            **kwargs: Additional keyword arguments.
        """
        self.log("ERROR", message, **kwargs)

    def critical(self, message: str, **kwargs: Any) -> None:
        """Log critical message.

        Args:
            message: Message to log.
            **kwargs: Additional keyword arguments.
        """
        self.log("CRITICAL", message, **kwargs)

    def set_level(self, level: str) -> None:
        """Set log level.

        Args:
            level: New log level.
        """
        self.config.level = level

    def set_output_format(self, format: str) -> None:
        """Set output format.

        Args:
            format: Output format name.
        """
        self.config.output_format = format

    def set_output_file(self, path: str) -> None:
        """Set output file path.

        Args:
            path: File path to write logs.
        """
        self.config.output_file = path

    def add_handler(self, handler: Any) -> None:
        """Add log handler.

        Args:
            handler: Handler to add.
        """
        self._add_handler(handler)

    def remove_handler(self, handler: Any) -> None:
        """Remove log handler.

        Args:
            handler: Handler to remove.
        """
        if handler in self._handlers:
            self._handlers.remove(handler)

    def get_log_file_path(self) -> Optional[str]:
        """Get log file path.

        Returns:
            Log file path or None.
        """
        return self.config.output_file


class LogRecord:
    """Represents a log record."""

    def __init__(
        self,
        name: str,
        level: str,
        message: str,
        exc_info: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize log record.

        Args:
            name: Logger name.
            level: Log level.
            message: Log message.
            exc_info: Exception info (optional).
            **kwargs: Additional attributes.
        """
        self.name = name
        self.level = level
        self.message = message
        self.exc_info = exc_info
        self.kwargs = kwargs

    def __str__(self) -> str:
        """String representation."""
        return self.message


class LogHandler:
    """Base class for log handlers."""

    def handle(self, record: Any) -> None:
        """Handle log record.

        Args:
            record: Log record to handle.
        """
        raise NotImplementedError


class ConsoleHandler(LogHandler):
    """Console output handler."""

    def __init__(self, formatter: LogFormatter) -> None:
        """Initialize console handler.

        Args:
            formatter: Formatter to use.
        """
        self.formatter = formatter

    def handle(self, record: Any) -> None:
        """Handle log record.

        Args:
            record: Log record to handle.
        """
        self.formatter.format(record)


class FileHandler(LogHandler):
    """File output handler."""

    def __init__(
        self,
        path: str,
        formatter: LogFormatter,
        max_size_mb: int = 10,
        backup_count: int = 5,
    ) -> None:
        """Initialize file handler.

        Args:
            path: File path to write logs.
            formatter: Formatter to use.
            max_size_mb: Maximum file size in MB.
            backup_count: Number of backup files to keep.
        """
        self.path = path
        self.formatter = formatter
        self.max_size_mb = max_size_mb
        self.backup_count = backup_count
        self._file_size = 0
        self._file_path = Path(path)

    def handle(self, record: Any) -> None:
        """Handle log record.

        Args:
            record: Log record to handle.
        """
        message = self.formatter.format(record)
        self._file_size += len(message) + 1

        # Rotate file if needed
        if self._file_size > self.max_size_mb * 1024 * 1024:
            self._rotate_file()

        try:
            self._file_path.write_text(message, encoding="utf-8")
        except Exception as e:
            print(f"Error writing to file: {e}", file=sys.stderr)

    def _rotate_file(self) -> None:
        """Rotate log file."""
        if not self._file_path.exists():
            return

        # Remove oldest backup
        oldest_backup = self._file_path.with_suffix(f".{self.backup_count}.log")
        if oldest_backup.exists():
            oldest_backup.unlink()

        # Shift existing backups
        for i in range(self.backup_count, 1, -1):
            backup = self._file_path.with_suffix(f".{i}.log")
            if backup.exists():
                backup.rename(self._file_path.with_suffix(f".{i - 1}.log"))

        # Move current file to backup
        self._file_path.rename(self._file_path.with_suffix(f".1.log"))


class TextHandler(LogHandler):
    """Text output handler."""

    def __init__(self, formatter: LogFormatter) -> None:
        """Initialize text handler.

        Args:
            formatter: Formatter to use.
        """
        self.formatter = formatter

    def handle(self, record: Any) -> None:
        """Handle log record.

        Args:
            record: Log record to handle.
        """
        self.formatter.format(record)


class StructuredTelemetryLogger:
    """Structured telemetry logger with formatted CLI banner methods."""

    def __init__(self, verbose: bool = False, name: str = "AXIOM") -> None:
        self.verbose = verbose
        self.name = name
        self.logger = PrettyLogger(name=name)

    def log_header(self, text: str) -> None:
        """Print prominent section header."""
        border = "═" * 70
        print(f"\n{Fore.CYAN}{Style.BRIGHT}{border}")
        print(f"  ⚡ {text}")
        print(f"{border}{Style.RESET_ALL}\n")

    def log_subheader(self, text: str) -> None:
        """Print subheader line."""
        print(f"{Fore.MAGENTA}  ▶ {text}{Style.RESET_ALL}")

    def log_info(self, text: str) -> None:
        """Print info line."""
        print(f"{Fore.GREEN}  ℹ [INFO] {text}{Style.RESET_ALL}")

    def log_warning(self, text: str) -> None:
        """Print warning line."""
        print(f"{Fore.YELLOW}  ▲ [WARN] {text}{Style.RESET_ALL}")

    def log_error(self, text: str) -> None:
        """Print error line."""
        print(f"{Fore.RED}  ✖ [ERROR] {text}{Style.RESET_ALL}")

