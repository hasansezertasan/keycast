"""macOS permission checking and dialog UI."""

import logging
import subprocess
import sys
from typing import Literal

PermissionStatus = Literal["granted", "denied", "unknown"]


def check_accessibility_permission() -> PermissionStatus:
    """Check if the application has Accessibility permission on macOS.

    Returns:
        "granted" if permission is granted, "denied" if explicitly denied,
        "unknown" if status cannot be determined.
    """
    if sys.platform != "darwin":
        return "unknown"

    logger = logging.getLogger(__name__)

    try:
        # Use osascript to check if we can access accessibility features
        # This is a basic check that attempts an accessibility operation
        result = subprocess.run(
            [
                "osascript",
                "-e",
                "tell application \"System Events\" to get process 1",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

        if result.returncode == 0:
            return "granted"

    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.debug("Could not determine accessibility permission: %s", exc)
        return "unknown"
    except Exception as exc:
        logger.debug("Unexpected error checking accessibility permission: %s", exc)
        return "unknown"

    return "unknown"


def check_input_monitoring_permission() -> PermissionStatus:
    """Check if the application has Input Monitoring permission on macOS.

    Returns:
        "granted" if permission is granted, "denied" if explicitly denied,
        "unknown" if status cannot be determined.
    """
    if sys.platform != "darwin":
        return "unknown"

    logger = logging.getLogger(__name__)

    try:
        # Try to import pynput to verify input monitoring is accessible
        # The actual permission check happens when pynput listeners start
        from pynput import keyboard  # noqa: F401

        # If pynput imported successfully and we can introspect, assume it might work
        # A definitive check would require accessing the Security & Privacy database
        return "unknown"

    except ImportError:
        logger.debug("pynput not available for input monitoring check")
        return "unknown"
    except Exception as exc:
        logger.debug("Unexpected error checking input monitoring permission: %s", exc)
        return "unknown"


def check_permissions() -> dict[str, PermissionStatus]:
    """Check all required permissions on macOS.

    Returns:
        A dictionary with permission names as keys and status as values.
        Returns an empty dict on non-macOS platforms.
    """
    if sys.platform != "darwin":
        return {}

    return {
        "accessibility": check_accessibility_permission(),
        "input_monitoring": check_input_monitoring_permission(),
    }


def are_permissions_granted() -> bool:
    """Check if all required permissions are granted on macOS.

    Returns:
        True if all permissions are granted, False otherwise.
        Returns True on non-macOS platforms.
    """
    if sys.platform != "darwin":
        return True

    permissions = check_permissions()
    # If we can't determine status, assume permissions might be needed
    # This is a conservative approach
    if not permissions:
        return True

    # Only return True if we explicitly know all are granted
    return all(status == "granted" for status in permissions.values())


def show_permission_dialog(permissions_status: dict[str, PermissionStatus]) -> bool:
    """Show a dialog alerting the user about missing permissions.

    Args:
        permissions_status: Dictionary of permission names to their status.

    Returns:
        True if the user chose to continue anyway, False if they chose to quit.
    """
    if sys.platform != "darwin":
        return True

    import tkinter as tk  # noqa: PLC0415
    from tkinter import messagebox  # noqa: PLC0415

    # Determine which permissions are missing
    missing = [
        name.replace("_", " ").title()
        for name, status in permissions_status.items()
        if status != "granted"
    ]

    if not missing:
        return True

    # Create a root window (hidden)
    root = tk.Tk()
    root.withdraw()

    missing_text = " and ".join(missing)
    message = (
        f"keycast requires {missing_text} permission to monitor keyboard and mouse input.\n\n"
        f"To grant {missing_text} permission:\n"
        f"1. Open System Settings\n"
        f"2. Go to Privacy & Security\n"
        f"3. Select 'Accessibility' and/or 'Input Monitoring'\n"
        f"4. Add keycast to the allowed apps list\n"
        f"5. Restart keycast\n\n"
        f"Would you like to continue anyway or open System Settings?"
    )

    # Show a custom dialog with three options
    result = messagebox.askyesnocancel(
        "keycast Permissions Required",
        message,
        icon=messagebox.WARNING,
    )

    # Clean up the hidden root window
    root.destroy()

    # askyesnocancel returns: True (Yes), False (No), None (Cancel)
    # We'll treat: Yes = continue, No = open settings, Cancel = quit
    if result is None:
        # User clicked Cancel (or closed dialog) - quit
        return False
    if result is True:
        # User clicked Yes - continue anyway
        return True

    # User clicked No - try to open System Settings
    try:
        subprocess.run(
            ["open", "x-apple.systempreferences:com.apple.preference.security"],
            check=False,
            timeout=5,
        )
    except Exception:
        # If opening settings fails, just continue
        pass

    # After showing settings dialog, ask again if they want to continue
    root2 = tk.Tk()
    root2.withdraw()
    continue_anyway = messagebox.askyesno(
        "Continue?",
        "After granting permissions, restart keycast for them to take effect.\n\nContinue running keycast now?",
    )
    root2.destroy()

    return continue_anyway
