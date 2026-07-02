#! /usr/bin/env python3

# Copyright (c) 2026, Eugene Gershnik
# SPDX-License-Identifier: BSD-3-Clause

"""Standalone tests for mkdaemonuser (not pytest).

Creates real daemon accounts with invented, collision-unlikely names, verifies
them via pwd/grp, and unconditionally removes them afterwards. Must run as root,
since it creates and deletes actual accounts. Run it as:

    sudo ./test.py
"""

# pylint: disable=line-too-long

import grp
import os
import platform
import pwd
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "mkdaemonuser"

# Every shell the tool may pick as a platform default.
LOCKED_SHELLS = {"/bin/false", "/usr/bin/false", "/sbin/nologin", "/usr/sbin/nologin"}

ADMIN_DIRS = ("/usr/sbin", "/sbin", "/usr/bin", "/bin")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _which(name: str) -> str | None:
    """Locate a tool in the admin dirs or PATH (tests may use PATH freely)."""
    search = [*ADMIN_DIRS, *os.environ.get("PATH", "").split(os.pathsep)]
    for directory in search:
        if directory:
            candidate = Path(directory) / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    return None


def _sh(prog: str, *args: str) -> None:
    """Run a tool if it exists, discarding output and ignoring failures."""
    resolved = _which(prog)
    if resolved:
        subprocess.run([resolved, *args], capture_output=True, text=True, check=False)


def _is_alpine() -> bool:
    """Return True on Alpine Linux (BusyBox deluser/delgroup for cleanup)."""
    try:
        contents = Path("/etc/os-release").read_text(encoding="utf-8")
    except OSError:
        return False
    return any(line.strip() == "ID=alpine" for line in contents.splitlines())


def unique_name() -> str:
    """An invented account name unlikely to collide with anything real."""
    return "mkdut" + secrets.token_hex(4)


