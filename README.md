# AI Desktop Companion

Free local-first desktop companion prototype.

## Run

Open PowerShell in this folder and run:

```powershell
.\run_app.ps1
```

Or manually:

```powershell
.\.venv\Scripts\Activate.ps1
python -m assistant.main
```

## Install Dependencies

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Ollama

For real local AI replies, install Ollama and pull a small model:

```powershell
ollama pull qwen2.5:3b
```

The app still opens without Ollama and shows a friendly fallback response.
