$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir
& ".\.venv\Scripts\Activate.ps1"
python -c "from assistant.memory.store import MemoryStore; m=MemoryStore(); print('Saved facts:'); [print('-', f) for f in m.recent_facts(50)]"
