"""Logging configuration for the keycast application."""

import logging
from collections import OrderedDict
from logging.handlers import RotatingFileHandler
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from keycast.settings import LoggingSettings


def _needs_quoting(value: str) -> bool:
    """Return whether a field value must be ``repr``-quoted to stay one token.

    A field is meant to be a single whitespace-delimited ``key=value`` token. A
    value breaks that contract when it is empty (renders as a bare ``key=``, which
    looks like a missing value), contains ``=`` (``key=a=b`` is ambiguous about
    where the value starts), or contains whitespace (splits into multiple
    tokens). In those cases ``repr`` keeps the whole value one greppable token.
    """
    return not value or "=" in value or any(char.isspace() for char in value)


def format_event(event: str, **fields: object) -> str:
    """Render a log message as ``event key=value ...`` for structured text logs.

    keycast logs to a human-readable text file and the default formatter does
    not render ``logging``'s ``extra`` fields, so structured context is embedded
    in the message itself. This keeps messages greppable (``grep kind=keyboard``)
    while staying readable. A value whose ``str`` is empty, contains ``=``, or
    contains whitespace (space, tab, newline) is quoted with ``repr`` so each
    field remains a single whitespace-delimited token (see :func:`_needs_quoting`).

    Args:
        event: The snake_case event name (e.g. ``"keyboard_listener_started"``).
        **fields: Structured context rendered as ``key=value`` pairs, in order.

    Returns:
        ``event`` alone when no fields are given, otherwise
        ``"event key=value key2=value2"``.
    """
    if not fields:
        return event
    rendered = " ".join(
        f"{key}={value!r}" if _needs_quoting(str(value)) else f"{key}={value}"
        for key, value in fields.items()
    )
    return f"{event} {rendered}"


class _ErrorThrottler:
    """Throttle repeated exception logging from a hot callback.

    A persistent bug in a frequently-invoked callback would otherwise log an
    identical traceback on *every* call (each keystroke/click, or every fade
    tick). This logs the first occurrence of each distinct error (by type and
    source location) with a full traceback, suppresses the noisy repeats, and
    emits a periodic summary so a recurring failure stays visible without
    flooding the log.
    """

    def __init__(
        self,
        logger: logging.Logger,
        *,
        summary_interval: int = 100,
        max_distinct: int = 256,
    ) -> None:
        """Initialize the throttler.

        Args:
            logger: The logger to emit through.
            summary_interval: Emit a summary every this many repeats of an error.
            max_distinct: Cap on the number of distinct errors tracked. When
                exceeded the *least-recently-seen* error is evicted one at a
                time, so a long-running session that hits many different errors
                cannot grow this dict without bound — while a genuinely
                recurring error, refreshed on every occurrence, is never evicted
                and so keeps an accurate repeat count.
        """
        self._logger = logger
        self._summary_interval = summary_interval
        self._max_distinct = max_distinct
        # Ordered by recency of last occurrence so eviction can drop the oldest
        # distinct error instead of clearing every counter (which would reset a
        # recurring error's running count and re-flood its traceback).
        self._counts: OrderedDict[str, int] = OrderedDict()

    @staticmethod
    def _error_key(exc: BaseException) -> str:
        """Build a stable grouping key for ``exc``.

        Keys on the exception type and the source location of the *innermost*
        frame in its traceback rather than ``str(exc)``: an exception message
        may embed variable data (a key repr, click coordinates), which would
        make every event look like a new error and re-introduce the very log
        flood this class exists to suppress. The code location is stable across
        repeats of the same bug.

        Args:
            exc: The caught exception.

        Returns:
            A grouping key combining the exception type and its origin site.
        """
        tb = exc.__traceback__
        location = "<unknown>"
        if tb is not None:
            innermost = tb
            while innermost.tb_next is not None:
                innermost = innermost.tb_next
            frame = innermost.tb_frame
            location = f"{frame.f_code.co_filename}:{innermost.tb_lineno}"
        return f"{type(exc).__name__}@{location}"

    def log(self, event: str, exc: BaseException, **fields: object) -> None:
        """Log ``exc`` under ``event``, throttling identical repeats.

        The first occurrence is logged with ``exc``'s traceback via
        ``exc_info=exc`` (not ``logger.exception()``, which reads the *ambient*
        exception): the traceback comes from the passed ``exc`` regardless of
        whether the call site is still inside an ``except`` block, so a caller
        passing a stored exception cannot silently lose the traceback.

        Mutates ``_counts`` without locking and so assumes a single calling
        thread. That holds for its current callers: each listener owns its own
        throttler and pynput delivers events serially per listener, and the
        display's throttler is only touched from the Tk main loop. A future
        refactor that shares one throttler across threads would need a lock here.

        Args:
            event: The snake_case event name describing what failed.
            exc: The caught exception (used to group repeats).
            **fields: Structured context rendered as ``key=value`` pairs.
        """
        key = self._error_key(exc)
        count = self._counts.get(key, 0) + 1
        self._counts[key] = count
        # Mark this error as the most recently seen, then bound memory by
        # evicting the least-recently-seen distinct error(s). A recurring error
        # is refreshed here on every occurrence, so it is never the eviction
        # target and its count survives a burst of unrelated one-off errors.
        self._counts.move_to_end(key)
        while len(self._counts) > self._max_distinct:
            self._counts.popitem(last=False)

        if count == 1:
            self._logger.error(format_event(event, **fields), exc_info=exc)
        elif count % self._summary_interval == 0:
            self._logger.warning(
                format_event(event, **fields, repeated=count, error_key=key)
            )


def setup_logging(settings: LoggingSettings) -> None:
    """Set up logging configuration.

    Args:
        settings: Logging settings
    """
    logging.basicConfig(
        level=getattr(logging, settings.level),
        format=settings.format,
        force=True,
    )
    # Configure file logging if specified. A problem opening the log file
    # (unwritable directory, read-only home, disk full) must not crash the
    # application: console logging from basicConfig above already works, so we
    # degrade to console-only and warn. The catch is intentionally broad
    # (Exception, not just OSError) to honor that contract — no file-handler
    # setup failure should escape this function and abort startup.
    if settings.file_path:
        try:
            # Ensure the parent directory exists before opening the handler.
            settings.file_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                settings.file_path,
                maxBytes=settings.max_file_size_mb * 1024 * 1024,
                backupCount=settings.backup_count,
            )
        except Exception:
            logging.getLogger(__name__).warning(
                "Could not set up file logging at %s; using console logging only.",
                settings.file_path,
                exc_info=True,
            )
        else:
            # ``settings.format`` is pre-validated by
            # ``LoggingSettings._validate_format`` (it constructs a Formatter at
            # config load), so this cannot raise here. If that validator is ever
            # removed, a bad format would raise *after* basicConfig succeeded and
            # escape setup_logging — re-add the validation if you touch it.
            file_handler.setFormatter(
                logging.Formatter(settings.format),
            )
            root_logger = logging.getLogger()
            # basicConfig(force=True) above closes the stream handlers it manages
            # but not handlers we added ourselves. Remove any RotatingFileHandler
            # from a previous setup_logging call so repeated invocations cannot
            # leak file descriptors or duplicate every log line.
            for handler in root_logger.handlers[:]:
                if isinstance(handler, RotatingFileHandler):
                    root_logger.removeHandler(handler)
                    handler.close()
            root_logger.addHandler(file_handler)
