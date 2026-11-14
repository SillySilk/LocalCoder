#!/bin/sh
# Mac/Linux (untested): create a terminal command (default: george) that opens
# LocalCoder in the current folder. Usage: ./install-command.sh [name]
NAME="${1:-george}"
DIR="$(cd "$(dirname "$0")" && pwd)"
BIN="$HOME/.local/bin"
mkdir -p "$BIN"
chmod +x "$DIR/localcoder.sh"
printf '#!/bin/sh
exec "%s/localcoder.sh" "$@"
' "$DIR" > "$BIN/$NAME"
chmod +x "$BIN/$NAME"
echo "Created $BIN/$NAME"
case ":$PATH:" in
    *":$BIN:"*) ;;
    *) echo "Note: add $BIN to your PATH so your shell can find it." ;;
esac
echo "Open a new terminal and type: $NAME"
