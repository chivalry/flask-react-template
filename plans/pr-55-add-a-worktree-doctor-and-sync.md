# Issue #21: Add a Worktree Doctor and Sync Devcontainer Extensions

## Context

`scripts/worktree-setup.sh` builds `.venv` with whatever `python3` comes first on `PATH`
and never checks the result. On this machine that is routinely a virtualenv's python: the
session that wrote this plan ran with `VIRTUAL_ENV` set and the repository's `.venv/bin`
first on `PATH`, and that interpreter's `sys._base_executable` is a versioned Cellar
path. `~/Projects/employment/resume/.venv/pyvenv.cfg` records such a base: its `home`
names `3.13.13`, which Homebrew has deleted, and the venv survives only because its
`bin/python3.13` links to the stable `opt` path. This change adds an interpreter guard, an
import smoke test, `--no-open`, `npm run doctor`, and a `postAttachCommand` that installs
`.vscode/extensions.json` in the dev container. It also fixes the dev container itself,
which no longer builds (Context point 7).

No backend or frontend code changes. All of it is shell, one `package.json` line, two
`devcontainer.json` changes, and documentation.

### Where the references and the issue are wrong

Each of these was checked while planning, and each changes what gets ported.

1. **Ranch-tracker's installer cannot work in a local dev container.** Dev Containers
   0.469.0 runs `postAttachCommand` as `docker exec ... /bin/sh -c '<command>'`
   (`spec-node/devContainersSpecCLI.js`), outside any VS Code terminal, so VS Code's
   remote `code` is not on `PATH` and `VSCODE_IPC_HOOK_CLI` is unset. `command -v code`
   still succeeds, because the image's `common-utils` feature ships a
   `/usr/local/bin/code` shim, but that shim exits 127 with
   `code or code-insiders is not installed`, which ends ranch-tracker's script at its
   first install. Its other paths, `.vscode-remote` and `/vscode/bin`, come from a
   Codespaces fix (`3c95a1c`) and do not match the server at
   `~/.vscode-server/bin/<commit>/bin/code-server` either. This comes from reading the
   extension's bundles and the published image, not from a live container, so Step 6 of
   Verification attaches a real one.
2. **Even the real `code` would mislead.** Without a terminal's IPC socket, VS Code's
   remote `code` prints a notice and exits 0 (`src/vs/server/node/server.cli.ts`), which
   would store a marker with nothing installed. `code-server` reports failure honestly: it
   carries on past a failed id and exits 1 at the end
   (`extensionManagementCLI.ts`, `remoteExtensionHostAgentCli.ts`).
3. **Ranch-tracker's pipe hides a parser failure.** `python3 ... | while read` takes the
   loop's status, so a file that does not parse installs nothing and still stores the
   marker. This plan captures the output first.
4. **The issue's premise is half right.** It says nothing installs the recommendations in
   the container. `customizations.vscode.extensions` installs 21 of the 23, once, when a
   container first starts. The sync adds `vitest.explorer`, and a later recommendation
   reaches the container with no second edit. Both lists remain, so they can still differ;
   the other missing id is host-only (decision 3).
5. **The interpreter guard must run before `git`.** Ranch-tracker's runs after
   `git worktree add`, which leaves a worktree behind on refusal. The first acceptance
   criterion is written to run from a repository root, where anything but an early
   refusal would create a worktree named `x`.
6. **A Cellar check on the interpreter's path would warn on every Homebrew Mac.**
   `/opt/homebrew/bin/python3.13` is a symlink into the Cellar, yet Homebrew reports every
   base interpreter's `sys._base_executable` as the stable
   `/opt/homebrew/opt/python@3.13/bin/python3.13`, even when the Cellar's framework binary
   is called directly. This repository's own `.venv/pyvenv.cfg` has
   `home = /opt/homebrew/opt/python@3.13/bin` beside an `executable` line naming a Cellar
   version that no longer exists, and it works. So both scripts read the `home` line
   alone. Only a venv built from a venv gets a Cellar `home`, which the guard prevents,
   so the setup warning is a backstop; the doctor's warning is what finds older venvs.
7. **The dev container does not build today.** The image
   `mcr.microsoft.com/devcontainers/python:3.12` moved to Debian trixie: its
   `dev.containers.variant` label reads `3.12-trixie`, built 2026-10-28.
   `docker-in-docker:2` defaults `moby` to true, and its `install.sh` refuses that on
   trixie with `exit 1`. Ranch-tracker hit this in `7955385 fix moby error`. This machine
   holds no dev container image or `vscode` volume, so nothing here has built the
   configuration lately, and the third acceptance criterion cannot pass without
   `"moby": false`.

### Decisions

Chuck chose 1, 2, and 3 on 2026-10-31. Each departs from the issue or from ranch-tracker
on purpose, so do not restore the original wording.

1. **An active virtualenv is looked past, not refused.** With `PYTHON_BIN` unset, the
   script takes the first `python3` on `PATH` outside a virtualenv and prints which. The
   issue says to refuse. Refusing would stop every agent-run setup in a session like this
   one, because `/plan-issue` and `/plan-pr` run the script unattended. An explicit
   `PYTHON_BIN` inside a virtualenv is still refused by name, which is the acceptance
   criterion, and so is a `PATH` with no base `python3`.
2. **Local dev containers on VS Code Stable only.** The script looks under
   `~/.vscode-server`, the layout the extension's source establishes. Ranch-tracker's
   Codespaces paths are not ported, because nothing here can verify them and they need a
   different `--server-data-dir`. In a Codespace, or under Insiders, which keeps its own
   `.vscode-server-insiders` tree, the script says it found no server and exits 0, and
   `customizations.vscode.extensions` still works.
3. **`ms-vscode-remote.*` ids are skipped.** `.vscode/extensions.json` recommends
   `ms-vscode-remote.remote-containers`, whose `extensionKind` is `ui`, for the host.
   `customizations.vscode.extensions` already leaves it out. VS Code's remote CLI refuses
   to install such an extension, but `code-server` uses the base CLI class, whose
   `validateExtensionKind` returns true, so without the filter it would land in the
   container, where it cannot run.
4. **`customizations.vscode.extensions` stays, and the marker waits for proof.** The list
   gets the editor working on first attach, it is what a Codespace falls back on, and
   removing it is not in the issue. It can overlap the script, though. The server starts
   installing the list as it starts listening, and on a rebuild `postCreateCommand`
   finishes quickly because `.venv` and `node_modules` survive on the bind mount.
   `extensions.json` is read-modify-write under an in-process queue only, so two processes
   can lose each other's entry while `code-server` exits 0. This timing is reasoned, not
   measured. So the script runs `--list-extensions` after installing and writes the marker
   only when every id is listed; otherwise it exits 1 and the next attach finishes it.
   Listing runs in a new process, well after the script's last write has settled.
5. **The doctor reports everything.** Ranch-tracker's stops at a dead interpreter. This
   one continues, because the Cellar line often explains the dead interpreter and the
   other checks do not depend on it.
6. **The doctor reads the current directory, as ranch-tracker's does.** `npm run doctor`
   always runs from a worktree root, where the `.vscode/settings.json` warning fires only
   if that file was deleted. It is for `sh main/scripts/worktree-doctor.sh` run from the
   container directory, which a `cd` to the script's own directory would hide. The
   installer also trusts its working directory, because the spec runs every lifecycle
   command from the workspace folder.
7. **The ready lines stay last.** `/plan-issue` reads the host ports from the script's
   last lines, so VS Code opens before them.
8. **A failing `code` does not fail setup.** The worktree is finished by then, so the
   script prints how to open it instead.
9. **Bad input stops before `git`.** `--no-open` anywhere but first would otherwise pass
   as the branch or the offset. A non-numeric offset, or one like `08` that the shell
   reads as octal, fails only in arithmetic after the worktree exists. A relative path
   or `PATH` entry would stop resolving once the script moves into the worktree, so
   `PYTHON_BIN` is resolved with `command -v` and made absolute before anything checks
   or uses it, and the search for a base `python3` skips relative entries. PR #55's
   review found the bare-command case, which `command -v` alone does not settle: `dash`
   answers relative to a relative entry and with the bare name for an empty one. A name
   `command -v` cannot find stays as given, so the refusal quotes it and nothing looks
   for it in the current directory.
