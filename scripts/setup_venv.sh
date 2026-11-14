#!/usr/bin/env sh
set -eu

python3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" || {
    echo "Python 3.10 or newer is required. Install it and ensure 'python3' points to that version." >&2
    exit 1
}

python3 -m venv .venv || {
    echo "Could not create .venv. Confirm Python 3.10+ and venv support are installed." >&2
    exit 1
}

./.venv/bin/python -m pip install --upgrade pip || {
    echo "Could not upgrade pip in .venv." >&2
    exit 1
}

./.venv/bin/python -m pip install -r requirements.txt || {
    echo "Could not install requirements. Check network access and requirements.txt." >&2
    exit 1
}

echo "Environment ready. Activate it with: . .venv/bin/activate"
