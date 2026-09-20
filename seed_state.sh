#!/usr/bin/env bash
# Seed the private state repo with your current database and resume.
# Usage: ./scripts_seed_state.sh /path/to/cloned/private-repo
set -euo pipefail
DEST="${1:?usage: ./scripts_seed_state.sh /path/to/private-state-repo}"
cd "$(dirname "$0")"
[ -d "$DEST/.git" ] || { echo "not a git repo: $DEST"; exit 1; }
mkdir -p "$DEST/drafts" "$DEST/resumes"
cp data/jobs.db            "$DEST/jobs.db"
cp data/master_resume.json "$DEST/master_resume.json"
cp -r output/drafts/.      "$DEST/drafts/"  2>/dev/null || true
cp -r output/resumes/.     "$DEST/resumes/" 2>/dev/null || true
cd "$DEST"
git add -A && git commit -q -m "Seed state from local run" && git push
echo "seeded: $(du -sh jobs.db | cut -f1) database, $(ls resumes | wc -l) resumes"