10. **The skills do not change.** `~/.ai/commands/plan-issue.md` and `plan-pr.md` get the
    new interpreter choice for free. They omit `--no-open`, so a new worktree opens in
    VS Code, which is where the implementation session runs, as ranch-tracker does today.
11. **`.vscode/extensions.json` stays strict JSON.** VS Code tolerates comments there and
    `json.loads` does not, so a comment stops the script with a `JSONDecodeError` on every
    attach, visibly and without a marker. The file is strict today, and stripping
    full-line comments would still fail on trailing commas and block comments.
12. **`docker-in-docker` gets `"moby": false`.** The issue does not mention it, but its
    third criterion cannot pass without it (Context point 7).
13. **Guards added after implementation.** Mutation checks left real gaps, so on
    2026-10-31 Chuck added eight beyond the first draft of these tests: `unset PYTHON_BIN`
    at the top of the setup test, which otherwise fails when a developer has it exported;
    a bare-command and an empty `PYTHON_BIN` case; `008` in place of `08`; a quiet
    missing-`.venv` case in the doctor test; a second `ms-vscode-remote.*` id; a three-id
    lost-id case with a longer id listed; and a stub that lists only what an install
    left. The tests below are the final ones.

## Branch

`issue-21-add-a-worktree-doctor-and-sync` — already checked out; PR #55 exists. This is
a single checkout, not a worktree layout.

## Change

**7 files to edit**: `scripts/worktree-setup.sh`, `scripts/tests/test-worktree-setup.sh`,
`package.json`, `.devcontainer/devcontainer.json`, `README.md`, `ai/project.md`,
`tools.md`.

**4 files to create**: `scripts/worktree-doctor.sh`,
`.devcontainer/install-vscode-extensions.sh` (both mode 755),
`scripts/tests/test-worktree-doctor.sh`, and
`scripts/tests/test-install-vscode-extensions.sh` (both mode 644, like every test).

Shell scripts here use 2-space indentation, whatever `.editorconfig` says, to match the
surrounding files. Keep every line within 90 characters.

### scripts/worktree-setup.sh — guard the interpreter, smoke-test the venv, open VS Code

Replace lines 1 to 21 with this. Everything from `# The container directory name doubles
as the Compose project prefix.` through `set_env DATABASE_URL` stays as it is.

```sh
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
  # Resolve it now: a relative path or PATH entry stops resolving once the script moves
  # into the worktree. dash's command -v keeps such a path relative, and answers with the
  # bare name for an empty PATH entry. A name it cannot find stays as given, for the
  # refusal below.
  if python_bin=$(command -v "$PYTHON_BIN"); then
    case "$python_bin" in /*) ;; *) python_bin="$PWD/$python_bin" ;; esac
  else
    python_bin=$PYTHON_BIN
  fi
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
```

Replace lines 101 to 114, the `# Backend venv` comment through the last `echo`, with:

```sh
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
```

### scripts/worktree-doctor.sh — new

```sh
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
```

### package.json — add the script

After the `"prepare": "husky",` line (line 23):

```json
    "doctor": "sh scripts/worktree-doctor.sh",
```

### .devcontainer/install-vscode-extensions.sh — new

```sh
#!/bin/sh
# .devcontainer/install-vscode-extensions.sh
#
# The dev container's postAttachCommand, which runs from the workspace folder. It installs
# the recommendations in .vscode/extensions.json, which customizations.vscode.extensions
# in devcontainer.json only partly repeats, and which VS Code installs only when a
# container first starts. A marker records the sha256 of the file it last installed, so
# an attach installs nothing until that file changes. A failed install writes no marker,
# so the next attach retries.
#
# postAttachCommand runs through docker exec, outside any VS Code terminal, where no code
# command works: the image's /usr/local/bin/code is a shim that exits 127, and VS Code's
# remote code needs a terminal's IPC socket. So this calls the server itself.
set -eu

recommendations=.vscode/extensions.json
server_dir="$HOME/.vscode-server"
marker="$server_dir/data/Machine/.recommended-extensions.sha256"

# find_code_server -> the newest code-server, since a VS Code update leaves the old one.
find_code_server() {
  ls -t "$server_dir"/bin/*/bin/code-server 2>/dev/null | head -n 1
}

# read_recommendations -> the file's sha256, then one extension id per line. The remote
# development extensions run on the host and have nothing to do in a container.
read_recommendations() {
  python3 - "$recommendations" <<'PYTHON'
import hashlib
import json
import sys

with open(sys.argv[1], 'rb') as handle:
    content = handle.read()
print(hashlib.sha256(content).hexdigest())
for extension in json.loads(content).get('recommendations', []):
    if not extension.startswith('ms-vscode-remote.'):
        print(extension)
PYTHON
}

if [ ! -f "$recommendations" ]; then
  echo "No $recommendations, so no extensions to install."
  exit 0
fi

code_server=$(find_code_server)
if [ -z "$code_server" ]; then
  echo "No VS Code server under $server_dir, so no extensions installed."
  exit 0
fi

# Captured rather than piped, so a file that does not parse stops the script here.
parsed=$(read_recommendations)
sha=$(printf '%s\n' "$parsed" | head -n 1)
if [ -f "$marker" ] && [ "$(cat "$marker")" = "$sha" ]; then
  exit 0
fi

extensions=$(printf '%s\n' "$parsed" | tail -n +2)
set --
for extension in $extensions; do
  set -- "$@" --install-extension "$extension"
done

# One call: code-server carries on past an id it cannot install and exits 1 at the end,
# which stops this script before the marker. Given no id it would start a server.
if [ "$#" -gt 0 ]; then
  "$code_server" --server-data-dir "$server_dir" "$@"

  # On a rebuild the server can still be installing devcontainer.json's list, and two
  # processes can lose each other's write to extensions.json while both exit 0. So the
  # marker waits until the server lists every id; the next attach installs any it lost.
  installed=$("$code_server" --server-data-dir "$server_dir" --list-extensions)
  for extension in $extensions; do
    if ! printf '%s\n' "$installed" | grep -Fqxi -- "$extension"; then
      echo "ERROR: $extension is not installed; the next attach tries again." >&2
      exit 1
    fi
  done
fi

mkdir -p "${marker%/*}"
printf '%s\n' "$sha" > "$marker"
```

### .devcontainer/devcontainer.json — build on trixie, and run the script on attach

Replace line 8 with this (Context point 7):

```json
    "ghcr.io/devcontainers/features/docker-in-docker:2": {
      "moby": false
    }
```

Add a comma to the end of line 60, the `postCreateCommand`, and add this line after it. A
string runs in `/bin/sh` from the workspace folder, and `sh` keeps it independent of the
file's mode, which ranch-tracker had to fix by hand in `7955385`.

```json
  "postAttachCommand": "sh .devcontainer/install-vscode-extensions.sh"
```

### scripts/tests/test-worktree-setup.sh — cover the new branches

The first block replaces lines 1 to 20, and adds a real interpreter, because a stub could
only repeat what the test expects of the virtualenv check.

