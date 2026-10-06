#!/usr/bin/env python3
"""Structured DCInside reads and persistent HTTP login. No browser dependency."""
from __future__ import annotations

import argparse
from contextlib import contextmanager, nullcontext
import fcntl
import getpass
from importlib.metadata import PackageNotFoundError, distribution
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time

import requests
from dcinside_http_login import DCInsideHTTP, LoginError

VERSION = "0.4.3"
SESSION_TTL = 7 * 24 * 60 * 60
SUPPORTED = ["capabilities", "instructions", "list", "read", "comments", "comment", "login", "status", "logout"]


class ToolError(Exception):
    def __init__(self, code, message, *, details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # Never echo unknown arguments: a caller may accidentally supply a password.
        raise ToolError("INVALID_ARGUMENT", "Invalid arguments. Use --help; passwords are never command-line arguments.")


def default_state_dir():
    explicit = os.environ.get("DCINSIDE_STATE_DIR")
    if explicit:
        return Path(explicit).expanduser()
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "dcinside"


def instructions_path():
    """Locate the guide in a checkout/skill or through an installed wheel's RECORD."""
    local = Path(__file__).resolve().with_name("SKILL.md")
    if local.is_file():
        return local
    try:
        package = distribution("dcinside-http")
    except PackageNotFoundError:
        raise ToolError("LOCAL_ERROR", "Agent instructions are missing. Reinstall dcinside-http.") from None
    for entry in package.files or ():
        if entry.parts[-3:] == ("share", "dcinside", "SKILL.md"):
            guide = Path(package.locate_file(entry))
            if guide.is_file():
                return guide.resolve()
    raise ToolError("LOCAL_ERROR", "Agent instructions are missing. Reinstall dcinside-http.")


class SessionStore:
    """Private local cookies only. The file is not encrypted; never share it."""
    def __init__(self, directory):
        self.directory = Path(directory).expanduser()
        self.path = self.directory / "session.json"

    def _private_directory(self, create=False):
        if not self.directory.exists() and not self.directory.is_symlink():
            if not create:
                return False
            self.directory.mkdir(mode=0o700, parents=True)
        info = self.directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077
                or (hasattr(os, "getuid") and info.st_uid != os.getuid())):
            raise ToolError("UNSAFE_SESSION", "Session directory must be owned by you, not a symlink, and have mode 700.")
        return True

    @contextmanager
    def lock(self):
        """Serialize load/request/save so concurrent commands cannot restore stale cookies."""
        self._private_directory(create=True)
        fd = os.open(self.directory / ".session.lock",
                     os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077
                    or (hasattr(os, "getuid") and info.st_uid != os.getuid())):
                raise ToolError("UNSAFE_SESSION", "Session lock must be a private file owned by you.")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ToolError("SESSION_BUSY", "Another command is using this session. Wait for it to finish.") from None
            yield
        finally:
            os.close(fd)

    def load(self, session):
        if self.path.is_symlink():
            raise ToolError("UNSAFE_SESSION", "Session file must not be a symlink.")
        if not self._private_directory() or not self.path.exists():
            return None
        fd = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            info = os.fstat(handle.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 1_000_000
                    or (hasattr(os, "getuid") and info.st_uid != os.getuid())):
                raise ToolError("UNSAFE_SESSION", "Session file must be a private file with mode 600.")
            try:
                payload = json.load(handle)
                if payload["version"] != 1 or not isinstance(payload["cookies"], list):
                    raise ValueError()
                age = time.time() - float(payload["saved_at"])
                if age < -60 or age >= SESSION_TTL:
                    raise ToolError("SESSION_EXPIRED", "Saved session expired. Run login again.")
                jar = requests.cookies.RequestsCookieJar()
                for record in payload["cookies"]:
                    domain = record["domain"].lstrip(".")
                    if domain not in ("dcinside.com", "m.dcinside.com", "msign.dcinside.com", "sso.dcinside.com", "gall.dcinside.com", "sign.dcinside.com"):
                        raise ValueError()
                    if record.get("expires") is not None and record["expires"] <= time.time():
                        continue
                    jar.set_cookie(requests.cookies.create_cookie(**record))
                session.cookies.update(jar)
                return {"nickname": payload.get("nickname"), "saved_at": payload["saved_at"]}
            except (ValueError, KeyError, TypeError):
                raise ToolError("INVALID_SESSION", "Saved session cannot be read. Remove it with logout and log in again.") from None

    def save(self, session, identity, *, saved_at=None):
        self._private_directory(create=True)
        if self.path.is_symlink():
            raise ToolError("UNSAFE_SESSION", "Session file must not be a symlink.")
        cookies = [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path,
                    "secure": c.secure, "expires": c.expires, "discard": c.discard,
                    "rest": dict(c._rest)} for c in session.cookies]
        payload = {"version": 1, "saved_at": time.time() if saved_at is None else saved_at,
                   "nickname": identity["nickname"], "cookies": cookies}
        fd, temporary = tempfile.mkstemp(prefix=".session-", dir=self.directory)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def forget(self):
        if not self._private_directory():
            return False
        if self.path.is_symlink():
            raise ToolError("UNSAFE_SESSION", "Session file must not be a symlink.")
        try:
            self.path.unlink()
            return True
        except FileNotFoundError:
            return False


