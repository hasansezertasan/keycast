"""Tests for the Keycast application lifecycle."""

from collections.abc import Iterator
from unittest.mock import Mock, call, patch

import pytest

import keycast.application as application_module
from keycast.application import Keycast


@pytest.fixture
def keycast() -> Iterator[Keycast]:
    """Build a Keycast with every collaborator mocked out.

    Patches settings/logging/window/listeners so no real config file, tkinter
    window or input hook is created.

    Yields:
        A Keycast instance whose components are mocks.
    """
    with (
        patch("keycast.application.Settings") as settings_cls,
        patch("keycast.application.setup_logging"),
        patch("keycast.application.DisplayWindow") as window_cls,
        patch("keycast.application.MouseListener") as mouse_cls,
        patch("keycast.application.KeyListener") as key_cls,
        # Neutralize the update check (no config read, no GitHub-bound thread);
        # the wiring is asserted explicitly in TestUpdateCheck.
        patch("keycast.application.notify_pending_update"),
    ):
        settings = Mock()
        settings.show_startup_status = False
        settings_cls.create_settings_file.return_value = settings
        window_cls.return_value = Mock()
        mouse_cls.return_value = Mock()
        key_cls.return_value = Mock()
        yield Keycast()


class TestStop:
    """Keycast.stop teardown behavior."""

    def test_stop_stops_all_components(self, keycast: Keycast) -> None:
        keycast.stop()

        keycast.mouse_listener.stop.assert_called_once()
        keycast.key_listener.stop.assert_called_once()
        keycast.display_window.stop.assert_called_once()

    def test_stop_is_idempotent(self, keycast: Keycast) -> None:
        """A second stop() is a no-op (guards double shutdown from signal+finally)."""
        keycast.stop()
        keycast.stop()

        keycast.mouse_listener.stop.assert_called_once()
        keycast.key_listener.stop.assert_called_once()
        keycast.display_window.stop.assert_called_once()

    def test_stop_is_best_effort(self, keycast: Keycast) -> None:
        """A failure stopping one component does not skip the others."""
        keycast.mouse_listener.stop.side_effect = RuntimeError("boom")

        keycast.stop()  # must not raise

        keycast.key_listener.stop.assert_called_once()
        keycast.display_window.stop.assert_called_once()