```bash
#!/usr/bin/env bash
# Exercise scripts/worktree-setup.sh with real git: bare-repo containers cloned from
# local origins, set up as README's Worktrees section describes, and stub python3, npm,
# and code commands. It checks which commit a new worktree starts from (origin/staging
# when the origin has that branch, origin/main when it has only main, and an existing
# origin branch as it is), the branch the worktree is on, and the isolated .env it gets;
# then the arguments it refuses, the interpreter that builds the venv, the import smoke
# test, the Cellar warning, and opening VS Code. It runs the script with sh, as README
# does, and exits 77 without git or python3. It runs under macOS's bash 3.2 and on Linux
# in CI, so the test avoids bash 4 features.
set -euo pipefail
# A value exported in a developer's shell would choose the interpreter for every case.
unset PYTHON_BIN
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
command -v git > /dev/null ||
  { echo 'test-worktree-setup.sh needs git.' >&2; exit 77; }
command -v python3 > /dev/null ||
  { echo 'test-worktree-setup.sh needs python3.' >&2; exit 77; }
# A developer's active virtualenv makes python3 its own interpreter, so take the base
# behind it. The virtualenv check runs on this, not on a stub, and real-venv is one it
# must refuse.
BASE_PYTHON=$(python3 -c 'import sys; print(sys._base_executable)')
SH=$(command -v sh)
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT
mkdir -p "$TEST_DIR/bin" "$TEST_DIR/editor-bin" "$TEST_DIR/elsewhere" "$TEST_DIR/tools"
export TEST_DIR BASE_PYTHON
export PATH="$TEST_DIR/editor-bin:$TEST_DIR/bin:$PATH"
"$BASE_PYTHON" -m venv --without-pip "$TEST_DIR/real-venv"
COMMANDS="$TEST_DIR/commands"
OUTPUT="$TEST_DIR/output"
FETCH_REFSPEC='+refs/heads/*:refs/remotes/origin/*'
```

Keep the git configuration block (lines 22 to 30). Replace lines 32 to 40, the helpers,
with:

```bash
# A bare `! grep` never fails under set -e, so both checks exit explicitly.
assert_contains() {
  grep -Eq -- "$1" "$2" || { echo "Missing /$1/ in ${2##*/}" >&2; exit 1; }
}

refute_contains() {
  if grep -Eq -- "$1" "$2"; then echo "Unexpected /$1/ in ${2##*/}" >&2; exit 1; fi
}

# expect_calls LINE... -> the stubs ran exactly these lines, in this order.
expect_calls() {
  printf '%s\n' "$@" | diff -u - "$COMMANDS"
}
```

Replace lines 42 to 67, the mock and its shadow check, with:

```bash
# python3 answers -c on the real base interpreter, unlogged. Otherwise it accepts only
# `-m venv .venv`, which makes a .venv/bin holding a pip and a python that are this stub
# as well, and a pyvenv.cfg whose home is $TEST_DIR/venv-home. python fails while
# $TEST_DIR/import-fails exists, code prints a line and fails while $TEST_DIR/code-fails
# exists, and pip and npm only log. Each logs its call to $TEST_DIR/commands.
cat > "$TEST_DIR/bin/mock-command" <<'MOCK'
#!/usr/bin/env bash
set -eu
name=${0##*/}
case "$name ${1:-}" in
  'python3 -c' | 'python3.12 -c') exec "$BASE_PYTHON" "$@" ;;
esac
printf '%s\n' "$name $*" >> "$TEST_DIR/commands"
case "$name" in
  python3 | python3.12)
    [ "$*" = '-m venv .venv' ] || { echo "Unexpected $name call: $*" >&2; exit 1; }
    mkdir -p .venv/bin
    ln -s "$TEST_DIR/bin/mock-command" .venv/bin/pip
    ln -s "$TEST_DIR/bin/mock-command" .venv/bin/python
    {
      printf 'home = %s\n' "$(cat "$TEST_DIR/venv-home")"
      echo 'executable = /opt/homebrew/Cellar/python@3.13/3.13.18/bin/python3.13'
    } > .venv/pyvenv.cfg
    ;;
  python) [ ! -f "$TEST_DIR/import-fails" ] ;;
  code)
    echo 'VS Code opened'
    [ ! -f "$TEST_DIR/code-fails" ]
    ;;
  pip | npm) ;;
  *) echo "Unexpected mock command: $name" >&2; exit 1 ;;
esac
MOCK
chmod +x "$TEST_DIR/bin/mock-command"
ln -s mock-command "$TEST_DIR/bin/python3"
ln -s mock-command "$TEST_DIR/bin/npm"
ln -s ../bin/mock-command "$TEST_DIR/editor-bin/code"
ln -s "$TEST_DIR/bin/mock-command" "$TEST_DIR/elsewhere/python3.12"
# A stub that did not come first on PATH would let the script build a real virtualenv,
# install real packages, or open a real window. Every case passes an explicit port
# offset, so the script never calls lsof.
for stub in bin/python3 bin/npm editor-bin/code; do
  [ "$(command -v "${stub##*/}")" = "$TEST_DIR/$stub" ] ||
    { echo "The ${stub##*/} stub does not shadow the real command." >&2; exit 1; }
done
# Every command the script and the stubs need, and no code, for a machine without one.
for command in basename bash cat cp git grep ln mkdir mktemp mv sed sh tr; do
  ln -s "$(command -v "$command")" "$TEST_DIR/tools/$command"
done
# Each venv starts as a Homebrew python's: home on the stable opt path, while the
# executable line the stub writes names the Cellar regardless.
OPT_HOME=/opt/homebrew/opt/python@3.13/bin
CELLAR_HOME=/opt/homebrew/Cellar/python@3.13/3.13.18/bin
printf '%s\n' "$OPT_HOME" > "$TEST_DIR/venv-home"
```

Keep the seed, origin, and `make_container` blocks and the `cp` of the script (lines 69
to 106). Replace lines 108 to 116, `run_worktree_setup`, with:

```bash
# run_setup CONTAINER ARGUMENT... -> run the copy of worktree-setup.sh from the container
# directory, as README does, with a fresh command log and SETUP_PATH, when it is set, as
# its PATH. The status is the script's.
run_setup() {
  local container=$1
  shift
  : > "$COMMANDS"
  (cd "$TEST_DIR/$container" && PATH="${SETUP_PATH:-$PATH}" "$SH" \
    "$TEST_DIR/worktree-setup.sh" "$@") > "$OUTPUT" 2>&1
}

# run_worktree_setup CONTAINER ARGUMENT... -> the run must succeed; show its output if
# it fails.
run_worktree_setup() {
  run_setup "$@" ||
    { echo "worktree-setup.sh ${*:2} failed in $1. Its output:" >&2
      cat "$OUTPUT" >&2; exit 1; }
}

# expect_refused MESSAGE CONTAINER ARGUMENT... -> the run must exit 1 and print MESSAGE.
expect_refused() {
  local message=$1 status=0
  shift
  run_setup "$@" || status=$?
  [ "$status" -eq 1 ] ||
    { echo "worktree-setup.sh ${*:2} exited $status. Its output:" >&2
      cat "$OUTPUT" >&2; exit 1; }
  assert_contains "$message" "$OUTPUT"
}

# assert_nothing_created CONTAINER BRANCH -> a refused run left no worktree or branch and
# ran no stub.
assert_nothing_created() {
  [ ! -e "$TEST_DIR/$1/$2" ] || { echo "Worktree $2 exists." >&2; exit 1; }
  if git -C "$TEST_DIR/$1" show-ref --verify --quiet "refs/heads/$2"; then
    echo "Branch $2 exists." >&2
    exit 1
  fi
  [ ! -s "$COMMANDS" ] || { echo 'The refused run called a stub.' >&2; exit 1; }
}

# assert_ports_last -> the ready lines end the output, because /plan-issue reads them.
assert_ports_last() {
  tail -n 1 "$OUTPUT" | grep -Eq '^  DB_PORT=[0-9]+ ' ||
    { echo 'The ports are not the last line of the output.' >&2; exit 1; }
}
```

Keep `assert_worktree_state` (lines 118 to 128). Replace lines 130 to 153, the cases,
with:

