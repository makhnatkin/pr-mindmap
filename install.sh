#!/bin/sh
# Links this folder as the pr-mindmap skill of Claude Code and puts `prmap` on the PATH.
# Safe to run again; it never replaces a real folder or file, only its own links.
set -e
here=$(cd "$(dirname "$0")" && pwd)

link() { # link <target> <link path>
  if [ -L "$2" ] || [ ! -e "$2" ]; then
    mkdir -p "$(dirname "$2")"
    ln -sfn "$1" "$2"
    echo "linked $2 -> $1"
  else
    echo "skipped $2: it exists and is not a link" >&2
  fi
}

link "$here" "$HOME/.claude/skills/pr-mindmap"
link "$here/prmap" "$HOME/.local/bin/prmap"
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) echo "add ~/.local/bin to PATH to run prmap from anywhere, or call $here/prmap" ;;
esac
