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

# The developer's own git configuration must not decide a case, or sign a commit.
cat > "$TEST_DIR/gitconfig" <<'CONFIG'
[user]
    name = Worktree Test
    email = worktree-test@example.com
[commit]
    gpgsign = false
CONFIG
export GIT_CONFIG_GLOBAL="$TEST_DIR/gitconfig" GIT_CONFIG_NOSYSTEM=1

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

# The seed repository holds the real .env.example on main, one empty commit on a staging
# branch, and one on issue-2-existing, which branches from main. Each commit has its own
# message, so no two branches share a tip.
seed() { git -C "$TEST_DIR/seed" "$@"; }
git init -q -b main "$TEST_DIR/seed"
cp "$REPO_DIR/.env.example" "$TEST_DIR/seed/.env.example"
seed add .env.example
seed commit -q -m 'Add the example environment'
seed checkout -q -b staging
seed commit -q --allow-empty -m 'Start staging'
seed checkout -q main
seed checkout -q -b issue-2-existing
seed commit -q --allow-empty -m 'Start issue 2'
seed checkout -q main

# One origin has every branch; the other has main alone, as a repository from before
# staging existed. Each container is a bare clone in .git with the fetch refspec that
# bare clones lack, as README's Worktrees section sets it up.
git clone -q --bare "$TEST_DIR/seed" "$TEST_DIR/origin.git"
git clone -q --bare --single-branch --branch main "$TEST_DIR/seed" \
  "$TEST_DIR/origin-main.git"
make_container() {
  mkdir "$TEST_DIR/$1"
  git clone -q --bare "$TEST_DIR/$2" "$TEST_DIR/$1/.git"
  git -C "$TEST_DIR/$1" config remote.origin.fetch "$FETCH_REFSPEC"
}
make_container container-a origin.git
make_container container-b origin-main.git
# Then the seed moves both branches ahead and the origins follow, so each container's own
# staging and main fall behind: only a fetched origin/* ref names the tip a new branch
# must fork from.
seed checkout -q staging
seed commit -q --allow-empty -m 'Advance staging'
seed checkout -q main
seed commit -q --allow-empty -m 'Advance main'
seed push -q "$TEST_DIR/origin.git" staging main
seed push -q "$TEST_DIR/origin-main.git" main
cp "$REPO_DIR/scripts/worktree-setup.sh" "$TEST_DIR/worktree-setup.sh"

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

# assert_worktree_state CONTAINER BRANCH SEED-BRANCH -> the worktree CONTAINER/BRANCH is
# on BRANCH, at the commit that SEED-BRANCH has in the seed repository.
assert_worktree_state() {
  local worktree="$TEST_DIR/$1/$2" head branch
  head=$(git -C "$worktree" rev-parse HEAD)
  branch=$(git -C "$worktree" symbolic-ref --short HEAD)
  [ "$branch" = "$2" ] ||
    { echo "Expected $1/$2 to be on $2, not $branch." >&2; exit 1; }
  [ "$head" = "$(seed rev-parse "$3")" ] ||
    { echo "Expected $1/$2 to start at the seed's $3." >&2; exit 1; }
}

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
