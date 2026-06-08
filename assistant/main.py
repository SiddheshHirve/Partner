from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from assistant.ui.companion_window import CompanionWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("AI Desktop Companion")
    app.setQuitOnLastWindowClosed(False)

    window = CompanionWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
