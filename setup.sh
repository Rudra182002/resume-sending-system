#!/usr/bin/env bash
# One-shot environment setup. Run after cloning, or when imports start failing.
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
./.venv/bin/pip install --upgrade pip --quiet
./.venv/bin/pip install -r requirements.txt --quiet
[ -f .env ] || { cp .env.example .env; echo "created .env - fill it in"; }
echo "--- import check ---"
./.venv/bin/python -c "
import importlib
mods = ['anthropic','openai','httpx','pydantic','yaml','dotenv','rich','jinja2',
        'pypdf','tenacity','reportlab','fastapi','uvicorn','multipart','playwright']
bad = []
for m in mods:
    try:
        importlib.import_module(m)
    except Exception as e:
        bad.append(m + ' (' + type(e).__name__ + ')')
print('missing:', bad or 'none')
"
echo "setup done -> ./.venv/bin/python -m resume_bot doctor"
