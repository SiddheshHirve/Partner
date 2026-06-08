from __future__ import annotations

import os
import re
import subprocess
import webbrowser
import psutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from assistant.memory.store import MemoryStore


@dataclass(frozen=True)
class ToolResult:
    handled: bool
    message: str
    reminder_id: int | None = None
    reminder_due_at: datetime | None = None
    reminder_text: str | None = None
    animation_state: str | None = None
    animation_action: str | None = None


class LocalToolRouter:
    def __init__(self, memory: MemoryStore) -> None:
        self._memory = memory
        self._last_hits: list[Path] = []
        self._app_cache: dict[str, str] = {}
        self._running_processes: dict[str, int] = {}
        self._timer_start = datetime.now() if False else None  # Tracks stopwatch start time
        self._last_whatsapp_chat = None  # Tracks last focused WhatsApp contact
        self.last_active_window_title = ""


    def handle(self, text: str) -> ToolResult:
        cleaned = text.strip()
        lowered = cleaned.lower()

        anim_result = self._try_animation(cleaned)
        if anim_result.handled:
            return anim_result

        if lowered in {"what do you remember", "what do you remember?", "show memory", "show memories"}:
            return self._show_memories()

        if lowered.startswith("forget "):
            return ToolResult(
                True,
                "I can show memories now, but selective forgetting is not wired yet. For now, ask me what I remember and we will add delete next.",
            )

        repeat_result = self._try_repeat(cleaned)
        if repeat_result.handled:
            return repeat_result

        note_result = self._try_save_note(cleaned)
        if note_result.handled:
            return note_result

        screen_result = self._try_screen_info(cleaned)
        if screen_result.handled:
            return screen_result

        desktop_result = self._try_desktop_files(cleaned)
        if desktop_result.handled:
            return desktop_result

        whatsapp_result = self._try_whatsapp(cleaned)
        if whatsapp_result.handled:
            return whatsapp_result

        yt_selection_result = self._try_youtube_selection(cleaned)
        if yt_selection_result.handled:
            return yt_selection_result

        timer_result = self._try_timer(cleaned)
        if timer_result.handled:
            return timer_result

        time_result = self._try_system_time(cleaned)
        if time_result.handled:
            return time_result

        stats_result = self._try_system_stats(cleaned)
        if stats_result.handled:
            return stats_result

        closer = self._try_close(cleaned)
        if closer.handled:
            return closer

        reminder = self._try_create_reminder(cleaned)
        if reminder.handled:
            return reminder

        search = self._try_search(cleaned)
        if search.handled:
            return search

        opener = self._try_open(cleaned)
        if opener.handled:
            return opener

        finder = self._try_find_file(cleaned)
        if finder.handled:
            return finder

        return ToolResult(False, "")

    def _show_memories(self) -> ToolResult:
        facts = self._memory.recent_facts(8)
        if not facts:
            return ToolResult(True, "I don't have saved memories yet. Tell me `remember that ...` and I'll keep it.")
        return ToolResult(True, "Here's what I remember:\n" + "\n".join(f"- {fact}" for fact in facts))

    def _try_create_reminder(self, text: str) -> ToolResult:
        if not re.search(r"\b(remind me|reminder|remember to)\b", text, re.IGNORECASE):
            return ToolResult(False, "")

        due_at = self._parse_due_time(text)
        if due_at is None:
            return ToolResult(
                True,
                "I can do reminders. Try `remind me in 10 minutes to drink water` or `remind me at 8:30 to study`.",
            )

        reminder_text = self._extract_reminder_text(text)
        reminder_id = self._memory.add_reminder(reminder_text, due_at)
        friendly_time = due_at.strftime("%I:%M %p").lstrip("0")
        return ToolResult(
            True,
            f"Bet. I'll remind you at {friendly_time}: {reminder_text}",
            reminder_id=reminder_id,
            reminder_due_at=due_at,
            reminder_text=reminder_text,
        )

    def _parse_due_time(self, text: str) -> datetime | None:
        now = datetime.now()

        relative = re.search(
            r"\bin\s+(\d+)\s*(minute|minutes|min|mins|hour|hours|hr|hrs)\b",
            text,
            re.IGNORECASE,
        )
        if relative:
            amount = int(relative.group(1))
            unit = relative.group(2).lower()
            if unit.startswith(("hour", "hr")):
                return now + timedelta(hours=amount)
            return now + timedelta(minutes=amount)

        absolute = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", text, re.IGNORECASE)
        if absolute:
            hour = int(absolute.group(1))
            minute = int(absolute.group(2) or 0)
            suffix = (absolute.group(3) or "").lower()
            if suffix == "pm" and hour < 12:
                hour += 12
            if suffix == "am" and hour == 12:
                hour = 0
            if hour > 23 or minute > 59:
                return None
            due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if due <= now:
                due += timedelta(days=1)
            return due

        return None

    def _extract_reminder_text(self, text: str) -> str:
        cleaned = re.sub(r"\bremind me\b", "", text, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\bremember to\b", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\bin\s+\d+\s*(minute|minutes|min|mins|hour|hours|hr|hrs)\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bat\s+\d{1,2}(?::\d{2})?\s*(am|pm)?\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^\bto\b\s*", "", cleaned, flags=re.IGNORECASE).strip(" .")
        return cleaned or "the thing you asked me to remind you about"

    def _try_open(self, text: str) -> ToolResult:
        match = re.search(r"\b(open|launch|start)\s+(.+)", text, re.IGNORECASE)
        if not match:
            return ToolResult(False, "")

        target = match.group(2).strip().lower()
        
        last_hit = self._match_last_hit(target)
        if last_hit is not None:
            os.startfile(str(last_hit))  # noqa: S606
            return ToolResult(True, f"Opened {last_hit.name}.")

        folders = {
            "downloads": Path.home() / "Downloads",
            "documents": Path.home() / "Documents",
            "desktop": Path.home() / "Desktop",
        }

        if target in folders:
            os.startfile(str(folders[target]))  # noqa: S606
            return ToolResult(True, f"Opened {target}.")

        result = self._find_and_open_app(target)
        if result.handled:
            return result

        return ToolResult(False, "")

    def _try_search(self, text: str) -> ToolResult:
        if re.search(r"\b(search|look up|find on)\s+(youtube|yt|utube|you tube)\b", text, re.IGNORECASE):
            query = re.sub(
                r"\b(search|look up|find on|youtube|yt|utube|you tube)\b",
                "",
                text,
                flags=re.IGNORECASE,
            ).strip()
            if not query:
                return ToolResult(True, "What do you want to search on YouTube?")
            url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
            webbrowser.open(url)  # noqa: S602
            return ToolResult(True, f"Searching YouTube for '{query}'...")
        
        if re.search(r"\b(youtube|yt|utube|you tube)\b", text, re.IGNORECASE):
            query = re.sub(r"\b(youtube|yt|utube|you tube)\b", "", text, flags=re.IGNORECASE).strip()
            if query:
                url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
                webbrowser.open(url)  # noqa: S602
                return ToolResult(True, f"Searching YouTube for '{query}'...")

        if re.search(r"\b(google|search|find|look up)\b", text, re.IGNORECASE):
            query = re.sub(
                r"\b(google|search|find|look up)\b",
                "",
                text,
                flags=re.IGNORECASE,
            ).strip()
            if not query:
                return ToolResult(True, "What do you want me to search for?")
            url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
            webbrowser.open(url)  # noqa: S602
            return ToolResult(True, f"Searching Google for '{query}'...")

        return ToolResult(False, "")

    def _find_and_open_app(self, app_name: str) -> ToolResult:
        builtin_apps = {
            # System tools
            "notepad": "notepad.exe",
            "calculator": "calc.exe",
            "calc": "calc.exe",
            "paint": "mspaint.exe",
            "ms paint": "mspaint.exe",
            "file explorer": "explorer.exe",
            "explorer": "explorer.exe",
            "settings": "ms-settings:",
            "task manager": "taskmgr.exe",
            "cmd": "cmd.exe",
            "command prompt": "cmd.exe",
            "powershell": "powershell.exe",
            "terminal": "wt.exe",
            "windows terminal": "wt.exe",
            "control panel": "control.exe",
            "device manager": "devmgmt.msc",
            "disk management": "diskmgmt.msc",
            "services": "services.msc",
            "event viewer": "eventvwr.msc",
            "regedit": "regedit.exe",
            "registry": "regedit.exe",
            "system info": "msinfo32.exe",
            "memory": "wmic",
            "processor": "wmic",
        }

        if app_name in builtin_apps:
            command = builtin_apps[app_name]
            return self._execute_app(command, app_name)

        found = self._smart_app_search(app_name)
        if found:
            return self._execute_app(found, app_name)

        return ToolResult(True, f"I couldn't find {app_name} installed. Is it installed?")

    def _smart_app_search(self, app_name: str) -> str | None:
        if app_name in self._app_cache:
            return self._app_cache[app_name]

        # Try Registry App Paths lookup first (extremely fast and reliable)
        app_mapping = {
            "brave": ["brave.exe"],
            "chrome": ["chrome.exe"],
            "google chrome": ["chrome.exe"],
            "firefox": ["firefox.exe"],
            "edge": ["msedge.exe"],
            "discord": ["Discord.exe"],
            "telegram": ["Telegram.exe"],
            "slack": ["slack.exe"],
            "teams": ["Teams.exe"],
            "spotify": ["Spotify.exe"],
            "obs": ["obs64.exe"],
            "vlc": ["vlc.exe"],
            "code": ["Code.exe"],
            "vscode": ["Code.exe"],
            "visual studio code": ["Code.exe"],
            "notepad++": ["notepad++.exe"],
            "sublime": ["sublime_text.exe"],
        }
        registry_names = [app_name, f"{app_name}.exe"]
        if app_name in app_mapping:
            registry_names.append(app_mapping[app_name][0])
            
        import winreg
        for r_name in registry_names:
            if not r_name.endswith(".exe"):
                r_name = f"{r_name}.exe"
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                path = f"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\{r_name}"
                try:
                    with winreg.OpenKey(hive, path) as key:
                        val, _ = winreg.QueryValueEx(key, "")
                        if val:
                            val = val.strip('"')
                            if os.path.exists(val):
                                self._app_cache[app_name] = val
                                return val
                except FileNotFoundError:
                    continue

        found = self._find_running_app(app_name)
        if found:
            self._app_cache[app_name] = found
            return found


        app_mapping = {
            # Browsers
            "brave": ["brave.exe", "BraveSoftware"],
            "chrome": ["chrome.exe", "Google Chrome"],
            "google chrome": ["chrome.exe", "Google Chrome"],
            "firefox": ["firefox.exe", "Mozilla Firefox"],
            "edge": ["msedge.exe", "Microsoft Edge"],
            
            # Communication
            "discord": ["Discord.exe", "Discord"],
            "discord app": ["Discord.exe", "Discord"],
            "telegram": ["Telegram.exe", "Telegram"],
            "slack": ["slack.exe", "Slack"],
            "teams": ["Teams.exe", "Microsoft Teams"],
            "microsoft teams": ["Teams.exe", "Microsoft Teams"],
            
            # Streaming & Media
            "spotify": ["Spotify.exe", "Spotify"],
            "obs": ["obs64.exe", "OBS Studio"],
            "obs studio": ["obs64.exe", "OBS Studio"],
            "vlc": ["vlc.exe", "VLC"],
            "vlc media": ["vlc.exe", "VLC"],
            "vlc player": ["vlc.exe", "VLC"],
            "comet": ["comet.exe", "Comet"],
            "comet app": ["comet.exe", "Comet"],
            
            # Development
            "code": ["Code.exe", "Visual Studio Code"],
            "vs code": ["Code.exe", "Visual Studio Code"],
            "vscode": ["Code.exe", "Visual Studio Code"],
            "visual studio code": ["Code.exe", "Visual Studio Code"],
            "notepad++": ["notepad++.exe", "Notepad++"],
            "notepad plus": ["notepad++.exe", "Notepad++"],
            "sublime": ["sublime_text.exe", "Sublime Text"],
            "sublime text": ["sublime_text.exe", "Sublime Text"],
            
            # Microsoft Office
            "word": ["WINWORD.exe", "Microsoft Word"],
            "microsoft word": ["WINWORD.exe", "Microsoft Word"],
            "ms word": ["WINWORD.exe", "Microsoft Word"],
            "powerpoint": ["POWERPNT.exe", "Microsoft PowerPoint"],
            "ppt": ["POWERPNT.exe", "Microsoft PowerPoint"],
            "power point": ["POWERPNT.exe", "Microsoft PowerPoint"],
            "ms powerpoint": ["POWERPNT.exe", "Microsoft PowerPoint"],
            "excel": ["EXCEL.exe", "Microsoft Excel"],
            "ms excel": ["EXCEL.exe", "Microsoft Excel"],
            "microsoft excel": ["EXCEL.exe", "Microsoft Excel"],
            "access": ["MSACCESS.exe", "Microsoft Access"],
            "outlook": ["OUTLOOK.exe", "Microsoft Outlook"],
            "ms outlook": ["OUTLOOK.exe", "Microsoft Outlook"],
            "onenote": ["ONENOTE.exe", "Microsoft OneNote"],
            "one note": ["ONENOTE.exe", "Microsoft OneNote"],
            "publisher": ["MSPUB.exe", "Microsoft Publisher"],
            "project": ["WINPROJ.exe", "Microsoft Project"],
            
            # Gaming & Streaming
            "steam": ["steam.exe", "Steam"],
            "steam games": ["steam.exe", "Steam"],
            "epic": ["EpicGamesLauncher.exe", "Epic Games Launcher"],
            "epic games": ["EpicGamesLauncher.exe", "Epic Games Launcher"],
            "twitch": ["Twitch.exe", "Twitch"],
            
            # Compression & Utilities
            "7zip": ["7zFM.exe", "7-Zip"],
            "7z": ["7zFM.exe", "7-Zip"],
            "winrar": ["WinRAR.exe", "WinRAR"],
            "rar": ["WinRAR.exe", "WinRAR"],
            
            # Graphics & Design
            "photoshop": ["photoshop.exe", "Adobe Photoshop"],
            "gimp": ["gimp-2.exe", "GIMP"],
            "paint": ["mspaint.exe", "Paint"],
            "ms paint": ["mspaint.exe", "Paint"],
            "paint 3d": ["mspaint.exe", "Paint"],
            "blender": ["blender.exe", "Blender"],
            "figma": ["Figma.exe", "Figma"],
            "inkscape": ["inkscape.exe", "Inkscape"],
            
            # Cloud & Storage
            "onedrive": ["OneDrive.exe", "OneDrive"],
            "google drive": ["GoogleDrive.exe", "Google Drive"],
            "dropbox": ["Dropbox.exe", "Dropbox"],
            
            # Entertainment
            "netflix": ["Netflix.exe", "Netflix"],
            "disney+": ["Disney+.exe", "Disney Plus"],
            "amazon prime": ["PrimeVideo.exe", "Prime Video"],
            "prime video": ["PrimeVideo.exe", "Prime Video"],
            "hbomax": ["HBOMax.exe", "HBO Max"],
            
            # Development Tools
            "git": ["git.exe", "Git"],
            "github desktop": ["GitHubDesktop.exe", "GitHub Desktop"],
            "docker": ["Docker Desktop.exe", "Docker"],
            "postman": ["Postman.exe", "Postman"],
            
            # System Tools
            "cmd": ["cmd.exe", "Command Prompt"],
            "command prompt": ["cmd.exe", "Command Prompt"],
            "powershell": ["powershell.exe", "PowerShell"],
            "terminal": ["wt.exe", "Windows Terminal"],
            "windows terminal": ["wt.exe", "Windows Terminal"],
            "task manager": ["taskmgr.exe", "Task Manager"],
        }

        exe_name = None
        search_terms = []
        
        if app_name in app_mapping:
            exe_name, *search_terms = app_mapping[app_name]
        else:
            exe_name = f"{app_name}.exe"
            search_terms = [app_name]

        found = self._deep_search_program_files(exe_name, search_terms)
        if found:
            self._app_cache[app_name] = found
            return found

        return None

    def _find_running_app(self, app_name: str) -> str | None:
        try:
            best_match = None
            for proc in psutil.process_iter(["pid", "name", "exe"]):
                try:
                    proc_name = proc.info["name"].lower()
                    exe_path = proc.info.get("exe", "")
                    
                    if app_name.lower() in proc_name:
                        if exe_path and os.path.exists(exe_path):
                            if not "crashhandler" in proc_name.lower():
                                return exe_path
                            best_match = exe_path
                    
                    if proc_name.endswith(f"{app_name}.exe".lower()):
                        if exe_path and os.path.exists(exe_path):
                            return exe_path

                    if f"{app_name}.exe".lower() == proc_name:
                        if exe_path and os.path.exists(exe_path):
                            return exe_path
                            
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            if best_match:
                return best_match
        except Exception:
            pass
        
        return None

    def _deep_search_program_files(self, exe_name: str, search_terms: list[str]) -> str | None:
        search_paths = [
            Path(os.environ.get("ProgramFiles", "")),
            Path(os.environ.get("ProgramFiles(x86)", "")),
            Path.home() / "AppData" / "Local",
            Path.home() / "AppData" / "Local" / "Programs",
            Path.home() / "AppData" / "Roaming",
            Path("C:\\Program Files"),
            Path("C:\\Program Files (x86)"),
        ]

        searched_dirs = set()

        for base_path in search_paths:
            if not base_path.exists():
                continue

            try:
                for root, dirs, files in os.walk(base_path):
                    root_path = Path(root)
                    dir_key = str(root_path).lower()

                    if dir_key in searched_dirs:
                        continue
                    searched_dirs.add(dir_key)

                    for file in files:
                        if file.lower() == exe_name.lower():
                            full_path = root_path / file
                            self._app_cache[exe_name] = str(full_path)
                            return str(full_path)

                    dirs[:] = [
                        d
                        for d in dirs
                        if d not in {
                            ".git", ".venv", "__pycache__", "node_modules",
                            "User Data", "Temp", "Cache", "Crashpad", "Local Storage",
                            "Application Support", "History", "GPUCache", "CacheStorage"
                        }
                        and not d.startswith(".")
                        and not d.startswith("~")
                    ]

            except (OSError, PermissionError):
                continue

        return None

    def _execute_app(self, command: str, app_name: str) -> ToolResult:
        try:
            if command.startswith("ms-"):
                os.startfile(command)  # noqa: S606
                return ToolResult(True, f"Opened {app_name}! 🚀")

            process = subprocess.Popen([str(command)], shell=False)
            self._running_processes[app_name.lower()] = process.pid
            return ToolResult(True, f"Opened {app_name}! 🚀")

        except FileNotFoundError:
            return ToolResult(True, f"App path not found: {command}")
        except Exception as exc:
            return ToolResult(True, f"Error opening {app_name}: {exc}")

    def _try_timer(self, text: str) -> ToolResult:
        lowered = text.lower().strip()

        # Start timer commands
        if any(cmd in lowered for cmd in ["start timer", "start stopwatch", "start timing", "begin timer"]):
            self._timer_start = datetime.now()
            return ToolResult(
                True,
                "Stopwatch initiated, sir. I am keeping track of the time."
            )

        # Stop timer commands
        if any(cmd in lowered for cmd in ["stop timer", "stop stopwatch", "stop timing", "end timer"]):
            if self._timer_start is None:
                return ToolResult(True, "There is no active timer running, sir.")
            
            elapsed = datetime.now() - self._timer_start
            self._timer_start = None
            
            # Format elapsed time nicely
            seconds = int(elapsed.total_seconds())
            hours, remainder = divmod(seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            
            parts = []
            if hours > 0:
                parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
            if minutes > 0:
                parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
            if seconds > 0 or not parts:
                parts.append(f"{seconds} second{'s' if seconds > 1 else ''}")
                
            time_str = " and ".join(parts)
            return ToolResult(
                True,
                f"Stopwatch stopped, sir. Elapsed time: {time_str}."
            )

        # Check timer commands
        if any(cmd in lowered for cmd in ["how much time passed", "time elapsed", "check timer", "timer status", "time passed"]):
            if self._timer_start is None:
                return ToolResult(True, "There is no active timer running, sir.")
            
            elapsed = datetime.now() - self._timer_start
            seconds = int(elapsed.total_seconds())
            hours, remainder = divmod(seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            
            parts = []
            if hours > 0:
                parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
            if minutes > 0:
                parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
            if seconds > 0 or not parts:
                parts.append(f"{seconds} second{'s' if seconds > 1 else ''}")
                
            time_str = " and ".join(parts)
            return ToolResult(
                True,
                f"Active stopwatch: {time_str} has elapsed so far, sir."
            )

        return ToolResult(False, "")

    def _try_repeat(self, text: str) -> ToolResult:
        lowered = text.lower().strip("?. ")
        repeat_triggers = {
            "repeat",
            "repeat that",
            "repeat what you said",
            "say that again",
            "what did you say",
            "what was that",
            "can you repeat",
            "say again"
        }

        if lowered in repeat_triggers:
            # Look at recent messages to find the last reply from the assistant
            recent = self._memory.recent_messages(limit=15)
            # recent is in chronological order, so check from the end
            for role, content in reversed(recent):
                if role == "assistant":
                    # Avoid repeating napping alert falls backs or empty values
                    if content and "waking it up" not in content.lower():
                        return ToolResult(True, content)
            
            return ToolResult(True, "I haven't said anything yet, sir.")

        return ToolResult(False, "")

    def _try_screen_info(self, text: str) -> ToolResult:
        lowered = text.lower().strip("?. ")
        triggers = {
            "what's on my screen", "whats on my screen", "what is on my screen",
            "what project am i working on", "whats project i m working on", "what project i am working on",
            "what window is open", "what am i doing", "what am i working on",
            "whats all tabs open", "what tabs are open", "whats on my window", "what's on my window",
            "what window is active", "whats active window", "active window", "current window",
            "what window am i on", "what app am i on", "what app is open", "what's on my window now",
            "whats on my window now", "what is on my window now",
            "what all tabs are running", "what tabs are running", "what apps are running",
            "what apps are open", "what is open", "what is running", "what's running", "whats running"
        }

        if any(trigger in lowered for trigger in triggers):
            windows = self._get_open_windows()
            
            # Prefer the tracked last_active_window_title if available to bypass focus stealing
            active_window = getattr(self, "last_active_window_title", "")
            if not active_window and windows:
                active_window = windows[0]
                
            if not active_window:
                return ToolResult(True, "I don't see any active application windows open, sir.")
            
            # Ensure the active window is not listed twice in the visible list
            if windows and active_window in windows:
                windows.remove(active_window)
            
            # Extract folder/project if the active window is an IDE
            project_match = None
            ide_names = {"visual studio code", "vscode", "pycharm", "intellij", "eclipse", "sublime text", "notepad++"}
            
            if any(ide in active_window.lower() for ide in ide_names):
                parts = active_window.split(" - ")
                if len(parts) >= 3:
                    project_match = parts[-2]
                else:
                    project_match = parts[0]
                    
            lines = [f"- {w}" for w in windows]
            windows_list = "\n".join(lines[:6])
            
            if project_match:
                return ToolResult(
                    True,
                    f"It looks like you are working on the project '{project_match}' in your IDE, sir.\n"
                    f"Active Window: {active_window}\n\n"
                    f"Here is what else is running on your screen:\n{windows_list}" if windows_list else f"Active Window: {active_window}"
                )
                
            # Otherwise return standard active window info
            return ToolResult(
                True,
                f"You are currently looking at **{active_window}**, sir.\n\n"
                f"Here are the active windows visible on your screen:\n{windows_list}" if windows_list else f"You are currently looking at **{active_window}**, sir."
            )


        return ToolResult(False, "")

    def _get_open_windows(self) -> list[str]:
        import ctypes
        EnumWindows = ctypes.windll.user32.EnumWindows
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        GetWindowText = ctypes.windll.user32.GetWindowTextW
        GetWindowTextLength = ctypes.windll.user32.GetWindowTextLengthW
        IsWindowVisible = ctypes.windll.user32.IsWindowVisible
        GetWindowLong = ctypes.windll.user32.GetWindowLongW
        
        titles = []

        def foreach_window(hwnd, lParam):
            if not IsWindowVisible(hwnd):
                return True
                
            length = GetWindowTextLength(hwnd)

            if length <= 0:
                return True
                
            buff = ctypes.create_unicode_buffer(length + 1)
            GetWindowText(hwnd, buff, length + 1)
            title = buff.value
            
            title_lower = title.lower()
            if title in {
                "Program Manager", "Settings", "AI Desktop Companion", 
                "Windows Input Experience", "Host Process for Windows Tasks",
                "Calculator", "Cortana", "Start", "Search", "Task Host Window",
                "Command Prompt", "Windows PowerShell", "Windows Terminal"
            } or any(sys_win in title_lower for sys_win in [
                "nvidia", "amd", "intel", "realtek", "driver", "system overlay", 
                "microsoft text input", "ime", "notification", "start_companion.bat",
                "assistant.main", "powershell", "cmd.exe", "conhost", "terminal", "wt.exe",
                "python", "py.exe"
            ]):
                return True
                
            GWL_EXSTYLE = -20
            WS_EX_TOOLWINDOW = 0x00000080
            ex_style = GetWindowLong(hwnd, GWL_EXSTYLE)
            if ex_style & WS_EX_TOOLWINDOW:
                return True
                
            GWL_STYLE = -16
            WS_CHILD = 0x40000000
            style = GetWindowLong(hwnd, GWL_STYLE)
            if style & WS_CHILD:
                return True
                
            parent = ctypes.windll.user32.GetParent(hwnd)
            if parent and IsWindowVisible(parent):
                parent_len = GetWindowTextLength(parent)
                if parent_len > 0:
                    return True
                
            titles.append(title)
            return True

        EnumWindows(EnumWindowsProc(foreach_window), 0)
        return list(dict.fromkeys(titles))

    def _try_desktop_files(self, text: str) -> ToolResult:
        lowered = text.lower().strip("?. ")
        triggers = {
            "tell files count or names in desktop",
            "files on desktop",
            "what files are on my desktop",
            "list desktop files",
            "count desktop files",
            "show desktop files",
            "what's on my desktop",
            "whats on my desktop"
        }

        if any(trigger in lowered for trigger in triggers):
            desktop_path = Path.home() / "Desktop"
            if not desktop_path.exists():
                return ToolResult(True, "I couldn't locate your Desktop folder, sir.")
            
            files = []
            folders = []
            try:
                for item in desktop_path.iterdir():
                    if item.name.startswith((".", "~")) or item.name.lower() in {"desktop.ini", "ntuser.dat"}:
                        continue
                    if item.is_file():
                        files.append(item.name)
                    elif item.is_dir():
                        folders.append(item.name)
            except Exception as e:
                return ToolResult(True, f"Error scanning Desktop: {e}")
                
            total_count = len(files) + len(folders)
            if total_count == 0:
                return ToolResult(True, "Your Desktop is currently empty, sir.")
                
            msg = f"You have {len(files)} files and {len(folders)} folders on your Desktop, sir.\n\n"
            if folders:
                msg += "**Folders:**\n" + "\n".join(f"- {f}" for f in folders[:10])
                if len(folders) > 10:
                    msg += f"\n- and {len(folders) - 10} more folders..."
                msg += "\n\n"
            if files:
                msg += "**Files:**\n" + "\n".join(f"- {f}" for f in files[:10])
                if len(files) > 10:
                    msg += f"\n- and {len(files) - 10} more files..."
                    
            return ToolResult(True, msg)

        return ToolResult(False, "")

    def _press_key(self, key_code: int) -> None:
        import ctypes
        import time
        ctypes.windll.user32.keybd_event(key_code, 0, 0, 0)
        time.sleep(0.05)
        ctypes.windll.user32.keybd_event(key_code, 0, 2, 0) # KEYEVENTF_KEYUP = 2
        time.sleep(0.05)

    def _press_combo(self, modifier: int, key_code: int) -> None:
        import ctypes
        import time
        ctypes.windll.user32.keybd_event(modifier, 0, 0, 0)
        time.sleep(0.05)
        ctypes.windll.user32.keybd_event(key_code, 0, 0, 0)
        time.sleep(0.05)
        ctypes.windll.user32.keybd_event(key_code, 0, 2, 0) # KEYEVENTF_KEYUP = 2
        time.sleep(0.05)
        ctypes.windll.user32.keybd_event(modifier, 0, 2, 0)
        time.sleep(0.05)

    def _paste_via_clipboard(self, text: str) -> None:
        from PySide6.QtWidgets import QApplication
        import time
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(text)
            time.sleep(0.1)
            self._press_combo(0x11, 0x56) # Ctrl + V
            time.sleep(0.05)

    def _whatsapp_action(self, chat_name: str, message: str | None) -> ToolResult:
        import os
        import time
        
        # Save last chat contact
        self._last_whatsapp_chat = chat_name
        
        # 1. Detect if the chat is already open on screen
        if self._focus_whatsapp_chat(chat_name):
            if message:
                time.sleep(0.2)
                self._paste_via_clipboard(message)
                time.sleep(0.1)
                self._press_key(0x0D) # Enter (Send)
                return ToolResult(
                    True,
                    f"Active chat found. Message sent to '{chat_name}', sir."
                )
            return ToolResult(
                True,
                f"The chat with '{chat_name}' is already open on your screen, sir."
            )
        
        # 2. Otherwise open WhatsApp and search
        try:
            os.startfile("whatsapp://")
        except Exception:
            pass
            
        time.sleep(1.5) # Give it time to launch/restore
        
        focused = self._focus_whatsapp_window()
        if not focused:
            return ToolResult(True, "I opened WhatsApp, but couldn't focus the window, sir. Please make sure WhatsApp is installed and running.")

        # Focus search: Ctrl + F
        self._press_combo(0x11, 0x46) # Ctrl + F
        time.sleep(0.3)
        
        # Paste chat name
        self._paste_via_clipboard(chat_name)
        time.sleep(0.8) # Let list filter
        
        # Open chat: Enter
        self._press_key(0x0D) # Enter
        time.sleep(0.4)
        
        if message:
            # Paste and send message
            self._paste_via_clipboard(message)
            time.sleep(0.1)
            self._press_key(0x0D) # Enter (Send)
            return ToolResult(
                True,
                f"I searched for '{chat_name}' in WhatsApp and attempted to send your message, sir. (Note: If this contact is not in your list, the message could not be sent.)"
            )
            
        return ToolResult(
            True,
            f"I focused WhatsApp and searched for '{chat_name}', sir. If the contact exists, the chat should now be open."
        )


    def _focus_whatsapp_window(self) -> bool:
        import ctypes
        EnumWindows = ctypes.windll.user32.EnumWindows
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        IsWindowVisible = ctypes.windll.user32.IsWindowVisible
        GetWindowTextLength = ctypes.windll.user32.GetWindowTextLengthW
        GetWindowText = ctypes.windll.user32.GetWindowTextW
        
        target_hwnd = None
        
        def foreach_window(hwnd, lParam):
            nonlocal target_hwnd
            if IsWindowVisible(hwnd):
                length = GetWindowTextLength(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    GetWindowText(hwnd, buff, length + 1)
                    title = buff.value
                    if "whatsapp" in title.lower():
                        target_hwnd = hwnd
                        return False
            return True
            
        EnumWindows(EnumWindowsProc(foreach_window), 0)
        
        if target_hwnd:
            if ctypes.windll.user32.IsIconic(target_hwnd):
                ctypes.windll.user32.ShowWindow(target_hwnd, 9) # SW_RESTORE
            else:
                ctypes.windll.user32.ShowWindow(target_hwnd, 5) # SW_SHOW
            ctypes.windll.user32.BringWindowToTop(target_hwnd)
            ctypes.windll.user32.SetForegroundWindow(target_hwnd)
            return True
        return False

    def _focus_whatsapp_chat(self, chat_name: str) -> bool:
        import ctypes
        EnumWindows = ctypes.windll.user32.EnumWindows
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        IsWindowVisible = ctypes.windll.user32.IsWindowVisible
        GetWindowTextLength = ctypes.windll.user32.GetWindowTextLengthW
        GetWindowText = ctypes.windll.user32.GetWindowTextW
        
        target_hwnd = None
        
        def foreach_window(hwnd, lParam):
            nonlocal target_hwnd
            if IsWindowVisible(hwnd):
                length = GetWindowTextLength(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    GetWindowText(hwnd, buff, length + 1)
                    title = buff.value.lower()
                    if chat_name.lower() in title and "whatsapp" in title:
                        target_hwnd = hwnd
                        return False
            return True
            
        EnumWindows(EnumWindowsProc(foreach_window), 0)
        
        if target_hwnd:
            if ctypes.windll.user32.IsIconic(target_hwnd):
                ctypes.windll.user32.ShowWindow(target_hwnd, 9) # SW_RESTORE
            else:
                ctypes.windll.user32.ShowWindow(target_hwnd, 5) # SW_SHOW
            ctypes.windll.user32.BringWindowToTop(target_hwnd)
            ctypes.windll.user32.SetForegroundWindow(target_hwnd)
            return True
        return False

    def _try_whatsapp(self, text: str) -> ToolResult:
        lowered = text.lower().strip()
        
        # 1. Follow-up: Send message to "him"/"her"/"them"/"it" or "the chat" (using last chat name)
        msg_ref_match = re.search(
            r"\b(?:send a\s+)?(?:msg|message|reply)\s+(?:to\s+)?(?:him|her|them|it|the chat|that contact)\s+(?:saying|with|say)\s+(.+)",
            text,
            re.IGNORECASE
        )
        if msg_ref_match:
            if self._last_whatsapp_chat:
                message_content = msg_ref_match.group(1).strip()
                return self._whatsapp_action(self._last_whatsapp_chat, message_content)
            else:
                return ToolResult(True, "Who should I send the message to, sir?")

        # 2. General message trigger: "wp msg yash C hello", "send message yash C hello", "reply to yash C hello"
        send_match = re.search(
            r"\b(?:whatsapp|wp|send msg to|send message to|msg|message|reply to)\s+([^.]+?)\s+(?:saying|with|say|msg|message)\s+(.+)",
            text,
            re.IGNORECASE
        )
        if send_match:
            chat_name = send_match.group(1).strip()
            message_content = send_match.group(2).strip()
            return self._whatsapp_action(chat_name, message_content)

        # 3. Shortforms / slang: "wp yash C", "whatsapp yash C", "open yash C chat", "open yash C on whatsapp"
        # Match: "open [user] on whatsapp"
        open_wp_match = re.search(
            r"\b(?:open|chat with)\s+([^.]+?)\s+(?:on whatsapp|on wp)\b",
            text,
            re.IGNORECASE
        )
        if open_wp_match:
            chat_name = open_wp_match.group(1).strip()
            return self._whatsapp_action(chat_name, None)

        # Match general open chat
        open_match = re.search(
            r"\b(?:whatsapp|wp|open whatsapp chat|open chat with|open chat)\s+([^.]+?)(?:\s+chat)?$",
            text,
            re.IGNORECASE
        )
        if open_match:
            chat_name = open_match.group(1).strip()
            return self._whatsapp_action(chat_name, None)

        return ToolResult(False, "")

    def _try_save_note(self, text: str) -> ToolResult:
        lowered = text.lower().strip()
        
        match = re.search(
            r"\b(?:save a note as|save note|take a note|add note|remember that|remember to|save a note|write a note)\s+(.+)",
            text,
            re.IGNORECASE
        )
        if match:
            content = match.group(1).strip().strip('"')
            # Bypass reminders
            if re.search(r"\b(in\s+\d+|at\s+\d+)\b", lowered):
                return ToolResult(False, "")
                
            cleaned_content = re.sub(r"^(to|that)\s+", "", content, flags=re.IGNORECASE).strip()
            
            success = self._memory.add_fact(cleaned_content)
            if success:
                return ToolResult(True, f"Bet. I've saved that to my memory, sir: '{cleaned_content}'.")
            else:
                return ToolResult(True, f"I already remember that, sir: '{cleaned_content}'.")
                
        return ToolResult(False, "")

    def _try_youtube_selection(self, text: str) -> ToolResult:
        lowered = text.lower().strip("?. ")
        
        match = re.search(
            r"\b(?:play|open|select)\s+(?:the\s+)?(\d+(?:st|nd|rd|th)?|first|second|third|fourth|fifth|2nd|3rd|4th|5th)\s+(?:video|song|result|one)?",
            lowered
        )
        
        if match:
            ordinal = match.group(1)
            index_map = {
                "first": 0, "1st": 0, "1": 0,
                "second": 1, "2nd": 1, "2": 1,
                "third": 2, "3rd": 2, "3": 2,
                "fourth": 3, "4th": 3, "4": 3,
                "fifth": 4, "5th": 4, "5": 4
            }
            
            idx = index_map.get(ordinal, -1)
            if idx == -1:
                return ToolResult(False, "")
                
            last_query = self._get_last_youtube_search()
            if not last_query:
                return ToolResult(True, "I don't remember what search you did recently, sir. Could you repeat the search?")
                
            import webbrowser
            video_ids = self._get_youtube_video_ids(last_query)
            if not video_ids or len(video_ids) <= idx:
                return ToolResult(True, f"I couldn't retrieve the {ordinal} video for '{last_query}', sir.")
                
            video_url = f"https://www.youtube.com/watch?v={video_ids[idx]}"
            webbrowser.open(video_url)
            return ToolResult(True, f"Playing the {ordinal} video for '{last_query}', sir.")

        return ToolResult(False, "")

    def _get_last_youtube_search(self) -> str | None:
        recent = self._memory.recent_messages(limit=20)
        for role, content in reversed(recent):
            if role == "user":
                content_lower = content.lower()
                if "youtube" in content_lower or "yt" in content_lower:
                    query = re.sub(
                        r"\b(youtube|yt|utube|you tube|search|look up|find on)\b",
                        "",
                        content,
                        flags=re.IGNORECASE
                    ).strip()
                    if query:
                        return query
        return None

    def _get_youtube_video_ids(self, query: str) -> list[str]:
        import requests
        import re
        url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        try:
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                video_ids = re.findall(r'"videoId":"([^"]+)"', res.text)
                return list(dict.fromkeys(video_ids))
        except Exception:
            pass
        return []

    def _try_system_time(self, text: str) -> ToolResult:
        lowered = text.lower().strip()
        time_triggers = {"what time is it", "what's the time", "tell me the time", "current time", "time right now"}
        date_triggers = {"what is today's date", "what's today's date", "what day is today", "current date", "today's date", "what date is today"}

        if any(trigger in lowered for trigger in time_triggers):
            now = datetime.now()
            time_str = now.strftime("%I:%M %p").lstrip("0")
            return ToolResult(True, f"It is currently {time_str}, sir.")

        if any(trigger in lowered for trigger in date_triggers):
            now = datetime.now()
            date_str = now.strftime("%A, %B %d, %Y")
            return ToolResult(True, f"Today is {date_str}, sir.")

        return ToolResult(False, "")

    def _try_system_stats(self, text: str) -> ToolResult:
        lowered = text.lower().strip()
        triggers = {"system stats", "cpu usage", "ram usage", "memory usage", "check system", "pc status", "check status"}

        if any(trigger in lowered for trigger in triggers):
            cpu_percent = psutil.cpu_percent(interval=0.1)
            virtual_mem = psutil.virtual_memory()
            ram_percent = virtual_mem.percent
            ram_used_gb = virtual_mem.used / (1024**3)
            ram_total_gb = virtual_mem.total / (1024**3)

            message = (
                f"Checking system diagnostics, sir.\n"
                f"- CPU Usage: {cpu_percent}%\n"
                f"- Memory Usage: {ram_percent}% ({ram_used_gb:.1f} GB of {ram_total_gb:.1f} GB used)"
            )
            return ToolResult(True, message)

        return ToolResult(False, "")

    def _try_close(self, text: str) -> ToolResult:
        lowered = text.lower().strip()

        close_match = re.search(r"\b(close|kill|stop|quit|exit)\s+(.+)", lowered)
        if close_match:
            target = close_match.group(2).strip()
            return self._kill_app(target)

        if lowered in {"close desktop", "close downloads", "close documents", "close explorer", "close file explorer"}:
            return ToolResult(
                True,
                "I won't close Windows Explorer blindly yet. That's risky. For now, close that folder window manually.",
            )
        if lowered in {"close yourself", "close gojo", "hide gojo", "hide yourself"}:
            return ToolResult(True, "Use the blue x or tray menu for now. I'll add self-hide command next.")
        return ToolResult(False, "")

    def _kill_app(self, app_name: str) -> ToolResult:
        app_processes = {
            "brave": ["brave.exe"],
            "chrome": ["chrome.exe"],
            "firefox": ["firefox.exe"],
            "edge": ["msedge.exe"],
            "discord": ["discord.exe"],
            "spotify": ["spotify.exe"],
            "teams": ["teams.exe"],
            "obs": ["obs64.exe"],
            "steam": ["steam.exe"],
            "vlc": ["vlc.exe"],
            "notepad": ["notepad.exe"],
            "calc": ["calc.exe"],
            "calculator": ["calc.exe"],
            "code": ["code.exe"],
            "vscode": ["code.exe"],
            "vs code": ["code.exe"],
            "slack": ["slack.exe"],
            "telegram": ["telegram.exe"],
            "zoom": ["zoom.exe"],
            "skype": ["skype.exe"],
            "task manager": ["taskmgr.exe"],
            "taskmgr": ["taskmgr.exe"],
            "command prompt": ["cmd.exe"],
            "cmd": ["cmd.exe"],
            "powershell": ["powershell.exe"],
            "terminal": ["wt.exe"],
            "windows terminal": ["wt.exe"],
        }

        lowered_name = app_name.lower().strip()
        process_names = app_processes.get(lowered_name, [])
        if not process_names:
            process_names = [
                f"{lowered_name}.exe",
                f"{lowered_name.replace(' ', '')}.exe",
                f"{lowered_name.replace(' ', '_')}.exe"
            ]

        killed = False
        killed_names = set()
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                proc_name = proc.info["name"].lower()
                is_match = False
                if proc_name in process_names:
                    is_match = True
                else:
                    clean_target = lowered_name.replace(".exe", "")
                    if len(clean_target) >= 3:
                        if clean_target in proc_name or clean_target.replace(" ", "") in proc_name:
                            if proc_name not in {"explorer.exe", "svchost.exe", "python.exe", "pythonw.exe", "conhost.exe"}:
                                is_match = True

                if is_match:
                    proc.kill()
                    killed = True
                    killed_names.add(proc.info["name"])
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        if killed:
            names_str = ", ".join(killed_names)
            return ToolResult(True, f"Closed {app_name} ({names_str}). ✓")
        return ToolResult(True, f"Couldn't find {app_name} running. Is it open?")

    def _try_find_file(self, text: str) -> ToolResult:
        match = re.search(r"\b(find|search)\s+(.+)", text, re.IGNORECASE)
        if not match:
            return ToolResult(False, "")

        query = match.group(2).strip().strip('"')
        query = re.sub(r"\b(file|folder|for)\b", "", query, flags=re.IGNORECASE).strip()
        if len(query) < 2:
            return ToolResult(True, "Give me a little more of the file name and I'll search.")

        roots = [Path.home()]
        hits: list[Path] = []
        skipped_dirs = {
            ".git", ".venv", "__pycache__", "node_modules", "site-packages",
            "AppData", "Application Data", "Cookies", "Local Settings", "My Documents",
            "NetHood", "PrintHood", "Recent", "SendTo", "Templates", "OneDrive",
            ".TurboVPN", ".android", ".antigravity", ".arduinoIDE", ".aws", ".cache",
            ".codeium", ".codex", ".config", ".copilot", ".cursor", ".dotnet", ".eclipse",
            ".expo", ".gemini", ".ghcp-appmod", ".ghcp-appmod-java", ".gk", ".gradle",
            ".ipython", ".lemminx", ".local", ".m2", ".matplotlib", ".ollama", ".p2",
            ".redhat", ".rsp", ".sbx-denybin", ".streamlit", ".sts4", ".templateengine",
            ".thumbnails", ".vscode", ".vscode-shared", ".windsurf", "scoop", "eclipse",
            "npm-cache"
        }
        scanned = 0
        for root in roots:
            if not root.exists():
                continue
            try:
                for current_root, dirs, files in os.walk(root):
                    # Prune folders we want to skip (including hidden folders)
                    dirs[:] = [
                        d for d in dirs 
                        if d not in skipped_dirs 
                        and not d.startswith(".") 
                        and not d.startswith("~")
                    ]
                    current_path = Path(current_root)
                    for name in files + dirs:
                        scanned += 1
                        if query.lower() in name.lower():
                            hits.append(current_path / name)
                        # Cap at 5 hits or 15000 scanned entries to ensure responsiveness
                        if len(hits) >= 5 or scanned >= 15000:
                            break
                    if len(hits) >= 5 or scanned >= 15000:
                        break
            except OSError:
                continue
            if len(hits) >= 5 or scanned >= 15000:
                break

        if not hits:
            return ToolResult(True, f"I couldn't find anything matching `{query}` in your home directory, sir.")

        self._last_hits = hits
        if len(hits) == 1 or hits[0].name.lower() == query.lower():
            try:
                os.startfile(str(hits[0]))  # noqa: S606 - user-requested local open.
                return ToolResult(True, f"Found and opened {hits[0].name}.")
            except Exception as e:
                return ToolResult(True, f"Found {hits[0].name} but couldn't open it: {e}")

        lines = [f"{idx + 1}. {path.name} (in ...\\{path.parent.name})" for idx, path in enumerate(hits[:4])]
        return ToolResult(True, "I found these matching items, sir:\n" + "\n".join(lines) + "\nSay `open first` if you want the top one.")

    def _match_last_hit(self, target: str) -> Path | None:
        if not self._last_hits:
            return None
        if target in {"it", "that", "first", "result", "first result", "file", "the file"}:
            return self._last_hits[0]
        number_words = {"second": 1, "third": 2}
        if target in number_words and len(self._last_hits) > number_words[target]:
            return self._last_hits[number_words[target]]
        for hit in self._last_hits:
            if target == hit.name.lower() or target in hit.name.lower():
                return hit
        return None

    def _find_vs_code(self) -> Path | str | None:
        candidates = [
            Path.home() / "AppData" / "Local" / "Programs" / "Microsoft VS Code" / "Code.exe",
            Path(os.environ.get("ProgramFiles", "")) / "Microsoft VS Code" / "Code.exe",
            Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft VS Code" / "Code.exe",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return "code"

    def _try_animation(self, text: str) -> ToolResult:
        lowered = text.lower().strip("?.! ")
        
        dance_triggers = {"dance", "do a dance", "can you dance", "show me some moves", "dance for me"}
        if lowered in dance_triggers:
            return ToolResult(True, "Check out my moves!", animation_action="dance")
            
        walk_triggers = {"walk", "walk around", "take a walk", "stretch your legs", "move around"}
        if lowered in walk_triggers:
            return ToolResult(True, "Sure, I'll stretch my legs a bit.", animation_action="walk")
            
        sleep_triggers = {"sleep", "go to sleep", "take a nap", "sleep gojo"}
        if lowered in sleep_triggers:
            return ToolResult(True, "Alright, turning off for a bit. Zzz...", animation_action="sleep")
            
        wake_triggers = {"wake up", "wake", "wake up gojo"}
        if lowered in wake_triggers:
            return ToolResult(True, "Huh? What? I'm awake!", animation_action="wake_up")
            
        happy_triggers = {"be happy", "happy", "smile", "laugh"}
        if lowered in happy_triggers:
            return ToolResult(True, "Heh, you make me happy!", animation_state="happy")
            
        sad_triggers = {"be sad", "sad", "cry"}
        if lowered in sad_triggers:
            return ToolResult(True, "Aww... that's sad.", animation_state="sad")

        domain_triggers = {"domain", "domain expansion", "infinite void", "crossed fingers", "jjk pose", "pose"}
        if lowered in domain_triggers:
            return ToolResult(True, "Domain Expansion: Infinite Void!", animation_action="domain")

        pervert_triggers = {"pervert", "pervert move", "kiss", "blow kiss", "tease"}
        if lowered in pervert_triggers:
            return ToolResult(True, "Mwah~ ❤️", animation_action="pervert")
            
        return ToolResult(False, "")

