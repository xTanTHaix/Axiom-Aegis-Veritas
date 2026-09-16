"""
CLI Module: ANSI Progress Bar with Spinner, Ticks, and ETA Calculation.

Features:
- Real-time progress bar with spinner animation
- Tick-based progress display
- Automatic ETA calculation
- Support for percentage, completed, total, and duration display
- Configurable bar width and speed
- Multiple styles: default, simple, and detailed
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import Optional

import sys
from colorama import Fore, Style, init

init(autoreset=True)


@dataclass
class ProgressConfig:
    """Configuration for progress bar."""

    width: int = 40
    speed: float = 0.1
    show_eta: bool = True
    show_percentage: bool = True
    show_completed: bool = True
    show_total: bool = True
    show_duration: bool = True
    style: str = "default"
    bar_char: str = "="
    fill_char: str = "#"
    empty_char: str = " "


class ProgressBar:
    """ANSI progress bar with spinner and ETA calculation."""

    def __init__(
        self,
        total: int = 0,
        config: Optional[ProgressConfig] = None,
    ) -> None:
        """Initialize progress bar.

        Args:
            total: Total number of iterations. Optional (default: 0).
            config: Optional configuration. Uses defaults if not provided.
        """
        self.total = total
        self.current = 0
        self.config = config or ProgressConfig()
        self.start_time: Optional[float] = None
        self._running = True
        self._spinner_frame: int = 0
        self._spinner_frames = ["-", "\\", "|", "/"]
        self._last_update_time: float = 0
        self._current_layer: Optional[str] = None
        self._current_task: Optional[str] = None

    @property
    def current_layer(self) -> Optional[str]:
        """Current layer name."""
        return self._current_layer

    @property
    def current_task(self) -> Optional[str]:
        """Current task name."""
        return self._current_task

    def start(self, layer: str = "", task: str = "") -> None:
        """Start a new layer/task on the progress bar.

        Args:
            layer: Name of the layer (e.g., "Layer 1").
            task: Name of the task within the layer.

        Raises:
            ValueError: If both layer and task are empty.
        """
        if not layer and not task:
            self._current_layer = None
            self._current_task = None
            return
        if not layer:
            raise ValueError("layer must be provided when task is provided")
        self._current_layer = layer
        self._current_task = task

    def complete(self) -> None:
        """Mark the current layer/task as completed."""
        self._current_layer = None
        self._current_task = None

    def reset(self) -> None:
        """Reset progress bar to initial state, clearing layer/task info."""
        self.current = 0
        self.start_time = None
        self._last_update_time = time.time()
        self._current_layer = None
        self._current_task = None

    def finish(self) -> None:
        """Mark progress bar as completed."""
        self.current = self.total
        self._running = False

    def is_finished(self) -> bool:
        """Check if progress bar is finished."""
        return self._running and self.current >= self.total

    def progress(self) -> str:
        """Get current progress bar string."""
        return self._update_bar()

    def __iter__(self) -> "ProgressBar":
        """Enable iteration for progress bar."""
        return self

    def __next__(self) -> None:
        """Increment and update progress bar."""
        if self._running:
            self.update()
        else:
            raise StopIteration
        return self.progress()

    def __call__(self) -> str:
        """Call as function to get progress string."""
        return self.progress()

    def __repr__(self) -> str:
        """Return a string representation of the progress bar."""
        layer = self._current_layer or ""
        task = self._current_task or ""
        return f"ProgressBar(layer={layer!r}, task={task!r}, current={self.current}, total={self.total})"

    def _update_bar(self) -> str:
        """Update and return ANSI progress bar string."""
        if self._running:
            elapsed = time.time() - self.start_time if self.start_time else 0
            pct = (self.current / self.total * 100) if self.total > 0 else 0
            filled = int(self.config.width * pct / 100)
            bar = self.config.fill_char * filled + self.config.empty_char * (self.config.width - filled)
            spinner = self._spinner_frames[self._spinner_frame % len(self._spinner_frames)]
            if self.config.show_percentage:
                eta = ""
                if self.total > 0 and self.start_time:
                    rate = self.current / elapsed if elapsed > 0 else 0
                    remaining = (self.total - self.current) / rate if rate > 0 else 0
                    eta = f" | ETA: {remaining:.0f}s"
                return (
                    f"{self._current_layer or ''}: {spinner} [{bar}] {pct:.0f}% "
                    f"({self.current}/{self.total}){eta}"
                )
            return f"{self._current_layer or ''}: {spinner} [{bar}] {pct:.0f}% ({self.current}/{self.total})"
        return f"ProgressBar finished: {self.current}/{self.total}"


# Backwards compatibility alias for AXIOM CLI entrypoints
AxiomProgressBar = ProgressBar