```bash
# With a staging branch on the origin, a new branch forks from origin/staging, the
# default branch, not from main. The worktree's .env takes the project name from the
# container and the three ports from the offset, and the venv is built and its import
# checked before the packages are installed. --no-open leaves VS Code closed, and an opt
# home draws no warning, though the Cellar appears elsewhere in pyvenv.cfg.
run_worktree_setup container-a --no-open issue-1-new 3
assert_worktree_state container-a issue-1-new staging
ENV_FILE="$TEST_DIR/container-a/issue-1-new/.env"
assert_contains '^COMPOSE_PROJECT_NAME=container-a-issue-1-new$' "$ENV_FILE"
assert_contains '^DB_PORT=5435$' "$ENV_FILE"
assert_contains '^BACKEND_PORT=5003$' "$ENV_FILE"
assert_contains '^FRONTEND_PORT=5177$' "$ENV_FILE"
assert_contains '^PUBLIC_BASE_URL=http://localhost:5177$' "$ENV_FILE"
expect_calls 'python3 -m venv .venv' 'pip install -r requirements-dev.txt' \
  'python -c import src_back.app' 'npm install'
assert_contains "^Building .venv with $TEST_DIR/bin/python3$" "$OUTPUT"
assert_contains "^Open this worktree with: code $TEST_DIR/.*/issue-1-new$" "$OUTPUT"
refute_contains 'WARNING' "$OUTPUT"
assert_ports_last

# A branch that already exists on the origin is checked out as it is, not forked again
# from staging. Without --no-open the finished worktree opens in VS Code, after every
# other step and before the ready lines, which stay last because /plan-issue reads the
# ports from them.
run_worktree_setup container-a issue-2-existing 4
assert_worktree_state container-a issue-2-existing issue-2-existing
expect_calls 'python3 -m venv .venv' 'pip install -r requirements-dev.txt' \
  'python -c import src_back.app' 'npm install' \
  "code $TEST_DIR/container-a/issue-2-existing"
refute_contains '^Open this worktree' "$OUTPUT"
assert_contains '^  DB_PORT=5436 BACKEND_PORT=5004 FRONTEND_PORT=5178$' "$OUTPUT"
assert_ports_last

# An origin with no staging branch still gets origin/main as the base.
run_worktree_setup container-b --no-open issue-1-new 3
assert_worktree_state container-b issue-1-new main

# Arguments the script cannot use are refused before git runs, including --no-open
# anywhere it would pass as the branch or the offset, and an offset with a leading zero,
# which the shell would read as octal. Offset 0 itself is fine.
expect_refused '^usage: ' container-a
expect_refused '^usage: ' container-a --no-open
expect_refused '^usage: ' container-a -x 3
expect_refused '^usage: ' container-a issue-3-usage --no-open
expect_refused '^usage: ' container-a issue-3-usage 5 --no-open
expect_refused '^usage: ' container-a issue-3-usage five
expect_refused '^usage: ' container-a issue-3-usage 5x
expect_refused '^usage: ' container-a issue-3-usage 008
assert_nothing_created container-a issue-3-usage
run_worktree_setup container-b --no-open issue-3-offset-zero 0
assert_contains '^DB_PORT=5432$' "$TEST_DIR/container-b/issue-3-offset-zero/.env"
# Outside a repository a fetch would exit 128, so this proves git has not run.
expect_refused '^usage: ' elsewhere issue-3-usage five

# A PYTHON_BIN inside a real virtualenv is refused by name before anything is created,
# and so is one that does not run.
export PYTHON_BIN="$TEST_DIR/real-venv/bin/python"
expect_refused "^ERROR: PYTHON_BIN=$PYTHON_BIN is inside a virtualenv" \
  container-a issue-4-refused 5
assert_nothing_created container-a issue-4-refused
export PYTHON_BIN="$TEST_DIR/missing/python3"
expect_refused "^ERROR: PYTHON_BIN=$PYTHON_BIN does not run" \
  container-a issue-4-refused 5
assert_nothing_created container-a issue-4-refused
export PYTHON_BIN=python3.99
expect_refused '^ERROR: PYTHON_BIN=python3\.99 does not run' \
  container-a issue-4-refused 5
assert_nothing_created container-a issue-4-refused

# A base PYTHON_BIN builds the venv in place of python3.
export PYTHON_BIN="$TEST_DIR/elsewhere/python3.12"
run_worktree_setup container-a --no-open issue-5-python-bin 5
assert_contains '^python3\.12 -m venv \.venv$' "$COMMANDS"
refute_contains '^python3 ' "$COMMANDS"

# A relative one still works once the script has moved into the worktree, and so does a
# bare command, even through a relative PATH entry or an empty one, which means the
# directory the script started in. An empty PYTHON_BIN counts as unset.
export PYTHON_BIN=../elsewhere/python3.12
run_worktree_setup container-a --no-open issue-5-relative-python-bin 12
assert_contains '^python3\.12 -m venv \.venv$' "$COMMANDS"
export PYTHON_BIN=python3.12
SETUP_PATH="$TEST_DIR/elsewhere:$PATH"
run_worktree_setup container-a --no-open issue-5-command-python-bin 14
assert_contains '^python3\.12 -m venv \.venv$' "$COMMANDS"
SETUP_PATH="../elsewhere:$PATH"
run_worktree_setup container-a --no-open issue-5-command-relative-entry 16
assert_contains '^python3\.12 -m venv \.venv$' "$COMMANDS"
ln -s "$TEST_DIR/bin/mock-command" "$TEST_DIR/container-a/python3.12"
SETUP_PATH=":$PATH"
run_worktree_setup container-a --no-open issue-5-command-empty-entry 17
assert_contains '^python3\.12 -m venv \.venv$' "$COMMANDS"
rm "$TEST_DIR/container-a/python3.12"
unset SETUP_PATH
export PYTHON_BIN=
run_worktree_setup container-a --no-open issue-5-empty-python-bin 15
assert_contains '^python3 -m venv \.venv$' "$COMMANDS"
unset PYTHON_BIN

# An active virtualenv comes first on PATH, and the script looks past it to the stub. It
# skips a relative PATH entry, which would stop resolving in the worktree. On a PATH of
# nothing but virtualenvs it refuses, and this PATH has no git to get further.
SETUP_PATH="$TEST_DIR/real-venv/bin:$PATH"
run_worktree_setup container-a --no-open issue-6-active-venv 6
assert_contains '^python3 -m venv \.venv$' "$COMMANDS"
SETUP_PATH="../bin:$PATH"
run_worktree_setup container-a --no-open issue-6-relative-path 13
assert_contains "^Building .venv with $TEST_DIR/bin/python3$" "$OUTPUT"
SETUP_PATH="$TEST_DIR/real-venv/bin"
expect_refused '^ERROR: no python3 on PATH outside a virtualenv' \
  container-a issue-7-no-base 7
assert_nothing_created container-a issue-7-no-base
unset SETUP_PATH

# A venv that cannot import the project stops the setup before npm install.
touch "$TEST_DIR/import-fails"
expect_refused '^ERROR: \.venv cannot import src_back\.app' \
  container-a --no-open issue-8-broken-venv 8
expect_calls 'python3 -m venv .venv' 'pip install -r requirements-dev.txt' \
  'python -c import src_back.app'
rm "$TEST_DIR/import-fails"

# A venv whose home is a Cellar path warns and still finishes.
printf '%s\n' "$CELLAR_HOME" > "$TEST_DIR/venv-home"
run_worktree_setup container-a --no-open issue-9-cellar-home 9
assert_contains '^WARNING: \.venv records a versioned Homebrew Cellar path' "$OUTPUT"
printf '%s\n' "$OPT_HOME" > "$TEST_DIR/venv-home"

# On a PATH with no code command, the script says how to open the worktree.
SETUP_PATH="$TEST_DIR/tools:$TEST_DIR/bin"
run_worktree_setup container-a issue-10-no-code 10
unset SETUP_PATH
assert_contains '^Open this worktree with: code .*/issue-10-no-code$' "$OUTPUT"
refute_contains '^code ' "$COMMANDS"
assert_ports_last

# A code command that fails costs the window, not the finished setup.
touch "$TEST_DIR/code-fails"
run_worktree_setup container-a issue-11-code-fails 11
assert_contains '^code ' "$COMMANDS"
assert_contains '^Open this worktree with: code .*/issue-11-code-fails$' "$OUTPUT"
assert_ports_last
rm "$TEST_DIR/code-fails"

echo 'worktree-setup.sh regression checks passed.'
```

### scripts/tests/test-worktree-doctor.sh — new

