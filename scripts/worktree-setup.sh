#!/bin/sh
# scripts/worktree-setup.sh <branch> [<port-offset>]
#
# Run from the bare-repo container directory (the one holding main/ and the other
# worktrees). Creates a sibling worktree for <branch>, fully bootstrapped: .env,
# virtualenv, node_modules, per-worktree git hooks, and an isolated Docker Compose
# project with shifted host ports.
#
# <port-offset> shifts the database, backend, and frontend host ports so several
# worktrees can run the full Docker stack at once. Use a distinct integer per
# worktree (0, 1, 2, ...).
set -eu

branch="${1:-}"
offset="${2:-0}"

if [ -z "$branch" ]; then
  echo "usage: worktree-setup.sh <branch> [<port-offset>]" >&2
  exit 1
fi

# The container directory name doubles as the Compose project prefix.
repo=$(basename "$(pwd)")

# A filesystem- and Compose-safe slug for the directory and project name.
slug=$(printf '%s' "$branch" | tr '/A-Z' '-a-z')

# Fetch so new branches fork from current origin/main and a freshly pushed
# remote branch is detected rather than recreated locally and divergent.
git fetch origin

# Create the worktree: track an existing origin branch, else branch off main.
# A bare clone made without a fetch refspec has no origin/* refs; fall back to
# the local main branch in that case.
if git show-ref --verify --quiet "refs/remotes/origin/$branch"; then
  git worktree add "$slug" "$branch"
elif git show-ref --verify --quiet refs/remotes/origin/main; then
  git worktree add "$slug" -b "$branch" origin/main
else
  git worktree add "$slug" -b "$branch" main
fi

cd "$slug"

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
set_env DATABASE_URL "postgresql://app:app@localhost:$db_port/app"

# Backend venv (tests use in-memory SQLite, no Docker) and frontend deps.
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
npm install

# Hooks: point core.hooksPath at the tracked, relative .husky so it resolves per
# worktree. husky keeps this value relative across npm installs, so a shared
# (common-config) setting works for every worktree. Do NOT enable
# extensions.worktreeConfig: with core.bare=true it makes git treat every
# worktree as bare. Set last so the npm install above cannot leave a stale value.
git config core.hooksPath .husky

echo "Worktree '$branch' ready at $(pwd)"
echo "  COMPOSE_PROJECT_NAME=$repo-$slug"
echo "  DB_PORT=$db_port BACKEND_PORT=$backend_port FRONTEND_PORT=$frontend_port"
