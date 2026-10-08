"""Test PDF processing and preflight without external services.

Subprocess and HTTP mocks use temporary files to verify replacement and
cleanup behavior. Selected subprocess tests run only the Python
interpreter to check actual stdout and stderr handling.
"""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "ocr_summary.py"
spec = importlib.util.spec_from_file_location("workflow", SCRIPT)
workflow = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = workflow
spec.loader.exec_module(workflow)


class PdfOcrSummaryTests(unittest.TestCase):
    """Verify workflow behavior, CLI settings, and file preservation."""
    def setUp(self):
        """Skip Ollama preflight for tests focused on PDF processing."""
        self.enterContext(patch.object(workflow, "check_ollama"))

    def run_workflow(self, text, response, redo=False, fail_metadata=False, verbose=False,
                     change_original=False, dry_run=False):
        """Run the workflow with simulated OCR and API results.

        The temporary source has a Unicode filename containing spaces.
        Flags
        simulate failures, concurrent changes, and dry-run or verbose
        behavior.
        The fixture verifies output routing and cleanup before
        returning.

        Returns:
            Final source bytes, original bytes, recorded commands, and
            any
            caught exception, which is None when processing succeeds.
        """
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory).resolve() / "Résumé with spaces.pdf"
            original = b"original document"
            pdf.write_bytes(original)
            original_stat = pdf.stat()
            commands = []

            def run(command, **kwargs):
                commands.append(command)
                if command[0] == "pdftotext":
                    self.assertEqual(kwargs["stdout"], subprocess.PIPE)
                    return subprocess.CompletedProcess(command, 0, text, "PDF warning")
                if "--subject" in command:
                    if fail_metadata:
                        return subprocess.CompletedProcess(command, 1, "", "Metadata write failed")
                    Path(command[-1]).write_bytes(b"finished document")
                    if change_original:
                        pdf.write_bytes(b"concurrent modification")
                else:
                    self.assertEqual(command[command.index("--mode") + 1], "redo" if redo else "skip")
                    Path(command[-1]).write_bytes(b"OCR document")
                if verbose:
                    self.assertIsNone(kwargs["stderr"])
                    self.assertIsNone(kwargs["stdout"])
                else:
                    self.assertEqual(kwargs["stderr"], subprocess.PIPE)
                    self.assertEqual(kwargs["stdout"], subprocess.PIPE)
                return subprocess.CompletedProcess(command, 0, "OCR progress", "OCR warning")

            def open_request(request, timeout):
                payload = json.loads(request.data)
                self.assertEqual(payload["model"], "qwen3.5:9b")
                self.assertFalse(payload["think"])
                self.assertFalse(payload["stream"])
                return io.BytesIO(json.dumps(response).encode("utf-8"))

            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.object(workflow.subprocess, "run", side_effect=run), \
                 patch("urllib.request.OpenerDirector.open", side_effect=open_request), \
                 contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                try:
                    workflow.process(pdf, redo=redo, verbose=verbose, dry_run=dry_run)
                    outcome = None
                except Exception as error:
                    outcome = error
            self.assertEqual(list(pdf.parent.iterdir()), [pdf])
            if dry_run and outcome is None:
                self.assertIn(pdf.name, stdout.getvalue())
                self.assertIn("Kanban: Limit work in progress and identify bottlenecks.", stdout.getvalue())
                self.assertEqual(pdf.read_bytes(), original)
                self.assertEqual(pdf.stat().st_mtime_ns, original_stat.st_mtime_ns)
                self.assertEqual(pdf.stat().st_ino, original_stat.st_ino)
                self.assertFalse(any("--subject" in command for command in commands))
            else:
                self.assertEqual(stdout.getvalue(), "")
            if not verbose:
                self.assertEqual(stderr.getvalue(), "")
            elif outcome is None:
                self.assertIn("OCR:", stderr.getvalue())
                if dry_run:
                    self.assertNotIn("Writing PDF Subject", stderr.getvalue())
                else:
                    self.assertIn("Summary:", stderr.getvalue())
            return pdf.read_bytes(), original, commands, outcome

    def answer(self, response=None, reason="stop"):
        """Build a completed API response with a structured summary."""
        return {"done": True, "done_reason": reason,
                "response": response or json.dumps({"summary": "Kanban: Limit work in progress and identify bottlenecks.", "keywords": ["Kanban", "WIP"]})}

    def test_success_and_subject_argument(self):
        contents, original, commands, error = self.run_workflow("Kanban, bottlenecks", self.answer())
        self.assertIsNone(error)
        self.assertNotEqual(contents, original)
        self.assertEqual(len(commands), 3)
        self.assertEqual(commands[-1][commands[-1].index("--subject") + 1], "Kanban: Limit work in progress and identify bottlenecks.")
        self.assertEqual(commands[-1][commands[-1].index("--ocr-engine") + 1], "none")
        self.assertEqual(commands[-1][commands[-1].index("--pdf-renderer") + 1], "fpdf2")

    def test_many_pages_and_redo(self):
        contents, original, commands, error = self.run_workflow("Kanban: Limit work in progress.\n" * 1400, self.answer(), redo=True)
        self.assertIsNone(error)
        self.assertNotEqual(contents, original)

    def test_empty_extracted_text_keeps_original(self):
        contents, original, commands, error = self.run_workflow("\f \n", self.answer())
        self.assertIsNotNone(error)
        self.assertEqual(contents, original)
        self.assertEqual(len(commands), 2)

    def test_invalid_model_output_keeps_original(self):
        contents, original, commands, error = self.run_workflow("Kanban", self.answer(response="bad JSON"))
        self.assertIsNotNone(error)
        self.assertEqual(contents, original)
        self.assertEqual(len(commands), 2)

    def test_truncated_response_keeps_original(self):
        contents, original, commands, error = self.run_workflow("Kanban", self.answer(reason="length"))
        self.assertIsNotNone(error)
        self.assertEqual(contents, original)

    def test_metadata_failure_keeps_original(self):
        contents, original, commands, error = self.run_workflow("Kanban", self.answer(), fail_metadata=True)
        self.assertIsNotNone(error)
        self.assertEqual(contents, original)
        self.assertIn("Metadata write failed", str(error))

    def test_invalid_api_responses_keep_original(self):
        responses = [
            [],
            {"error": "model unavailable"},
            {"done": True, "done_reason": "stop"},
            self.answer(response="[]"),
            self.answer(response='{"summary": 42}'),
            self.answer(response='{"summary": " "}'),
        ]
        for response in responses:
            with self.subTest(response=response):
                contents, original, commands, error = self.run_workflow("Kanban", response)
                self.assertIsInstance(error, workflow.WorkflowError)
                self.assertEqual(contents, original)

    def test_concurrent_change_is_not_overwritten(self):
        contents, original, commands, error = self.run_workflow(
            "Kanban", self.answer(), change_original=True
        )
        self.assertIsInstance(error, workflow.WorkflowError)
        self.assertEqual(contents, b"concurrent modification")

    def test_batch_continues_after_error(self):
        stderr = io.StringIO()
        with patch.object(workflow.sys, "argv", ["script", "first.pdf", "second.pdf"]), \
             patch.object(workflow.shutil, "which", return_value="found"), \
             patch.object(workflow, "process", side_effect=[workflow.WorkflowError("failure"), None]) as process, \
             contextlib.redirect_stderr(stderr):
            self.assertEqual(workflow.main(), 1)
        self.assertEqual(process.call_count, 2)
        self.assertIn("first.pdf", stderr.getvalue())
        self.assertNotIn("second.pdf", stderr.getvalue())

    def test_verbose_success(self):
        contents, original, commands, error = self.run_workflow("Kanban", self.answer(), verbose=True)
        self.assertIsNone(error)

    def test_dry_run_outputs_summary_without_changes(self):
        contents, original, commands, error = self.run_workflow(
            "Kanban", self.answer(), dry_run=True
        )
        self.assertIsNone(error)
        self.assertEqual(contents, original)
        self.assertEqual(len(commands), 2)

    def test_dry_run_with_redo_and_verbose(self):
        contents, original, commands, error = self.run_workflow(
            "Kanban", self.answer(), dry_run=True, redo=True, verbose=True
        )
        self.assertIsNone(error)
        self.assertEqual(contents, original)

    def test_dry_run_failure_has_no_result_or_changes(self):
        contents, original, commands, error = self.run_workflow(
            "Kanban", self.answer(response="invalid JSON"), dry_run=True
        )
        self.assertIsInstance(error, workflow.WorkflowError)
        self.assertEqual(contents, original)

    def test_cli_dry_run(self):
        with patch.object(workflow.shutil, "which", return_value="found"), \
             patch.object(workflow, "process") as process:
            self.assertEqual(workflow.main(["--dry-run", "input.pdf"]), 0)
        self.assertEqual(process.call_args.kwargs, {"dry_run": True, "skip_processed": False})

    def test_real_child_output_silent_on_success(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            workflow.run_command([workflow.sys.executable, "-c", "import sys; print('progress'); print('warning', file=sys.stderr)"])
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_real_child_error_retains_details(self):
        with self.assertRaisesRegex(RuntimeError, "read failed"):
            workflow.run_command([workflow.sys.executable, "-c", "import sys; print('read failed', file=sys.stderr); sys.exit(2)"])

    def test_cli_default_and_verbose_flags(self):
        for flags in ([], ["-v"], ["--verbose"]):
            with patch.object(workflow.sys, "argv", ["script", *flags, "input.pdf"]), \
                 patch.object(workflow.shutil, "which", return_value="found"), \
                 patch.object(workflow, "process") as process:
                self.assertEqual(workflow.main(), 0)
                self.assertEqual(process.call_args.args[1:], (workflow.Settings(), False, bool(flags)))

    def test_cli_error_output_and_status(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(workflow.sys, "argv", ["script", "input.pdf"]), \
             patch.object(workflow.shutil, "which", return_value="found"), \
             patch.object(workflow, "process", side_effect=workflow.WorkflowError("OCR failure details")), \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(workflow.main(), 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("OCR failure details", stderr.getvalue())

    def test_cron_path(self):
        with patch.dict(workflow.os.environ, {"PATH": "/usr/bin:/bin"}), \
             patch.object(workflow.sys, "argv", ["script", "input.pdf"]), \
             patch.object(workflow.shutil, "which", return_value="found"), \
             patch.object(workflow, "process"):
            self.assertEqual(workflow.main(), 0)
            paths = workflow.os.environ["PATH"].split(workflow.os.pathsep)
            self.assertIn(str(Path.home() / ".local/bin"), paths)
            self.assertIn("/opt/homebrew/bin", paths)

    def test_chunk_coverage(self):
        text = "ä" * 15000
        parts = list(workflow.split_text_into_sections(text))
        self.assertEqual("".join(parts), text)
        self.assertLessEqual(max(map(len, parts)), workflow.MAX_SECTION_CHARACTERS)

    def parse_settings(self, *arguments):
        """Parse options and a sample PDF into validated Settings."""
        parser = workflow.build_argument_parser()
        args = parser.parse_args([*arguments, "input.pdf"])
        return workflow.settings_from_arguments(args, parser)

    def test_repeated_and_joined_languages_reach_ocr_separately(self):
        for flags in (("-l", "deu", "-l", "eng"), ("--ocr-language", "deu+eng")):
            with self.subTest(flags=flags):
                settings = self.parse_settings(*flags, "-l", "deu")
                with patch.object(workflow, "run_command") as run:
                    workflow.apply_ocr(Path("input.pdf"), Path("output.pdf"), settings.ocr, False, False)
                command = run.call_args.args[0]
                languages = [command[i + 1] for i, item in enumerate(command) if item == "-l"]
                self.assertEqual(languages, ["deu", "eng"])
                self.assertNotIn("deu+eng", command)

    def test_custom_ocr_settings_reach_external_commands(self):
        settings = self.parse_settings(
            "--recognition-mode", "accurate", "--disable-language-correction",
            "--jobs", "2", "--pdf-renderer", "fpdf2", "--output-type", "pdfa-2",
            "--optimize", "1", "--command-timeout", "30",
            "--ocrmypdf-command", "/custom/ocrmypdf", "--pdftotext-command", "/custom/pdftotext",
        )
        with patch.object(workflow, "run_command", return_value="text") as run:
            workflow.apply_ocr(Path("a.pdf"), Path("b.pdf"), settings.ocr, True, False)
            workflow.extract_pdf_text(Path("b.pdf"), settings.ocr, False)
            workflow.write_pdf_metadata(Path("b.pdf"), Path("c.pdf"), workflow.DocumentSummary("summary", ("topic",)), settings.ocr, False)
        ocr, extraction, metadata = run.call_args_list
        self.assertEqual(ocr.args[0][0], "/custom/ocrmypdf")
        self.assertEqual(extraction.args[0][0], "/custom/pdftotext")
        self.assertIn("--appleocr-disable-correction", ocr.args[0])
        for option, value in (("--jobs", "2"), ("--pdf-renderer", "fpdf2"),
                              ("--appleocr-recognition-mode", "accurate"), ("--mode", "redo")):
            self.assertEqual(ocr.args[0][ocr.args[0].index(option) + 1], value)
        for call in (ocr, extraction, metadata):
            self.assertEqual(call.kwargs["timeout"], 30)
        for call in (ocr, metadata):
            self.assertEqual(call.args[0][call.args[0].index("--output-type") + 1], "pdfa-2")

    def test_custom_model_settings_and_language_reach_request(self):
        settings = self.parse_settings(
            "--model", "qwen3.5:4b", "--ollama-url", "http://localhost:12345/",
            "--timeout", "45", "--context-tokens", "4096", "--max-response-tokens", "512",
            "--temperature", "0.4", "--keep-alive", "0", "--think",
            "--summary-language", "German", "--summary-words", "75",
            "--section-summary-words", "40",
        )
        request = workflow.build_summary_request("content", settings.ollama, settings.summary.document_prompt())
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, "http://localhost:12345/api/generate")
        self.assertEqual(payload["model"], "qwen3.5:4b")
        self.assertEqual(payload["options"], {"num_ctx": 4096, "num_predict": 512, "temperature": 0.4})
        self.assertEqual(payload["keep_alive"], 0)
        self.assertTrue(payload["think"])
        self.assertIn("in German", payload["prompt"])
        self.assertIn("75 words", payload["prompt"])
        self.assertIn("40 words", settings.summary.section_prompt())
        with patch("urllib.request.OpenerDirector.open", return_value=io.BytesIO(json.dumps(self.answer()).encode())) as open_request:
            workflow.request_summary("content", settings.ollama, "instructions")
        self.assertEqual(open_request.call_args.kwargs["timeout"], 45)

    def test_configuration_reaches_batch_processor(self):
        with patch.object(workflow.shutil, "which", return_value="found"), \
             patch.object(workflow, "process") as process:
            self.assertEqual(workflow.main(["-l", "eng", "--summary-language", "German", "input.pdf"]), 0)
        settings = process.call_args.args[1]
        self.assertEqual(settings.ocr.languages, ("eng",))
        self.assertEqual(settings.summary.language, "German")

    def test_summary_language_defaults_to_current_lang(self):
        cases = {
            "de_DE.UTF-8": "de-DE",
            "de_CH.UTF-8": "de-CH",
            "en_GB.UTF-8": "en-GB",
            "fr_FR@euro": "fr-FR",
            "pt_BR.UTF-8": "pt-BR",
            "ja_JP.UTF-8": "ja-JP",
            "de": "de",
            "": "English",
            "C": "English",
            "C.UTF-8": "English",
            "POSIX": "English",
            "not a locale": "English",
        }
        for lang, expected in cases.items():
            with self.subTest(lang=lang), patch.dict(workflow.os.environ, {"LANG": lang}):
                settings = self.parse_settings()
                self.assertEqual(settings.summary.language, expected)
                self.assertEqual(workflow.SummarySettings().language, expected)
                self.assertEqual(workflow.Settings().summary.language, expected)
                self.assertIn(f"in {expected}", settings.summary.document_prompt())
                self.assertIn(f"in {expected}", settings.summary.section_prompt())

    def test_explicit_output_language_overrides_lang(self):
        with patch.dict(workflow.os.environ, {"LANG": "de_DE.UTF-8"}):
            for option in ("--summary-language", "--output-language"):
                with self.subTest(option=option):
                    settings = self.parse_settings(option, "French")
                    self.assertEqual(settings.summary.language, "French")
                    self.assertEqual(settings.ocr.languages, ("deu",))

    def test_unset_lang_falls_back_without_changing_environment(self):
        with patch.dict(workflow.os.environ, {}, clear=True):
            self.assertEqual(self.parse_settings().summary.language, "English")
            self.assertNotIn("LANG", workflow.os.environ)

    def test_model_receives_content_only_instructions(self):
        request = workflow.build_summary_request("source", workflow.OllamaSettings(), "Summarize")
        system = json.loads(request.data)["system"]
        self.assertIn("Omit unreadable or ambiguous details instead of guessing", system)
        self.assertIn("Do not include comments about", system)
        self.assertIn("OCR quality", system)
        self.assertNotIn("Flag relevant uncertainties", system)

    def test_invalid_configuration_rejected_before_processing(self):
        cases = [
            ("--jobs", "0"), ("--section-chars", "-1"), ("--timeout", "nan"),
            ("--temperature", "inf"), ("--temperature", "3"), ("--keep-alive", "forever"),
            ("--summary-language", " "), ("--ollama-url", "file:///tmp/server"),
            ("--ollama-url", "http://localhost:99999"), ("--ollama-url", "http://user:pass@localhost"),
            ("-l", "de"), ("-l", "deu+"), ("-l", "und"),
            ("-l", "und+eng", "--recognition-mode", "accurate"),
            ("--context-tokens", "512", "--max-response-tokens", "512"),
        ]
        for flags in cases:
            with self.subTest(flags=flags), patch.object(workflow, "process") as process, \
                 contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    workflow.main([*flags, "input.pdf"])
                self.assertEqual(error.exception.code, 2)
                process.assert_not_called()

    def test_automatic_language_detection_and_no_think(self):
        settings = self.parse_settings("-l", "und", "--recognition-mode", "accurate", "--no-think", "--keep-alive", "-1")
        self.assertEqual(settings.ocr.languages, ("und",))
        self.assertFalse(settings.ollama.think)
        self.assertEqual(settings.ollama.keep_alive, -1)

    def test_command_timeout_is_reported_without_traceback(self):
        with patch.object(workflow.subprocess, "run", side_effect=subprocess.TimeoutExpired("ocrmypdf", 30)):
            with self.assertRaisesRegex(workflow.WorkflowError, "timed out"):
                workflow.run_command(["ocrmypdf"], timeout=30)

    def test_section_limit_and_round_limit(self):
        self.assertEqual(list(workflow.split_text_into_sections("abcdefg", limit=3)), ["abc", "def", "g"])
        settings = self.parse_settings("--section-chars", "100", "--max-summary-rounds", "1")
        with patch.object(workflow, "request_summary", return_value="x" * 20) as request:
            with self.assertRaisesRegex(workflow.WorkflowError, "Maximum summary rounds"):
                workflow.summarize_document("a" * 1000, settings, False)
        self.assertEqual(request.call_count, 10)


class OllamaPreflightTests(unittest.TestCase):
    """Verify Ollama preflight against simulated server responses."""
    def test_capabilities_and_generation_checked_once_before_batch(self):
        responses = [
            io.BytesIO(json.dumps({"capabilities": ["completion", "thinking"]}).encode()),
            io.BytesIO(json.dumps({"done": True, "done_reason": "stop", "response": "OK"}).encode()),
        ]
        with patch("urllib.request.OpenerDirector.open", side_effect=responses) as open_request, \
             patch.object(workflow.shutil, "which", return_value="found"), \
             patch.object(workflow, "process") as process:
            self.assertEqual(workflow.main(["--context-tokens", "4096", "first.pdf", "second.pdf"]), 0)
        self.assertEqual(process.call_count, 2)
        self.assertEqual([call.args[0] for call in process.call_args_list], [Path("first.pdf"), Path("second.pdf")])
        show, generate = open_request.call_args_list
        self.assertTrue(show.args[0].full_url.endswith("/api/show"))
        payload = json.loads(generate.args[0].data)
        self.assertEqual(payload["model"], workflow.DEFAULT_MODEL)
        self.assertEqual(payload["options"]["num_ctx"], 4096)
        self.assertLessEqual(payload["options"]["num_predict"], 8)
        self.assertNotIn("first.pdf", payload["prompt"])

    def assert_preflight_failure(self, responses):
        """Assert that a startup error prevents all PDF processing.

        Returns:
            Captured stderr for assertions about the reported server
            failure.
        """
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("urllib.request.OpenerDirector.open", side_effect=responses), \
             patch.object(workflow.shutil, "which", return_value="found"), \
             patch.object(workflow, "process") as process, \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(workflow.main(["first.pdf", "second.pdf"]), 1)
        process.assert_not_called()
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue().count("Preflight failed:"), 1)
        return stderr.getvalue()

    def test_unreachable_server_stops_before_ocr(self):
        message = self.assert_preflight_failure([workflow.urllib.error.URLError("connection refused")])
        self.assertIn("connection refused", message)

    def test_missing_model_retains_server_error(self):
        error = workflow.urllib.error.HTTPError(
            "http://localhost:11434/api/show", 404, "Not Found", {},
            io.BytesIO(b'{"error": "model not found"}'),
        )
        self.assertIn("model not found", self.assert_preflight_failure([error]))

    def test_embedding_model_is_rejected(self):
        message = self.assert_preflight_failure([io.BytesIO(b'{"capabilities": ["embedding"]}')])
        self.assertIn("text generation", message)

    def test_load_or_generation_failure_stops_before_ocr(self):
        message = self.assert_preflight_failure([
            io.BytesIO(b'{"capabilities": ["completion"]}'),
            io.BytesIO(b'{"error": "insufficient memory"}'),
        ])
        self.assertIn("insufficient memory", message)

    def test_empty_generation_is_rejected(self):
        self.assertIn("produced no text", self.assert_preflight_failure([
            io.BytesIO(b'{"capabilities": ["completion"]}'),
            io.BytesIO(b'{"done": true, "response": ""}'),
        ]))

    def test_thinking_requires_model_support(self):
        with patch.object(workflow, "send_ollama_request", return_value={"capabilities": ["completion"]}):
            with self.assertRaisesRegex(workflow.WorkflowError, "does not support --think"):
                workflow.check_ollama(workflow.OllamaSettings(think=True), False)


class SkipProcessedTests(unittest.TestCase):
    """Verify that --skip-processed avoids OCR and inference for described files."""

    def process_with_info(self, name, info, **kwargs):
        """Run process() on a placeholder file with mocked metadata output."""
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / name
            source.write_bytes(b"original")
            stat = source.stat()
            with patch.object(workflow, "run_command", return_value=info) as run, \
                 patch.object(workflow, "apply_ocr") as ocr, \
                 patch.object(workflow, "prepare_image") as prepare, \
                 patch.object(workflow, "summarize_document") as summarize:
                workflow.process(source, skip_processed=True, **kwargs)
            self.assertEqual(source.read_bytes(), b"original")
            self.assertEqual(source.stat().st_mtime_ns, stat.st_mtime_ns)
            self.assertEqual(list(source.parent.iterdir()), [source])
            return run, ocr, prepare, summarize

    def test_pdf_with_subject_and_keywords_is_skipped(self):
        info = "Title:          Scan\nSubject:        Eine Beschreibung.\nKeywords:       Kanban, WIP\nPages: 1\n"
        run, ocr, prepare, summarize = self.process_with_info("done.pdf", info)
        self.assertEqual(run.call_args.args[0][0], "pdfinfo")
        ocr.assert_not_called()
        summarize.assert_not_called()

    def test_pdf_missing_either_field_is_processed(self):
        for info in ("Title: Scan\n", "Subject: Text\n", "Keywords: Kanban\n",
                     "Subject:\nKeywords:   \n"):
            with self.subTest(info=info), \
                 tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / "new.pdf"
                source.write_bytes(b"original")
                with patch.object(workflow, "run_command", return_value=info), \
                     patch.object(workflow, "apply_ocr") as ocr, \
                     patch.object(workflow, "extract_pdf_text", return_value="Text"), \
                     patch.object(workflow, "summarize_document",
                                  return_value=workflow.DocumentSummary("S", ("k",))), \
                     patch.object(workflow, "write_pdf_metadata",
                                  side_effect=lambda src, dst, *a: dst.write_bytes(b"new")):
                    workflow.process(source, skip_processed=True)
                ocr.assert_called_once()
                self.assertEqual(source.read_bytes(), b"new")

    def test_image_with_xmp_description_and_keywords_is_skipped(self):
        info = json.dumps([{"SourceFile": "x", "XMP-dc:Description": "Text", "XMP-dc:Subject": ["a"]}])
        run, ocr, prepare, summarize = self.process_with_info("done.JPG", info)
        self.assertEqual(run.call_args.args[0][0], "exiftool")
        prepare.assert_not_called()
        ocr.assert_not_called()
        summarize.assert_not_called()

    def test_image_without_metadata_is_not_skipped(self):
        with patch.object(workflow, "run_command", return_value=json.dumps([{"SourceFile": "x"}])):
            self.assertFalse(workflow.has_image_metadata(Path("x.png"), workflow.Settings(), False))

    def test_unreadable_image_metadata_is_an_error(self):
        with patch.object(workflow, "run_command", return_value="not json"), \
             self.assertRaises(workflow.WorkflowError):
            workflow.has_image_metadata(Path("x.png"), workflow.Settings(), False)

    def test_skip_is_reported_only_when_verbose(self):
        info = "Subject: S\nKeywords: k\n"
        for verbose in (False, True):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                self.process_with_info("done.pdf", info, verbose=verbose)
            self.assertEqual("Skipping" in stderr.getvalue(), verbose)

    def test_cli_passes_flag_and_requires_pdfinfo(self):
        with patch.object(workflow.shutil, "which", return_value="found"), \
             patch.object(workflow, "check_ollama"), \
             patch.object(workflow, "process") as process:
            self.assertEqual(workflow.main(["--skip-processed", "input.pdf"]), 0)
        self.assertTrue(process.call_args.kwargs["skip_processed"])
        with patch.object(workflow.shutil, "which", side_effect=lambda c: None if c == "pdfinfo" else c), \
             patch.object(workflow, "check_ollama"), \
             contextlib.redirect_stderr(io.StringIO()), \
             self.assertRaises(SystemExit) as raised:
            workflow.main(["--skip-processed", "input.pdf"])
        self.assertEqual(raised.exception.code, 2)
        # Without the flag, pdfinfo stays optional.
        with patch.object(workflow.shutil, "which", side_effect=lambda c: None if c == "pdfinfo" else c), \
             patch.object(workflow, "check_ollama"), \
             patch.object(workflow, "process"):
            self.assertEqual(workflow.main(["input.pdf"]), 0)


class VersionTests(unittest.TestCase):
    """Verify --version output and its version sources."""

    def test_version_option_prints_and_exits_without_files(self):
        stdout = io.StringIO()
        with patch.object(workflow, "program_version", return_value="1.2.3"), \
             contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
            workflow.main(["--version"])
        self.assertEqual(raised.exception.code, 0)
        self.assertRegex(stdout.getvalue(), r" 1\.2\.3 \(Python 3\.\d+\.\d+\)\n$")

    def test_checkout_version_matches_pyproject(self):
        expected = workflow.tomllib.loads(
            (SCRIPT.parent / "pyproject.toml").read_text(encoding="utf-8")
        )["project"]["version"]
        with patch.object(
            workflow.importlib.metadata, "version",
            side_effect=workflow.importlib.metadata.PackageNotFoundError,
        ):
            self.assertEqual(workflow.program_version(), expected)

    def test_installed_metadata_takes_precedence(self):
        with patch.object(workflow.importlib.metadata, "version", return_value="9.9.9"):
            self.assertEqual(workflow.program_version(), "9.9.9")


class AppleDoubleTests(unittest.TestCase):
    """Verify that macOS "._" companion files are skipped, not failed."""

    def test_appledouble_files_are_skipped_without_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            companion = Path(directory) / "._Report.pdf"
            companion.write_bytes(workflow.APPLEDOUBLE_MAGIC + b"\x00\x02\x00\x00")
            real = Path(directory) / "Report.pdf"
            real.write_bytes(b"%PDF-1.7")
            stderr = io.StringIO()
            with patch.object(workflow.shutil, "which", return_value="found"), \
                 patch.object(workflow, "check_ollama"), \
                 patch.object(workflow, "process") as process, \
                 contextlib.redirect_stderr(stderr):
                self.assertEqual(workflow.main(["-v", str(companion), str(real)]), 0)
            self.assertEqual([c.args[0] for c in process.call_args_list], [real])
            self.assertIn("Skipping AppleDouble", stderr.getvalue())

    def test_real_file_with_dot_underscore_name_is_processed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "._notes.pdf"
            path.write_bytes(b"%PDF-1.7")
            self.assertFalse(workflow.is_appledouble_file(path))
            self.assertFalse(workflow.is_appledouble_file(Path(directory) / "._missing.pdf"))


class VolumeRetryTests(unittest.TestCase):
    """Verify waiting for an unreachable network volume and resuming."""

    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.source = Path(self.directory) / "Scan.pdf"
        self.source.write_bytes(b"original")
        self.up = True
        self.enterContext(patch.object(workflow, "is_reachable", side_effect=lambda path: self.up))
        self.retry = workflow.RetrySettings(interval=5, timeout=60)

    def run_retry(self, run, seen=None, retry=None, wait=None):
        seen = {self.source.parent} if seen is None else seen
        return workflow.process_with_volume_retry(
            self.source, run, retry or self.retry, seen, False,
            wait=wait or (lambda *args: True),
        )

    def test_file_is_repeated_once_the_volume_returns(self):
        calls = []

        def run():
            calls.append(1)
            if len(calls) == 1:
                self.up = False
                raise OSError(57, "Socket is not connected")

        def wait(path, retry, verbose):
            self.up = True
            return True

        self.run_retry(run, wait=wait)
        self.assertEqual(len(calls), 2)

    def test_unseen_directory_fails_immediately(self):
        self.up = False
        waited = []
        with self.assertRaises(OSError):
            self.run_retry(lambda: (_ for _ in ()).throw(OSError("gone")), seen=set(),
                           wait=lambda *args: waited.append(1))
        self.assertEqual(waited, [])

    def test_zero_timeout_disables_waiting(self):
        def run():
            self.up = False
            raise OSError("gone")

        waited = []
        with self.assertRaises(OSError):
            self.run_retry(run, retry=workflow.RetrySettings(5, 0),
                           wait=lambda *args: waited.append(1))
        self.assertEqual(waited, [])

    def test_failure_on_a_reachable_volume_is_not_retried(self):
        waited = []
        with self.assertRaises(workflow.WorkflowError):
            self.run_retry(lambda: (_ for _ in ()).throw(workflow.WorkflowError("OCR failed")),
                           wait=lambda *args: waited.append(1))
        self.assertEqual(waited, [])

    def test_timeout_raises_volume_unavailable(self):
        def run():
            self.up = False
            raise OSError("gone")

        with self.assertRaises(workflow.VolumeUnavailableError):
            self.run_retry(run, wait=lambda *args: False)

    def test_file_replaced_before_the_outage_is_not_processed_again(self):
        calls = []

        def run():
            calls.append(1)
            # Replacement succeeded, then cleanup lost the volume.
            self.source.write_bytes(b"processed with metadata")
            self.up = False
            raise OSError(5, "Input/output error")

        def wait(path, retry, verbose):
            self.up = True
            return True

        self.run_retry(run, wait=wait)
        self.assertEqual(calls, [1])

    def test_wait_polls_until_reachable_or_deadline(self):
        now = [0.0]
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds

        states = iter([False, False, True])
        with patch.object(workflow, "is_reachable", side_effect=lambda path: next(states)), \
             contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertTrue(workflow.wait_for_volume(
                self.source, self.retry, False, sleep=sleep, clock=lambda: now[0]))
        self.assertEqual(sleeps, [5, 5, 5])
        self.assertIn("waiting up to 60 seconds", stderr.getvalue())
        with patch.object(workflow, "is_reachable", return_value=False), \
             contextlib.redirect_stderr(io.StringIO()):
            now[0] = 0.0
            self.assertFalse(workflow.wait_for_volume(
                self.source, workflow.RetrySettings(25, 60), False,
                sleep=sleep, clock=lambda: now[0]))
        self.assertEqual(now[0], 60.0)

    def test_batch_continues_and_stops_waiting_after_a_timeout(self):
        other = Path(self.directory) / "Other.pdf"
        other.write_bytes(b"x")
        outcomes = []

        def process(path, *args, **kwargs):
            outcomes.append(path.name)
            self.up = False
            raise OSError(57, "Socket is not connected")

        stderr = io.StringIO()
        with patch.object(workflow.shutil, "which", return_value="found"), \
             patch.object(workflow, "check_ollama"), \
             patch.object(workflow, "process", side_effect=process), \
             contextlib.redirect_stderr(stderr):
            status = workflow.main([
                "--retry-timeout", "0.05", "--retry-interval", "0.01",
                str(self.source), str(other),
            ])
        self.assertEqual(status, 1)
        # The first file waits once; the second fails at once instead of waiting again.
        self.assertEqual(stderr.getvalue().count("is unreachable; waiting"), 1)
        self.assertEqual(stderr.getvalue().count("Failed for"), 2)
        self.assertEqual(outcomes, ["Scan.pdf", "Other.pdf"])

    def test_timeout_option_accepts_zero_and_rejects_negative(self):
        self.assertEqual(workflow.nonnegative_seconds("0"), 0.0)
        for value in ("-1", "inf", "nan"):
            with self.assertRaises(workflow.argparse.ArgumentTypeError):
                workflow.nonnegative_seconds(value)


if __name__ == "__main__":
    unittest.main()
