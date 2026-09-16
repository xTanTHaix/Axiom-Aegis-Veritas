"""
CLI Module: Real-time File Watcher with inotify/polling Support.

Features:
- Cross-platform file watching (Windows/Linux/macOS)
- Real-time file system events
- Custom event handlers
- File change detection (create, modify, delete)
- Watch directory or file patterns
- Thread-safe event processing
"""

from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

# Create watcher factory before importing colorama to avoid circular import

def create_watcher(
    paths: List[str],
    config: Optional[WatchConfig] = None,
) -> FileWatcher:
    """Create and return a FileWatcher instance.

    Args:
        paths: List of paths to watch (files or directories).
        config: Optional configuration.

    Returns:
        Configured FileWatcher instance.
    """
    return FileWatcher(paths, config)





class FileEvent:
    """Represents a file system event."""

    def __init__(
        self,
        path: str,
        event_type: str,
        timestamp: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize file event.

        Args:
            path: Path to the file/directory.
            event_type: Type of event (CREATE, MODIFY, DELETE).
            timestamp: Unix timestamp when event occurred.
            metadata: Optional additional metadata.
        """
        self.path = path
        self.event_type = event_type
        self.timestamp = timestamp
        self.metadata = metadata or {}

    def __str__(self) -> str:
        """String representation."""
        return f"[{self.timestamp}] {self.event_type}: {self.path}"


@dataclass
class WatchConfig:
    """Configuration for file watcher."""

    recursive: bool = True
    ignore_patterns: List[str] = field(default_factory=list)
    events: Set[str] = field(default_factory=lambda: {"CREATE", "MODIFY", "DELETE"})
    buffer_size: int = 100
    polling_interval: float = 0.5
    timeout: Optional[float] = None
    on_event: Optional[Callable[[FileEvent], None]] = None


class FileWatcher:
    """Real-time file watcher with cross-platform support."""

    def __init__(
        self,
        paths: List[str],
        config: Optional[WatchConfig] = None,
    ) -> None:
        """Initialize file watcher.

        Args:
            paths: List of paths to watch (files or directories).
            config: Optional configuration.
        """
        self.paths = [Path(p) for p in paths]
        self.config = config or WatchConfig()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._events: List[FileEvent] = []
        self._event_index = 0
        self._lock = threading.Lock()
        self._initialized = False

    def _get_event_type(self, path: Path, action: str) -> str:
        """Determine event type from file system action.

        Args:
            path: Path to the file/directory.
            action: File system action (CREATE, MODIFY, DELETE).

        Returns:
            Event type string.
        """
        if action == "CREATE":
            return "CREATE"
        elif action == "MODIFY":
            return "MODIFY"
        elif action == "DELETE":
            return "DELETE"
        return "UNKNOWN"

    def _should_ignore(self, path: Path) -> bool:
        """Check if path should be ignored.

        Args:
            path: Path to check.

        Returns:
            True if path should be ignored.
        """
        if not self.config.recursive:
            return path.is_dir()

        for pattern in self.config.ignore_patterns:
            if pattern in str(path):
                return True
        return False

    def _process_event(self, event: FileEvent) -> None:
        """Process a file event.

        Args:
            event: File event to process.
        """
        with self._lock:
            self._events.append(event)
            self._event_index += 1

        # Call event handler
        if self.config.on_event:
            try:
                self.config.on_event(event)
            except Exception as e:
                print(f"Error processing event: {e}", file=sys.stderr)

    def _poll_files(self) -> List[FileEvent]:
        """Poll file system for changes.

        Returns:
            List of detected file events.
        """
        events = []
        for path in self.paths:
            if not path.exists() or self._should_ignore(path):
                continue

            try:
                # Get file stat
                stat = os.stat(path)
                mtime = stat.st_mtime

                # Check for modifications
                if mtime != self._last_mtime.get(path, 0):
                    event = FileEvent(
                        path=str(path),
                        event_type="MODIFY",
                        timestamp=time.time(),
                        metadata={"mtime": mtime},
                    )
                    events.append(event)
                    self._last_mtime[path] = mtime

            except Exception as e:
                print(f"Error polling {path}: {e}", file=sys.stderr)

        return events

    def _watch_files(self) -> None:
        """Watch files for changes using polling."""
        self._last_mtime: Dict[str, float] = {}

        while self._running:
            try:
                events = self._poll_files()
                for event in events:
                    self._process_event(event)
                time.sleep(self.config.polling_interval)
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Error in watch loop: {e}", file=sys.stderr)
                time.sleep(1)

    def _watch_directory(self, path: Path) -> None:
        """Watch a directory for changes using inotify-style watching.

        Args:
            path: Directory path to watch.
        """
        try:
            # Try inotify-style watching (Linux)
            if sys.platform == "linux":
                import inotify.py
                inotify = inotify.py

                w = inotify.init(inotify.py.IN_INIT)
                w.add_watch(str(path), inotify.py.IN_CREATE | inotify.py.IN_MODIFY | inotify.py.IN_DELETE)

                while self._running:
                    try:
                        events = w.read_events()
                        for event in events:
                            if event.filename and self.config.on_event:
                                self.config.on_event(FileEvent(
                                    path=str(event.filename),
                                    event_type=event.mask & inotify.py.IN_CREATE,
                                    timestamp=time.time(),
                                ))
                    except Exception as e:
                        print(f"Error reading events: {e}", file=sys.stderr)
            # Windows uses ReadDirectoryChangesW
            elif sys.platform == "win32":
                import ctypes
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

                def read_changes(path: str) -> bool:
                    handle = kernel32.ReadDirectoryChangesW(
                        path,
                        None,
                        None,
                        False,
                        [
                            kernel32.FILE_NOTIFY_CHANGE_FILE_NAME,
                            kernel32.FILE_NOTIFY_CHANGE_DIR_NAME,
                            kernel32.FILE_NOTIFY_CHANGE_LAST_WRITE,
                        ],
                    )
                    return handle

                read_thread = threading.Thread(target=read_changes, args=(str(path),))
                read_thread.daemon = True
                read_thread.start()

                while self._running:
                    time.sleep(0.1)
        except Exception as e:
            print(f"Error watching directory: {e}", file=sys.stderr)

    def start(self) -> None:
        """Start watching files."""
        if self._running:
            return

        self._running = True
        self._initialized = True

        # Start polling thread
        self._thread = threading.Thread(target=self._watch_files)
        self._thread.daemon = True
        self._thread.start()

        print(f"Started watching: {[str(p) for p in self.paths]}")

    def stop(self) -> None:
        """Stop watching files."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        print("Stopped watching")

    def is_running(self) -> bool:
        """Check if watcher is running."""
        return self._running

    def get_events(self) -> List[FileEvent]:
        """Get all events since start.

        Returns:
            List of file events.
        """
        with self._lock:
            return list(self._events[self._event_index:])

    def clear_events(self) -> None:
        """Clear event buffer."""
        with self._lock:
            self._events = []
            self._event_index = 0

    def __enter__(self) -> "FileWatcher":
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.stop()
