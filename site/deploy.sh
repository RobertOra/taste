#!/bin/bash
# Publish site/static to RobertOra/taste-test (private repo; GitHub Pages needs GitHub Pro for private repos).
# Uses a separate git history in data/_deploy.git so the website repo never mixes with the research repo.
set -eo pipefail
cd "$(dirname "$0")/.."
python3 -I site/stamp.py   # version every file reference: no new page with older cached files
export GIT_DIR="$PWD/data/_deploy.git" GIT_WORK_TREE="$PWD/site/static"
git add -A
git -c user.name="RobertOra" -c user.email="robu.ora@gmail.com" commit -qm "${1:-Update site}" || echo "nothing to commit"
git push origin main
