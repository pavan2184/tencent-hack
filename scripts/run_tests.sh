#!/bin/bash
# Runs the backend app + library test suites (offline, mock mode). See docs/TESTING.md.
set -euo pipefail
cd "$(dirname "$0")/.."
exec make test
