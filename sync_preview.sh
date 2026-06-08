#!/bin/bash
# Mirror the web app into /tmp so the (Desktop-sandboxed) preview server can serve it.
set -e
DEST=/tmp/mapgen_preview
mkdir -p "$DEST"
cp -R web/. "$DEST"/
echo "synced web/ -> $DEST"
