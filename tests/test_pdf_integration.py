"""End-to-end test of ``ocr-summary *.pdf`` with native OCR and mocked Ollama.

Unlike the other test modules, this one runs the real OCRmyPDF/AppleOCR and
poppler tools on synthetic scanned PDFs. It is skipped where they are missing.
"""

import contextlib
import glob
import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # Pillow is only needed to draw the synthetic scans.
    Image = None

SCRIPT = Path(__file__).resolve().parents[1] / "ocr_summary.py"
spec = importlib.util.spec_from_file_location("pdf_integration_workflow", SCRIPT)
workflow = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = workflow
spec.loader.exec_module(workflow)
# Find pipx and Homebrew tools like the CLI does, so the skip check is accurate.
workflow.configure_command_search_path()

FONT = Path("/System/Library/Fonts/Helvetica.ttc")
REQUIRED_COMMANDS = ("ocrmypdf", "pdftotext", "pdfinfo")

# Each synthetic document is an image-only PDF; the words are chosen to be
# distinctive and easy for OCR to read at this size.
DOCUMENTS = {
    "invoice.pdf": (
        "INVOICE 2024",
        "Customer: Example Garden Supplies",
        "Item: Tomato seedlings",
        "Total amount: 42 euros",
    ),
    "minutes.pdf": (
        "MEETING MINUTES",
        "Topic: Bicycle shelter",
        "Decision: Build before winter",
        "Responsible: Facility team",
    ),
}
# Lowercase words that must survive OCR for the text to count as correct.
EXPECTED_WORDS = {
    "invoice.pdf": ("invoice", "tomato", "seedlings", "garden"),
    "minutes.pdf": ("minutes", "bicycle", "shelter", "winter"),
}


def draw_scanned_pdf(path: Path, lines: tuple[str, ...]) -> None:
    """Write an A4 PDF that contains only a raster image of the text."""
    page = Image.new("RGB", (1654, 2339), "white")  # A4 at 200 dpi
    canvas = ImageDraw.Draw(page)
    font = ImageFont.truetype(str(FONT), 72)
    for index, line in enumerate(lines):
        canvas.text((150, 200 + index * 160), line, fill="black", font=font)
    page.save(path, "PDF", resolution=200.0)


def pdf_text(path: Path) -> str:
    """Extract the text layer of a PDF as lowercase words."""
    output = subprocess.run(
        ["pdftotext", "-enc", "UTF-8", str(path), "-"],
        check=True, capture_output=True, text=True, encoding="utf-8",
    ).stdout
    return " ".join(output.lower().split())


def pdf_subject(path: Path) -> str:
    """Return the Subject field reported by pdfinfo."""
    output = subprocess.run(
        ["pdfinfo", str(path)], check=True, capture_output=True, text=True, encoding="utf-8",
    ).stdout
    for line in output.splitlines():
        if line.startswith("Subject:"):
            return line.partition(":")[2].strip()
    return ""


@unittest.skipUnless(sys.platform == "darwin", "AppleOCR requires macOS")
@unittest.skipIf(Image is None or not FONT.exists(), "Pillow and Helvetica are required")
@unittest.skipUnless(
    all(shutil.which(command) for command in REQUIRED_COMMANDS),
    "OCRmyPDF and poppler are required",
)
class PdfGlobIntegrationTests(unittest.TestCase):
    """Verify ``ocr-summary *.pdf`` on image-only PDFs."""

    def test_glob_of_scanned_pdfs_adds_text_and_metadata(self):
        summary = workflow.DocumentSummary("Synthetic test summary.", ("alpha", "beta"))
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for name, lines in DOCUMENTS.items():
                draw_scanned_pdf(folder / name, lines)
            for name in DOCUMENTS:
                self.assertEqual(pdf_text(folder / name), "", f"{name} must start without text")

            stdout, stderr = io.StringIO(), io.StringIO()
            previous = Path.cwd()
            # The shell expands the pattern, so do the same from the working directory.
            os.chdir(folder)
            try:
                arguments = sorted(glob.glob("*.pdf"))
                self.assertEqual(arguments, sorted(DOCUMENTS))
                with patch.object(workflow, "check_ollama"), \
                     patch.object(workflow, "summarize_document", return_value=summary) as summarize, \
                     contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    status = workflow.main(arguments)
            finally:
                os.chdir(previous)

            self.assertEqual(stderr.getvalue(), "")
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(status, 0)
            # Only the two inputs remain: no temporary files, backups, or sidecars.
            self.assertEqual(sorted(path.name for path in folder.iterdir()), sorted(DOCUMENTS))
            self.assertEqual(summarize.call_count, len(DOCUMENTS))

            for name, words in EXPECTED_WORDS.items():
                with self.subTest(file=name):
                    text = pdf_text(folder / name)
                    for word in words:
                        self.assertIn(word, text)
                    self.assertEqual(pdf_subject(folder / name), summary.summary)


if __name__ == "__main__":
    unittest.main()
