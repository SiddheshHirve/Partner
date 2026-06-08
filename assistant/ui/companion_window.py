from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, QThreadPool, QTimer, Qt
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from assistant.automation.local_tools import LocalToolRouter, ToolResult
from assistant.app.config import AppConfig
from assistant.brain.ollama_client import OllamaClient
from assistant.memory.store import MemoryStore
from assistant.ui.chat_worker import ChatWorker


ASSET_DIR = Path(__file__).resolve().parents[1] / "assets"
AVATAR_PATH = ASSET_DIR / "pp.png"
IDLE_MESSAGE = "Yo. I'm here."


class SpeechBubble(QLabel):
    def __init__(self) -> None:
        super().__init__(IDLE_MESSAGE)
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.setMinimumSize(230, 82)
        self.setMaximumHeight(112)
        self.setContentsMargins(20, 14, 20, 22)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect().adjusted(4, 4, -4, -22)
        path = QPainterPath()
        path.addRoundedRect(rect, 44, 44)

        tail = QPainterPath()
        tail.moveTo(rect.center().x() + 18, rect.bottom() - 4)
        tail.lineTo(rect.center().x() + 42, rect.bottom() + 20)
        tail.lineTo(rect.center().x() - 2, rect.bottom() + 4)
        tail.closeSubpath()
        path = path.united(tail)

        painter.setBrush(QColor(255, 255, 255, 242))
        painter.setPen(QPen(QColor("#111111"), 3))
        painter.drawPath(path)
        super().paintEvent(event)


