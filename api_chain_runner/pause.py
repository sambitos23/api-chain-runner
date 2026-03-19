"""PauseController — background keyboard listener for pause/resume during chain execution."""

from __future__ import annotations

import sys
import threading
import time


class PauseController:
    """Listens for 'p' (pause) and 'r' (resume) keypresses in a background
    thread. Other code calls :meth:`wait_if_paused` to block while paused.

    The controller also tracks how long execution has been paused so that
    callers (e.g. polling timeouts) can subtract paused time.
    """

    def __init__(self) -> None:
        self._paused = threading.Event()  # set = paused
        self._stop = threading.Event()
        self._total_paused: float = 0.0
        self._pause_start: float | None = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def total_paused(self) -> float:
        """Total seconds spent in paused state (including current pause)."""
        with self._lock:
            extra = 0.0
            if self._pause_start is not None:
                extra = time.monotonic() - self._pause_start
            return self._total_paused + extra

    def start(self) -> None:
        """Start the background keyboard listener thread."""
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the background listener."""
        self._stop.set()
        if self._paused.is_set():
            self._paused.clear()

    def wait_if_paused(self) -> None:
        """Block the calling thread while paused. Returns immediately if not paused."""
        if self._paused.is_set():
            print("         ⏸️  Paused — press 'r' or Enter to resume...")
            while self._paused.is_set():
                time.sleep(0.1)
            print("         ▶️  Resumed")

    def _listen(self) -> None:
        """Background thread: read single characters from stdin."""
        try:
            import tty
            import termios

            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            try:
                tty.setcbreak(fd)
                while not self._stop.is_set():
                    if _char_available(fd):
                        ch = sys.stdin.read(1)
                        self._handle_key(ch)
                    else:
                        time.sleep(0.05)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        except (ImportError, OSError):
            # Fallback for non-Unix or piped stdin — use line-based input
            self._listen_fallback()

    def _listen_fallback(self) -> None:
        """Fallback listener using readline (works on Windows / piped stdin)."""
        while not self._stop.is_set():
            try:
                line = sys.stdin.readline().strip().lower()
                if line:
                    self._handle_key(line[0])
            except (EOFError, OSError):
                break

    def _handle_key(self, ch: str) -> None:
        ch = ch.lower()
        if ch == "p" and not self._paused.is_set():
            with self._lock:
                self._pause_start = time.monotonic()
            self._paused.set()
            print("\n         ⏸️  Pause requested — will pause at next safe point...")
        elif ch in ("r", "\n", "\r") and self._paused.is_set():
            with self._lock:
                if self._pause_start is not None:
                    self._total_paused += time.monotonic() - self._pause_start
                    self._pause_start = None
            self._paused.clear()


def _char_available(fd: int) -> bool:
    """Check if a character is available on the given file descriptor."""
    import select
    return bool(select.select([fd], [], [], 0.05)[0])
