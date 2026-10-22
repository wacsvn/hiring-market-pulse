#!/usr/bin/env bash
# Fails if any tracked file matches a blocklisted pattern (e.g. names that must not be published).
# The pattern comes from $SCRUB_PATTERN (a CI secret) so the blocklist itself is never committed.
# git grep exit codes: 0 = match found, 1 = no match, >1 = error. Only 1 is a pass.
set -uo pipefail

if [[ -z "${SCRUB_PATTERN:-}" ]]; then
  echo "SCRUB_PATTERN is not set; refusing to report a pass without a pattern." >&2
  exit 2
fi

git grep -n -i -E -e "$SCRUB_PATTERN" -- .
status=$?
case $status in
  1) echo "scrub check: clean"; exit 0 ;;
  0) echo "scrub check: blocklisted text found (see above)" >&2; exit 1 ;;
  *) echo "scrub check: git grep failed with status $status" >&2; exit "$status" ;;
esac
