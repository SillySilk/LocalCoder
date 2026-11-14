#!/bin/sh
# LocalCoder for Mac/Linux (untested): run Claude Code / OpenCode on local
# Ollama models. Usage: ./localcoder.sh [project_folder] [lc_launch options]
DIR="$(cd "$(dirname "$0")" && pwd)"
if [ $# -gt 0 ] && [ "${1#-}" = "$1" ]; then
    FOLDER="$1"; shift
else
    FOLDER="$PWD"
fi
PY="$(command -v python3 || command -v python)"
if [ -z "$PY" ]; then
    echo "LocalCoder needs Python 3." >&2
    exit 1
fi
exec "$PY" "$DIR/lc_launch.py" "$FOLDER" "$@"
