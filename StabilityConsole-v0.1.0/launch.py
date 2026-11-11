"""One user entry point; reuse the app-managed integration runtime when available."""
import os
from pathlib import Path
import subprocess
import sys
from core import data_dir
from integration_runtime import runtime_paths, runtime_ready

if __name__ == '__main__':
    _, runtime = runtime_paths(data_dir())
    python = str(runtime) if runtime_ready(data_dir()) else sys.executable
    command=[python,'-m','unittest','discover','-s','tests','-v'] if '--self-test' in sys.argv else [python,str(Path(__file__).with_name('app.py'))]
    raise SystemExit(subprocess.call(command,cwd=str(Path(__file__).parent)))
