#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export UV_CACHE_DIR="${UV_CACHE_DIR:-$script_dir/.uv-cache}"

exec uv run --project "$script_dir" --frozen python "$script_dir/convert_score.py" "$@"
