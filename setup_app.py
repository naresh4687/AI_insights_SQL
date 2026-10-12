"""Guided setup for InsightSQL: run it once after downloading the project.

    python3 setup_app.py            # asks a few questions (Windows: py setup_app.py)
    python3 setup_app.py --yes      # no questions: the defaults (Demo Mode, no AI key)
    python3 setup_app.py --dev      # also install the test tools and the test browser
    python3 setup_app.py --start    # start the app at the end without asking

Easier still: double-click setup_windows.bat (Windows) or setup_mac.command (Mac), or run
setup_mac_linux.sh (Linux). They also install Python if it is missing, then run this file.

Step by step it:
  1. checks the Python version (3.12 or newer);
  2. creates the virtual environment .venv (if missing);
  3. installs the packages from requirements.txt;
  4. creates .env from .env.example (an existing .env is never overwritten) and fills in a
     new encryption key for saved connection passwords;
  5. optionally stores your Gemini API key (typed in hidden, saved only in .env);
  6. creates the sample database;
  7. prints how to start the app, on this computer and on a phone;
  8. offers to start it now and opens it in the browser.

Running it again is safe: finished steps are skipped. Details: README.md, section 3.
"""

import argparse
import getpass
import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MIN_PYTHON = (3, 12)


def say(step: str, text: str) -> None:
    print(f"\n[{step}] {text}", flush=True)


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(*command, cwd: Path = ROOT) -> None:
    subprocess.run([str(c) for c in command], cwd=cwd, check=True)


def set_env_value(env_file: Path, name: str, value: str) -> bool:
    """Set ``name`` in ``env_file`` when it is missing or empty; never change a value already set.
    Returns True if the file was changed."""
    lines = env_file.read_text().splitlines() if env_file.exists() else []
    for i, line in enumerate(lines):
        key, sep, current = line.partition("=")
        if sep and key.strip() == name:
            if current.strip():
                return False
            lines[i] = f"{name}={value}"
            break
    else:
        lines.append(f"{name}={value}")
    env_file.write_text("\n".join(lines) + "\n")
    return True


def env_value(env_file: Path, name: str) -> str:
    for line in env_file.read_text().splitlines() if env_file.exists() else []:
        key, sep, value = line.partition("=")
        if sep and key.strip() == name:
            return value.strip()
    return ""


def ask_yes_no(question: str, default: bool, assume_yes: bool) -> bool:
    if assume_yes:
        return default
    answer = input(f"{question} [{'Y/n' if default else 'y/N'}] ").strip().lower()
    return default if not answer else answer.startswith("y")


