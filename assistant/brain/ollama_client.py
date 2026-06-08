from __future__ import annotations

import json
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import requests

from assistant.app.config import AppConfig
from assistant.memory.store import MemoryStore


class OllamaClient:
    def __init__(self, config: AppConfig, memory: MemoryStore | None = None) -> None:
        self._config = config
        self._memory = memory or MemoryStore()
        self._model_name = config.model_name
        self._keepalive_thread: threading.Thread | None = None
        self._keepalive_active = False
        self._is_ready = False
        
        # Start initialization in a background thread to prevent GUI hang
        threading.Thread(target=self._async_init, daemon=True).start()

    def _async_init(self) -> None:
        # Start Ollama server if not running
        self._ensure_ollama_running()
        
        # Select the best available model
        self._select_available_model()
        
        # Pre-load the model immediately (wait for it to load)
        self._preload_model()
        
        # Start background keepalive thread
        self._start_keepalive_thread()
        
        self._is_ready = True

    def _select_available_model(self) -> None:
        """Check if the configured model exists; if not, fallback to an available model."""
        tags_url = self._config.ollama_url.replace("/api/chat", "/api/tags")
        try:
            response = requests.get(tags_url, timeout=3)
            if response.status_code == 200:
                data = response.json()
                models = [m["name"] for m in data.get("models", [])]
                if models:
                    # Exact match
                    if self._config.model_name in models:
                        self._model_name = self._config.model_name
                    else:
                        # Try matching base name (e.g., "qwen2.5:3b" matches "qwen2.5:3b-instruct")
                        base_config = self._config.model_name.split(":")[0]
                        matched = [m for m in models if m.startswith(base_config)]
                        if matched:
                            self._model_name = matched[0]
                        else:
                            # Fallback to the first available model
                            self._model_name = models[0]
                else:
                    self._model_name = self._config.model_name
            else:
                self._model_name = self._config.model_name
        except Exception:
            self._model_name = self._config.model_name

    def stream_chat(self, prompt: str) -> Iterator[str]:
        # Wait up to 10 seconds for background initialization if it's still running
        start_time = time.time()
        while not self._is_ready and (time.time() - start_time < 10.0):
            time.sleep(0.1)
        yield from self._stream_chat_with_retry(prompt, did_retry=False)

    def _stream_chat_with_retry(self, prompt: str, did_retry: bool) -> Iterator[str]:
        memories = self._memory.recent_facts()
        recent_messages = self._memory.recent_messages()
        memory_text = "\n".join(f"- {fact}" for fact in memories) or "- No saved memories yet."

        messages = [
            {
                "role": "system",
                "content": (
                    "You are Gojo, the user's desktop AI companion. "
                    "Never introduce yourself as Qwen, Alibaba, an AI model, or a language model. "
                    "If asked who you are, say you are Gojo, the user's local desktop companion. "
                    "Speak with confident, playful, warm energy, but stay helpful and concise. "
                    "You are inspired by the user's chosen Gojo character image, but you are a desktop assistant, "
                    "not the copyrighted anime character himself. "
                    "Use the saved memory when it is relevant.\n\n"
                    f"Saved memory:\n{memory_text}"
                ),
            }
        ]

        for role, content in recent_messages:
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self._model_name,
            "stream": True,
            "keep_alive": "24h",
            "messages": messages,
        }

        try:
            with requests.post(
                self._config.ollama_url, json=payload, stream=True, timeout=(5, 180)
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    data = json.loads(line)
                    content = data.get("message", {}).get("content", "")
                    if content:
                        yield content
                    if data.get("done"):
                        break
        except requests.RequestException:
            if not did_retry and self._start_ollama_server():
                yield "Brain was napping. Waking it up..."
                time.sleep(3)
                yield from self._stream_chat_with_retry(prompt, did_retry=True)
                return
            yield (
                "My local brain is offline right now. "
                "Open Ollama, then try me again."
            )

    def _start_ollama_server(self) -> bool:
        ollama = Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe"
        if not ollama.exists():
            return False
        try:
            subprocess.Popen(
                [str(ollama), "serve"],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except OSError:
            return False

    def _ensure_ollama_running(self) -> None:
        """Ensure Ollama server is running."""
        for attempt in range(10):
            try:
                requests.get("http://127.0.0.1:11434/api/tags", timeout=1)
                return
            except requests.RequestException:
                if attempt == 0:
                    self._start_ollama_server()
                time.sleep(1)

    def _preload_model(self) -> None:
        """Pre-load the model into memory on startup."""
        try:
            payload = {
                "model": self._model_name,
                "stream": False,
                "keep_alive": "24h",
                "prompt": "say hello",
            }
            requests.post(
                self._config.ollama_url.replace("/api/chat", "/api/generate"),
                json=payload,
                timeout=60,
            )
        except Exception:
            pass

    def _start_keepalive_thread(self) -> None:
        """Start background thread to keep model loaded."""
        self._keepalive_active = True
        self._keepalive_thread = threading.Thread(
            target=self._keepalive_loop,
            daemon=True,
        )
        self._keepalive_thread.start()

    def _keepalive_loop(self) -> None:
        """Periodically ping the model to keep it loaded."""
        while self._keepalive_active:
            try:
                time.sleep(60)
                payload = {
                    "model": self._model_name,
                    "stream": False,
                    "keep_alive": "24h",
                    "prompt": "ok",
                }
                requests.post(
                    self._config.ollama_url.replace("/api/chat", "/api/generate"),
                    json=payload,
                    timeout=10,
                )
            except Exception:
                pass

    def stop(self) -> None:
        """Stop the keepalive thread."""
        self._keepalive_active = False
        if self._keepalive_thread:
            self._keepalive_thread.join(timeout=2)
