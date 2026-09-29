#!/bin/sh
# llmtest installer for macOS and Linux.
#
#   curl -fsSL https://raw.githubusercontent.com/mijanlab/LLMtest/main/install.sh | sh
#
# Nothing needs to be installed first. The script sets up uv (a fast, self-contained Python
# tool installer from Astral) if it's missing; uv downloads Python itself when the system
# has no suitable version, and installs llmtest into its own isolated environment, like pipx.
# No sudo, git, pip, or pipx required.
#
# Optional: LLMTEST_SOURCE installs from another source (a local checkout, branch zip, etc.).
set -eu

SOURCE="${LLMTEST_SOURCE:-https://github.com/mijanlab/LLMtest/archive/refs/heads/main.zip}"

if [ -t 1 ]; then
  cyan='\033[36m' green='\033[32m' yellow='\033[33m' red='\033[31m' reset='\033[0m'
else
  cyan='' green='' yellow='' red='' reset=''
fi
info() { printf "${cyan}%s${reset}\n" "$1"; }
ok()   { printf "${green}✔ %s${reset}\n" "$1"; }
warn() { printf "${yellow}⚠ %s${reset}\n" "$1"; }
fail() { printf "${red}✖ %s${reset}\n" "$1" >&2; exit 1; }

case "$(uname -s)" in
  MINGW* | MSYS* | CYGWIN*)
    fail "On Windows, run this in PowerShell instead:  irm https://raw.githubusercontent.com/mijanlab/LLMtest/main/install.ps1 | iex" ;;
esac

find_uv() {
  if command -v uv >/dev/null 2>&1; then command -v uv; return; fi
  for candidate in "${UV_INSTALL_DIR:-}/uv" "${XDG_BIN_HOME:-}/uv" "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
    if [ -x "$candidate" ]; then echo "$candidate"; return; fi
  done
}

# --- 1. uv ------------------------------------------------------------------
uv=$(find_uv)
if [ -z "$uv" ]; then
  info "Setting up uv (one-time, no sudo needed)..."
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- https://astral.sh/uv/install.sh | sh >/dev/null
  else
    fail "curl or wget is required to download uv."
  fi
  uv=$(find_uv)
  [ -n "$uv" ] || fail "uv installation did not succeed. See https://docs.astral.sh/uv/getting-started/installation/"
  ok "uv installed."
fi

# --- 2. llmtest ---------------------------------------------------------------
info "Installing llmtest (uv fetches Python automatically if needed)..."
# --reinstall --refresh: always get the newest code, so re-running this script also updates llmtest.
"$uv" tool install --force --reinstall --refresh --quiet "$SOURCE" || fail "llmtest installation failed."

bin_dir=$("$uv" tool dir --bin)
"$bin_dir/llmtest" --version >/dev/null 2>&1 || fail "llmtest was installed but did not start."
ok "llmtest installed."

# --- 3. PATH ------------------------------------------------------------------
"$uv" tool update-shell >/dev/null 2>&1 || true

case ":$PATH:" in
  *":$bin_dir:"*)
    # An older pip-installed llmtest earlier on PATH would shadow this one.
    other=$(command -v llmtest || true)
    if [ -n "$other" ] && [ "$other" != "$bin_dir/llmtest" ]; then
      warn "Another llmtest at $other comes first on your PATH. Remove it with: pip uninstall llmtest"
    fi
    printf "\nRun: ${green}llmtest${reset}\n" ;;
  *)
    printf "\nOpen a new terminal, then run: ${green}llmtest${reset}\n"
    printf "Or use it right now: ${green}%s/llmtest${reset}\n" "$bin_dir" ;;
esac
