"""Windrose Save Recovery Tool – entry point."""

import sys
import logging
from pathlib import Path

# Ensure logs/ directory exists before any handler tries to write.
Path("logs").mkdir(exist_ok=True)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Windrose Save Recovery Tool")
    app.setAttribute(Qt.AA_UseHighDpiPixmaps)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
