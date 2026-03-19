"""Tests for api_chain_runner.pause.PauseController."""

import threading
import time

from api_chain_runner.pause import PauseController


class TestPauseControllerState:
    """Test basic pause/resume state management."""

    def test_not_paused_by_default(self):
        pc = PauseController()
        assert not pc._paused.is_set()

    def test_total_paused_starts_at_zero(self):
        pc = PauseController()
        assert pc.total_paused == 0.0

    def test_wait_if_paused_returns_immediately_when_not_paused(self):
        pc = PauseController()
        start = time.monotonic()
        pc.wait_if_paused()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1

    def test_pause_and_resume_via_handle_key(self):
        pc = PauseController()
        pc._handle_key("p")
        assert pc._paused.is_set()
        pc._handle_key("r")
        assert not pc._paused.is_set()

    def test_resume_with_enter_key(self):
        pc = PauseController()
        pc._handle_key("p")
        assert pc._paused.is_set()
        pc._handle_key("\n")
        assert not pc._paused.is_set()

    def test_double_pause_ignored(self):
        pc = PauseController()
        pc._handle_key("p")
        pc._handle_key("p")  # should not error
        assert pc._paused.is_set()

    def test_resume_when_not_paused_ignored(self):
        pc = PauseController()
        pc._handle_key("r")  # should not error
        assert not pc._paused.is_set()


class TestPauseControllerTiming:
    """Test that paused time is tracked correctly."""

    def test_total_paused_tracks_pause_duration(self):
        pc = PauseController()
        pc._handle_key("p")
        time.sleep(0.2)
        pc._handle_key("r")
        assert pc.total_paused >= 0.15

    def test_total_paused_accumulates_across_multiple_pauses(self):
        pc = PauseController()
        pc._handle_key("p")
        time.sleep(0.1)
        pc._handle_key("r")
        first = pc.total_paused

        pc._handle_key("p")
        time.sleep(0.1)
        pc._handle_key("r")
        assert pc.total_paused >= first + 0.05

    def test_wait_if_paused_blocks_until_resumed(self):
        pc = PauseController()
        pc._handle_key("p")

        # Resume from another thread after a short delay
        def resume_later():
            time.sleep(0.2)
            pc._handle_key("r")

        t = threading.Thread(target=resume_later)
        t.start()

        start = time.monotonic()
        pc.wait_if_paused()
        elapsed = time.monotonic() - start
        t.join()

        assert elapsed >= 0.15


class TestPauseControllerStop:
    """Test stop behavior."""

    def test_stop_clears_pause(self):
        pc = PauseController()
        pc._handle_key("p")
        assert pc._paused.is_set()
        pc.stop()
        assert not pc._paused.is_set()