```bash
#!/usr/bin/env bash
# Exercise scripts/worktree-doctor.sh against a disposable worktree with a stub
# .venv/bin/python: a healthy worktree, each fatal finding, each warning, and a fatal
# finding that still lets the other checks report. It runs the script with sh, as npm
# does, under macOS's bash 3.2 and on Linux in CI, so it avoids bash 4 features.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT
export TEST_DIR
WORKTREE="$TEST_DIR/worktree"
COMMANDS="$TEST_DIR/commands"
OUTPUT="$TEST_DIR/output"
MOCK_PYTHON="$TEST_DIR/mock-python"
OPT_HOME=/opt/homebrew/opt/python@3.13/bin
CELLAR_HOME=/opt/homebrew/Cellar/python@3.13/3.13.18/bin

# python logs each call to $TEST_DIR/commands, answers --version, and fails the import
# with a traceback while $TEST_DIR/import-fails exists.
cat > "$MOCK_PYTHON" <<'MOCK'
#!/usr/bin/env bash
set -eu
printf 'python %s\n' "$*" >> "$TEST_DIR/commands"
case "$1" in
  --version) echo 'Python 3.12.7' ;;
  -c)
    if [ -f "$TEST_DIR/import-fails" ]; then
      echo 'Traceback (most recent call last):' >&2
      echo "ModuleNotFoundError: No module named 'flask'" >&2
      exit 1
    fi
    ;;
  *) echo "Unexpected python call: $*" >&2; exit 1 ;;
esac
MOCK
chmod +x "$MOCK_PYTHON"

# A bare `! grep` never fails under set -e, so both checks exit explicitly.
assert_contains() {
  grep -Eq -- "$1" "$2" || { echo "Missing /$1/ in ${2##*/}" >&2; exit 1; }
}

refute_contains() {
  if grep -Eq -- "$1" "$2"; then echo "Unexpected /$1/ in ${2##*/}" >&2; exit 1; fi
}

# set_venv_home DIRECTORY -> pyvenv.cfg as a real venv writes it: home is DIRECTORY, and
# the executable line names the Cellar whatever home says.
set_venv_home() {
  printf 'home = %s\nexecutable = %s\n' "$1" \
    /opt/homebrew/Cellar/python@3.13/3.13.17/bin/python3.13 \
    > "$WORKTREE/.venv/pyvenv.cfg"
}

# make_worktree -> a healthy worktree in place of whatever was there.
make_worktree() {
  rm -rf "$WORKTREE"
  mkdir -p "$WORKTREE/.venv/bin" "$WORKTREE/.vscode" "$WORKTREE/node_modules"
  cp "$MOCK_PYTHON" "$WORKTREE/.venv/bin/python"
  touch "$WORKTREE/.vscode/settings.json"
  set_venv_home "$OPT_HOME"
}

# run_doctor EXPECTED-STATUS -> run the doctor from the worktree root, as npm does, with a
# fresh command log, and check how it exits.
run_doctor() {
  local status=0
  : > "$COMMANDS"
  (cd "$WORKTREE" && sh "$REPO_DIR/scripts/worktree-doctor.sh") > "$OUTPUT" 2>&1 ||
    status=$?
  [ "$status" -eq "$1" ] ||
    { echo "Expected exit $1, not $status. Its output:" >&2
      cat "$OUTPUT" >&2; exit 1; }
}

# A healthy worktree exits 0 with nothing to report, though its pyvenv.cfg names the
# Cellar on the executable line, as a real one does.
make_worktree
run_doctor 0
refute_contains '^(warn|FAIL) ' "$OUTPUT"
assert_contains '^ok    interpreter runs \(Python 3\.12\.7\)$' "$OUTPUT"
assert_contains '^ok    the project imports$' "$OUTPUT"
assert_contains '^ok    venv base survives Homebrew upgrades$' "$OUTPUT"
assert_contains '^ok    VS Code reads \.vscode/settings\.json here$' "$OUTPUT"
assert_contains '^ok    node_modules is present$' "$OUTPUT"
assert_contains "^  .*/worktree/\.venv/bin/python$" "$OUTPUT"
printf '%s\n' 'python --version' 'python -c import src_back.app' | diff -u - "$COMMANDS"

# Without .venv it exits 1, says how to rebuild, and still reports the other checks.
# It reaches no verdict on the import or the base, and leaks no shell error.
rm -rf "$WORKTREE/.venv"
run_doctor 1
assert_contains '^FAIL  no working interpreter at \.venv/bin/python$' "$OUTPUT"
assert_contains 'from a shell with no virtualenv active:$' "$OUTPUT"
assert_contains 'pip install -r requirements-dev\.txt$' "$OUTPUT"
assert_contains '^ok    VS Code reads \.vscode/settings\.json here$' "$OUTPUT"
assert_contains '^ok    node_modules is present$' "$OUTPUT"
assert_contains "^  .*/worktree/\.venv/bin/python$" "$OUTPUT"
refute_contains 'project imports|does not import|venv base|pyvenv' "$OUTPUT"
refute_contains 'No such file|not found' "$OUTPUT"

# The link a deleted base leaves behind fails the same way, and the Cellar warning that
# explains it still appears.
make_worktree
rm "$WORKTREE/.venv/bin/python"
ln -s "$TEST_DIR/deleted/python3.13" "$WORKTREE/.venv/bin/python"
set_venv_home "$CELLAR_HOME"
run_doctor 1
assert_contains '^FAIL  no working interpreter at \.venv/bin/python$' "$OUTPUT"
assert_contains '^warn  venv base is a versioned Homebrew Cellar path$' "$OUTPUT"

# So does an interpreter that is there but cannot start, which a file test would pass.
make_worktree
printf '#!/bin/sh\nexit 1\n' > "$WORKTREE/.venv/bin/python"
run_doctor 1
assert_contains '^FAIL  no working interpreter at \.venv/bin/python$' "$OUTPUT"

# An interpreter that runs but cannot import the project exits 1 and shows the error's
# last line, not the traceback.
make_worktree
touch "$TEST_DIR/import-fails"
run_doctor 1
rm "$TEST_DIR/import-fails"
assert_contains '^FAIL  the project does not import$' "$OUTPUT"
assert_contains "^      ModuleNotFoundError: No module named 'flask'$" "$OUTPUT"
assert_contains 'install with: \.venv/bin/pip install -r requirements-dev\.txt$' "$OUTPUT"
refute_contains 'Traceback' "$OUTPUT"

# Each warning leaves the exit status at 0, and the Cellar one says how to rebuild.
make_worktree
set_venv_home "$CELLAR_HOME"
run_doctor 0
assert_contains '^warn  venv base is a versioned Homebrew Cellar path$' "$OUTPUT"
assert_contains 'rm -rf \.venv && python3 -m venv \.venv$' "$OUTPUT"

make_worktree
rm "$WORKTREE/.vscode/settings.json"
run_doctor 0
assert_contains '^warn  no \.vscode/settings\.json here' "$OUTPUT"

make_worktree
rmdir "$WORKTREE/node_modules"
run_doctor 0
assert_contains '^warn  no node_modules; run npm install$' "$OUTPUT"

# npm run doctor is this script.
assert_contains '"doctor": "sh scripts/worktree-doctor\.sh"' "$REPO_DIR/package.json"

echo 'worktree-doctor.sh regression checks passed.'
```

### scripts/tests/test-install-vscode-extensions.sh — new