def free_port(first: int = 8501, tries: int = 20) -> int:
    """The first port from ``first`` that nothing is listening on (another copy of the app may
    already use 8501; its answer must not be taken for this one's)."""
    for port in range(first, first + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError(f"No free port between {first} and {first + tries - 1}.")


def start_app(py: Path, port: int | None = None) -> None:
    """Run the app until Ctrl+C and open it in the browser once it answers. Streamlit runs
    "headless" so that it does not stop to ask for an email address on its first run."""
    port = port or free_port()
    if port != 8501:
        print(f"  Port 8501 is already in use (is the app already running?), so this one uses {port}.", flush=True)
    url = f"http://localhost:{port}"
    app = subprocess.Popen([str(py), "-m", "streamlit", "run", "app.py", "--server.headless", "true",
                            "--server.port", str(port), "--browser.gatherUsageStats", "false"], cwd=ROOT)
    try:
        for _ in range(120):
            if app.poll() is not None:
                print("  The app stopped while starting; see the messages above.", flush=True)
                return
            try:
                urllib.request.urlopen(f"{url}/_stcore/health", timeout=1)
                break
            except OSError:
                time.sleep(0.5)
        print(f"\n  InsightSQL is running at {url}  (press Ctrl+C here to stop it)", flush=True)
        webbrowser.open(url)
        app.wait()
    except KeyboardInterrupt:
        app.terminate()
        app.wait()
        print("\n  InsightSQL stopped. Run the setup again (or the commands above) to start it.", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Guided setup for InsightSQL.")
    parser.add_argument("--yes", action="store_true", help="no questions: use the defaults")
    parser.add_argument("--dev", action="store_true", help="also install the test tools and browser")
    parser.add_argument("--start", action="store_true", help="start the app at the end without asking")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(line_buffering=True)  # messages appear at once, even in a log file

    print("InsightSQL setup — about 2 minutes. Run it again at any time; finished steps are skipped.", flush=True)

    say("1/8", "Checking Python")
    if sys.version_info < MIN_PYTHON:
        print(f"  Python {'.'.join(map(str, MIN_PYTHON))} or newer is needed; this is {sys.version.split()[0]}.\n"
              "  Install it from https://www.python.org/downloads/ and run this again with it.")
        return 1
    print(f"  Python {sys.version.split()[0]}: OK", flush=True)

    venv = ROOT / ".venv"
    py = venv_python(venv)
    say("2/8", "Virtual environment (.venv)")
    if py.exists():
        print("  Already there: skipped", flush=True)
    else:
        run(sys.executable, "-m", "venv", venv)
        print("  Created", flush=True)

    say("3/8", "Installing packages (the first time takes a minute or two)")
    requirements = "requirements-dev.txt" if args.dev else "requirements.txt"
    run(py, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", requirements)
    print(f"  Installed from {requirements}", flush=True)
    if args.dev:
        print("  Installing the test browser (Chromium)", flush=True)
        try:
            run(py, "-m", "playwright", "install", "chromium")
        except subprocess.CalledProcessError:
            print("  Could not install Chromium; browser tests will use Google Chrome if it is installed.", flush=True)

    env_file = ROOT / ".env"
    say("4/8", "Settings file (.env)")
    if env_file.exists():
        print("  .env already exists: kept as it is", flush=True)
    else:
        env_file.write_text((ROOT / ".env.example").read_text())
        print("  Created from .env.example", flush=True)
    key = subprocess.run([str(py), "-c", "from cryptography.fernet import Fernet; "
                                        "print(Fernet.generate_key().decode())"],
                         check=True, capture_output=True, text=True).stdout.strip()
    if set_env_value(env_file, "INSIGHTSQL_SECRET_KEY", key):
        print("  Added a new INSIGHTSQL_SECRET_KEY (encrypts saved connection passwords).\n"
              "  Keep a copy of .env somewhere safe: without this key, saved passwords cannot be read.")
    else:
        print("  INSIGHTSQL_SECRET_KEY already set: kept", flush=True)

    say("5/8", "AI Mode (optional)")
    if env_value(env_file, "GEMINI_API_KEY"):
        print("  A Gemini API key is already set: kept", flush=True)
    elif ask_yes_no("  Add a Gemini API key now? Demo Mode works without one.", False, args.yes):
        print("  Get a key at https://aistudio.google.com/apikey", flush=True)
        gemini_key = getpass.getpass("  Paste the key (it is not shown): ").strip()
        if gemini_key:
            set_env_value(env_file, "GEMINI_API_KEY", gemini_key)
            print("  Saved in .env (never commit .env; it is git-ignored)", flush=True)
        else:
            print("  Nothing entered: skipped", flush=True)
    else:
        print("  Skipped: the app runs in Demo Mode. Add GEMINI_API_KEY to .env later (README section 7).", flush=True)

    say("6/8", "Sample database")
    run(py, "-c", "from src import config, database; database.ensure_database(config.get_db_path()); "
                  "print('  Ready:', config.get_db_path().relative_to(config.PROJECT_ROOT))")

    say("7/8", "Done! Start the app with:")
    activate = r".venv\Scripts\activate" if os.name == "nt" else "source .venv/bin/activate"
    print(f"""
      {activate}
      streamlit run app.py

  Then open http://localhost:8501 (stop with Ctrl+C).

  On a phone on the same Wi-Fi:  streamlit run app.py --server.address 0.0.0.0
  and open http://<this computer's address>:8501 (README section 4).

  Show it to someone: README section 6 (demo script). Put it online: README section 13.""")
    if args.dev:
        print("  Run the tests: pytest   (README section 15)", flush=True)

    # --yes alone never starts it (unattended setups); --start always does; otherwise ask.
    if args.start or (not args.yes and ask_yes_no("\n[8/8] Start InsightSQL now? It opens in your browser.",
                                                   True, assume_yes=False)):
        start_app(py)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as exc:
        print(f"\nSetup stopped: a step failed ({' '.join(map(str, exc.cmd[:3]))} …). "
              "Check your internet connection and run it again.")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nSetup cancelled. Run it again to continue where it stopped.", flush=True)
        sys.exit(1)
