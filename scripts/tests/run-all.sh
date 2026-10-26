#!/usr/bin/env bash
# Check the syntax of every shell script in the repository with the shell its shebang
# names, then run each scripts/tests/test-*.sh. A test that cannot run on this machine,
# because it needs Linux or a tool that is missing, says why and exits 77: a skip
# locally, but a failure in CI, so CI runs every test. `npm run test:scripts` and CI
# both run this file; it runs under macOS's bash 3.2 and on Linux.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
failures=0
checked=0

# Tracked files plus new ones git does not ignore, so a script is checked before it is
# committed. The listing is captured on its own line because set -e cannot see a git
# failure inside a process substitution, which would pass as an empty list.
files=$(git ls-files --cached --others --exclude-standard)
while IFS= read -r file; do
  [ -f "$file" ] || continue
  first_line=
  IFS= read -r first_line < "$file" || true
  case $first_line in
    '#!/bin/sh'* | '#!/usr/bin/env sh'*) shell=sh ;;
    '#!/bin/bash'* | '#!/usr/bin/env bash'*) shell=bash ;;
    *)
      # Nothing says which shell checks a .sh file without a shebang.
      case $file in
        *.sh)
          echo "FAIL $file has no sh or bash shebang" >&2
          failures=$((failures + 1))
          ;;
      esac
      continue
      ;;
  esac
  checked=$((checked + 1))
  if ! "$shell" -n "$file"; then
    echo "FAIL $shell -n $file" >&2
    failures=$((failures + 1))
  fi
done <<< "$files"
echo "Checked the syntax of $checked scripts."

for test_file in scripts/tests/test-*.sh; do
  status=0
  bash "$test_file" || status=$?
  case $status in
    0) echo "PASS $test_file" ;;
    77)
      if [ "${CI:-}" = true ]; then
        echo "FAIL $test_file skipped itself, and CI runs every test" >&2
        failures=$((failures + 1))
      else
        echo "SKIP $test_file"
      fi
      ;;
    *)
      echo "FAIL $test_file exited $status" >&2
      failures=$((failures + 1))
      ;;
  esac
done

if [ "$failures" -gt 0 ]; then
  echo "$failures shell script check(s) failed." >&2
  exit 1
fi
echo 'All shell script checks passed.'