```bash
#!/usr/bin/env bash
# Exercise .devcontainer/install-vscode-extensions.sh in a disposable repository, under a
# disposable HOME that holds stub VS Code servers: which server it picks, what it asks
# that server to install, and when its marker skips the install. It exits 77 without
# python3, which the script parses with. It runs under macOS's bash 3.2 and on Linux in
# CI, so it avoids bash 4 features.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
command -v python3 > /dev/null ||
  { echo 'test-install-vscode-extensions.sh needs python3.' >&2; exit 77; }
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT
export TEST_DIR
# The space proves the script quotes every path that starts from HOME.
export HOME="$TEST_DIR/ho me"
REPOSITORY="$TEST_DIR/repository"
mkdir -p "$HOME" "$REPOSITORY/.devcontainer" "$REPOSITORY/.vscode"
cp "$REPO_DIR/.devcontainer/install-vscode-extensions.sh" "$REPOSITORY/.devcontainer/"
RECOMMENDATIONS="$REPOSITORY/.vscode/extensions.json"
SERVER_DIR="$HOME/.vscode-server"
MARKER="$SERVER_DIR/data/Machine/.recommended-extensions.sha256"
COMMANDS="$TEST_DIR/commands"
OUTPUT="$TEST_DIR/output"
DATA_DIRECTORY="--server-data-dir $SERVER_DIR"

# A bare `! grep` never fails under set -e, so both checks exit explicitly.
assert_contains() {
  grep -Eq -- "$1" "$2" || { echo "Missing /$1/ in ${2##*/}" >&2; exit 1; }
}

refute_contains() {
  if grep -Eq -- "$1" "$2"; then echo "Unexpected /$1/ in ${2##*/}" >&2; exit 1; fi
}

# expect_call LINE -> the servers ran exactly this one line.
expect_call() {
  printf '%s\n' "$1" | diff -u - "$COMMANDS"
}

# expect_no_calls -> no server ran.
expect_no_calls() {
  [ ! -s "$COMMANDS" ] || { echo 'A server ran:' >&2; cat "$COMMANDS" >&2; exit 1; }
}

# expect_no_marker -> nothing recorded an install.
expect_no_marker() {
  [ ! -e "$MARKER" ] || { echo 'A marker exists.' >&2; exit 1; }
}

# expect_marker SHA -> the marker still holds SHA.
expect_marker() {
  [ "$(cat "$MARKER")" = "$1" ] || { echo 'The marker changed.' >&2; exit 1; }
}

# add_server COMMIT STAMP -> a stub code-server for COMMIT, modified at the touch -t
# STAMP. It logs an install and fails it while $TEST_DIR/install-fails exists. Otherwise
# the install leaves $TEST_DIR/listed as what it lists next, in capitals, because the real
# list keeps each publisher's letter case, so a list before the install finds nothing.
add_server() {
  local server="$SERVER_DIR/bin/$1/bin/code-server"
  mkdir -p "${server%/*}"
  cat > "$server" <<MOCK
#!/usr/bin/env bash
set -eu
if [ "\$*" = '--server-data-dir $SERVER_DIR --list-extensions' ]; then
  tr 'a-z' 'A-Z' < "\$TEST_DIR/installed"
  exit 0
fi
printf '%s\n' "$1 \$*" >> "\$TEST_DIR/commands"
[ ! -f "\$TEST_DIR/install-fails" ]
cp "\$TEST_DIR/listed" "\$TEST_DIR/installed"
MOCK
  chmod +x "$server"
  touch -t "$2" "$server"
}

# recommend ID... -> write a recommendations file holding these ids, plus an unwanted id
# that must never install, and have the servers list every id.
recommend() {
  local ids
  ids=$(printf '"%s",' "$@")
  printf '{"recommendations": [%s], "unwantedRecommendations": ["no.thanks"]}\n' \
    "${ids%,}" > "$RECOMMENDATIONS"
  printf '%s\n' "$@" > "$TEST_DIR/listed"
}

# attach [EXPECTED-STATUS] -> run the script as postAttachCommand does, from the
# repository root with a relative path, and check how it exits.
attach() {
  local expected=${1:-0} status=0
  : > "$COMMANDS"
  (cd "$REPOSITORY" && sh .devcontainer/install-vscode-extensions.sh) > "$OUTPUT" 2>&1 ||
    status=$?
  [ "$status" -eq "$expected" ] ||
    { echo "Expected exit $expected, not $status. Its output:" >&2
      cat "$OUTPUT" >&2; exit 1; }
}

# With no server under HOME there is nothing to install with, which is not a failure, and
# no marker, so the next attach tries again.
recommend one.first two.second
attach
assert_contains '^No VS Code server under ' "$OUTPUT"
expect_no_marker

# The first attach installs each recommendation in one call and records the file's
# sha256. It leaves out the host-only extensions and the unwanted id, and it creates the
# marker's directory.
add_server aaaa-older 202601010000
recommend one.first ms-vscode-remote.remote-containers \
  ms-vscode-remote.remote-ssh two.second
attach
expect_call "aaaa-older $DATA_DIRECTORY --install-extension one.first \
--install-extension two.second"
assert_contains '^[0-9a-f]{64}$' "$MARKER"

# A second attach installs nothing and prints nothing.
attach
expect_no_calls
[ ! -s "$OUTPUT" ] ||
  { echo 'An up-to-date attach printed:' >&2; cat "$OUTPUT" >&2; exit 1; }

# Any change to the file installs again, even one that leaves the same ids, through the
# newest server, which sorts neither first nor last by name.
add_server mmmm-newest 202606010000
add_server zzzz-middle 202603010000
printf ' \n' >> "$RECOMMENDATIONS"
attach
expect_call "mmmm-newest $DATA_DIRECTORY --install-extension one.first \
--install-extension two.second"
recommend one.first four.fourth
attach
expect_call "mmmm-newest $DATA_DIRECTORY --install-extension one.first \
--install-extension four.fourth"
attach
expect_no_calls

# A failed install exits with the server's status and keeps the old marker, so the next
# attach installs again, even when the server already lists every id.
MARKER_BEFORE=$(cat "$MARKER")
recommend five.fifth
cp "$TEST_DIR/listed" "$TEST_DIR/installed"
touch "$TEST_DIR/install-fails"
attach 1
expect_marker "$MARKER_BEFORE"
rm "$TEST_DIR/install-fails"
attach
expect_call "mmmm-newest $DATA_DIRECTORY --install-extension five.fifth"

# An install that exits 0 but leaves an id off the server's list fails the same way, by
# name, so a write lost to the server's own installs is retried. Every id counts, a longer
# id does not stand in for it, and letter case does not count as a loss, because the
# stub lists in capitals.
MARKER_BEFORE=$(cat "$MARKER")
recommend six.sixth seven.seventh eight.eighth
printf '%s\n' six.sixth seven.seventh-pack eight.eighth > "$TEST_DIR/listed"
attach 1
assert_contains '^ERROR: seven\.seventh is not installed' "$OUTPUT"
expect_marker "$MARKER_BEFORE"
recommend six.sixth seven.seventh eight.eighth
attach
[ "$(cat "$MARKER")" != "$MARKER_BEFORE" ] ||
  { echo 'The retry wrote no marker.' >&2; exit 1; }

# A file that does not parse stops the script: no install, and no new marker.
MARKER_BEFORE=$(cat "$MARKER")
printf 'not json\n' > "$RECOMMENDATIONS"
attach 1
expect_no_calls
expect_marker "$MARKER_BEFORE"

# A file with nothing to install calls no server, because a call with no ids would start
# one, and records the file so the next attach does not parse it for nothing. That holds
# for a list of only host-side ids and for a file with no list at all.
rm "$MARKER"
recommend ms-vscode-remote.remote-containers
attach
expect_no_calls
assert_contains '^[0-9a-f]{64}$' "$MARKER"
rm "$MARKER"
printf '{}\n' > "$RECOMMENDATIONS"
attach
expect_no_calls
assert_contains '^[0-9a-f]{64}$' "$MARKER"

# Without the file there is nothing to do, which is not a failure.
rm "$RECOMMENDATIONS"
attach
assert_contains '^No .*extensions\.json, so no extensions to install\.$' "$OUTPUT"
expect_no_calls

# The repository's own file parses, and installs the one recommendation that
# customizations.vscode.extensions lacks, plus another Microsoft id, so the host-only
# filter stays narrow. postAttachCommand runs this script, and the container can build:
# docker-in-docker refuses Moby on the image's Debian release.
cp "$REPO_DIR/.vscode/extensions.json" "$RECOMMENDATIONS"
python3 - "$RECOMMENDATIONS" > "$TEST_DIR/listed" <<'PYTHON'
import json
import sys

with open(sys.argv[1], encoding='utf-8') as handle:
    print('\n'.join(json.load(handle)['recommendations']))
PYTHON
attach
assert_contains ' --install-extension vitest\.explorer( |$)' "$COMMANDS"
assert_contains ' --install-extension ms-python\.python( |$)' "$COMMANDS"
refute_contains 'ms-vscode-remote' "$COMMANDS"
DEVCONTAINER="$REPO_DIR/.devcontainer/devcontainer.json"
assert_contains '"postAttachCommand": "sh \.devcontainer/install-vscode-extensions\.sh"' \
  "$DEVCONTAINER"
assert_contains '"moby": false' "$DEVCONTAINER"

echo 'install-vscode-extensions.sh regression checks passed.'
```

