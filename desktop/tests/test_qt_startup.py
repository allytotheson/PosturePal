"""Exercise discovery with a genuinely hidden macOS Qt platform library."""

import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


@unittest.skipUnless(sys.platform == "darwin", "macOS platform-plugin flags")
class QtStartupTests(unittest.TestCase):
    def test_hidden_plugin_repair_and_permission_error_in_fresh_process(self):
        script = textwrap.dedent("""
            import os
            import shutil
            import stat
            import tempfile
            from pathlib import Path
            from unittest.mock import patch
            from PySide6.QtCore import QCoreApplication, QLibraryInfo
            from posturepal.qt_startup import create_application

            source = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)) / 'platforms/libqoffscreen.dylib'
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                directory = root / 'platforms'
                directory.mkdir()
                library = directory / source.name
                shutil.copyfile(source, library)
                os.chflags(library, library.stat().st_flags | stat.UF_HIDDEN)
                os.environ['QT_QPA_PLATFORM'] = 'offscreen'
                os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = str(directory)
                QCoreApplication.setLibraryPaths([str(root)])
                with patch('posturepal.qt_startup.QLibraryInfo.path', return_value=str(root)):
                    with patch('posturepal.qt_startup.os.chflags', side_effect=PermissionError('read-only plugins')):
                        try:
                            create_application([])
                        except RuntimeError as exc:
                            assert 'chflags nohidden' in str(exc), str(exc)
                            assert str(library) in str(exc), str(exc)
                        else:
                            raise AssertionError('Unrepairable plugins must fail before QApplication')
                    application = create_application([])
                    assert application.platformName() == 'offscreen'
                    assert not library.stat().st_flags & stat.UF_HIDDEN
                    assert create_application([]) is application
                    print('Hidden plugin repaired and Qt started')
        """)
        environment = os.environ.copy()
        environment.pop("QT_PLUGIN_PATH", None)
        environment.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            env=environment,
            text=True,
            capture_output=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Hidden plugin repaired and Qt started", result.stdout)
