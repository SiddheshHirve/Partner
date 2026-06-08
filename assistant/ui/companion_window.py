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
    QLinearGradient,
    QRadialGradient,
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
        
        # Load all sprites
        self._sprites = {}
        for key in ["idle", "walk_1", "walk_2", "dance_1", "dance_2", "sleep", "happy", "sad", "domain", "pervert"]:
            path = ASSET_DIR / f"{key}.png"
            if path.exists():
                self._sprites[key] = QPixmap(str(path))
            else:
                self._sprites[key] = QPixmap(str(AVATAR_PATH))
                
        self._state = "idle"
        self._frame = 0
        self._facing_left = False
        self._particles: list[dict] = []
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._next_frame)
        self._timer.start(30)  # ~33 fps for smoother animations

    def set_state(self, state: str) -> None:
        self._state = state
        self.setGraphicsEffect(None)
        self.update()

    def _next_frame(self) -> None:
        self._frame = (self._frame + 1) % 360
        self._update_particles()
        self.update()

    def _get_current_pixmap(self) -> QPixmap:
        state = self._state
        
        if state == "walking":
            # Swap walk frames every 6 ticks (~180ms per frame)
            frame_idx = (self._frame // 6) % 2
            key = f"walk_{frame_idx + 1}"
            return self._sprites.get(key, self._sprites.get("idle"))
        elif state == "dancing":
            # Swap dance frames every 8 ticks
            frame_idx = (self._frame // 8) % 2
            key = f"dance_{frame_idx + 1}"
            return self._sprites.get(key, self._sprites.get("idle"))
        elif state in self._sprites:
            return self._sprites[state]
            
        return self._sprites.get("idle")

    def _update_particles(self) -> None:
        import random
        state = self._state
        
        # Periodic particle spawning based on animation state
        if state == "sleeping" and random.random() < 0.05:
            self._particles.append({
                "type": "Zzz",
                "text": random.choice(["z", "Z", "Zz"]),
                "x": float(self.rect().center().x() + 25),
                "y": float(self.rect().center().y() - 50),
                "vx": random.uniform(0.3, 0.9),
                "vy": random.uniform(-1.0, -1.8),
                "opacity": 1.0,
                "size": random.uniform(10.0, 16.0)
            })
        elif state == "happy" and random.random() < 0.15:
            self._particles.append({
                "type": "heart",
                "x": float(self.rect().center().x() + random.uniform(-40, 40)),
                "y": float(self.rect().center().y() - 70),
                "vx": random.uniform(-0.5, 0.5),
                "vy": random.uniform(-1.2, -2.4),
                "opacity": 1.0,
                "size": random.uniform(10.0, 16.0),
                "rot": random.uniform(-15, 15),
                "rot_vel": random.uniform(-0.5, 0.5)
            })
        elif state == "pervert" and random.random() < 0.25:
            self._particles.append({
                "type": "kiss_heart",
                "x": float(self.rect().center().x() + random.uniform(-20, 20)),
                "y": float(self.rect().center().y() - 60),
                "vx": random.uniform(-1.5, 1.5),
                "vy": random.uniform(-2.5, -4.5),
                "opacity": 1.0,
                "size": random.uniform(8.0, 16.0),
                "rot": random.uniform(0, 360),
                "rot_vel": random.uniform(-4, 4)
            })
        elif state == "thinking" and random.random() < 0.04:
            self._particles.append({
                "type": "think",
                "text": random.choice(["?", "💬", "💭"]),
                "x": float(self.rect().center().x() + random.uniform(-40, 40)),
                "y": float(self.rect().center().y() - 80),
                "vx": random.uniform(-0.4, 0.4),
                "vy": random.uniform(-0.8, -1.5),
                "opacity": 1.0,
                "size": random.uniform(12.0, 18.0)
            })
        elif state == "domain" and random.random() < 0.30:
            self._particles.append({
                "type": "domain_star",
                "x": float(self.rect().center().x() + random.uniform(-60, 60)),
                "y": float(self.rect().center().y() - 70),
                "vx": random.uniform(-1.0, 1.0),
                "vy": random.uniform(-2.0, -4.0),
                "opacity": 1.0,
                "size": random.uniform(6.0, 15.0),
                "rot": random.uniform(0, 360),
                "rot_vel": random.uniform(-6, 6)
            })

        # Update position and opacity
        for p in self._particles:
            p["x"] += p["vx"]
            p["y"] += p["vy"]
            p["opacity"] -= 0.016  # fade out
            p["size"] += 0.04      # grow slightly
            if "rot" in p:
                p["rot"] += p["rot_vel"]

        # Filter out dead particles
        self._particles = [p for p in self._particles if p["opacity"] > 0]

    def _draw_particles(self, painter: QPainter) -> None:
        for p in self._particles:
            painter.save()
            
            if p["type"] == "Zzz":
                font = QFont("Segoe UI", int(p["size"]))
                painter.setFont(font)
                color = QColor(100, 140, 255, int(p["opacity"] * 255))
                painter.setPen(color)
                painter.drawText(int(p["x"]), int(p["y"]), p["text"])
            elif p["type"] == "think":
                font = QFont("Segoe UI", int(p["size"]))
                painter.setFont(font)
                color = QColor(50, 100, 240, int(p["opacity"] * 255))
                painter.setPen(color)
                painter.drawText(int(p["x"]), int(p["y"]), p["text"])
            elif p["type"] == "heart":
                color = QColor(255, 60, 100, int(p["opacity"] * 255))
                painter.setPen(Qt.NoPen)
                painter.setBrush(color)
                painter.translate(p["x"], p["y"])
                painter.rotate(p.get("rot", 0))
                
                path = QPainterPath()
                sz = p["size"]
                path.moveTo(0, sz / 4)
                path.cubicTo(-sz / 2, -sz / 2, -sz, sz / 3, 0, sz)
                path.cubicTo(sz, sz / 3, sz / 2, -sz / 2, 0, sz / 4)
                painter.drawPath(path)
            elif p["type"] == "kiss_heart":
                color = QColor(255, 105, 180, int(p["opacity"] * 255))
                painter.setPen(Qt.NoPen)
                painter.setBrush(color)
                painter.translate(p["x"], p["y"])
                painter.rotate(p.get("rot", 0))
                
                path = QPainterPath()
                sz = p["size"]
                path.moveTo(0, sz / 4)
                path.cubicTo(-sz / 2, -sz / 2, -sz, sz / 3, 0, sz)
                path.cubicTo(sz, sz / 3, sz / 2, -sz / 2, 0, sz / 4)
                painter.drawPath(path)
            elif p["type"] == "domain_star":
                color = QColor(180, 80, 255, int(p["opacity"] * 255))
                painter.setPen(Qt.NoPen)
                painter.setBrush(color)
                painter.translate(p["x"], p["y"])
                painter.rotate(p.get("rot", 0))
                
                # Draw 4-pointed star centered at (0, 0)
                path = QPainterPath()
                sz = p["size"]
                path.moveTo(0, -sz)
                path.quadTo(0, 0, sz, 0)
                path.quadTo(0, 0, 0, sz)
                path.quadTo(0, 0, -sz, 0)
                path.quadTo(0, 0, 0, -sz)
                painter.drawPath(path)
                
            painter.restore()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        pixmap = self._get_current_pixmap()
        if pixmap.isNull():
            painter.setBrush(QColor("#dce8ff"))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(self.rect(), 8, 8)
            return

        rect = self.rect()
        cx = rect.center().x()
        cy = rect.center().y()

        state = self._state
        phase = self._frame * 0.1

        y_offset = 0
        rotation = 0.0
        scale_x = 1.0
        scale_y = 1.0

        if state == "thinking":
            y_offset = int(math.sin(phase * 0.8) * 8)
            scale_x = 0.98 + math.sin(phase * 0.5) * 0.015
            scale_y = 0.98 + math.cos(phase * 0.5) * 0.015
        elif state == "talking":
            y_offset = int(math.sin(phase * 1.5) * 4)
            scale_x = 1.0 + math.sin(phase * 1.5) * 0.01
            scale_y = 1.0 - math.sin(phase * 1.5) * 0.015
        elif state == "walking":
            y_offset = int(abs(math.sin(phase * 2.0)) * -6)
            rotation = math.sin(phase * 1.5) * 8
        elif state == "dancing":
            dance_step = (self._frame // 15) % 4
            if dance_step == 0:  # Rocking hop
                y_offset = int(abs(math.sin(phase * 3)) * -15)
                rotation = math.sin(phase * 2) * 15
            elif dance_step == 1:  # Squash/stretch
                scale_x = 1.15 + math.sin(phase * 3) * 0.1
                scale_y = 0.85 - math.sin(phase * 3) * 0.1
            elif dance_step == 2:  # Spin
                rotation = (self._frame * 15) % 360
            elif dance_step == 3:  # Bounce and shake
                scale_x = 1.0 + math.sin(phase * 4) * 0.08
                scale_y = 1.0 + math.sin(phase * 4) * 0.08
                y_offset = int(math.sin(phase * 5) * 3)
        elif state == "sleeping":
            rotation = 75.0  # Lay down on side
            scale_y = 0.95 + math.sin(phase * 0.3) * 0.02
            scale_x = 1.0
            y_offset = 12
        elif state == "happy":
            y_offset = -abs(int(math.sin(phase * 2.5) * 22))
            rotation = math.sin(phase * 2) * 10
            scale_x = 1.02 + math.sin(phase * 2.5) * 0.03
            scale_y = 0.98 - math.sin(phase * 2.5) * 0.03
        elif state == "sad":
            rotation = -8.0
            scale_y = 0.92
            scale_x = 1.0
            y_offset = 6
        elif state == "domain":
            scale_x = 1.08 + math.sin(phase * 4.0) * 0.03
            scale_y = 1.08 + math.sin(phase * 4.0) * 0.03
            rotation = math.sin(phase * 8.0) * 3.0  # Intense vibration
            y_offset = int(math.sin(phase * 1.5) * 6)
        elif state == "pervert":
            # Heartbeat pulsation logic: double-pulse beat
            heartbeat = (phase * 2.0) % (math.pi * 2)
            pulse = 1.0
            if heartbeat < 0.6:
                pulse = 1.06 + math.sin(heartbeat * (math.pi / 0.6)) * 0.08
            elif heartbeat < 1.2:
                pulse = 1.0 + math.sin((heartbeat - 0.6) * (math.pi / 0.6)) * 0.03
            scale_x = pulse
            scale_y = pulse
            rotation = math.sin(phase * 1.2) * 4.0
            y_offset = int(math.sin(phase * 0.6) * 4) - 5
        else:  # idle
            y_offset = int(math.sin(phase * 0.4) * 3)
            scale_x = 0.985 + math.sin(phase * 0.4) * 0.006
            scale_y = 0.985 - math.sin(phase * 0.4) * 0.006

        painter.save()
        painter.translate(cx, cy + y_offset)
        painter.rotate(rotation)
        
        # Draw background auras
        if state == "pervert":
            painter.save()
            aura_grad = QRadialGradient(QPoint(0, 0), 120)
            aura_grad.setColorAt(0, QColor(255, 182, 193, 140))  # Soft pink
            aura_grad.setColorAt(0.5, QColor(255, 105, 180, 50))  # Hot pink
            aura_grad.setColorAt(1, QColor(255, 105, 180, 0))
            painter.setBrush(aura_grad)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPoint(0, 0), 130, 130)
            painter.restore()
        elif state == "domain":
            painter.save()
            aura_grad = QRadialGradient(QPoint(0, 0), 130)
            aura_grad.setColorAt(0, QColor(147, 112, 219, 160))  # Medium Purple
            aura_grad.setColorAt(0.5, QColor(75, 0, 130, 70))    # Indigo
            aura_grad.setColorAt(1, QColor(0, 0, 0, 0))
            painter.setBrush(aura_grad)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPoint(0, 0), 140, 140)
            painter.restore()

        # Apply horizontal flip when facing left
        actual_scale_x = -scale_x if self._facing_left else scale_x
        painter.scale(actual_scale_x, scale_y)

        # Draw centered
        base = QRect(-100, -135, 200, 270)
        scaled = pixmap.scaled(
            base.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        draw_rect = QRect(
            -scaled.width() // 2,
            -scaled.height() // 2,
            scaled.width(),
            scaled.height(),
        )
        painter.drawPixmap(draw_rect, scaled)
        painter.restore()

        # Draw overlay particles
        self._draw_particles(painter)


class DomainOverlay(QWidget):
    def __init__(self) -> None:
        super().__init__()
        # Show on top, translucent, no window decoration, pass mouse events through, do not focus
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.SubWindow
            | Qt.WindowTransparentForInput
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        
        # Geometry: cover the primary screen
        screen_geo = QApplication.primaryScreen().geometry()
        self.setGeometry(screen_geo)
        
        self.opacity = 0.0
        self.fade_dir = 1  # 1: fade in, 0: hold, -1: fade out
        self.hold_frames = 0
        
        # Cosmic stars
        self.stars = []
        import random
        for _ in range(80):
            self.stars.append({
                "x": random.uniform(0, screen_geo.width()),
                "y": random.uniform(0, screen_geo.height()),
                "size": random.uniform(1.0, 3.5),
                "speed": random.uniform(0.15, 0.45),
                "color": random.choice([
                    QColor(180, 100, 255),  # Violet
                    QColor(100, 200, 255),  # Cyan
                    QColor(255, 255, 255),  # White
                    QColor(230, 190, 255),  # Soft purple
                ])
            })
            
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_overlay)
        self.timer.start(16)  # ~60 fps

    def start_fade_out(self) -> None:
        self.fade_dir = -1

    def update_overlay(self) -> None:
        # Fade state machine
        if self.fade_dir == 1:
            self.opacity += 0.02
            if self.opacity >= 0.75:
                self.opacity = 0.75
                self.fade_dir = 0
                self.hold_frames = 220  # Hold for ~3.6 seconds
        elif self.fade_dir == 0:
            if self.hold_frames > 0:
                self.hold_frames -= 1
            else:
                self.fade_dir = -1
        elif self.fade_dir == -1:
            self.opacity -= 0.02
            if self.opacity <= 0.0:
                self.opacity = 0.0
                self.timer.stop()
                self.close()

        # Update stars position
        h = self.height()
        w = self.width()
        import random
        for s in self.stars:
            s["y"] -= s["speed"]
            if s["y"] < 0:
                s["y"] = h
                s["x"] = random.uniform(0, w)

        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 1. Background dark translucent fill
        bg_color = QColor(12, 6, 24, int(self.opacity * 240))
        painter.fillRect(self.rect(), bg_color)
        
        # 2. Nebula/Space core radial glow in screen center
        center = self.rect().center()
        rad = min(self.width(), self.height()) // 2
        grad = QRadialGradient(center, rad)
        grad.setColorAt(0, QColor(75, 0, 130, int(self.opacity * 130)))
        grad.setColorAt(0.5, QColor(18, 9, 36, int(self.opacity * 70)))
        grad.setColorAt(1, QColor(0, 0, 0, 0))
        painter.fillRect(self.rect(), grad)
        
        # 3. Draw drifting stars
        for s in self.stars:
            c = QColor(s["color"])
            c.setAlpha(int(self.opacity * 255))
            painter.setPen(Qt.NoPen)
            painter.setBrush(c)
            painter.drawEllipse(QPoint(int(s["x"]), int(s["y"])), int(s["size"]), int(s["size"]))

        # 4. Draw stylized text banner in the middle of the screen
        painter.save()
        
        # Shadow for readability
        painter.setPen(QColor(0, 0, 0, int(self.opacity * 255)))
        
        # Title "DOMAIN EXPANSION"
        font_title = QFont("Segoe UI", 36, QFont.Bold)
        painter.setFont(font_title)
        title_rect_shadow = self.rect().adjusted(3, -97, 3, -97)
        painter.drawText(title_rect_shadow, Qt.AlignCenter, "DOMAIN EXPANSION")
        
        painter.setPen(QColor(255, 255, 255, int(self.opacity * 255)))
        title_rect = self.rect().adjusted(0, -100, 0, 0)
        painter.drawText(title_rect, Qt.AlignCenter, "DOMAIN EXPANSION")
        
        # Subtitle "INFINITE VOID"
        font_sub = QFont("Segoe UI", 52, QFont.Bold)
        painter.setFont(font_sub)
        sub_rect_shadow = self.rect().adjusted(4, 24, 4, 24)
        painter.setPen(QColor(0, 0, 0, int(self.opacity * 255)))
        painter.drawText(sub_rect_shadow, Qt.AlignCenter, "INFINITE VOID")
        
        sub_rect = self.rect().adjusted(0, 20, 0, 0)
        painter.setPen(QColor(162, 89, 255, int(self.opacity * 255)))  # Neon Purple
        painter.drawText(sub_rect, Qt.AlignCenter, "INFINITE VOID")
        
        painter.restore()


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

        # Gravity Toggle Button
        self._gravity_btn = QPushButton("Gravity: ON")
        self._gravity_btn.setCheckable(True)
        self._gravity_btn.setChecked(True)
        self._gravity_btn.setObjectName("gravity_btn")
        self._gravity_btn.setFixedSize(85, 24)
        self._gravity_btn.clicked.connect(self._toggle_gravity)

        # Physics & Animation timers
        self._is_dragging = False
        self._gravity_timer = QTimer(self)
        self._gravity_timer.timeout.connect(self._gravity_step)
        self._velocity_y = 0.0

        self._walk_timer = QTimer(self)
        self._walk_timer.timeout.connect(self._walk_step)
        self._walk_target_x = 0

        self._idle_action_timer = QTimer(self)
        self._idle_action_timer.timeout.connect(self._perform_random_idle_action)
        self._idle_action_timer.start(15000)  # Check for random action every 15 seconds

        self.setWindowTitle("AI Desktop Companion")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(300, 500)

        # Position Gojo at the bottom-right standing on the taskbar on startup
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.right() - 320
        y = screen.bottom() - 500
        self.move(x, y)

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
        top_bar.addWidget(self._gravity_btn)
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
            
            QPushButton#gravity_btn {
                background: rgba(47, 126, 247, 180);
                border-radius: 6px;
                padding: 4px 6px;
                font-size: 10px;
                font-weight: bold;
            }
            QPushButton#gravity_btn:checked {
                background: rgba(47, 126, 247, 238);
                border: 1px solid rgba(255, 255, 255, 80);
            }
            QPushButton#gravity_btn:unchecked, QPushButton#gravity_btn:!checked {
                background: rgba(100, 110, 120, 140);
                color: #d1d5db;
            }
            """
        )

    def _send_message(self) -> None:
        prompt = self._input.text().strip()
        if not prompt:
            return

        self._input.clear()
        
        # Intercept messages if Gojo is sleeping
        if self._avatar._state == "sleeping":
            if any(w in prompt.lower() for w in ["wake up", "wake"]):
                self.wake_up()
            else:
                self._complete_direct_response("Zzz... (He's asleep. Right-click to wake him, or say 'wake up'!)")
            return

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

        active_window = self._last_active_window
        open_windows = self._tools._get_open_windows()
        if not active_window and open_windows:
            active_window = open_windows[0]

        worker = ChatWorker(
            self._client,
            prompt,
            active_window=active_window,
            open_windows=open_windows,
        )
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
            
        if result.animation_action:
            if result.animation_action == "walk":
                self.start_walking()
            elif result.animation_action == "dance":
                self.start_dancing()
            elif result.animation_action == "sleep":
                self.start_sleeping()
            elif result.animation_action == "wake_up":
                self.wake_up()
            elif result.animation_action == "domain":
                self.start_domain()
            elif result.animation_action == "pervert":
                self.start_pervert()
                
        if result.animation_state:
            self._avatar.set_state(result.animation_state)
            if result.animation_state in ["happy", "sad", "thinking", "domain", "pervert"]:
                # Revert to idle after 5 seconds
                QTimer.singleShot(5000, lambda: self._avatar.set_state("idle") if self._avatar._state == result.animation_state else None)

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
            if self._avatar._state == "sleeping":
                self.wake_up()
                event.accept()
                return
                
            if hasattr(self, "_shake_timer") and self._shake_timer.isActive():
                self._shake_timer.stop()
                if hasattr(self, "_orig_pos"):
                    self.move(self._orig_pos)

            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._is_dragging = True
            self._gravity_timer.stop()  # Stop physics while dragging
            self._walk_timer.stop()    # Stop walking while dragging
            self._avatar.set_state("thinking")
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if event.buttons() & Qt.LeftButton and self._is_dragging:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._is_dragging = False
            self._avatar.set_state("idle")
            self._start_falling()
            event.accept()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        menu = QMenu(self)
        
        walk_action = QAction("Take a Walk 🚶", self)
        walk_action.triggered.connect(self.start_walking)
        
        dance_action = QAction("Dance! 🕺", self)
        dance_action.triggered.connect(self.start_dancing)
        
        sleep_action = QAction("Go to Sleep 💤", self)
        sleep_action.triggered.connect(self.start_sleeping)
        
        wake_action = QAction("Wake Up ⏰", self)
        wake_action.triggered.connect(self.wake_up)
        
        happy_action = QAction("Make Happy ❤️", self)
        happy_action.triggered.connect(lambda: self._avatar.set_state("happy"))
        
        sad_action = QAction("Make Sad 😢", self)
        sad_action.triggered.connect(lambda: self._avatar.set_state("sad"))

        idle_action = QAction("Sit Idle", self)
        idle_action.triggered.connect(lambda: self._avatar.set_state("idle"))
        
        domain_action = QAction("Domain Expansion 🤞", self)
        domain_action.triggered.connect(self.start_domain)
        
        pervert_action = QAction("Tease / Blow Kiss 😘", self)
        pervert_action.triggered.connect(self.start_pervert)

        menu.addAction(walk_action)
        menu.addAction(dance_action)
        menu.addAction(domain_action)
        menu.addAction(pervert_action)
        
        if self._avatar._state == "sleeping":
            menu.addAction(wake_action)
        else:
            menu.addAction(sleep_action)
            
        menu.addSeparator()
        
        express_menu = menu.addMenu("Express Emotion")
        express_menu.addAction(happy_action)
        express_menu.addAction(sad_action)
        express_menu.addAction(idle_action)
        
        menu.addSeparator()
        
        hide_action = QAction("Hide Gojo", self)
        hide_action.triggered.connect(self.hide)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(QApplication.quit)
        
        menu.addAction(hide_action)
        menu.addAction(quit_action)
        
        menu.exec(event.globalPos())

    # --- Gravity / Falling Simulation ---
    def _start_falling(self) -> None:
        if self._avatar._state == "sleeping":
            return
        # If gravity is disabled, don't fall
        if not self._gravity_btn.isChecked():
            return
            
        screen = QApplication.primaryScreen().availableGeometry()
        bottom_y = screen.bottom() - self.height()
        if self.y() < bottom_y:
            self._velocity_y = 0.0
            self._avatar.set_state("thinking")  # floating pose while falling
            self._gravity_timer.start(16)  # ~60 fps physics updates

    def _gravity_step(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        bottom_y = screen.bottom() - self.height()
        
        self._velocity_y += 1.3  # Gravity acceleration
        new_y = self.y() + int(self._velocity_y)
        
        if new_y >= bottom_y:
            new_y = bottom_y
            self.move(self.x(), new_y)
            self._gravity_timer.stop()
            self._trigger_bounce()
        else:
            self.move(self.x(), new_y)

    def _trigger_bounce(self) -> None:
        self._avatar.set_state("happy")  # Happy landing celebration!
        QTimer.singleShot(1500, lambda: self._avatar.set_state("idle") if self._avatar._state == "happy" else None)

    # --- Walking / Patrol Simulation ---
    def start_walking(self) -> None:
        if self._avatar._state == "sleeping" or self._gravity_timer.isActive():
            return
            
        screen = QApplication.primaryScreen().availableGeometry()
        current_x = self.x()
        
        # Pick a random target X position
        min_x = screen.left()
        max_x = screen.right() - self.width()
        import random
        target_x = random.randint(min_x, max_x)
        
        # Turn avatar to face the target X (inverted to fix walking backwards)
        self._avatar._facing_left = (target_x > current_x)
        
        self._walk_target_x = target_x
        self._avatar.set_state("walking")
        self._walk_timer.start(25)  # smooth walking updates

    def _walk_step(self) -> None:
        if self._is_dragging or self._gravity_timer.isActive():
            self._walk_timer.stop()
            self._avatar.set_state("idle")
            return
            
        current_x = self.x()
        target_x = self._walk_target_x
        step_size = 4  # pixels per frame
        
        if abs(current_x - target_x) <= step_size:
            self.move(target_x, self.y())
            self._walk_timer.stop()
            self._avatar.set_state("idle")
        else:
            direction = 1 if target_x > current_x else -1
            self.move(current_x + direction * step_size, self.y())

    # --- Other Actions ---
    def start_dancing(self) -> None:
        if self._avatar._state == "sleeping" or self._gravity_timer.isActive():
            return
        self._avatar.set_state("dancing")
        self._bubble.setText("Check out my moves!")
        # Dance for 6 seconds, then stop
        QTimer.singleShot(6000, lambda: self._avatar.set_state("idle") if self._avatar._state == "dancing" else None)

    def start_sleeping(self) -> None:
        self._walk_timer.stop()
        self._gravity_timer.stop()
        self._avatar.set_state("sleeping")
        self._bubble.setText("Zzz...")

    def wake_up(self) -> None:
        if self._avatar._state == "sleeping":
            self._avatar.set_state("happy")
            self._bubble.setText("Yo! I'm awake!")
            # Stay happy for 2 seconds, then go back to idle
            QTimer.singleShot(2000, lambda: self._avatar.set_state("idle") if self._avatar._state == "happy" else None)

    # --- Random Idle Actions ---
    def _perform_random_idle_action(self) -> None:
        # Only perform actions if completely idle, resting on the floor, and not active
        if self._avatar._state != "idle" or self._walk_timer.isActive() or self._gravity_timer.isActive() or self._is_dragging:
            return
            
        import random
        choice = random.random()
        if choice < 0.12:  # 12% chance to take a walk
            self.start_walking()
        elif choice < 0.16:  # 4% chance to do a quick dance
            self.start_dancing()
        elif choice < 0.18:  # 2% chance to express brief happiness
            self._avatar.set_state("happy")
            QTimer.singleShot(3000, lambda: self._avatar.set_state("idle") if self._avatar._state == "happy" else None)

    # --- New Helpers ---
    def _toggle_gravity(self, checked: bool) -> None:
        self._gravity_btn.setText("Gravity: ON" if checked else "Gravity: OFF")
        if not checked:
            self._gravity_timer.stop()
            self._avatar.set_state("idle")
        else:
            self._start_falling()

    def start_domain(self) -> None:
        if self._avatar._state == "sleeping" or self._gravity_timer.isActive():
            return
        self._avatar.set_state("domain")
        self._bubble.setText("Domain Expansion: Infinite Void!")
        
        # Start full-screen cosmic overlay
        self._domain_overlay = DomainOverlay()
        self._domain_overlay.show()
        
        # Start window shake effect
        self._shake_count = 0
        self._orig_pos = self.pos()
        self._shake_timer = QTimer(self)
        self._shake_timer.timeout.connect(self._do_shake)
        self._shake_timer.start(20)  # 50 Hz shake updates
        
        # Domain expansion runs for 6 seconds, then fades out and resets
        QTimer.singleShot(6000, self._stop_domain)

    def _do_shake(self) -> None:
        import random
        # Shake window for ~600ms (30 ticks of 20ms)
        if self._shake_count < 30:
            dx = random.randint(-6, 6)
            dy = random.randint(-6, 6)
            self.move(self._orig_pos.x() + dx, self._orig_pos.y() + dy)
            self._shake_count += 1
        else:
            self._shake_timer.stop()
            self.move(self._orig_pos)

    def _stop_domain(self) -> None:
        if hasattr(self, "_domain_overlay") and self._domain_overlay:
            self._domain_overlay.start_fade_out()
        if self._avatar._state == "domain":
            self._avatar.set_state("idle")

    def start_pervert(self) -> None:
        if self._avatar._state == "sleeping" or self._gravity_timer.isActive():
            return
        self._avatar.set_state("pervert")
        self._bubble.setText("Mwah~ ❤️")
        QTimer.singleShot(4000, lambda: self._avatar.set_state("idle") if self._avatar._state == "pervert" else None)
