from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = APP_DIR / "data"
DB_PATH = DATA_DIR / "memory.sqlite3"


class MemoryStore:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fact TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    done INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def add_message(self, role: str, content: str) -> None:
        content = content.strip()
        if not content:
            return
        with self._connect() as con:
            con.execute(
                "INSERT INTO messages (role, content) VALUES (?, ?)",
                (role, content[:2000]),
            )
            con.commit()

    def add_fact(self, fact: str) -> bool:
        fact = self._clean_fact(fact)
        if not fact:
            return False
        with self._connect() as con:
            con.execute("INSERT OR IGNORE INTO memories (fact) VALUES (?)", (fact,))
            con.commit()
            return con.total_changes > 0

    def recent_facts(self, limit: int = 12) -> list[str]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT fact FROM memories ORDER BY created_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [row[0] for row in rows]

    def recent_messages(self, limit: int = 6) -> list[tuple[str, str]]:
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT role, content
                FROM messages
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [(row[0], row[1]) for row in reversed(rows)]

    def add_reminder(self, text: str, due_at: datetime) -> int:
        text = text.strip()
        with self._connect() as con:
            cur = con.execute(
                "INSERT INTO reminders (text, due_at) VALUES (?, ?)",
                (text[:500], due_at.isoformat(timespec="seconds")),
            )
            con.commit()
            return int(cur.lastrowid)

    def pending_reminders(self) -> list[tuple[int, str, datetime]]:
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT id, text, due_at
                FROM reminders
                WHERE done = 0
                ORDER BY due_at ASC
                """
            ).fetchall()
        reminders: list[tuple[int, str, datetime]] = []
        for reminder_id, text, due_at in rows:
            reminders.append((reminder_id, text, datetime.fromisoformat(due_at)))
        return reminders

    def mark_reminder_done(self, reminder_id: int) -> None:
        with self._connect() as con:
            con.execute("UPDATE reminders SET done = 1 WHERE id = ?", (reminder_id,))
            con.commit()

    def remember_from_user_text(self, text: str) -> bool:
        facts: list[str] = []
        for pattern in (
            r"\bremember that (.+)",
            r"\bremember this[: ]+(.+)",
            r"\bmy name is ([^.!,]+)",
            r"\bi am ([^.!,]+)",
            r"\bi like ([^.!,]+)",
            r"\bi love ([^.!,]+)",
        ):
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                fact = match.group(1).strip()
                if pattern.startswith(r"\bmy name"):
                    fact = f"The user's name is {fact}"
                elif pattern.startswith(r"\bi am"):
                    fact = f"The user is {fact}"
                elif pattern.startswith(r"\bi like"):
                    fact = f"The user likes {fact}"
                elif pattern.startswith(r"\bi love"):
                    fact = f"The user loves {fact}"
                if self.add_fact(fact):
                    facts.append(self._clean_fact(fact))
        return bool(facts)

    def _clean_fact(self, fact: str) -> str:
        fact = re.sub(r"\s+", " ", fact).strip(" .")
        return fact[:300]
