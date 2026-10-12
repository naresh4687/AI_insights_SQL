#!/usr/bin/env bash
# InsightSQL setup for Mac and Linux: installs Python 3.12 if it is missing, then runs the
# guided setup (setup_app.py), which installs everything else and can start the app.
#
#   Mac:   double-click setup_mac.command (or run: bash setup_mac_linux.sh)
#   Linux: bash setup_mac_linux.sh
#
# Any options are passed on to setup_app.py, for example: bash setup_mac_linux.sh --yes
set -euo pipefail
cd "$(dirname "$0")"

good_python() {  # prints a python command that is 3.12+ and can create virtual environments
  for cmd in python3.13 python3.12 python3 python; do
    if command -v "$cmd" >/dev/null 2>&1 &&
       "$cmd" -c 'import sys, venv, ensurepip; sys.exit(0 if sys.version_info >= (3, 12) else 1)' >/dev/null 2>&1; then
      echo "$cmd"; return 0
    fi
  done
  return 1
}

if ! PY=$(good_python); then
  echo "Python 3.12 or newer (with venv) was not found. Installing it..."
  if [[ "$(uname)" == "Darwin" ]]; then
    if command -v brew >/dev/null 2>&1; then
      brew install python@3.12
    else
      echo "Please install Python 3.12 from https://www.python.org/downloads/macos/"
      echo "(or Homebrew from https://brew.sh), then run this again."
      exit 1
    fi
  elif command -v apt-get >/dev/null 2>&1; then
    echo "Your password may be asked (sudo) to install system packages."
    sudo apt-get update
    sudo apt-get install -y python3.12 python3.12-venv || {
      echo "Python 3.12 is not in this system's package list (Ubuntu 24.04 or newer has it)."
      echo "Install Python 3.12 from https://www.python.org/downloads/ and run this again."
      exit 1
    }
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y python3.12
  else
    echo "Please install Python 3.12 from https://www.python.org/downloads/ and run this again."
    exit 1
  fi
  PY=$(good_python) || { echo "Python was installed but could not be found; open a new terminal and run this again."; exit 1; }
fi

echo "Using $("$PY" --version)"
exec "$PY" setup_app.py "$@"