### README.md — Worktrees section and the Scripts table

Replace the paragraph at lines 158 to 163 and the one at lines 165 to 167 with:

```markdown
`scripts/worktree-setup.sh` creates the worktree on a new branch from `origin/staging`
(or `origin/main` where there is no `staging`), copies `.env` from `main/`, gives the
stack its own `COMPOSE_PROJECT_NAME`, and shifts its ports by the smallest offset that
no other worktree's `.env` reserves and nothing is listening on; a second argument sets
the offset instead. It then builds the venv, checks that it imports the project, and
installs `node_modules`, and `npm install` points the shared `core.hooksPath` at
`.husky/_`, which resolves inside each worktree.

The first `python3` on `PATH` outside a virtualenv builds the venv. `PYTHON_BIN`, a
command or a path, names another, and the script refuses it if it sits inside a
virtualenv: a venv built from another venv can record a versioned Homebrew Cellar
directory as its base, which the next `brew upgrade` deletes. The script warns if the
new venv recorded one anyway.

Open each worktree in its own VS Code window, never the container directory: only a
worktree has the `.vscode/settings.json` that points the Python extension at its
`.venv`. The script opens the new worktree that way when `code` is on `PATH`, unless
`--no-open` comes before the branch name.

`npm run doctor`, run in a worktree, reports whether it still works. It exits 1 when
`.venv/bin/python` does not run or the project does not import, and it warns about a
venv based on a Cellar path, a missing `.vscode/settings.json`, and missing
`node_modules`.
```

In the Scripts table, after the `npm run fallow` row:

```markdown
| `npm run doctor`         | Check this worktree's venv and `node_modules`   |
```

### ai/project.md — Commands and Worktrees

After the `npm run fallow` line (line 78):

```markdown
- `npm run doctor` - check this worktree: exits 1 when `.venv/bin/python` does not run or
  the project does not import, and warns about a venv based on a Homebrew Cellar path, a
  missing `.vscode/settings.json`, and missing `node_modules`
```

After the Worktrees section's paragraph, which ends at line 274, add a new paragraph:

```markdown
The script builds `.venv` with the first `python3` on `PATH` outside a virtualenv, or
with `PYTHON_BIN`, which it refuses inside one, and stops if the venv cannot import
`src_back.app`. It opens the finished worktree in VS Code when `code` is on `PATH`,
unless `--no-open` comes before the branch. `npm run doctor` repeats the checks on an
existing worktree.
```

### tools.md — the shell, Dev Containers, and worktree entries

Replace lines 25 to 27:

```markdown
- **Bash and POSIX sh**: the scripts. `docker/entrypoint.sh`, `docker/job-loop.sh`, the
  dev container's `install-vscode-extensions.sh`, and the local helpers `up.sh`,
  `down.sh`, `docker-url.sh`, `worktree-setup.sh`, and `worktree-doctor.sh` are POSIX sh;
  the server and deployment scripts and the Claude Code hook are Bash.
```

Replace lines 383 to 386:

```markdown
- **Dev Containers**: `.devcontainer/devcontainer.json` starts from Microsoft's Python
  3.12 dev container image, adds Node 22 and Docker-in-Docker, with `moby` off because
  the image's Debian release has no Moby packages, fills `.venv` from
  `requirements-dev.txt`, installs `node_modules`, and forwards the Flask and Vite
  ports, so a fresh machine gets the whole toolchain.
  `.devcontainer/install-vscode-extensions.sh` runs at every attach and installs the
  recommendations in `.vscode/extensions.json` through the container's VS Code server,
  once per change of that file, because VS Code installs the list in `devcontainer.json`
  only when a container first starts. It skips the remote development extensions, which
  run on the host.
```

Replace lines 395 to 397:

```markdown
- **Git worktrees**: `scripts/worktree-setup.sh` supports a bare-repo layout with one
  worktree per branch, each with its own `.env`, Compose project, shifted ports,
  `.venv`, and `node_modules`, so several branches can run side by side. It builds each
  `.venv` from a Python outside any virtualenv and checks that it imports the project;
  `scripts/worktree-doctor.sh`, as `npm run doctor`, checks a worktree again later.
```

## Parallelism

Implementer model: Sonnet 5.5, per #27's order. Opus 5.5 orchestrates and reviews.

**Can be done in parallel**: Groups A, B, and C share no file, and none reads another's.

- **Group A**: `scripts/worktree-setup.sh`, `scripts/tests/test-worktree-setup.sh`.
- **Group B**: `scripts/worktree-doctor.sh`, `scripts/tests/test-worktree-doctor.sh`,
  `package.json`.
- **Group C**: `.devcontainer/install-vscode-extensions.sh`,
  `.devcontainer/devcontainer.json`, `scripts/tests/test-install-vscode-extensions.sh`.

**Must be sequential**: Group D, `README.md`, `ai/project.md`, and `tools.md`, follows A
to C, so the documentation describes what they built.

Each group runs its own test with `bash scripts/tests/<file>` and, on a scratch copy of
the repository and never the real files, the mutations below with a timeout on each run,
because a hang counts as a gap. Report survivors, and any extra mutations tried, instead
of adding tests this plan does not list.

Group A mutations of `worktree-setup.sh`:

1. Move the interpreter block below `git worktree add`.
2. Change `!=` to `==` in `virtualenv_state`.
3. Take the first `python3` on `PATH` whatever its state.
4. Ignore `PYTHON_BIN`.
5. Accept `True` in the `PYTHON_BIN` case.
6. Delete the `*)` refusal in that case.
7. Delete the smoke test.
8. Move the smoke test after `npm install`.
9. Search all of `pyvenv.cfg` for the Cellar, not the `home` line.
10. Make the Cellar warning `exit 1`.
11. Move the `code` block below the ready lines.
12. Replace it with an unguarded `code "$PWD"`.
13. Delete the `$open_editor` check.
14. Delete `[ "$#" -le 2 ] || usage`.
15. Delete the offset `case`.
16. Delete `-*` from the branch `case`.
17. Delete `| 0[0-9]*` from the offset `case`.
18. Make the offset `case` refuse `0` as well (`0*`).
19. Delete the line that makes a relative `PYTHON_BIN` absolute.
20. Delete the relative-entry `case` from `first_base_python`.
21. Move the argument checks below `git fetch`.
22. Print the open hint after the ready lines.
23. Skip `command -v`, so a bare `PYTHON_BIN` stays bare.
24. Make only an answer holding a slash absolute, which only `dash` shows.
25. Make a name `command -v` cannot find absolute as well.

Group B mutations of `worktree-doctor.sh` and `package.json`:

1. Import `flask` instead of `src_back.app`.
2. `exit 1` straight after the interpreter failure.
3. Search all of `pyvenv.cfg` for the Cellar.
4. Make the Cellar finding `fail`.
5. Make the `node_modules` finding `fail`.
6. Make the `settings.json` finding `fail`.
7. Delete the `'')` case arm.
8. `exit 0` at the end.
9. Name `requirements.txt` in the hints.
10. Print the whole traceback.
11. Check only `[ -x .venv/bin/python ]`.
12. Rename the `package.json` script.
13. Name `requirements.txt` in the import failure's hint alone.
14. Delete `rebuild_hint` from the Cellar arm.
15. Print the interpreter path only when the worktree is healthy.

Group C mutations of `install-vscode-extensions.sh` and `devcontainer.json`:

