import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "report-design" / "scripts"


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lint = load_script("lint_report")
archive = load_script("archive_report")


class SecurityTests(unittest.TestCase):
    def test_active_html_is_rejected(self):
        payloads = [
            '<script>alert(1)</script>', '<img src="x" onerror="alert(1)">',
            '<iframe srcdoc="hello"></iframe>', '<object data="file:///secret">',
            '<embed src="https://example.invalid">', '<base href="file:///">',
            '<link rel="stylesheet" href="https://example.invalid/a.css">',
            '<meta http-equiv="refresh" content="0; url=https://example.invalid">',
            '<svg onload="alert(1)"/>',
        ]
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "report.html"
            for payload in payloads:
                with self.subTest(payload=payload):
                    report.write_text(payload, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        lint.validate_static_report(report)

    def test_temporary_files_are_unique_and_csp_is_present(self):
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "report.html"
            report.write_text('<html><head></head><body>ok</body></html>', encoding="utf-8")
            lint.validate_static_report(report)
            first = lint.with_injection(report, "", "", "test")
            second = lint.with_injection(report, "", "", "test")
            self.assertNotEqual(first, second)
            content = first.read_text(encoding="utf-8")
            self.assertIn("Content-Security-Policy", content)
            self.assertIn("default-src", content)
            self.assertEqual(report.read_text(encoding="utf-8"), '<html><head></head><body>ok</body></html>')

    def test_archive_is_private_selective_and_repeatable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            report = root / "report.html"
            report.write_text("first", encoding="utf-8")
            shots = root / "shots"
            shots.mkdir()
            (shots / "report.pdf").write_bytes(b"%PDF-test")
            (shots / "report.desktop.01.png").write_bytes(b"png")
            (shots / "report.env").write_text("private", encoding="utf-8")
            (shots / "report.other.pdf").write_bytes(b"private")
            dest = root / "archives"
            (dest / "v9").mkdir(parents=True)
            (dest / "v10").mkdir()
            target, created = archive.archive(report, shots, dest, "test")
            self.assertTrue(created)
            self.assertEqual(target.parent.name, "v10")
            self.assertEqual(set(p.name for p in target.iterdir()),
                             {"report.html", "report.pdf", "report.desktop.01.png", "archive-info.json"})
            info = json.loads((target / "archive-info.json").read_text(encoding="utf-8"))
            self.assertEqual(info["source_report"], "report.html")
            for item in info["artifacts"]:
                self.assertEqual(archive.sha256(target / item["name"]), item["sha256"])
            again, created = archive.archive(report, shots, dest, "test")
            self.assertFalse(created)
            self.assertEqual(target, again)
            report.write_text("changed", encoding="utf-8")
            changed, created = archive.archive(report, shots, dest, "test")
            self.assertTrue(created)
            self.assertNotEqual(target, changed)
            self.assertEqual((target / "report.html").read_text(encoding="utf-8"), "first")

    def test_archive_requires_destination(self):
        env = dict(os.environ)
        env.pop("OHMYREPORT_ARCHIVE_DIR", None)
        result = subprocess.run([sys.executable, str(SCRIPTS / "archive_report.py"), "absent.html"],
                                env=env, capture_output=True)
        self.assertEqual(result.returncode, 2)

    def test_new_report_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "report.html"
            command = [sys.executable, str(SCRIPTS / "new_report.py"), str(report)]
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
            original = report.read_bytes()
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertEqual(report.read_bytes(), original)

    def test_invalid_modes_fail_instead_of_passing_empty_scan(self):
        result = subprocess.run([sys.executable, str(SCRIPTS / "lint_report.py"),
                                 "absent.html", "--modes", "invalid"], capture_output=True)
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
