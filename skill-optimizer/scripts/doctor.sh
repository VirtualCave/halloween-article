#!/usr/bin/env sh
# skill-optimizer doctor: checks uv, which runs the skill's Python scripts and installs the Python and the libraries
# they declare, and prints how to install it on this system (macOS, Linux, or Windows through Git Bash).
# Nothing is installed without --install.
# Usage: sh doctor.sh [--install [--dry-run]] [--os windows|macos|linux]
#   --install   install what is missing; show the user the plan first (--install --dry-run) and wait for a yes
#   --dry-run   with --install: print the commands, run nothing
#   --os        plan for another system, assuming its usual package manager (with --install --dry-run)
set -u

install=0
dry=0
os=""
simulate=0
while [ $# -gt 0 ]; do
  case "$1" in
    --install) install=1 ;;
    --dry-run) dry=1 ;;
    --os) shift; os="${1:-}"; simulate=1 ;;
    -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1 (see --help)"; exit 2 ;;
  esac
  shift
done
case "$os" in
  ""|windows|macos|linux) ;;
  *) echo "Unknown --os $os: use windows, macos or linux"; exit 2 ;;
esac
if [ "$simulate" = 1 ] && { [ "$install" = 0 ] || [ "$dry" = 0 ]; }; then
  echo "--os only simulates an install plan: use it with --install --dry-run"; exit 2
fi
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
manual="https://docs.astral.sh/uv/getting-started/installation/"

if [ -z "$os" ]; then
  case "$(uname -s 2>/dev/null)" in
    Darwin) os=macos ;;
    MINGW*|MSYS*|CYGWIN*) os=windows ;;
    *) os=linux ;;
  esac
fi

has() { command -v "$1" >/dev/null 2>&1; }
# a package manager for the plan: when simulating another system, assume its usual one is there
manager() { [ "$simulate" = 1 ] || has "$1"; }

# uv on PATH, or where its installers put it (a fresh install is not on this shell's PATH yet)
find_uv() {
  if has uv; then command -v uv; return 0; fi
  for p in "$HOME/.local/bin/uv" "$HOME/.local/bin/uv.exe" "$HOME/.cargo/bin/uv" "$HOME/scoop/shims/uv.exe" \
           "$HOME/AppData/Local/Microsoft/WinGet/Links/uv.exe" /opt/homebrew/bin/uv /usr/local/bin/uv; do
    if [ -x "$p" ]; then echo "$p"; return 0; fi
  done
  return 1
}

# the install command for uv: the system's package manager when there is one, else the official installer
plan() {
  if has curl || [ "$simulate" = 1 ]; then unix="curl -LsSf https://astral.sh/uv/install.sh | sh"
  else unix="wget -qO- https://astral.sh/uv/install.sh | sh"; fi
  case "$os" in
    windows)
      if manager scoop; then echo "scoop install uv"
      elif manager winget; then echo "winget install --id astral-sh.uv -e --accept-source-agreements --accept-package-agreements"
      else echo 'powershell -NoProfile -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'; fi ;;
    macos)
      if manager brew; then echo "brew install uv"; else echo "$unix"; fi ;;
    *) echo "$unix" ;;
  esac
}

version() { "$1" --version 2>/dev/null | awk '{print $2}'; }

echo "os $os"
missing=0
uv=""
if [ "$simulate" = 0 ] && uv=$(find_uv); then
  if has uv; then echo "ok uv $(version "$uv") ($uv)"
  else echo "ok uv $(version "$uv") ($uv, not on PATH: call it by this path or open a new terminal)"; fi
  if py=$("$uv" python find ">=3.10" 2>/dev/null); then echo "ok python ($py)"
  else echo "note python: none >= 3.10 yet; uv downloads one on the first run (or now: uv python install)"; fi
else
  missing=1
  echo "MISSING uv: runs the Python scripts and installs the Python and libraries they declare"
  echo "  install: $(plan)"
  echo "  manual:  $manual"
fi

if [ "$install" = 1 ] && [ "$missing" = 1 ]; then
  cmd=$(plan)
  if [ "$dry" = 1 ]; then
    echo "would run: $cmd"
  else
    # package managers print pages (Scoop updates every bucket first): the log keeps them, the summary does not
    log="${TMPDIR:-/tmp}/skill-optimizer-doctor.log"
    echo "running: $cmd (output in $log)"
    if ! sh -c "$cmd" >"$log" 2>&1; then
      tail -n 5 "$log"
      echo "DOCTOR: the install failed (log: $log); install by hand: $manual"
      exit 1
    fi
    if ! uv=$(find_uv); then echo "DOCTOR: uv installed but not found: open a new terminal and run the doctor again"; exit 1; fi
    missing=0
    echo "ok uv $(version "$uv") ($uv)"
  fi
fi
# with --install, also prepare the scripts: uv downloads the Python and the libraries they declare, once
if [ "$install" = 1 ] && [ "$dry" = 0 ] && [ "$missing" = 0 ]; then
  if "$uv" run -q "$here/audit.py" --help >/dev/null 2>&1; then echo "ok scripts ready (Python and libraries in uv's cache)"
  else missing=1; echo "MISSING scripts: uv could not prepare them (offline?); see: $uv run $here/audit.py --help"; fi
fi

if [ "$missing" = 0 ]; then
  run="uv"; has uv || run="$uv"
  echo "DOCTOR OK - run the scripts with: $run run $here/<script>.py"
  exit 0
fi
if [ "$install" = 1 ] && [ "$dry" = 1 ]; then
  echo "DOCTOR: dry run - show the user the command above, run --install only after a yes"
else
  echo "DOCTOR: uv missing - show the user the install command (--install --dry-run), run --install only after a yes"
fi
exit 1