class AvatarImage(QLabel):
    def __init__(self) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(210, 285)
        self.setMaximumSize(250, 340)
        self._pixmap = QPixmap(str(AVATAR_PATH))
        self._state = "idle"
        self._frame = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._next_frame)
        self._timer.start(80)

    def set_state(self, state: str) -> None:
        self._state = state
        self.setGraphicsEffect(None)
        self.update()

    def _next_frame(self) -> None:
        self._frame = (self._frame + 1) % 360
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if self._pixmap.isNull():
            painter.setBrush(QColor("#dce8ff"))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(self.rect(), 8, 8)
            return

        phase = self._frame / 10
        if self._state == "thinking":
            y_offset = int(math.sin(phase * 1.8) * 5)
            scale = 0.97 + (math.sin(phase) * 0.015)
        elif self._state == "talking":
            y_offset = int(math.sin(phase * 2.5) * 4)
            scale = 1.0 + (math.sin(phase * 2.5) * 0.012)
        else:
            y_offset = int(math.sin(phase) * 3)
            scale = 0.985 + (math.sin(phase) * 0.006)

        base = self.rect().adjusted(0, 8, 0, -4)
        width = int(base.width() * scale)
        height = int(base.height() * scale)
        target = QRect(
            base.center().x() - width // 2,
            base.center().y() - height // 2 + y_offset,
            width,
            height,
        )
        scaled = self._pixmap.scaled(
            target.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        draw_rect = QRect(
            target.center().x() - scaled.width() // 2,
            target.center().y() - scaled.height() // 2,
            scaled.width(),
            scaled.height(),
        )
        painter.drawPixmap(draw_rect, scaled)


class CompanionWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._drag_offset = QPoint()
        self._thread_pool = QThreadPool.globalInstance()
        self._config = AppConfig()
        self._memory = MemoryStore()
        self._tools = LocalToolRouter(self._memory)
        self._client = OllamaClient(self._config, self._memory)
        self._active_workers: list[ChatWorker] = []
        self._reminder_timers: dict[int, QTimer] = {}
        self._reply_text = ""
        self._reset_timer = QTimer(self)
        self._reset_timer.setSingleShot(True)
        self._reset_timer.timeout.connect(self._reset_bubble)
        
        self._last_active_window = ""
        self._active_window_timer = QTimer(self)
        self._active_window_timer.timeout.connect(self._track_active_window)
        self._active_window_timer.start(800)


        self.setWindowTitle("AI Desktop Companion")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(300, 500)

        self._bubble = SpeechBubble()
        self._avatar = AvatarImage()

        self._input = QLineEdit()
        self._input.setPlaceholderText("Talk to him...")
        self._input.returnPressed.connect(self._send_message)

        self._send = QPushButton("Send")
        self._send.clicked.connect(self._send_message)

        self._hide = QPushButton("x")
        self._hide.setToolTip("Hide")
        self._hide.setFixedSize(24, 24)
        self._hide.clicked.connect(self.hide)

        self._build_layout()
        self._build_tray()
        self._apply_styles()
        self._schedule_pending_reminders()

    def _build_layout(self) -> None:
        top_bar = QHBoxLayout()
        top_bar.addStretch(1)
        top_bar.addWidget(self._hide)

        composer = QHBoxLayout()
        composer.setSpacing(8)
        composer.addWidget(self._input, 1)
        composer.addWidget(self._send)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(4)
        root.addLayout(top_bar)
        root.addWidget(self._bubble)
        root.addWidget(self._avatar, 1, Qt.AlignCenter)
        root.addLayout(composer)

    def _build_tray(self) -> None:
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(QIcon())
        self._tray.setToolTip("AI Desktop Companion")

        menu = QMenu()
        show_action = QAction("Show", self)
        show_action.triggered.connect(self.showNormal)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(QApplication.quit)
        menu.addAction(show_action)
        menu.addAction(quit_action)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QLabel { color: #101418; }
            QLineEdit {
                background: rgba(12, 15, 18, 232);
                color: #eef3f7;
                border: 1px solid rgba(255, 255, 255, 45);
                border-radius: 8px;
                padding: 8px;
                selection-background-color: #2f7ef7;
            }
            QPushButton {
                background: rgba(47, 126, 247, 238);
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 10px;
                font-weight: 700;
            }
            QPushButton:hover { background: #4b91ff; }
            QPushButton:disabled { background: rgba(58, 70, 80, 220); color: #96a2ad; }
            """
        )

    def _send_message(self) -> None:
        prompt = self._input.text().strip()
        if not prompt:
            return

        self._input.clear()
        self._send.setDisabled(True)
        self._reset_timer.stop()
        self._reply_text = ""
        self._avatar.set_state("thinking")
        self._bubble.setText("Thinking...")
        self._memory.add_message("user", prompt)
        remembered = self._memory.remember_from_user_text(prompt)
        if remembered:
            self._complete_direct_response("Got it. I'll remember that.")
            return

        tool_result = self._tools.handle(prompt)
        if tool_result.handled:
            self._handle_tool_result(tool_result)
            return

        worker = ChatWorker(self._client, prompt)
        self._active_workers.append(worker)
        worker.signals.token.connect(self._append_token)
        worker.signals.failed.connect(self._show_error)
        worker.signals.finished.connect(lambda reply: self._finish_response(worker, reply))
        self._thread_pool.start(worker)

    def _append_token(self, token: str) -> None:
        self._reply_text += token
        self._avatar.set_state("talking")
        self._bubble.setText(self._reply_text.strip() or "...")

    def _show_error(self, message: str) -> None:
        self._reply_text = f"I hit an error: {message}"
        self._bubble.setText(self._reply_text)

    def _finish_response(self, worker: ChatWorker, reply: str) -> None:
        if worker in self._active_workers:
            self._active_workers.remove(worker)

        if not self._reply_text.strip():
            self._reply_text = (
                "I'm here, but the local model gave me an empty reply. "
                "Check Ollama and the selected model."
            )
            self._bubble.setText(self._reply_text)
            self._memory.add_message("assistant", self._reply_text)
        elif reply.strip():
            self._memory.add_message("assistant", reply)

        self._send.setDisabled(False)
        self._avatar.set_state("idle")
        self._reset_timer.start(7000)

    def _reset_bubble(self) -> None:
        if not self._active_workers:
            self._reply_text = ""
            self._bubble.setText(IDLE_MESSAGE)

    def _track_active_window(self) -> None:
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return
        buff = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
        title = buff.value
        if title:
            title_lower = title.lower()
            if title != "AI Desktop Companion" and not any(term in title_lower for term in [
                "start_companion.bat", "powershell", "cmd.exe", "conhost", "terminal", "wt.exe",
                "python", "py.exe"
            ]):
                self._last_active_window = title
                if hasattr(self._tools, "last_active_window_title"):
                    self._tools.last_active_window_title = title

    def _handle_tool_result(self, result: ToolResult) -> None:
        if result.reminder_id and result.reminder_due_at and result.reminder_text:
            self._schedule_reminder(result.reminder_id, result.reminder_text, result.reminder_due_at)
        self._complete_direct_response(result.message)

    def _complete_direct_response(self, message: str) -> None:
        self._reply_text = message
        self._bubble.setText(message)
        self._memory.add_message("assistant", message)
        self._send.setDisabled(False)
        self._avatar.set_state("idle")
        self._reset_timer.start(7000)

    def _schedule_pending_reminders(self) -> None:
        for reminder_id, text, due_at in self._memory.pending_reminders():
            self._schedule_reminder(reminder_id, text, due_at)

    def _schedule_reminder(self, reminder_id: int, text: str, due_at) -> None:
        if reminder_id in self._reminder_timers:
            self._reminder_timers[reminder_id].stop()

        delay_ms = int((due_at - datetime.now()).total_seconds() * 1000)
        delay_ms = max(1000, min(delay_ms, 2_147_000_000))
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._fire_reminder(reminder_id, text))
        timer.start(delay_ms)
        self._reminder_timers[reminder_id] = timer

    def _fire_reminder(self, reminder_id: int, text: str) -> None:
        self._memory.mark_reminder_done(reminder_id)
        self._reminder_timers.pop(reminder_id, None)
        message = f"Reminder: {text}"
        self._reply_text = message
        self._bubble.setText(message)
        self._avatar.set_state("idle")
        self._tray.showMessage("Gojo reminder", text, QSystemTrayIcon.MessageIcon.Information, 7000)
        self._reset_timer.start(7000)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.showNormal()
                self.raise_()
                self.activateWindow()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
