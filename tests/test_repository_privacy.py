"""Privacy guard tests use generated examples, never local user data."""
from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.check_repository_privacy import check_blob, Finding, scan


def fake_token() -> str:
    return "gh" + "p_" + "A1b2" * 10


class ContentPolicyTests(unittest.TestCase):
    def test_runtime_configuration_database_and_bundle_paths_are_blocked(self):
        for path in (
            "data/integration/receipts/request.json", "data/nested/task.txt",
            "config/local_queue.json", "config/settings.corrupt-20260101.json",
            "config/settings.json.tmp", "logs/events.txt", ".env", ".env.production",
            "export.sqlite3", "export.db-wal", "export.sql", "copy.bak",
            "app.log.1", "release.zip", "outputs/release/readme.txt",
            "exports/tasks.json", ".agents/session.md", ".codex/memory.md", "_internal/settings.json",
            "keys/private.pem", "id_ed25519", "screenshots/desktop.svg",
        ):
            with self.subTest(path=path):
                self.assertTrue(check_blob(path, b"{}"))

    def test_examples_and_ordinary_source_are_allowed(self):
        for path, content in (
            ("config/settings.example.json", b'{"ai":{"enabled":false}}'),
            (".env.example", b"API_KEY=replace-me"),
            (".env.template", b"API_KEY=replace-me"),
            ("app/database/migrations.py", b"def migrate():\n    pass\n"),
            ("README.md", b"Contact engineer@example.com or 123+developer@users.noreply.github.com"),
            ("example.md", b"https://mail.google.com/mail/u/0/#all/example"),
        ):
            with self.subTest(path=path):
                self.assertEqual([], check_blob(path, content))

    def test_tokens_private_keys_paths_and_mail_links_are_blocked(self):
        windows_path = "C:" + "\\Users\\" + "synthetic-person\\file.txt"
        escaped_windows_path = windows_path.replace("\\", "\\\\")
        unix_path = "/" + "home" + "/synthetic-person/file.txt"
        email = "synthetic-person" + "@" + "internal.invalid"
        message = "https://mail.google.com/mail/u/0/#inbox/" + "0123abcd" * 2
        private_key = "-----BEGIN " + "PRIVATE KEY-----"
        url_password = "https://" + "name:synthetic-password" + "@" + "host.invalid"
        for value in (fake_token(), windows_path, escaped_windows_path, unix_path, email, message, private_key, url_password):
            with self.subTest(kind=value[:5]):
                findings = check_blob("example.txt", ("safe\n" + value).encode())
                self.assertTrue(findings)
                self.assertTrue(all(finding.line == 2 for finding in findings))
                self.assertNotIn(value, "\n".join(finding.display() for finding in findings))

    def test_binary_replacement_and_unknown_binary_require_review(self):
        for path in ("app/resources/icons/sitetask-icon.png", "desktop.png"):
            self.assertTrue(check_blob(path, b"\x89PNG\x00unreviewed"))
        self.assertTrue(check_blob("text.txt", b"hidden\x00content"))
        self.assertTrue(check_blob("link.txt", b"somewhere", "120000"))

    def test_diagnostic_does_not_print_match_or_allow_multiline_injection(self):
        finding = Finding("file\n::warning::text.txt", "credential token", 3)
        self.assertNotIn("\n", finding.display())
        self.assertNotIn(fake_token(), finding.display())
        self.assertNotIn(fake_token(), Finding(fake_token() + ".txt", "credential token").display())


class GitSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sitetask-privacy-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Privacy Test")
        self.git("config", "user.email", "privacy-test@example.com")
        self.git("config", "commit.gpgsign", "false")

    def git(self, *arguments):
        subprocess.run(["git", *arguments], cwd=self.root, check=True, capture_output=True)

    def write(self, filename, value):
        path = self.root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")

    def test_index_scans_staged_blob_even_after_clean_worktree_edit(self):
        self.write("sample.txt", fake_token())
        self.git("add", "sample.txt")
        self.write("sample.txt", "clean replacement")
        count, findings = scan(str(self.root))
        self.assertEqual(1, count)
        self.assertEqual(["credential token"], [finding.category for finding in findings])

    def test_untracked_and_unstaged_private_files_are_not_read(self):
        self.write("sample.txt", "safe tracked content")
        self.git("add", "sample.txt")
        self.write("sample.txt", fake_token())
        self.write("data/sitetask.db", "not a database: must not be opened")
        self.assertEqual((1, []), scan(str(self.root)))

    def test_revision_checks_commit_not_current_index(self):
        self.write("sample.txt", "safe commit")
        self.git("add", "sample.txt")
        self.git("commit", "-qm", "Synthetic safe fixture")
        self.write("sample.txt", fake_token())
        self.git("add", "sample.txt")
        self.assertEqual((1, []), scan(str(self.root), "HEAD"))
        self.assertTrue(scan(str(self.root))[1])

    def test_forced_runtime_file_is_rejected_even_if_gitignore_would_hide_it(self):
        self.write(".gitignore", "data/\n")
        self.write("data/integration/receipts/fixture.json", "{}")
        self.git("add", "-f", "data/integration/receipts/fixture.json")
        self.assertEqual("runtime or build data", scan(str(self.root))[1][0].category)

    def test_repository_ignore_rules_cover_generated_data_and_preserve_example(self):
        policy = Path(__file__).resolve().parents[1] / ".gitignore"
        self.write(".gitignore", policy.read_text(encoding="utf-8"))
        private_paths = (
            "data/integration/receipts/fixture.json", "config/settings.corrupt-20260101.json",
            "config/local_queue.json", "config/settings.json.tmp", "logs/events.txt",
            ".env.production", "exports/tasks.json", "outputs/release.exe",
            ".agents/session.md", ".codex/memory.md", "_internal/package.py",
        )
        for path in private_paths:
            with self.subTest(path=path):
                result = subprocess.run(
                    ["git", "check-ignore", "--no-index", "-q", "--", path],
                    cwd=self.root, capture_output=True,
                )
                self.assertEqual(0, result.returncode)
        for path in ("config/settings.example.json", ".env.example", ".env.template", "app/database/migrations.py"):
            with self.subTest(path=path):
                result = subprocess.run(
                    ["git", "check-ignore", "--no-index", "-q", "--", path],
                    cwd=self.root, capture_output=True,
                )
                self.assertEqual(1, result.returncode)


if __name__ == "__main__":
    unittest.main()