def run_tool(*args: str) -> subprocess.CompletedProcess:
    """Invoke ../mkdaemonuser with the current interpreter."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, check=False,
    )


def get_pw(name: str) -> pwd.struct_passwd:
    """getpwnam with a few retries to absorb directory-propagation lag."""
    for attempt in range(10):
        try:
            return pwd.getpwnam(name)
        except KeyError:
            if attempt == 9:
                raise
            time.sleep(0.2)
    raise AssertionError("unreachable")


def get_gr(name: str) -> grp.struct_group:
    """getgrnam with a few retries to absorb directory-propagation lag."""
    for attempt in range(10):
        try:
            return grp.getgrnam(name)
        except KeyError:
            if attempt == 9:
                raise
            time.sleep(0.2)
    raise AssertionError("unreachable")


def delete_account(name: str) -> None:
    """Best-effort, platform-specific removal of a user and its group."""
    system = platform.system()
    if system == "Darwin":
        _sh("dscl", ".", "-delete", f"/Users/{name}")
        _sh("dscl", ".", "-delete", f"/Groups/{name}")
    elif system == "Linux" and _is_alpine():
        _sh("deluser", name)
        _sh("delgroup", name)
    elif system in ("FreeBSD", "DragonFly"):
        _sh("pw", "userdel", name)
        _sh("pw", "groupdel", name)
    else:
        # Linux (non-Alpine), OpenBSD, NetBSD, SunOS, Haiku, and fallback.
        _sh("userdel", name)
        _sh("groupdel", name)


def pick_locked_shell() -> str:
    """A locked shell that actually exists, so no tool balks at it."""
    for shell in ("/usr/sbin/nologin", "/sbin/nologin", "/usr/bin/false", "/bin/false"):
        if Path(shell).exists():
            return shell
    return "/bin/false"


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #

def test_basic_creation(home: str) -> None:
    """Default invocation creates a matching user + group with a locked shell."""
    name = unique_name()
    full_name = "Mkdaemonuser Test Account"
    try:
        result = run_tool(name, "-c", full_name, "-d", home)
        assert result.returncode == 0, f"exit={result.returncode} stderr={result.stderr!r}"

        match = re.fullmatch(r"uid=(\d+) gid=(\d+)", result.stdout.strip())
        assert match, f"unexpected stdout: {result.stdout!r}"
        reported_uid, reported_gid = int(match.group(1)), int(match.group(2))

        user = get_pw(name)
        group = get_gr(name)
        assert user.pw_uid == reported_uid, f"uid {user.pw_uid} != reported {reported_uid}"
        assert user.pw_gid == reported_gid, f"gid {user.pw_gid} != reported {reported_gid}"
        assert user.pw_gid == group.gr_gid, f"primary gid {user.pw_gid} != group {group.gr_gid}"
        assert user.pw_dir == home, f"home {user.pw_dir!r} != {home!r}"
        assert user.pw_gecos.split(",", 1)[0] == full_name, f"gecos {user.pw_gecos!r}"
        assert user.pw_shell in LOCKED_SHELLS, f"unexpected shell {user.pw_shell!r}"
    finally:
        delete_account(name)


def test_explicit_shell(home: str) -> None:
    """An explicit --shell is applied verbatim."""
    name = unique_name()
    shell = pick_locked_shell()
    try:
        result = run_tool(name, "-c", "Test", "-d", home, "-s", shell)
        assert result.returncode == 0, f"exit={result.returncode} stderr={result.stderr!r}"
        assert "warning" not in result.stderr, f"unexpected warning: {result.stderr!r}"
        user = get_pw(name)
        assert user.pw_shell == shell, f"shell {user.pw_shell!r} != {shell!r}"
    finally:
        delete_account(name)


def test_already_exists(home: str) -> None:
    """A second run for the same name is rejected without a traceback."""
    name = unique_name()
    try:
        first = run_tool(name, "-c", "Test", "-d", home)
        assert first.returncode == 0, f"setup failed: exit={first.returncode} stderr={first.stderr!r}"

        second = run_tool(name, "-c", "Test", "-d", home)
        assert second.returncode == 1, f"expected exit 1, got {second.returncode}"
        assert "already exists" in second.stderr, f"stderr={second.stderr!r}"
        assert "Traceback" not in second.stderr, "unexpected traceback on operational error"
    finally:
        delete_account(name)


def test_missing_required_argument(home: str) -> None:
    """Omitting a required option is an argparse usage error (exit 2)."""
    name = unique_name()
    try:
        result = run_tool(name, "-d", home)  # missing -c/--comment
        assert result.returncode == 2, f"expected exit 2, got {result.returncode}"
        assert "required" in result.stderr, f"stderr={result.stderr!r}"
        # Nothing should have been created.
        try:
            pwd.getpwnam(name)
            raise AssertionError(f"account {name!r} was unexpectedly created")
        except KeyError:
            pass
    finally:
        delete_account(name)  # belt and suspenders


def test_rejects_invalid_arguments(home: str) -> None:
    """Empty/whitespace values and relative paths are usage errors (exit 2)."""
    good = unique_name()
    cases = [
        (["", "-c", "Test", "-d", home], "empty or whitespace"),                  # empty login
        ([good, "-c", "   ", "-d", home], "empty or whitespace"),                 # whitespace comment
        ([good, "-c", "Test", "-d", "relative/dir"], "absolute path"),            # relative home
        ([good, "-c", "Test", "-d", home, "-s", "bin/false"], "absolute path"),   # relative shell
    ]
    try:
        for argv, needle in cases:
            result = run_tool(*argv)
            assert result.returncode == 2, \
                f"{argv}: expected exit 2, got {result.returncode} (stderr={result.stderr!r})"
            assert needle in result.stderr, f"{argv}: {needle!r} not in {result.stderr!r}"
        # Rejected arguments must never create anything.
        try:
            pwd.getpwnam(good)
            raise AssertionError(f"account {good!r} was unexpectedly created")
        except KeyError:
            pass
    finally:
        delete_account(good)  # belt and suspenders


def test_warns_on_missing_shell(home: str) -> None:
    """An absolute but non-existent shell warns yet still creates the account."""
    name = unique_name()
    missing_shell = "/opt/does/not/exist/nologin"
    try:
        result = run_tool(name, "-c", "Test", "-d", home, "-s", missing_shell)
        assert result.returncode == 0, f"exit={result.returncode} stderr={result.stderr!r}"
        assert "warning" in result.stderr, f"expected a warning, stderr={result.stderr!r}"
        user = get_pw(name)
        assert user.pw_shell == missing_shell, f"shell {user.pw_shell!r} != {missing_shell!r}"
    finally:
        delete_account(name)


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #

TESTS = [
    test_basic_creation,
    test_explicit_shell,
    test_already_exists,
    test_missing_required_argument,
    test_rejects_invalid_arguments,
    test_warns_on_missing_shell,
]

def main() -> int:
    """Run all tests, returning a process exit status (0 = all passed)."""
    if not SCRIPT.exists():
        print(f"cannot find script under test: {SCRIPT}", file=sys.stderr)
        return 2
    if os.geteuid() != 0:
        print("these tests create and delete real accounts; run as root (e.g. sudo).",
              file=sys.stderr)
        return 2

    home = tempfile.mkdtemp(prefix="mkdaemonuser-test-")
    failures = 0
    try:
        for test in TESTS:
            try:
                test(home)
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {test.__name__}: {exc}")
            except Exception as exc:  # pylint: disable=broad-except
                failures += 1
                print(f"ERROR {test.__name__}: {exc!r}")
            else:
                print(f"pass {test.__name__}")
    finally:
        shutil.rmtree(home, ignore_errors=True)

    passed = len(TESTS) - failures
    print(f"\n{passed}/{len(TESTS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
