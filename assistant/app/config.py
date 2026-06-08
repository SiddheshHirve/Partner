from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    ollama_url: str = "http://127.0.0.1:11434/api/chat"
    model_name: str = "qwen2.5:3b"
    assistant_name: str = "Companion"
