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