def parser():
    root = Parser(description=__doc__)
    root.add_argument("--state-dir", type=Path, default=default_state_dir(), help="Private session directory (before the command)")
    root.add_argument("--version", action="version", version=VERSION)
    commands = root.add_subparsers(dest="command", required=True, parser_class=Parser)
    commands.add_parser("capabilities", help="Supported operations and limits; no network")
    commands.add_parser("instructions", help="Bundled agent usage instructions; no network")
    for command in ("list", "read", "comments", "comment", "login", "status"):
        sub = commands.add_parser(command)
        sub.add_argument("--gallery", default="thesingularity")
        sub.add_argument("--kind", choices=("minor", "main"), default="minor")
        if command in ("list", "comments"):
            sub.add_argument("--page", type=int, default=1)
        if command == "list":
            sub.add_argument("--limit", type=int, default=5)
            sub.add_argument("--include-notices", action="store_true")
        if command in ("read", "comments", "comment"):
            sub.add_argument("post_id", type=int)
        if command == "comment":
            content = sub.add_mutually_exclusive_group(required=True)
            content.add_argument("--text")
            content.add_argument("--text-file", type=Path)
            sub.add_argument("--send", action="store_true", help="Publish the user-authorized text once; default is preview only")
        if command == "login":
            sub.add_argument("--user", required=True)
            sub.add_argument("--password-stdin", action="store_true", help="Read one password line from a trusted stdin pipe")
        if command in ("list", "read", "comments"):
            sub.add_argument("--anonymous", action="store_true", help="Do not load saved login cookies")
    commands.add_parser("logout", help="Forget this tool's local session; does not log out browsers")
    for unsupported in ("write",):
        commands.add_parser(unsupported, help="Not implemented; returns UNSUPPORTED_OPERATION")
    return root


def run(args):
    command = args.command
    if command == "capabilities":
        return {"version": VERSION, "transport": "http", "surface": "mobile", "base_url": "https://m.dcinside.com", "browser_required": False,
                "supported": SUPPORTED, "unsupported": ["create_post", "reply_to_comment", "edit", "delete", "vote"],
                "gallery_kinds": ["minor", "main"], "default_gallery": "thesingularity",
                "session": {"storage": "local file, directory 700/file 600, unencrypted cookies", "max_age_days": 7},
                "output": "JSON", "error_exit_code": 2}
    if command == "instructions":
        guide = instructions_path()
        return {"command": "dcinside", "path": str(guide), "instructions": guide.read_text(encoding="utf-8")}
    if command == "write":
        raise ToolError("UNSUPPORTED_OPERATION", "Post creation is not implemented. No content was submitted. Do not infer browser permission.")
    store = SessionStore(args.state_dir)
    with nullcontext() if getattr(args, "anonymous", False) else store.lock():
        if command == "logout":
            return {"local_session_removed": store.forget(), "browser_sessions_changed": False, "remote_logout": False}
        return run_with_client(args, store)


def run_with_client(args, store):
    command = args.command
    client = DCInsideHTTP(args.gallery, args.kind)
    try:
        if command == "login":
            if args.password_stdin:
                password = sys.stdin.readline().rstrip("\r\n")
            elif sys.stdin.isatty():
                password = getpass.getpass("Password: ")
            else:
                raise ToolError("CREDENTIALS_REQUIRED", "Use an interactive terminal for login, or explicitly select --password-stdin.")
            if not password:
                raise ToolError("CREDENTIALS_REQUIRED", "Password is required.")
            identity = client.login(args.user, password)
            password = ""
            store.save(client.session, identity)
            return {**identity, "session_saved": True, "password_saved": False}
        if not getattr(args, "anonymous", False):
            saved = store.load(client.session)
        else:
            saved = None
        result = error = None
        try:
            result = run_session_command(args, client, saved)
        except (ToolError, LoginError) as exc:
            error = exc
        except requests.RequestException:
            error = ToolError("NETWORK_ERROR", "Request failed. No automatic retry was performed.")
        except (ValueError, OSError):
            error = ToolError("LOCAL_ERROR", "Invalid input or local file access failed. Use --help and check the session directory permissions.")
        warning = None
        if saved:
            try:
                # Refresh cookies even on CAPTCHA rejection, without extending the login's TTL.
                store.save(client.session, saved, saved_at=saved["saved_at"])
            except (ToolError, OSError, ValueError):
                warning = {"code": "SESSION_SAVE_FAILED", "message": "Updated cookies could not be saved. The operation outcome is unchanged; do not resend a comment for this warning."}
        if error:
            if warning:
                error.details["session_warning"] = warning
            raise error
        if warning:
            result["warnings"] = [warning]
        return result
    finally:
        client.close()


def run_session_command(args, client, saved):
    if args.command == "status":
        if not saved:
            return {"authenticated": False, "reason": "NO_SESSION"}
        identity = client.verify_login()
        return {**identity, "saved_at": saved["saved_at"]}
    if args.command == "list":
        return client.list_posts(args.page, args.limit, args.include_notices)
    if args.command == "read":
        return client.read_post(args.post_id)
    if args.command == "comments":
        return client.read_comments(args.post_id, args.page)
    if args.command == "comment":
        if not saved:
            raise ToolError("LOGIN_REQUIRED", "Run login before commenting.")
        content = args.text if args.text is not None else args.text_file.read_text(encoding="utf-8")
        return client.create_comment(args.post_id, content, send=args.send)


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        output = {"ok": True, "data": run(args)}
        exit_code = 0
    except (ToolError, LoginError) as exc:
        output = {"ok": False, "error": {"code": exc.code, "message": str(exc)}}
        if exc.details:
            output["error"]["details"] = exc.details
        exit_code = 2
    except requests.RequestException:
        output = {"ok": False, "error": {"code": "NETWORK_ERROR", "message": "Request failed. No automatic retry was performed."}}
        exit_code = 2
    except (ValueError, OSError):
        output = {"ok": False, "error": {"code": "LOCAL_ERROR", "message": "Invalid input or local file access failed. Use --help and check the session directory permissions."}}
        exit_code = 2
    print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
