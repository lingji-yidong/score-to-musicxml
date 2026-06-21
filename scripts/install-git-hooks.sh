#!/bin/sh
set -eu

repository_root=$(git rev-parse --show-toplevel)
git -C "$repository_root" config core.hooksPath .githooks
chmod +x "$repository_root/.githooks/pre-commit"

echo "Git hooks enabled from .githooks"
