#!/bin/sh
# scripts/worktree-doctor.sh
#
# Report whether this worktree's environment works, as `npm run doctor`. Run it from a
# worktree root. A fatal finding (FAIL) makes it exit 1, so it also works as a gate; a
# warning (warn) leaves a worktree that runs today.
set -eu

status=0

pass() { printf 'ok    %s\n' "$1"; }
warn() { printf 'warn  %s\n' "$1" >&2; }
fail() {
  printf 'FAIL  %s\n' "$1" >&2
  status=1
}

# rebuild_hint -> how to replace this worktree's venv.
rebuild_hint() {
  echo '      rebuild it from a shell with no virtualenv active:' >&2
  echo '        rm -rf .venv && python3 -m venv .venv' >&2
  echo '        .venv/bin/pip install -r requirements-dev.txt' >&2
}

# Run the interpreter rather than test the file: a venv whose base was deleted keeps a
# dangling link in its bin.
if version=$(.venv/bin/python --version 2>&1); then
  pass "interpreter runs ($version)"
  if import_error=$(.venv/bin/python -c 'import src_back.app' 2>&1); then
    pass 'the project imports'
  else
    fail 'the project does not import'
    printf '%s\n' "$import_error" | tail -n 1 | sed 's/^/      /' >&2
    echo '      install with: .venv/bin/pip install -r requirements-dev.txt' >&2
  fi
else
  fail 'no working interpreter at .venv/bin/python'
  rebuild_hint
fi

# home alone: pyvenv.cfg's executable line names the Cellar even on a venv that survives
# upgrades. This runs after a dead interpreter too, because it is often the reason, and
# a missing file means no venv, which the check above already failed.
case "$(grep '^home' .venv/pyvenv.cfg 2>/dev/null)" in
  '') ;;
  */Cellar/*)
    warn 'venv base is a versioned Homebrew Cellar path'
    echo '      an upgrade deletes that directory, and the interpreter may go too;' >&2
    rebuild_hint
    ;;
  *) pass 'venv base survives Homebrew upgrades' ;;
esac

# Only a worktree root holds the file that points the Python extension at .venv, so its
# absence means this is the container directory.
if [ -f .vscode/settings.json ]; then
  pass 'VS Code reads .vscode/settings.json here'
else
  warn 'no .vscode/settings.json here; open a worktree root, not the container'
fi

if [ -d node_modules ]; then
  pass 'node_modules is present'
else
  warn 'no node_modules; run npm install'
fi

printf '\ninterpreter for VS Code (Python: Select Interpreter):\n  %s\n' \
  "$PWD/.venv/bin/python"

exit "$status"
