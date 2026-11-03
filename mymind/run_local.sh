#!/usr/bin/env bash
# One-command local start (macOS/Linux). Windows: see README.
set -e
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt
[ -f .env ] || cp .env.example .env
python -m database.seed
echo "Open http://127.0.0.1:5000"
python app.py
