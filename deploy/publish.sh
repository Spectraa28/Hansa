#!/usr/bin/env bash
# Sends the current main branch everywhere it needs to be, in one go:
#   1. Entire            the project's home, with its checkpoints
#   2. GitHub "project"  the whole project, for people to read
#   3. GitHub "main"     the frontend folder only, which Vercel builds the site from
#
#   bash deploy/publish.sh
#
# Needs a remote named "github" pointing at the GitHub repository. Does not touch the server;
# backend changes still need deploy/setup-server.sh run there.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

if [ -n "$(git status --porcelain)" ]; then echo "Commit your changes first." >&2; exit 1; fi
if [ "$(git rev-parse --abbrev-ref HEAD)" != "main" ]; then echo "Switch to main first." >&2; exit 1; fi

echo "== Entire";            git push origin main
echo "== GitHub: project";   git push github main:project
echo "== GitHub: site";      git subtree split --prefix=frontend -b frontend-only >/dev/null
                             git push github frontend-only:main
echo "Done. Vercel rebuilds the site from GitHub main within a minute or two."
