#!/bin/sh
# scripts/worktree-setup.sh [--no-open] <branch> [<port-offset>]
#
# Run from the bare-repo container directory (the one holding main/ and the other
# worktrees). Creates a sibling worktree for <branch>, fully bootstrapped: .env,
# virtualenv, node_modules, git hooks, and an isolated Docker Compose project with
# shifted host ports.
#
# <port-offset> shifts the database, backend, and frontend host ports so several
# worktrees can run the full Docker stack at once. Omit it to take the smallest
# offset from 1 up that no sibling worktree's .env reserves and whose ports are all
# free; main/ keeps offset 0.
#
# The first python3 on PATH outside a virtualenv builds .venv. PYTHON_BIN, a command or
# a path, names another, which must be outside a virtualenv too.
#
# --no-open skips opening the finished worktree in VS Code, which otherwise happens when
# code is on PATH.
set -eu

# usage -> say how to call this script and stop.
usage() {
  echo "usage: worktree-setup.sh [--no-open] <branch> [<port-offset>]" >&2
  exit 1
}

open_editor=yes
if [ "${1:-}" = --no-open ]; then
  open_editor=no
  shift
fi

branch="${1:-}"
offset="${2:-}"

# --no-open anywhere else would pass as the branch or the offset. A bad offset would fail
# in the arithmetic below, after the worktree exists, and a leading zero reads as octal.
[ "$#" -le 2 ] || usage
case "$branch" in '' | -*) usage ;; esac
case "$offset" in *[!0-9]* | 0[0-9]*) usage ;; esac

# virtualenv_state PYTHON -> True inside a virtualenv, False outside, nothing when PYTHON
# does not run.
virtualenv_state() {
  "$1" -c 'import sys; print(sys.prefix != sys.base_prefix)' 2>/dev/null
}

# first_base_python -> the first python3 on PATH outside a virtualenv, or nothing. An
# active virtualenv puts its own bin first, so plain python3 would be its interpreter. A
# relative entry would stop resolving once the script moves into the worktree.
first_base_python() {
  (
    IFS=:
    for directory in $PATH; do
      case "$directory" in /*) ;; *) continue ;; esac
      if [ "$(virtualenv_state "$directory/python3")" = False ]; then
        printf '%s\n' "$directory/python3"
        exit 0
      fi
    done
  )
}

# A venv built by another venv's python records that python's versioned Homebrew Cellar
# directory as its base, and the next upgrade deletes it. Choose before anything is
# created, so a refusal leaves no worktree or branch behind.
if [ -n "${PYTHON_BIN:-}" ]; then
  python_bin=$PYTHON_BIN
  case "$python_bin" in [!/]*/*) python_bin="$PWD/$python_bin" ;; esac
  case "$(virtualenv_state "$python_bin")" in
    False) ;;
    True)
      echo "ERROR: PYTHON_BIN=$python_bin is inside a virtualenv; name a base python." >&2
      exit 1
      ;;
    *)
      echo "ERROR: PYTHON_BIN=$python_bin does not run." >&2
      exit 1
      ;;
  esac
else
  python_bin=$(first_base_python)
  if [ -z "$python_bin" ]; then
    echo 'ERROR: no python3 on PATH outside a virtualenv; set PYTHON_BIN.' >&2
    exit 1
  fi
fi

# The container directory name doubles as the Compose project prefix.
repo=$(basename "$(pwd)")

# A filesystem- and Compose-safe slug for the directory and project name.
slug=$(printf '%s' "$branch" | tr '/A-Z' '-a-z')

# Fetch so new branches fork from the current integration branch, and a freshly pushed
# remote branch is detected rather than recreated locally and divergent.
git fetch origin

# Create the worktree: track an existing origin branch, else branch off origin/staging,
# the default branch, where it exists, else origin/main. A bare clone made without a
# fetch refspec has no origin/* refs; fall back to the local main branch in that case.
if git show-ref --verify --quiet "refs/remotes/origin/$branch"; then
  git worktree add "$slug" "$branch"
elif git show-ref --verify --quiet refs/remotes/origin/staging; then
  git worktree add "$slug" -b "$branch" origin/staging
