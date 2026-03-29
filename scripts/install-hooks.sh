#!/usr/bin/env bash
# Install git hooks for secret/data leak prevention.
# Run once after cloning: bash scripts/install-hooks.sh
set -euo pipefail

HOOKS_DIR="$(git rev-parse --show-toplevel)/.git/hooks"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE_DIR="$(cd "$SCRIPT_DIR/../githooks" && pwd)"

if [ ! -d "$SOURCE_DIR" ]; then
    echo "ERROR: githooks/ directory not found at $SOURCE_DIR"
    exit 1
fi

for hook in "$SOURCE_DIR"/*; do
    name=$(basename "$hook")
    cp "$hook" "$HOOKS_DIR/$name"
    chmod +x "$HOOKS_DIR/$name"
    echo "Installed hook: $name"
done

echo "Done. Git hooks installed."
