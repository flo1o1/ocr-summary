"""Guard every CLI option and the launcher against environment regressions.

The unit tests import the module inside the interpreter running the suite,
so they cannot notice a launcher that fails to start for users, for example
because of a module missing in an older Python. These tests execute the real
launcher in subprocesses, once per option and once per available supported
interpreter, and fail when a new option has no regression sample.
"""
import argparse
import importlib.util
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "ocr-summary"
SCRIPT = ROOT / "ocr_summary.py"
MINIMUM_PYTHON = (3, 11)  # Keep in sync with requires-python in pyproject.toml.
LAUNCH_TIMEOUT_SECONDS = 60

spec = importlib.util.spec_from_file_location("workflow_cli", SCRIPT)
workflow = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = workflow
spec.loader.exec_module(workflow)

# One valid sample per option string: (argument, destination, expected value).
# Flags without a value use None as the argument. A new option without an
# entry fails test_every_option_has_a_sample, which forces a sample here.
SAMPLES: dict[str, tuple[str | None, str, object]] = {
    "-l": ("eng+deu", "ocr_language", [("eng", "deu")]),
    "--ocr-language": ("eng", "ocr_language", [("eng",)]),
    "--language": ("fra", "ocr_language", [("fra",)]),
    "--recognition-mode": ("accurate", "recognition_mode", "accurate"),
    "--disable-language-correction": (None, "disable_language_correction", True),
    "--pdf-renderer": ("fpdf2", "pdf_renderer", "fpdf2"),
    "--jobs": ("2", "jobs", 2),
    "--output-type": ("pdfa-2", "output_type", "pdfa-2"),
    "--optimize": ("1", "optimize", 1),
    "--ocrmypdf-command": ("custom-ocrmypdf", "ocrmypdf_command", "custom-ocrmypdf"),
    "--pdftotext-command": ("custom-pdftotext", "pdftotext_command", "custom-pdftotext"),
    "--pdfinfo-command": ("custom-pdfinfo", "pdfinfo_command", "custom-pdfinfo"),
    "--command-timeout": ("30", "command_timeout", 30.0),
    "--image-dpi": ("150", "image_dpi", 150),
    "--sips-command": ("custom-sips", "sips_command", "custom-sips"),
    "--exiftool-command": ("custom-exiftool", "exiftool_command", "custom-exiftool"),
    "--model": ("example:1b", "model", "example:1b"),
    "--ollama-url": ("http://localhost:1234/", "ollama_url", "http://localhost:1234"),
    "--timeout": ("45", "timeout", 45.0),
    "--context-tokens": ("4096", "context_tokens", 4096),
    "--max-response-tokens": ("512", "max_response_tokens", 512),
    "--temperature": ("0.5", "temperature", 0.5),
    "--keep-alive": ("5m", "keep_alive", "5m"),
    "--think": (None, "think", True),
    "--no-think": (None, "think", False),
    "--summary-language": ("German", "summary_language", "German"),
    "--output-language": ("fr-FR", "summary_language", "fr-FR"),
    "--summary-words": ("80", "summary_words", 80),
    "--section-summary-words": ("60", "section_summary_words", 60),
    "--section-chars": ("3000", "section_chars", 3000),
    "--max-summary-rounds": ("3", "max_summary_rounds", 3),
    "--keyword-count": ("5", "keyword_count", 5),
    "-v": (None, "verbose", True),
    "--verbose": (None, "verbose", True),
    "--redo-ocr": (None, "redo_ocr", True),
    "--retry-timeout": ("0", "retry_timeout", 0.0),
    "--retry-interval": ("2", "retry_interval", 2.0),
    "--skip-processed": (None, "skip_processed", True),
    "--dry-run": (None, "dry_run", True),
}
# Actions that print and exit; covered by dedicated launcher tests below.
EXIT_OPTIONS = {"-h", "--help", "--version"}


def option_strings() -> set[str]:
    """Return every option string registered on the real parser."""
    parser = workflow.build_argument_parser()
    return {
        option
        for action in parser._actions
        for option in action.option_strings
    } - EXIT_OPTIONS


def launch(*arguments: str, interpreter: str | None = None):
    """Run the launcher as a user would and capture its output.

    Without an interpreter the launcher's shebang decides, exactly like a
    symlink in a PATH directory does.
    """
    command = [str(LAUNCHER), *arguments]
    if interpreter:
        command = [interpreter, *command]
    return subprocess.run(
        command, capture_output=True, text=True, timeout=LAUNCH_TIMEOUT_SECONDS
    )


def supported_interpreters() -> list[str]:
    """Find python3.N executables at or above the supported minimum."""
    found = []
    for minor in range(MINIMUM_PYTHON[1], 20):
        path = shutil.which(f"python3.{minor}")
        if path:
            found.append(path)
    return found