1. Drop `-t` from `ls`.
2. Search `.vscode-remote` in place of `.vscode-server`.
3. Drop `--server-data-dir`.
4. Drop the `ms-vscode-remote.` filter.
5. Drop the marker comparison.
6. Write the marker before installing.
7. Add `|| true` to the install.
8. Add `|| true` to `parsed=$(read_recommendations)`.
9. Delete the `"$#"` guard.
10. Delete `mkdir -p`.
11. Delete the missing-file check.
12. Delete the no-server exit.
13. Remove `postAttachCommand`.
14. Delete the `--list-extensions` check.
15. Drop `-i` from its `grep`.
16. Drop `--server-data-dir` from the list call.
17. Filter on `ms-` rather than `ms-vscode-remote.`.
18. Replace `ls -t ... | head` with `ls ... | tail`.
19. Hash the parsed ids rather than the file's bytes.
20. Use `['recommendations']` in place of `.get`.
21. Remove the quotes from `"$server_dir"` in `find_code_server`.
22. Print a line when the marker matches.
23. Remove `"moby": false`.

## No other changes needed

- `scripts/tests/run-all.sh` picks the two new tests up by glob, and its syntax pass finds
  `.devcontainer/install-vscode-extensions.sh` through `git ls-files`, so CI's Shell
  scripts job needs no edit.
- `.claude/settings.json` already allows `npm run *`.
- `~/.ai/commands/plan-issue.md` and `plan-pr.md` need no edit (decision 10).
- `customizations.vscode.extensions` stays (decision 4). `.env.example` is untouched,
  because `PYTHON_BIN` is a shell setting, read before any `.env` exists.

## Verification

Run these after the groups finish. `$SCRATCH` is a directory under the session's
scratchpad and `$REPO` is this repository. Nothing here touches this repository's `.venv`
or `node_modules`.

**Step 1: the tests under both shells.** Run the three test files as they stand, then
again with `dash` as `sh`, which is what CI's Ubuntu runs:

```bash
mkdir -p "$SCRATCH/dash-bin" && ln -sf /bin/dash "$SCRATCH/dash-bin/sh"
PATH="$SCRATCH/dash-bin:$PATH" bash scripts/tests/test-worktree-setup.sh
```

**A scratch copy** for Steps 2 to 4 holds the tracked and new files, with no `.env`,
`.venv`, or `node_modules`, in a repository of its own. Its one commit stays there:

```bash
mkdir -p "$SCRATCH/copy"
git ls-files --cached --others --exclude-standard |
  while IFS= read -r file; do [ ! -e "$file" ] || printf '%s\n' "$file"; done |
  tar -T - -cf - | tar -xf - -C "$SCRATCH/copy"
git -C "$SCRATCH/copy" init -q -b main
git -C "$SCRATCH/copy" add -A
git -C "$SCRATCH/copy" -c user.name=Check -c user.email=check@example.com \
  commit -q -m 'Scratch copy'
```

**Step 2: the first acceptance criterion.** From `$SCRATCH/copy`, this must print the
refusal naming the interpreter and exit 1, and `git worktree list` and
`git branch --list x` must show nothing new. The copy has no `.venv`, so it points at
this repository's real one:

```bash
PYTHON_BIN="$REPO/.venv/bin/python" sh scripts/worktree-setup.sh x 1
```

**Step 3: the second acceptance criterion.** In `$SCRATCH/copy`, build a real venv with
`/opt/homebrew/opt/python@3.13/bin/python3.13 -m venv .venv` and install
`requirements-dev.txt` into it. `npm run doctor` exits 0, and after `rm -rf .venv` there
it exits non-zero.

**Step 4: a real worktree end to end.** Make a bare container from the scratch copy as
README describes, and run the script from this session's shell, whose `python3` is the
active `.venv`:

```bash
mkdir "$SCRATCH/bare" && git clone -q --bare "$SCRATCH/copy" "$SCRATCH/bare/.git"
git -C "$SCRATCH/bare" config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
git -C "$SCRATCH/bare" fetch -q origin
cd "$SCRATCH/bare" && git worktree add -q main main
fnm exec --using=22 sh main/scripts/worktree-setup.sh --no-open issue-99-check 7
```

It must print a `Building .venv with` line naming a Homebrew `python3`, finish real pip
and npm installs, and leave `home = /opt/homebrew/opt/python@3.13/bin` in the new
`pyvenv.cfg`. `npm run doctor` there exits 0. Delete `$SCRATCH/bare` afterwards.

**Step 5: the full gates.** Run these in parallel and report each result:
`npm run test:scripts`, `npm run test`, `npm run lint`, `npm run lint:py`,
`npm run lint:md`, `npm run typecheck`, and `npx prettier --check .`. Then run
`git diff --check`.

**Step 6: a real dev container.** The build fix, points 1 and 2 of the Context, and
decision 4's overlap were read from code and never observed, so attach one. This must use
a scratch copy: the workspace is bind-mounted, so `postCreateCommand` would replace this
repository's Mac `.venv` and `node_modules` with Linux builds. Docker on this host holds
other projects' containers and volumes, so record the state first, without the times that
would make a diff noisy:

```bash
docker ps -a --format '{{.ID}} {{.Names}}' | sort > "$SCRATCH/containers.before"
docker volume ls --format '{{.Name}}' | sort > "$SCRATCH/volumes.before"
docker image ls --format '{{.ID}} {{.Repository}}:{{.Tag}}' | sort \
  > "$SCRATCH/images.before"
```

Copy the tracked and new files, and open the copy, which opens one VS Code window:

```bash
mkdir -p "$SCRATCH/attach"
git ls-files --cached --others --exclude-standard |
  while IFS= read -r file; do [ ! -e "$file" ] || printf '%s\n' "$file"; done |
  tar -T - -cf - | tar -xf - -C "$SCRATCH/attach"
hex=$(printf '%s' "$SCRATCH/attach" | xxd -p | tr -d '\n')
code --new-window --folder-uri "vscode-remote://dev-container+$hex/workspaces/attach"
```

If that URI does not attach, or a trust prompt holds it, ask Chuck to run
**Dev Containers: Reopen in Container** on the copy. Find the container with
`docker ps -q --filter "label=devcontainer.local_folder=$SCRATCH/attach"`, and poll for
the marker with a 20-minute limit, because a first attach pulls the image, builds the
features, and runs pip and npm. Commands run in the container like this, so that `~`
expands there rather than on the Mac:

```bash
docker exec -u vscode -w /workspaces/attach "$id" sh -c \
  '~/.vscode-server/bin/*/bin/code-server --list-extensions'
```

Then check each of these:

- The marker exists at `~/.vscode-server/data/Machine/.recommended-extensions.sha256`.
- The list holds `vitest.explorer` and every other id in `.vscode/extensions.json`, but
  not `ms-vscode-remote.remote-containers`. It keeps each publisher's letter case, so
  compare without case.
- Running `sh .devcontainer/install-vscode-extensions.sh` the same way, which is the
  `docker exec` an attach uses, prints nothing and installs nothing.
- Close the window and reopen the copy with the same `code` command, a real second
  attach. The marker's modification time does not change.
- After adding a space to `.vscode/extensions.json` in the copy, the script runs
  `code-server` again and rewrites the marker.
- For a rebuild, run `docker rm -f "$id"` and reopen the copy, so `postCreateCommand`
  finds `.venv` and `node_modules` on the bind mount and the script overlaps the server's
  installs. It may exit 1 naming a lost id; report whether it did. The marker and the full
  list must exist by the next attach at the latest.

Close the window, then remove by exact id or name only what the before-listings lack: the
labelled container, its volumes, the `vscode` volume, and the images the run pulled or
built. Never run `docker system prune`, `docker volume prune`, or any other prune,
because they would destroy other projects' data. Repeat the three listings and diff them
against the before files; they must match. The build cache grows and stays, which these
listings do not show. If an attach cannot be arranged, say so plainly rather than call the
third acceptance criterion met.

**Step 7: this plan.** Lint it, because lint-staged lints committed plans:
`npx markdownlint-cli2 plans/pr-55-add-a-worktree-doctor-and-sync.md`.
