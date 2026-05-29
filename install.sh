#!/bin/sh
set -eu

: "${HOME:?HOME is not set}"

REPO_URL="${SWAIN_REPO_URL:-https://github.com/Descry-Technologies/Swain.git}"
INSTALL_DIR="${SWAIN_INSTALL_DIR:-$HOME/.swain}"
SOURCE_DIR="${SWAIN_SOURCE_DIR:-$INSTALL_DIR/source}"
BIN_DIR="${SWAIN_BIN_DIR:-}"

say() {
  printf '%s\n' "$*"
}

fail() {
  printf 'swain install: %s\n' "$*" >&2
  exit 1
}

has() {
  command -v "$1" >/dev/null 2>&1
}

prepend_user_bins() {
  PATH="$BIN_DIR:$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  export PATH
}

default_bin_dir() {
  old_ifs=$IFS
  IFS=:
  for dir in $PATH; do
    IFS=$old_ifs
    [ -n "$dir" ] || continue
    case "$dir" in
      *"/.venv" | *"/.venv/"*) continue ;;
    esac
    if [ -d "$dir" ] && [ -w "$dir" ]; then
      printf '%s\n' "$dir"
      return
    fi
    IFS=:
  done
  IFS=$old_ifs
  printf '%s\n' "$HOME/.local/bin"
}

install_uv() {
  say "Installing uv..."
  if has curl; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  elif has wget; then
    wget -qO- https://astral.sh/uv/install.sh | sh
  else
    fail "install curl or wget, then rerun this installer"
  fi
}

check_python() {
  python3 - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
}

[ -n "$BIN_DIR" ] || BIN_DIR="$(default_bin_dir)"
has git || fail "git is required"
has python3 || fail "python3 is required"
check_python || fail "Python 3.11 or newer is required"

prepend_user_bins
if ! has uv; then
  install_uv
  prepend_user_bins
fi
has uv || fail "uv installed, but it is not on PATH"

mkdir -p "$INSTALL_DIR" "$BIN_DIR"

if [ -d "$SOURCE_DIR/.git" ]; then
  say "Updating Swain source..."
  git -C "$SOURCE_DIR" pull --ff-only
else
  say "Installing Swain source..."
  rm -rf "$SOURCE_DIR"
  git clone --depth=1 "$REPO_URL" "$SOURCE_DIR"
fi

say "Installing swain command..."
UV_TOOL_BIN_DIR="$BIN_DIR" uv tool install --force "$SOURCE_DIR"

if [ -x "$BIN_DIR/swain" ]; then
  say "Swain installed."
else
  fail "swain was not installed into $BIN_DIR"
fi

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    say ""
    say "Add this to your shell profile so 'swain' is available:"
    say "  export PATH=\"$BIN_DIR:\$PATH\""
    ;;
esac

say ""
say "Run inside your project:"
say "  cd /path/to/your/repo"
say "  swain"
say ""
say "Or try the offline demo:"
say "  swain demo"
say ""
say "First launch will explain Swain and help you choose Claude, Codex, or hybrid mode."
say "Later, run 'swain update' to pull the latest source install."