class OptionRegressionTests(unittest.TestCase):
    """Check each option parses and survives a real launcher start."""

    def test_every_option_has_a_sample(self):
        """A new option must come with a regression sample."""
        self.assertEqual(option_strings(), set(SAMPLES))

    def test_every_option_parses_to_the_expected_value(self):
        """Parse each sample in-process and compare the stored value."""
        parser = workflow.build_argument_parser()
        for option, (argument, destination, expected) in SAMPLES.items():
            with self.subTest(option=option):
                argv = [option] if argument is None else [option, argument]
                args = parser.parse_args([*argv, "input.pdf"])
                self.assertEqual(getattr(args, destination), expected)

    def test_every_option_is_accepted_by_the_launcher(self):
        """Start the launcher once per option; --help ends after parsing.

        Arguments are parsed left to right, so a rejected value exits with
        status 2 before --help prints, and an import-time crash exits with
        status 1.
        """
        for option, (argument, _, _) in SAMPLES.items():
            with self.subTest(option=option):
                argv = [option] if argument is None else [option, argument]
                result = launch(*argv, "--help")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage:", result.stdout)

    def test_invalid_values_are_rejected_with_status_two(self):
        """Validators must keep rejecting bad input with exit status 2."""
        invalid = [
            ("--jobs", "0"), ("--optimize", "9"), ("--temperature", "3"),
            ("--ollama-url", "ftp://host"), ("--keep-alive", "soon"),
            ("--ocr-language", "english"), ("--recognition-mode", "slow"),
            ("--retry-timeout", "-1"), ("--model", " "),
        ]
        for option, value in invalid:
            with self.subTest(option=option):
                result = launch(option, value, "--help")
                self.assertEqual(result.returncode, 2, result.stdout)


class LauncherRegressionTests(unittest.TestCase):
    """Check that the checkout launcher starts in user-like conditions."""

    def test_shebang_pins_no_minor_version(self):
        """Users run the launcher through a PATH symlink and its shebang."""
        first_line = LAUNCHER.read_text(encoding="utf-8").splitlines()[0]
        self.assertRegex(first_line, r"^#!/usr/bin/env python3?$")

    def test_launcher_is_executable(self):
        self.assertTrue(LAUNCHER.stat().st_mode & 0o111)

    def test_version_and_help_run_through_the_shebang(self):
        """Execute the launcher directly, as a symlink in PATH would."""
        version = launch("--version")
        self.assertEqual(version.returncode, 0, version.stderr)
        self.assertRegex(version.stdout, r"^ocr-summary \S+ \(Python 3\.\d+\.\d+\)")
        self.assertNotIn("unknown", version.stdout)
        self.assertEqual(launch("--help").returncode, 0)

    def test_missing_files_argument_exits_with_status_two(self):
        self.assertEqual(launch().returncode, 2)

    def test_launcher_starts_on_every_available_supported_python(self):
        """Run --version on each installed interpreter from the minimum up.

        Interpreters that are not installed are skipped here; the CI matrix
        covers the supported range.
        """
        interpreters = supported_interpreters()
        if not interpreters:
            self.skipTest("no python3.N interpreter found on PATH")
        for interpreter in interpreters:
            with self.subTest(interpreter=interpreter):
                result = launch("--version", interpreter=interpreter)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_launcher_survives_a_missing_tomllib(self):
        """Simulate an interpreter without tomllib, as Python 3.9 and 3.10.

        The checkout version lookup is the only tomllib user and must degrade
        to "unknown" instead of crashing the launcher at import time.
        """
        blocker = (
            "import importlib.abc, runpy, sys\n"
            "class Block(importlib.abc.MetaPathFinder):\n"
            "    def find_spec(self, name, path=None, target=None):\n"
            "        if name == 'tomllib':\n"
            "            raise ModuleNotFoundError(\"No module named 'tomllib'\")\n"
            "sys.meta_path.insert(0, Block())\n"
            "sys.modules.pop('tomllib', None)\n"
            f"sys.argv = [{str(LAUNCHER)!r}, '--version']\n"
            f"sys.path.insert(0, {str(ROOT)!r})\n"
            f"runpy.run_path({str(LAUNCHER)!r}, run_name='__main__')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", blocker],
            capture_output=True, text=True, timeout=LAUNCH_TIMEOUT_SECONDS,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("unknown", result.stdout)

    def test_source_parses_with_the_minimum_python_grammar(self):
        """Reject syntax newer than the declared minimum version."""
        import ast
        for path in (SCRIPT, LAUNCHER):
            with self.subTest(path=path.name):
                ast.parse(
                    path.read_text(encoding="utf-8"),
                    feature_version=MINIMUM_PYTHON,
                )

    def test_minimum_python_matches_pyproject(self):
        """Keep this suite's minimum aligned with the packaged one."""
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'requires-python\s*=\s*">=(\d+)\.(\d+)"', text)
        self.assertIsNotNone(match)
        self.assertEqual((int(match[1]), int(match[2])), MINIMUM_PYTHON)


if __name__ == "__main__":
    unittest.main()
