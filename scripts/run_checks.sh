#!/bin/bash
# Runs ruff (backend + libs) and the frontend linter. See docs/TESTING.md.
set -euo pipefail
cd "$(dirname "$0")/.."
exec make lint
