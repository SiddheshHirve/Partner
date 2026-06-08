from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from assistant.brain.ollama_client import OllamaClient


class ChatSignals(QObject):
    token = Signal(str)
    finished = Signal(str)
    failed = Signal(str)


class ChatWorker(QRunnable):
    def __init__(self, client: OllamaClient, prompt: str) -> None:
        super().__init__()
        self.signals = ChatSignals()
        self._client = client
        self._prompt = prompt
        self._reply = ""

    @Slot()
    def run(self) -> None:
        try:
            for token in self._client.stream_chat(self._prompt):
                self._reply += token
                self.signals.token.emit(token)
            self.signals.finished.emit(self._reply)
        except Exception as exc:  # Defensive boundary for the UI thread.
            self.signals.failed.emit(str(exc))
            self.signals.finished.emit(self._reply)