class TestInit:
    """Keycast.__init__ side effects."""

    def test_logs_version_and_platform_on_startup(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The first line after logging is configured stamps version + platform.

        This identifies the build and OS in a user-submitted ``main.log``;
        ``sys.platform`` is logged because it is the value ``settings.py`` keys
        off for cross-platform key-label normalization.
        """
        with (
            patch("keycast.application.Settings") as settings_cls,
            patch("keycast.application.setup_logging"),
            patch("keycast.application.DisplayWindow"),
            patch("keycast.application.MouseListener"),
            patch("keycast.application.KeyListener"),
            patch("keycast.application.__version__", "9.9.9"),
            patch("keycast.application.sys.platform", "testos"),
            caplog.at_level("INFO", logger="keycast.application"),
        ):
            settings_cls.create_settings_file.return_value = Mock()
            Keycast()

        assert "keycast_starting version=9.9.9 platform=testos" in caplog.text

    def test_logging_is_configured_from_effective_logging(self) -> None:
        """__init__ must route logging through Settings.effective_logging().

        This is the only place the PR's ``debug`` switch takes effect: a
        regression that passed ``settings.logging`` straight to setup_logging
        would silently stop debug mode from forcing DEBUG, yet leave the rest of
        the suite green. Pin that setup_logging receives effective_logging()'s
        return, not the raw logging settings.
        """
        with (
            patch("keycast.application.Settings") as settings_cls,
            patch("keycast.application.setup_logging") as setup_logging,
            patch("keycast.application.DisplayWindow"),
            patch("keycast.application.MouseListener"),
            patch("keycast.application.KeyListener"),
        ):
            settings = Mock()
            settings_cls.create_settings_file.return_value = settings
            Keycast()

        settings.effective_logging.assert_called_once_with()
        setup_logging.assert_called_once_with(settings.effective_logging.return_value)


class TestStart:
    """Keycast.start ordering and the auto_start / start_minimized wiring."""

    def test_display_starts_after_listeners(self, keycast: Keycast) -> None:
        """The display window starts last to avoid race conditions."""
        keycast.settings.auto_start = True
        keycast.settings.start_minimized = False
        manager = Mock()
        manager.attach_mock(keycast.mouse_listener.start, "mouse")
        manager.attach_mock(keycast.key_listener.start, "key")
        manager.attach_mock(keycast.display_window.start, "display")

        keycast.start()

        assert manager.mock_calls == [
            call.mouse(),
            call.key(),
            call.display(start_minimized=False),
        ]

    def test_autostart_disabled_skips_listeners_but_starts_overlay(
        self, keycast: Keycast
    ) -> None:
        """auto_start=False is a master switch: no listeners, overlay still runs."""
        keycast.settings.auto_start = False

        keycast.start()

        keycast.mouse_listener.start.assert_not_called()
        keycast.key_listener.start.assert_not_called()
        keycast.display_window.start.assert_called_once()

    def test_autostart_enabled_starts_both_listeners(self, keycast: Keycast) -> None:
        keycast.settings.auto_start = True

        keycast.start()

        keycast.mouse_listener.start.assert_called_once()
        keycast.key_listener.start.assert_called_once()

    def test_version_splash_shown_before_display_starts(self, keycast: Keycast) -> None:
        """A non-minimized start flashes the version through show_text, pre-loop."""
        keycast.settings.auto_start = True
        keycast.settings.start_minimized = False
        manager = Mock()
        manager.attach_mock(keycast.display_window.show_text, "show_text")
        manager.attach_mock(keycast.display_window.start, "start")

        with patch("keycast.application.__version__", "9.9.9"):
            keycast.start()

        # The splash is enqueued before the main loop starts, and carries the
        # running version verbatim.
        assert manager.mock_calls == [
            call.show_text("keycast 9.9.9"),
            call.start(start_minimized=False),
        ]

    def test_startup_status_shown_when_enabled(self, keycast: Keycast) -> None:
        keycast.settings.auto_start = True
        keycast.settings.start_minimized = False
        keycast.settings.show_startup_status = True
        keycast.mouse_listener.settings.enabled = True
        keycast.key_listener.settings.enabled = True
        manager = Mock()
        manager.attach_mock(keycast.display_window.show_text, "show_text")
        manager.attach_mock(keycast.display_window.start, "start")

        with patch("keycast.application.__version__", "9.9.9"):
            keycast.start()

        expected_status = Keycast._format_startup_status_line(
            {
                "keyboard": application_module._InputSourceStatus.ACTIVE,
                "mouse": application_module._InputSourceStatus.ACTIVE,
            }
        )
        assert manager.mock_calls == [
            call.show_text("keycast 9.9.9"),
            call.show_text(expected_status),
            call.start(start_minimized=False),
        ]

    def test_startup_status_logged_with_structured_fields(
        self, keycast: Keycast, caplog: pytest.LogCaptureFixture
    ) -> None:
        keycast.settings.auto_start = True
        keycast.settings.start_minimized = False
        keycast.mouse_listener.settings.enabled = True
        keycast.key_listener.settings.enabled = True

        with caplog.at_level("INFO", logger="keycast.application"):
            keycast.start()

        assert "startup_input_status" in caplog.text
        assert "keyboard=active" in caplog.text
        assert "mouse=active" in caplog.text
        assert "precheck=unknown" in caplog.text

    def test_windows_status_uses_listener_result_on_failure(
        self, keycast: Keycast
    ) -> None:
        keycast.settings.auto_start = True
        keycast.settings.start_minimized = False
        keycast.settings.show_startup_status = True
        keycast.mouse_listener.settings.enabled = True
        keycast.key_listener.settings.enabled = True
        keycast.key_listener.start.side_effect = RuntimeError("permission denied")

        with patch("keycast.application.platform.system", return_value="Windows"):
            keycast.start()

        expected_status = Keycast._format_startup_status_line(
            {
                "keyboard": application_module._InputSourceStatus.NO_ACCESS,
                "mouse": application_module._InputSourceStatus.ACTIVE,
            }
        )
        keycast.display_window.show_text.assert_any_call(expected_status)

    def test_macos_status_uses_precheck_denied_as_permission_needed(
        self, keycast: Keycast
    ) -> None:
        keycast.settings.auto_start = True
        keycast.settings.start_minimized = False
        keycast.settings.show_startup_status = True
        keycast.mouse_listener.settings.enabled = True
        keycast.key_listener.settings.enabled = True
        keycast.key_listener.start.side_effect = RuntimeError("permission denied")

        with (
            patch("keycast.application.platform.system", return_value="Darwin"),
            patch.object(Keycast, "_macos_permission_precheck", return_value=False),
        ):
            keycast.start()

        expected_status = Keycast._format_startup_status_line(
            {
                "keyboard": application_module._InputSourceStatus.NO_ACCESS,
                "mouse": application_module._InputSourceStatus.ACTIVE,
            }
        )
        keycast.display_window.show_text.assert_any_call(expected_status)

    def test_macos_status_falls_back_to_unknown_when_precheck_unavailable(
        self, keycast: Keycast
    ) -> None:
        keycast.settings.auto_start = True
        keycast.settings.start_minimized = False
        keycast.settings.show_startup_status = True
        keycast.mouse_listener.settings.enabled = True
        keycast.key_listener.settings.enabled = True
        keycast.key_listener.start.side_effect = RuntimeError("permission denied")

        with (
            patch("keycast.application.platform.system", return_value="Darwin"),
            patch.object(Keycast, "_macos_permission_precheck", return_value=None),
        ):
            keycast.start()

        expected_status = Keycast._format_startup_status_line(
            {
                "keyboard": application_module._InputSourceStatus.UNKNOWN,
                "mouse": application_module._InputSourceStatus.ACTIVE,
            }
        )
        keycast.display_window.show_text.assert_any_call(expected_status)

    def test_no_version_splash_on_minimized_start(self, keycast: Keycast) -> None:
        """A minimized start stays fully hidden: no splash to defeat the point."""
        keycast.settings.auto_start = True
        keycast.settings.start_minimized = True
        keycast.mouse_listener.settings.enabled = True
        keycast.key_listener.settings.enabled = True

        keycast.start()

        keycast.display_window.show_text.assert_not_called()

    def test_start_minimized_is_forwarded_to_display(self, keycast: Keycast) -> None:
        keycast.settings.auto_start = True
        keycast.settings.start_minimized = True
        # At least one source is live, so the minimized start is honored.
        keycast.mouse_listener.settings.enabled = True
        keycast.key_listener.settings.enabled = True

        keycast.start()

        keycast.display_window.start.assert_called_once_with(start_minimized=True)

    def test_start_minimized_kept_when_only_one_source_active(
        self, keycast: Keycast
    ) -> None:
        """One live listener is enough to re-show the overlay, so honor minimized."""
        keycast.settings.auto_start = True
        keycast.settings.start_minimized = True
        keycast.mouse_listener.settings.enabled = False  # mouse off
        keycast.key_listener.settings.enabled = True  # keyboard live

        keycast.start()

        keycast.display_window.start.assert_called_once_with(start_minimized=True)

    def test_start_minimized_ignored_when_all_listeners_disabled(
        self, keycast: Keycast, caplog: pytest.LogCaptureFixture
    ) -> None:
        """No live source ⇒ keep the overlay visible (a hidden one could never return)."""
        keycast.settings.auto_start = True
        keycast.settings.start_minimized = True
        keycast.mouse_listener.settings.enabled = False
        keycast.key_listener.settings.enabled = False

        with caplog.at_level("WARNING", logger="keycast.application"):
            keycast.start()

        keycast.display_window.start.assert_called_once_with(start_minimized=False)
        assert "start_minimized_ignored" in caplog.text
        assert "reason=no_active_input_source" in caplog.text

    def test_start_minimized_ignored_when_all_listeners_fail_to_start(
        self, keycast: Keycast, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Enabled listeners that fail (e.g. no permission) also leave none live."""
        keycast.settings.auto_start = True
        keycast.settings.start_minimized = True
        keycast.mouse_listener.settings.enabled = True
        keycast.key_listener.settings.enabled = True
        keycast.mouse_listener.start.side_effect = RuntimeError("permission denied")
        keycast.key_listener.start.side_effect = RuntimeError("permission denied")

        with caplog.at_level("WARNING", logger="keycast.application"):
            keycast.start()

        keycast.display_window.start.assert_called_once_with(start_minimized=False)
        assert "start_minimized_ignored" in caplog.text


class TestUpdateCheck:
    """The update-check call wired into Keycast.start (notifies via the overlay)."""

    def test_runs_on_normal_start(self, keycast: Keycast) -> None:
        """A non-minimized start passes the overlay sink and opt-out flag through."""
        keycast.settings.auto_start = True
        keycast.settings.start_minimized = False
        keycast.settings.check_for_updates = True

        with patch("keycast.application.__version__", "1.2.3"):
            keycast.start()

        application_module.notify_pending_update.assert_called_once_with(
            notify=keycast.display_window.show_text,
            current="1.2.3",
            enabled=True,
        )

    def test_skipped_on_minimized_start(self, keycast: Keycast) -> None:
        """A minimized start stays hidden, so no overlay update notice fires."""
        keycast.settings.auto_start = True
        keycast.settings.start_minimized = True
        keycast.mouse_listener.settings.enabled = True
        keycast.key_listener.settings.enabled = True

        keycast.start()

        application_module.notify_pending_update.assert_not_called()


class TestStartDegradesOnListenerFailure:
    """A listener failing to start must not abort startup ("degrade, don't crash").

    The most likely real-world failure is a missing OS input-monitoring
    permission (Accessibility on macOS). The overlay and the working listener
    should still run, with an actionable message logged.
    """

    def test_listener_start_failure_does_not_abort_startup(
        self, keycast: Keycast
    ) -> None:
        keycast.key_listener.start.side_effect = RuntimeError("permission denied")

        keycast.start()  # must not raise

        # The other listener and the overlay still start.
        keycast.mouse_listener.start.assert_called_once()
        keycast.display_window.start.assert_called_once()

    def test_listener_failure_logs_actionable_hint(
        self, keycast: Keycast, caplog: pytest.LogCaptureFixture
    ) -> None:
        keycast.mouse_listener.start.side_effect = RuntimeError("boom")

        with caplog.at_level("ERROR", logger="keycast.application"):
            keycast.start()

        assert "input_capture_unavailable" in caplog.text
        assert "listener=mouse" in caplog.text
        # A non-empty actionable hint accompanies the failure.
        assert "hint=" in caplog.text

    @pytest.mark.parametrize(
        ("system", "needle"),
        [
            ("Darwin", "Accessibility"),
            ("Linux", "input devices"),
            ("Windows", "monitor keyboard and mouse"),
        ],
    )
    def test_permission_hint_is_platform_specific(
        self, system: str, needle: str
    ) -> None:
        """Each supported platform gets a tailored, actionable hint."""
        with patch("keycast.application.platform.system", return_value=system):
            assert needle in Keycast._input_permission_hint()


class TestSignalHandler:
    """Keycast.signal_handler behavior."""

    def test_signal_handler_requests_stop(self, keycast: Keycast) -> None:
        """The handler only requests the loop to exit; it must not destroy in place."""
        keycast.signal_handler(2, None)

        keycast.display_window.request_stop.assert_called_once()
        keycast.display_window.stop.assert_not_called()

    def test_signal_handler_logs_signum(
        self, keycast: Keycast, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The shutdown log line carries the structured signum field."""
        with caplog.at_level("INFO", logger="keycast.application"):
            keycast.signal_handler(15, None)

        assert "shutdown_signal_received signum=15" in caplog.text


class TestRun:
    """Keycast.run orchestration."""

    def test_run_registers_handlers_and_stops_in_finally(
        self, keycast: Keycast
    ) -> None:
        with patch("keycast.application.signal.signal") as mock_signal:
            keycast.run()

        # SIGINT and SIGTERM are both wired to the handler.
        assert mock_signal.call_count == 2
        keycast.display_window.start.assert_called_once()
        # finally block tears everything down.
        keycast.display_window.stop.assert_called_once()

    def test_run_exits_nonzero_on_error(self, keycast: Keycast) -> None:
        """An unexpected start() error exits non-zero but still runs cleanup."""
        keycast.display_window.start.side_effect = RuntimeError("boom")

        with (
            patch("keycast.application.signal.signal"),
            pytest.raises(SystemExit) as exc_info,
        ):
            keycast.run()

        assert exc_info.value.code == 1
        keycast.display_window.stop.assert_called_once()

    def test_signal_during_run_requests_stop_before_destroy(
        self, keycast: Keycast
    ) -> None:
        """End-to-end: a signal during the loop schedules quit, destroys later.

        This guards the two-phase shutdown contract *across* the boundary the
        per-half tests cannot: ``request_stop`` (safe, in-loop) must run strictly
        before ``stop`` (teardown, on the main thread after mainloop returns). A
        regression making ``signal_handler`` call ``stop`` directly — the exact
        in-loop ``destroy`` that raises Tcl errors — would reorder these calls
        and fail here, while passing every isolated test.
        """
        manager = Mock()
        manager.attach_mock(keycast.display_window.request_stop, "request_stop")
        manager.attach_mock(keycast.display_window.stop, "stop")

        # Simulate a signal arriving while the (mocked) main loop is running.
        # start() is now called with start_minimized=..., so absorb any kwargs.
        keycast.display_window.start.side_effect = lambda **_kwargs: (
            keycast.signal_handler(2, None)
        )

        with patch("keycast.application.signal.signal"):
            keycast.run()

        assert manager.mock_calls == [call.request_stop(), call.stop()]

    def test_run_swallows_keyboard_interrupt_and_cleans_up(
        self, keycast: Keycast
    ) -> None:
        """Ctrl-C during start is logged and swallowed (no SystemExit), then cleaned up."""
        keycast.display_window.start.side_effect = KeyboardInterrupt

        with patch("keycast.application.signal.signal"):
            keycast.run()  # must not raise

        keycast.display_window.stop.assert_called_once()
