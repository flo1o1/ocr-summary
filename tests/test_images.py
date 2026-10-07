"""Test image routing, metadata integrity, and final keyword generation."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "ocr_summary.py"
spec = importlib.util.spec_from_file_location("image_workflow", SCRIPT)
workflow = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = workflow
spec.loader.exec_module(workflow)


class ImageWorkflowTests(unittest.TestCase):
    """Verify image preservation and safe mixed-format processing."""

    def exercise_image(self, suffix, dry_run=False, fail=False):
        """Run image orchestration with simulated external tools."""
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / ("Résumé with spaces" + suffix)
            source.write_bytes(b"original image data")
            initial_stat = source.stat()
            result = workflow.DocumentSummary("WIP begrenzen.", ("Kanban", "Engpässe"))

            def write_metadata(original, destination, *args):
                destination.write_bytes(b"image data with metadata")
                if fail:
                    raise workflow.WorkflowError("metadata verification failed")

            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.object(workflow, "prepare_image") as prepare, \
                 patch.object(workflow, "apply_ocr") as ocr, \
                 patch.object(workflow, "extract_pdf_text", return_value="OCR text"), \
                 patch.object(workflow, "summarize_document", return_value=result), \
                 patch.object(workflow, "write_image_metadata", side_effect=write_metadata) as write, \
                 patch.object(workflow, "write_pdf_metadata") as pdf_write, \
                 contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                if fail:
                    with self.assertRaises(workflow.WorkflowError):
                        workflow.process(source, redo=True)
                else:
                    workflow.process(source, redo=True, dry_run=dry_run)
            prepare.assert_called_once()
            self.assertEqual(ocr.call_args.args[3], False)
            self.assertEqual(ocr.call_args.kwargs["image_dpi"], 300)
            pdf_write.assert_not_called()
            self.assertEqual(list(source.parent.iterdir()), [source])
            self.assertEqual(stderr.getvalue(), "")
            if dry_run or fail:
                self.assertEqual(source.read_bytes(), b"original image data")
                self.assertEqual(source.stat().st_ino, initial_stat.st_ino)
                self.assertEqual(source.stat().st_mtime_ns, initial_stat.st_mtime_ns)
            else:
                self.assertEqual(source.read_bytes(), b"image data with metadata")
            if dry_run:
                write.assert_not_called()
                self.assertIn("Keywords: Kanban, Engpässe", stdout.getvalue())
                self.assertIn(result.summary, stdout.getvalue())
            else:
                self.assertEqual(stdout.getvalue(), "")

    def test_all_supported_image_suffixes(self):
        for suffix in (".jpg", ".JPEG", ".png", ".HEIC", ".heif"):
            with self.subTest(suffix=suffix):
                self.exercise_image(suffix)

    def test_image_dry_run_does_not_write_metadata(self):
        self.exercise_image(".heic", dry_run=True)

    def test_metadata_failure_preserves_original(self):
        self.exercise_image(".png", fail=True)

    def test_embedded_xmp_uses_unicode_description_and_keyword_array(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "original.png"
            source.write_bytes(b"pixels")
            destination = Path(directory) / "result.png"
            result = workflow.DocumentSummary("Überblick: Engpässe.", ("WIP", "Engpässe"))
            calls = []

            def run(arguments, *args, **kwargs):
                calls.append(arguments)
                if "-j" in arguments:
                    return json.dumps([{"XMP-dc:Description": result.summary,
                                        "XMP-dc:Subject": list(result.keywords)}])
                return ""

            with patch.object(workflow, "run_command", side_effect=run):
                workflow.write_image_metadata(source, destination, result, workflow.Settings(), False)
            payload = json.loads((destination.parent / "metadata.json").read_text())
            self.assertEqual(payload[0]["XMP-dc:Description-x-default"], result.summary)
            self.assertEqual(payload[0]["XMP-dc:Subject"], ["WIP", "Engpässe"])
            self.assertIn("-overwrite_original_in_place", calls[0])
            self.assertEqual(destination.read_bytes(), source.read_bytes())

    def test_metadata_readback_failure_prevents_success(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "original.jpg"
            source.write_bytes(b"pixels")
            destination = Path(directory) / "result.jpg"
            with patch.object(workflow, "run_command", return_value="[]"):
                with self.assertRaisesRegex(workflow.WorkflowError, "verification failed"):
                    workflow.write_image_metadata(source, destination,
                        workflow.DocumentSummary("Summary", ("topic",)), workflow.Settings(), False)
            self.assertEqual(source.read_bytes(), b"pixels")

    def test_missing_image_tool_stops_before_model_loading(self):
        with patch.object(workflow.shutil, "which", side_effect=lambda name: None if name == "exiftool" else "found"), \
             patch.object(workflow, "check_ollama") as check, \
             contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                workflow.main(["input.heic"])
        self.assertEqual(error.exception.code, 2)
        check.assert_not_called()

    def test_pdf_only_does_not_require_image_tools(self):
        with patch.object(workflow.shutil, "which", side_effect=lambda name: "found" if name in ("ocrmypdf", "pdftotext") else None), \
             patch.object(workflow, "check_ollama"), patch.object(workflow, "process"):
            self.assertEqual(workflow.main(["input.pdf"]), 0)

    def test_mixed_batch_uses_configurable_image_settings(self):
        with patch.object(workflow.shutil, "which", return_value="found"), \
             patch.object(workflow, "check_ollama"), patch.object(workflow, "process") as process:
            self.assertEqual(workflow.main([
                "--image-dpi", "200", "--sips-command", "/custom/sips",
                "--exiftool-command", "/custom/exiftool", "input.pdf", "photo.png", "photo.heic",
            ]), 0)
        self.assertEqual(process.call_count, 3)
        settings = process.call_args.args[1]
        self.assertEqual(settings.image, workflow.ImageSettings("/custom/sips", "/custom/exiftool", 200))


class FinalMetadataTests(unittest.TestCase):
    """Check final response schema and keyword validation."""

    def answer(self, keywords):
        return {"done": True, "done_reason": "stop",
                "response": json.dumps({"summary": "Summary", "keywords": keywords})}

    def test_summary_and_keywords_share_one_final_request(self):
        with patch.object(workflow, "send_ollama_request", return_value=self.answer(["Kanban", "kanban", "  WIP  "])) as send:
            result = workflow.request_document_summary("content", workflow.Settings())
        self.assertEqual(send.call_count, 1)
        payload = json.loads(send.call_args.args[0].data)
        self.assertEqual(payload["format"]["required"], ["summary", "keywords"])
        self.assertEqual(result.keywords, ("Kanban", "WIP"))
        self.assertEqual(result.summary, "Summary")

    def test_invalid_keywords_are_rejected(self):
        for keywords in (None, "topic", [], [""], [42], ["topic"] * 11):
            with self.subTest(keywords=keywords), \
                 patch.object(workflow, "send_ollama_request", return_value=self.answer(keywords)):
                with self.assertRaises(workflow.WorkflowError):
                    workflow.request_document_summary("content", workflow.Settings())

    def test_keyword_limit_reaches_schema_and_prompt(self):
        settings = workflow.Settings(summary=workflow.SummarySettings(keyword_count=5))
        with patch.object(workflow, "send_ollama_request", return_value=self.answer(["topic"])) as send:
            workflow.request_document_summary("content", settings)
        payload = json.loads(send.call_args.args[0].data)
        self.assertEqual(payload["format"]["properties"]["keywords"]["maxItems"], 5)
        self.assertIn("between 1 and 5", payload["prompt"])


if __name__ == "__main__":
    unittest.main()
