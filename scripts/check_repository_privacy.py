"""Check the Git index (or one commit) without reading local runtime data.

This conservative guard catches common accidental publications, not every kind
of private information. Review prose and newly approved assets before sharing.
Only filenames, line numbers and categories are reported; matched text is never
printed. Use --revision HEAD in CI and the default index check before committing.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from pathlib import PurePosixPath
import re
import subprocess
import sys


MAX_BLOB_BYTES = 1_048_576
RUNTIME_DIRECTORIES = {
    "data", "logs", "build", "dist", "outputs", "backups", "exports",
    ".agents", ".codex", "_internal",
}
ENV_EXAMPLES = {".env.example", ".env.template"}
BLOCKED_SUFFIXES = re.compile(
    r"(?i)(?:\.(?:db|sqlite|sqlite3)(?:[-.].*)?|\.log(?:[.-].*)?|"
    r"\.(?:bak|backup)(?:[.-].*)?|\.(?:dump|sql|zip|7z|rar|tar|gz|exe|dll|pyd|"
    r"pem|key|p12|pfx|kdbx))$"
)
# These existing UI icons were reviewed. A replacement or new binary needs
# manual privacy review before its SHA-256 is added here.
APPROVED_BINARY_SHA256 = {
    "app/resources/icons/arrow-down-gray.png": "ebf81e0dd777a67942e59b0f477b6576c66068886b3a714ee0ddd08887952ee6",
    "app/resources/icons/arrow-down-white.png": "e71435bd51333a617b23670c3153c22056b96a2df8434be5e8443c27f48a0b98",
    "app/resources/icons/arrow-up-gray.png": "8622c19b4052b8e17432708587b2fd4305a3ce94c68cc71643b83eb57f15c86a",
    "app/resources/icons/arrow-up-white.png": "c2337e25086141a4c445604cd851e1de9a44e2d3b0594958b7a6503cdd98fe24",
    "app/resources/icons/sitetask-icon.ico": "c3b0ed9efd70698831c8b1ea99f73a1dbc0557a92a50e11fa4e8fb93bcb8a6a3",
    "app/resources/icons/sitetask-icon.png": "0251048f4e96cf192291ef3757b71a88b6df16c6e08d629333f7f40c9730d115",
}
PATTERNS = (
    ("private key", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")),
    ("credential token", re.compile(
        r"\b(?:sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}|"
        r"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|"
        r"AKIA[A-Z0-9]{16}|xox[baprs]-[A-Za-z0-9-]{20,})\b"
    )),
    ("personal home path", re.compile(
        r"(?i)(?:[A-Z]:[/\\]+Users[/\\]+[^\s/\\<>\"']+|"
        r"/(?:home|Users)/[^\s/<>\"']+)"
    )),
    ("mail message link", re.compile(
        r"https?://mail\.google\.com/[^\s\"'<>]*#[^\s\"'<>]*/"
        r"(?:[a-f0-9]{12,}|[A-Za-z0-9_-]{20,})", re.IGNORECASE
    )),
    ("credential in URL", re.compile(r"https?://[^\s/:@]+:[^\s/@]+@")),
)
EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
PUBLIC_EMAIL_DOMAINS = {"example.com", "example.org", "example.net", "users.noreply.github.com"}


@dataclass(frozen=True)
class Finding:
    path: str
    category: str
    line: int | None = None

    def display(self) -> str:
        # A malicious filename must not inject terminal lines or Actions commands.
        safe_path = self.path
        for _, pattern in PATTERNS:
            safe_path = pattern.sub("[REDACTED]", safe_path)
        safe_path = ascii(EMAIL.sub("[REDACTED EMAIL]", safe_path))
        location = f"{safe_path}:{self.line}" if self.line else safe_path
        return f"{location}: {self.category}"


@dataclass(frozen=True)
class Entry:
    path: str
    oid: str
    mode: str


def path_category(path: str) -> str | None:
    normalized = path.lower()
    parts = PurePosixPath(normalized).parts
    name = parts[-1]
    if any(part in RUNTIME_DIRECTORIES for part in parts[:-1]):
        return "runtime or build data"
    if normalized.startswith("config/") and normalized != "config/settings.example.json":
        return "local configuration or backup"
    if (name == ".env" or name.startswith(".env.")) and name not in ENV_EXAMPLES:
        return "environment file"
    if BLOCKED_SUFFIXES.search(name):
        return "database, log, backup, bundle or credential file"
    if name.startswith(("id_rsa", "id_ed25519", "id_ecdsa")):
        return "SSH credential file"
    if any(part in {"screenshots", "screen-captures"} for part in parts[:-1]):
        return "screenshot requires manual review"
    return None


def check_blob(path: str, content: bytes, mode: str = "100644") -> list[Finding]:
    category = path_category(path)
    if category:
        return [Finding(path, category)]
    if mode not in {"100644", "100755"}:
        return [Finding(path, "symlink or submodule requires manual review")]
    if len(content) > MAX_BLOB_BYTES:
        return [Finding(path, "oversized file requires manual review")]
    if path in APPROVED_BINARY_SHA256:
        if hashlib.sha256(content).hexdigest() == APPROVED_BINARY_SHA256[path]:
            return []
        return [Finding(path, "changed binary requires manual review")]
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return [Finding(path, "unapproved binary requires manual review")]
    if "\x00" in text:
        return [Finding(path, "unapproved binary requires manual review")]
    findings = []
    for number, line in enumerate(text.splitlines(), 1):
        for label, pattern in PATTERNS:
            if pattern.search(line):
                findings.append(Finding(path, label, number))
        if any(match.group(1).lower() not in PUBLIC_EMAIL_DOMAINS for match in EMAIL.finditer(line)):
            findings.append(Finding(path, "personal or organization email", number))
    return findings


def git(*arguments: str, cwd: str | None = None, input_bytes: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", *arguments], cwd=cwd, input=input_bytes, capture_output=True, check=False
    )
    if result.returncode:
        # Git errors can include remote credentials, local paths, or blob content.
        raise RuntimeError("Git inspection failed; check repository/ref availability locally")
    return result.stdout


def entries(cwd: str | None = None, revision: str | None = None) -> list[Entry]:
    if revision is None:
        raw = git("ls-files", "--stage", "-z", cwd=cwd)
    else:
        resolved = git("rev-parse", "--verify", "--end-of-options", revision + "^{commit}", cwd=cwd).strip().decode("ascii")
        raw = git("ls-tree", "-r", "-z", "--full-tree", resolved, cwd=cwd)
    result = []
    for item in raw.split(b"\0"):
        if not item:
            continue
        header, filename = item.split(b"\t", 1)
        fields = header.decode("ascii").split()
        path = filename.decode("utf-8", "surrogateescape")
        if revision is None:
            mode, oid, stage = fields
            if stage != "0":
                raise RuntimeError("Resolve unmerged index entries before the privacy check")
        else:
            mode, _, oid = fields
        result.append(Entry(path, oid, mode))
    return result


def scan(cwd: str | None = None, revision: str | None = None) -> tuple[int, list[Finding]]:
    selected = entries(cwd, revision)
    findings = []
    for entry in selected:
        category = path_category(entry.path)
        if category:
            findings.append(Finding(entry.path, category))
            continue
        if entry.mode not in {"100644", "100755"}:
            findings.append(Finding(entry.path, "symlink or submodule requires manual review"))
            continue
        size = int(git("cat-file", "-s", entry.oid, cwd=cwd))
        if size > MAX_BLOB_BYTES:
            findings.append(Finding(entry.path, "oversized file requires manual review"))
            continue
        findings.extend(check_blob(entry.path, git("cat-file", "blob", entry.oid, cwd=cwd), entry.mode))
    return len(selected), findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", help="scan one commit instead of the index, e.g. HEAD")
    args = parser.parse_args(argv)
    try:
        count, findings = scan(revision=args.revision)
    except (RuntimeError, OSError, ValueError) as error:
        if isinstance(error, RuntimeError):
            print(str(error), file=sys.stderr)
        else:
            print("Privacy inspection could not complete", file=sys.stderr)
        return 2
    for finding in findings:
        print(finding.display())
    if findings:
        print(f"Privacy check failed: {len(findings)} finding(s); matched values omitted.")
        return 1
    print(f"Privacy check passed: {count} Git-tracked files scanned.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
