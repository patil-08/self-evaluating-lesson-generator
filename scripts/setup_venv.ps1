$ErrorActionPreference = "Stop"

python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.10 or newer is required. Install it and ensure 'python' points to that version."
}

python -m venv .venv
if ($LASTEXITCODE -ne 0) {
    throw "Could not create .venv. Confirm Python 3.10+ is installed and available as 'python'."
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Could not upgrade pip in .venv."
}

& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    throw "Could not install requirements. Check network access and requirements.txt."
}

Write-Host "Environment ready. Activate it with: .\.venv\Scripts\Activate.ps1"
