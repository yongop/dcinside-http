#!/usr/bin/env python3
"""Install/update the self-contained Codex skill without copying private state."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv

FILES = ("SKILL.md", "README.md", "agents/openai.yaml", "scripts/dcinside",
         "dcinside_cli.py", "dcinside_http_login.py", "requirements.txt", "install.py")
MARKER = ".dcinside-install.json"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def install(target, *, skip_dependencies=False):
    source = Path(__file__).resolve().parent
    target = target.expanduser().absolute()
    if target.is_symlink():
        raise RuntimeError("Installation target must not be a symlink.")
    if target.resolve() == source:
        raise RuntimeError("Use a separate skill installation directory.")
    if target.exists() and any(target.iterdir()):
        marker = target / MARKER
        if not marker.is_file() or marker.is_symlink():
            raise RuntimeError("Target is not a managed DCInside installation; preserving its files.")
        old = json.loads(marker.read_text())
        if old.get("package") != "dcinside-http":
            raise RuntimeError("Unexpected installation marker.")
        for name, expected in old["files"].items():
            if name not in FILES or (target / name).is_symlink():
                raise RuntimeError("Unexpected managed file; preserving installation.")
            if not (target / name).is_file() or digest(target / name) != expected:
                raise RuntimeError(f"Locally modified installation file: {name}. Preserving your changes.")
    target.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        destination = target / name
        parts = Path(name).parts
        parents = [target.joinpath(*parts[:i]) for i in range(1, len(parts))]
        if destination.is_symlink() or any(p.is_symlink() for p in parents):
            raise RuntimeError("Symlink in installation destination; stopped.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, destination)
    (target / "scripts/dcinside").chmod(0o755)
    manifest = {"package": "dcinside-http", "version": "0.4.3", "files": {name: digest(target / name) for name in FILES}}
    (target / MARKER).write_text(json.dumps(manifest, indent=2) + "\n")
    if not skip_dependencies:
        environment = target / ".venv"
        if environment.is_symlink():
            raise RuntimeError("Virtual environment must not be a symlink.")
        if not (environment / "bin/python").is_file():
            venv.EnvBuilder(with_pip=True).create(environment)
        subprocess.run([str(environment / "bin/python"), "-m", "pip", "install", "--disable-pip-version-check",
                        "-r", str(target / "requirements.txt")], check=True)
    executable = target / "scripts/dcinside"
    subprocess.run([str(executable), "capabilities"], check=True)
    print(f"Installed skill: {target}")
    print(f"Command: {executable}")
    print("Use $dcinside in a new chat, or read this installation's SKILL.md explicitly in an existing chat.")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    codex_base = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    parser.add_argument("--target", type=Path, default=codex_base / "skills/dcinside")
    parser.add_argument("--skip-dependencies", action="store_true", help="Use dependencies already available in the current Python environment")
    args = parser.parse_args()
    try:
        install(args.target, skip_dependencies=args.skip_dependencies)
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Installation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
