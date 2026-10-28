#!/usr/bin/env bash
# Exercise scripts/worktree-setup.sh with real git: bare-repo containers cloned from
# local origins, set up as README's Worktrees section describes, and stub python3 and
# npm commands. It checks which commit a new worktree starts from (origin/staging when
# the origin has that branch, origin/main when it has only main, and an existing origin
# branch as it is), the branch the worktree is on, and the isolated .env it gets. It
# runs the script with sh, as README does, and exits 77 without git. It runs under
# macOS's bash 3.2 and on Linux in CI, so the test avoids bash 4 features.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
command -v git > /dev/null ||
  { echo 'test-worktree-setup.sh needs git.' >&2; exit 77; }
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT
mkdir -p "$TEST_DIR/bin"
export TEST_DIR
export PATH="$TEST_DIR/bin:$PATH"
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

# A bare `! grep` never fails under set -e, so the check exits explicitly.
assert_contains() {
  grep -Eq -- "$1" "$2" || { echo "Missing /$1/ in ${2##*/}" >&2; exit 1; }
}

# expect_calls LINE... -> the stubs ran exactly these lines, in this order.
expect_calls() {
  printf '%s\n' "$@" | diff -u - "$COMMANDS"
}

# python3 accepts only `-m venv .venv`, which makes a .venv/bin holding a pip that is
# this stub as well; pip and npm only log. Each logs its call to $TEST_DIR/commands.
cat > "$TEST_DIR/bin/mock-command" <<'MOCK'
#!/usr/bin/env bash
set -eu
name=${0##*/}
printf '%s\n' "$name $*" >> "$TEST_DIR/commands"
case "$name" in
  python3)
    [ "$*" = '-m venv .venv' ] || { echo "Unexpected python3 call: $*" >&2; exit 1; }
    mkdir -p .venv/bin
    ln -s "$TEST_DIR/bin/mock-command" .venv/bin/pip
    ;;
  pip | npm) ;;
  *) echo "Unexpected mock command: $name" >&2; exit 1 ;;
esac
MOCK
chmod +x "$TEST_DIR/bin/mock-command"
# A stub that did not come first on PATH would let the script build a real virtualenv
# and install real packages. Every case passes an explicit port offset, so the script
# never calls lsof.
for command in python3 npm; do
  ln -s mock-command "$TEST_DIR/bin/$command"
  [ "$(command -v "$command")" = "$TEST_DIR/bin/$command" ] ||
    { echo "The $command stub does not shadow the real command." >&2; exit 1; }
done

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

# run_worktree_setup CONTAINER BRANCH OFFSET -> run the copy of worktree-setup.sh from
# the container directory, as README does, with a fresh command log; show its output if
# it fails.
run_worktree_setup() {
  : > "$COMMANDS"
  (cd "$TEST_DIR/$1" && sh "$TEST_DIR/worktree-setup.sh" "$2" "$3") > "$OUTPUT" 2>&1 ||
    { echo "worktree-setup.sh $2 failed in $1. Its output:" >&2
      cat "$OUTPUT" >&2; exit 1; }
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
# container and the three ports from the offset, and the venv and the packages are
# installed.
run_worktree_setup container-a issue-1-new 3
assert_worktree_state container-a issue-1-new staging
ENV_FILE="$TEST_DIR/container-a/issue-1-new/.env"
assert_contains '^COMPOSE_PROJECT_NAME=container-a-issue-1-new$' "$ENV_FILE"
assert_contains '^DB_PORT=5435$' "$ENV_FILE"
assert_contains '^BACKEND_PORT=5003$' "$ENV_FILE"
assert_contains '^FRONTEND_PORT=5177$' "$ENV_FILE"
assert_contains '^PUBLIC_BASE_URL=http://localhost:5177$' "$ENV_FILE"
expect_calls 'python3 -m venv .venv' 'pip install -r requirements-dev.txt' 'npm install'

# A branch that already exists on the origin is checked out as it is, not forked again
# from staging.
run_worktree_setup container-a issue-2-existing 4
assert_worktree_state container-a issue-2-existing issue-2-existing

# An origin with no staging branch still gets origin/main as the base.
run_worktree_setup container-b issue-1-new 3
assert_worktree_state container-b issue-1-new main

echo 'worktree-setup.sh regression checks passed.'
