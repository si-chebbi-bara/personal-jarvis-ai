"""PyQt6 chat window. Close button hides to the tray instead of quitting."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.llm_brain import handle
from core.voice import WakeWordListener, listen_once, strip_wake_word


class Worker(QThread):
    finished_ok = pyqtSignal(dict)

    def __init__(self, command: str):
        super().__init__()
        self.command = command

    def run(self) -> None:
        try:
            result = handle(self.command)
        except Exception as exc:
            result = {"success": False, "message": str(exc), "provider": "error"}
        self.finished_ok.emit(result)


class ListenWorker(QThread):
    finished_ok = pyqtSignal(dict)

    def run(self) -> None:
        self.finished_ok.emit(listen_once())


class JarvisWindow(QMainWindow):
    wake_heard = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Jarvis")
        self.resize(640, 520)
        self.setWindowIcon(_jarvis_icon())
        self._worker: Worker | None = None
        self._listen_worker: ListenWorker | None = None
        self._wake: WakeWordListener | None = None
        self.wake_heard.connect(self._run_from_wake)

        self.chat = QTextEdit()
        self.chat.setReadOnly(True)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type a command…")
        self.input.returnPressed.connect(self.send_text)

        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self.send_text)
        mic_btn = QPushButton("Mic")
        mic_btn.setToolTip("Listen once (needs pyaudio + portaudio19-dev)")
        mic_btn.clicked.connect(self.listen_once)
        self.wake_btn = QPushButton("Wake word: off")
        self.wake_btn.setCheckable(True)
        self.wake_btn.toggled.connect(self.toggle_wake)

        row = QHBoxLayout()
        row.addWidget(self.input)
        row.addWidget(send_btn)
        row.addWidget(mic_btn)
        row.addWidget(self.wake_btn)

        layout = QVBoxLayout()
        layout.addWidget(self.chat)
        layout.addLayout(row)
        wrap = QWidget()
        wrap.setLayout(layout)
        self.setCentralWidget(wrap)

        self._setup_tray()
        self._append("Jarvis", "Ready. Closing this window hides me in the tray. Right-click the tray icon to quit.")

    def _setup_tray(self) -> None:
        self.tray = QSystemTrayIcon(_jarvis_icon(), self)
        self.tray.setToolTip("Jarvis")
        menu = QMenu()
        show_action = QAction("Show", self)
        show_action.triggered.connect(self.show_from_tray)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.really_quit)
        menu.addAction(show_action)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_from_tray()

    def show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def really_quit(self) -> None:
        if self._wake:
            self._wake.stop()
        self.tray.hide()
        QApplication.quit()

    def closeEvent(self, event) -> None:  # noqa: N802
        event.ignore()
        self.hide()
        self.tray.showMessage(
            "Jarvis",
            "Still running in the background. Right-click the tray icon to quit.",
            QSystemTrayIcon.MessageIcon.Information,
            2500,
        )

    def _append(self, who: str, text: str) -> None:
        self.chat.append(f"<b>{who}:</b> {text.replace(chr(10), '<br>')}")

    def send_text(self) -> None:
        command = self.input.text().strip()
        if not command:
            return
        self.input.clear()
        self._run_command(command)

    def _run_command(self, command: str) -> None:
        if self._worker and self._worker.isRunning():
            self._append("Jarvis", "Still working on the last command…")
            return
        self._append("You", command)
        self._worker = Worker(command)
        self._worker.finished_ok.connect(self._on_result)
        self._worker.start()

    def _on_result(self, result: dict) -> None:
        tag = result.get("provider") or "?"
        prefix = "" if result.get("success") else "Failed — "
        self._append("Jarvis", f"{prefix}{result.get('message')}  <i>[{tag}]</i>")

    def listen_once(self) -> None:
        if self._listen_worker and self._listen_worker.isRunning():
            self._append("Jarvis", "Already listening…")
            return
        self._append("Jarvis", "Listening…")
        self._listen_worker = ListenWorker()
        self._listen_worker.finished_ok.connect(self._on_listen)
        self._listen_worker.start()

    def _on_listen(self, heard: dict) -> None:
        if not heard.get("success"):
            self._append("Jarvis", heard.get("message") or "Mic failed.")
            return
        text = heard.get("text") or ""
        self._run_command(strip_wake_word(text) or text)

    def toggle_wake(self, enabled: bool) -> None:
        if enabled:
            self.wake_btn.setText("Wake word: on")
            self._wake = WakeWordListener(self._from_wake)
            self._wake.start()
            self._append("Jarvis", "Wake word on. Say “Jarvis, what's my battery”.")
        else:
            self.wake_btn.setText("Wake word: off")
            if self._wake:
                self._wake.stop()
                self._wake = None
            self._append("Jarvis", "Wake word off.")

    def _from_wake(self, command: str) -> None:
        self.wake_heard.emit(command)

    @pyqtSlot(str)
    def _run_from_wake(self, command: str) -> None:
        self.show_from_tray()
        self._run_command(command)


def _jarvis_icon() -> QIcon:
    pix = QPixmap(64, 64)
    pix.fill(QColor("#0b1e2d"))
    painter = QPainter(pix)
    painter.setPen(QColor("#5ad2ff"))
    painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "J")
    painter.end()
    return QIcon(pix)


def main() -> None:
    # Make Qt find this project when launched as `python gui.py`
    root = Path(__file__).resolve().parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "Jarvis", "No system tray is available on this desktop.")
        # Still show the window so the app is usable.
    window = JarvisWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