elif git show-ref --verify --quiet refs/remotes/origin/main; then
  git worktree add "$slug" -b "$branch" origin/main
else
  git worktree add "$slug" -b "$branch" main
fi

cd "$slug"

# offset_taken N -> true when a sibling worktree's .env already holds one of offset
# N's ports, or something listens on one. A stopped stack listens on nothing, and
# other projects hold ports no .env here names, so both checks are needed.
offset_taken() {
  db=$((5432 + $1)) backend=$((5000 + $1)) frontend=$((5174 + $1))
  grep -qsE "^(DB_PORT=$db|BACKEND_PORT=$backend|FRONTEND_PORT=$frontend)\$" \
    ../*/.env && return 0
  for port in "$db" "$backend" "$frontend"; do
    lsof -i TCP:"$port" -sTCP:LISTEN -n -P 2>/dev/null | grep -q LISTEN && return 0
  done
  return 1
}

# Pick the offset just before this worktree's .env is written, so setups started
# together see each other's reservations.
if [ -z "$offset" ]; then
  offset=1
  while offset_taken "$offset"; do
    offset=$((offset + 1))
  done
fi

# Secrets are not tracked; start from the main worktree's .env, else the example.
if [ -f ../main/.env ]; then
  cp ../main/.env .env
else
  cp .env.example .env
fi

# set_env KEY VALUE -> replace the KEY= line in .env, or append one.
set_env() {
  if grep -qE "^$1=" .env; then
    tmp=$(mktemp)
    sed "s|^$1=.*|$1=$2|" .env > "$tmp"
    mv "$tmp" .env
  else
    printf '%s=%s\n' "$1" "$2" >> .env
  fi
}

db_port=$((5432 + offset))
backend_port=$((5000 + offset))
frontend_port=$((5174 + offset))

# Isolate the Docker stack for this worktree.
set_env COMPOSE_PROJECT_NAME "$repo-$slug"
set_env DB_PORT "$db_port"
set_env BACKEND_PORT "$backend_port"
set_env FRONTEND_PORT "$frontend_port"
set_env VITE_API_URL "http://localhost:$backend_port"
set_env PUBLIC_BASE_URL "http://localhost:$frontend_port"
set_env DATABASE_URL "postgresql://app:app@localhost:$db_port/app"

# Backend venv (tests use in-memory SQLite, no Docker) and frontend deps.
#
# npm install runs husky's prepare script, which sets the shared core.hooksPath to
# the relative .husky/_, so it resolves inside each worktree. Do NOT enable
# extensions.worktreeConfig: with core.bare=true it makes git treat every worktree
# as bare.
echo "Building .venv with $python_bin"
"$python_bin" -m venv .venv
.venv/bin/pip install -r requirements-dev.txt

# A venv that cannot import the project is broken now, so stop here rather than hand
# back a worktree that fails later inside an editor.
if ! .venv/bin/python -c 'import src_back.app'; then
  echo "ERROR: .venv cannot import src_back.app, so $(pwd) is unfinished." >&2
  exit 1
fi

npm install

# home, not the interpreter's own path: every Homebrew python3 resolves into the Cellar
# yet reports the stable opt path, and pyvenv.cfg's executable line names the Cellar on
# a venv that survives upgrades.
case "$(grep '^home' .venv/pyvenv.cfg)" in
  */Cellar/*)
    echo 'WARNING: .venv records a versioned Homebrew Cellar path as its base, which' >&2
    echo 'the next upgrade deletes. Rebuild it with a PYTHON_BIN outside the Cellar.' >&2
    ;;
esac

# Open the worktree itself, never the container directory: only a worktree has the
# .vscode/settings.json that points the Python extension at its .venv. The worktree is
# finished by now, so a code that fails costs only the window. The ready lines stay
# last, because /plan-issue reads the ports from them.
if [ "$open_editor" = no ] || ! command -v code >/dev/null 2>&1 || ! code "$PWD"; then
  echo "Open this worktree with: code $PWD"
fi

echo "Worktree '$branch' ready at $(pwd)"
echo "  COMPOSE_PROJECT_NAME=$repo-$slug"
echo "  port offset $offset"
echo "  DB_PORT=$db_port BACKEND_PORT=$backend_port FRONTEND_PORT=$frontend_port"
