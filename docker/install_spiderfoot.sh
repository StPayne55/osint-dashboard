#!/bin/sh
# Bundle SpiderFoot OSS (not HX) into an isolated venv. Adds ~200–400MB.
set -eu

VERSION="${SPIDERFOOT_VERSION:-v4.0}"
DEST="${SPIDERFOOT_HOME:-/opt/spiderfoot}"
REQS="${1:-/tmp/spiderfoot-requirements.txt}"
PATCH="${2:-/tmp/patch_spiderfoot.py}"

mkdir -p "$(dirname "$DEST")"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

echo "Downloading SpiderFoot ${VERSION} (open-source, not HX)..."
wget -q -O "$tmpdir/sf.tgz" \
  "https://github.com/smicallef/spiderfoot/archive/refs/tags/${VERSION}.tar.gz"
tar -xzf "$tmpdir/sf.tgz" -C "$tmpdir"
extracted="$(find "$tmpdir" -maxdepth 1 -type d -name 'spiderfoot-*' | head -n 1)"
if [ -z "$extracted" ]; then
  echo "Failed to extract SpiderFoot ${VERSION}" >&2
  exit 1
fi
rm -rf "$DEST"
mv "$extracted" "$DEST"

python3 -m venv "$DEST/.venv"
"$DEST/.venv/bin/pip" install --no-cache-dir --upgrade pip
"$DEST/.venv/bin/pip" install --no-cache-dir -r "$REQS"

python3 "$PATCH" "$DEST"

# CLI smoke: module list must load without importing the app venv.
(cd "$DEST" && "$DEST/.venv/bin/python" "$DEST/sf.py" -M >/dev/null)
echo "SpiderFoot ${VERSION} installed at ${DEST}"
