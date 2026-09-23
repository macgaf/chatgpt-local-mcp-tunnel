import json
import os
import tempfile
import unittest
from pathlib import Path

from home_readonly_mcp.policy import Policy, PolicyError
from home_readonly_mcp.service import ReadOnlyHomeService


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / "Projects/demo").mkdir(parents=True)
        (self.root / "Projects/demo/a.txt").write_text("hello\nworld\n", encoding="utf-8")
        (self.root / "Projects/demo/.env").write_text("SECRET=x\n", encoding="utf-8")
        (self.root / "Projects/demo/.env.example").write_text("TOKEN=example\n", encoding="utf-8")
        (self.root / ".ssh").mkdir()
        (self.root / ".ssh/id_ed25519").write_text("secret", encoding="utf-8")
        (self.root / "binary.bin").write_bytes(b"abc\x00def")
        self.policy = Policy(root=self.root)
        self.service = ReadOnlyHomeService(self.policy)

    def tearDown(self):
        self.tmp.cleanup()

    def test_normal_file_allowed(self):
        self.assertTrue(self.policy.resolve("Projects/demo/a.txt").allowed)

    def test_ssh_denied(self):
        self.assertFalse(self.policy.resolve(".ssh/id_ed25519").allowed)

    def test_env_denied(self):
        self.assertFalse(self.policy.resolve("Projects/demo/.env").allowed)

    def test_env_example_force_allowed(self):
        d = self.policy.resolve("Projects/demo/.env.example")
        self.assertTrue(d.allowed)
        self.assertEqual(d.reason, "force_allow")

    def test_parent_escape_denied(self):
        with self.assertRaises(PolicyError):
            self.policy.resolve("../outside")

    def test_absolute_outside_denied(self):
        with self.assertRaises(PolicyError):
            self.policy.resolve("/etc/passwd")

    def test_symlink_outside_denied(self):
        outside = Path(self.tmp.name).parent / "outside-home-ro-mcp-test.txt"
        outside.write_text("nope", encoding="utf-8")
        try:
            os.symlink(outside, self.root / "Projects/demo/link")
            with self.assertRaises(PolicyError):
                self.policy.resolve("Projects/demo/link")
        finally:
            outside.unlink(missing_ok=True)

    def test_symlink_inside_allowed(self):
        os.symlink(self.root / "Projects/demo/a.txt", self.root / "Projects/demo/link-in")
        self.assertTrue(self.policy.resolve("Projects/demo/link-in").allowed)

    def test_read_file(self):
        r = self.service.read_file("Projects/demo/a.txt")
        self.assertEqual(r["content"], "hello\nworld\n")

    def test_read_denied_file(self):
        with self.assertRaises(PolicyError):
            self.service.read_file("Projects/demo/.env")

    def test_binary_rejected(self):
        with self.assertRaises(ValueError):
            self.service.read_file("binary.bin")

    def test_listing_hides_denied(self):
        r = self.service.list_directory("Projects/demo")
        names = {e["name"] for e in r["entries"]}
        self.assertIn("a.txt", names)
        self.assertIn(".env.example", names)
        self.assertNotIn(".env", names)

    def test_find_files(self):
        r = self.service.find_files("*.txt", "Projects")
        self.assertIn("Projects/demo/a.txt", r["results"])

    def test_search_text(self):
        r = self.service.search_text("world", "Projects")
        self.assertEqual(r["results"][0]["path"], "Projects/demo/a.txt")
        self.assertEqual(r["results"][0]["line"], 2)

    def test_search_does_not_leak_env(self):
        r = self.service.search_text("SECRET", "Projects")
        self.assertEqual(r["results"], [])

    def test_default_deny_allow_list(self):
        p = Policy(root=self.root, default_policy="deny", allow=["Projects/**"], deny=["**/.env"], force_allow=[])
        self.assertTrue(p.resolve("Projects/demo/a.txt").allowed)
        self.assertFalse(p.resolve("binary.bin").allowed)

    def test_allow_recursive_pattern_includes_directory_itself(self):
        p = Policy(root=self.root, default_policy="deny", allow=["Projects/**"], deny=[], force_allow=[])
        self.assertTrue(p.resolve("Projects").allowed)
        self.assertTrue(p.resolve("Projects/demo/a.txt").allowed)

    def test_deny_wins_over_allow(self):
        p = Policy(root=self.root, default_policy="allow", allow=["Projects/**"], deny=["Projects/**/.env"], force_allow=[])
        self.assertFalse(p.resolve("Projects/demo/.env").allowed)

    def test_force_allow_wins_over_deny(self):
        p = Policy(root=self.root, default_policy="allow", allow=[], deny=["Projects/**/.env.example"], force_allow=["Projects/**/.env.example"])
        self.assertTrue(p.resolve("Projects/demo/.env.example").allowed)

    def test_file_info_sha(self):
        r = self.service.file_info("Projects/demo/a.txt")
        self.assertEqual(len(r["sha256"]), 64)

    def test_partial_read(self):
        r = self.service.read_file("Projects/demo/a.txt", 2, 2)
        self.assertEqual(r["content"], "world\n")

    def test_listing_skips_symlink_outside(self):
        outside = Path(self.tmp.name).parent / "outside-home-ro-mcp-list.txt"
        outside.write_text("needle", encoding="utf-8")
        try:
            os.symlink(outside, self.root / "Projects/demo/out-link")
            r = self.service.list_directory("Projects/demo")
            self.assertNotIn("out-link", {e["name"] for e in r["entries"]})
            r2 = self.service.search_text("needle", "Projects")
            self.assertEqual(r2["results"], [])
        finally:
            outside.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
