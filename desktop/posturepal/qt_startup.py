"""Repair macOS platform-plugin discovery before Qt creates an application."""

import os
import stat
import sys
from pathlib import Path

from PySide6.QtCore import QLibraryInfo
from PySide6.QtWidgets import QApplication


def create_application(argv=None):
    """Qt skips libraries carrying UF_HIDDEN, even at its own plugin path.

    Some copied/restored virtual environments have this flag on the bundled
    dylibs. Clear only that flag on the macOS platform plugins, preserving all
    other flags and file contents. Check on every launch because it can recur.
    """
    existing = QApplication.instance()
    if existing is not None:
        return existing
    if sys.platform == "darwin":
        directory = (
            Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)) / "platforms"
        )
        if not directory.is_dir():
            raise RuntimeError(
                f"Qt platform plugins are missing from {directory}. Reinstall PySide6 in this virtual environment."
            )
        for library in directory.glob("*.dylib"):
            try:
                flags = library.stat().st_flags
                if flags & stat.UF_HIDDEN:
                    os.chflags(library, flags & ~stat.UF_HIDDEN)
            except OSError as exc:
                raise RuntimeError(
                    f"Cannot prepare Qt platform plugin {library}: {exc}. "
                    f"Clear its hidden flag with: chflags nohidden '{library}'"
                ) from exc
    return QApplication(sys.argv if argv is None else argv)
