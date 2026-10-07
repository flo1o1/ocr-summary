# Project instructions

## Purpose and layout

OCR Summary is a macOS CLI that extracts text with Apple OCR, summarizes it
with a local Ollama model, and embeds a description and keywords in the input
file. Supported formats are PDF, JPEG, PNG, HEIC, and HEIF.

- `ocr_summary.py`: implementation, configuration dataclasses, and CLI.
- `ocr-summary`: executable launcher for a repository checkout.
- `pyproject.toml`: packaging and installed console command.
- `tests/`: standard-library unittest suite with mocked external services.
- `README.md`: authoritative installation, options, and user-facing behavior.
- `CONTRIBUTING.md`: development workflow and contribution requirements.

Read the relevant implementation and tests before making changes. Use relative
repository paths in documentation and examples. Keep these instructions useful
to any coding assistant; tool-specific additions belong in its adapter file.

## Development commands

Run from the repository root:

```sh
python3 -m unittest discover -s tests -v
python3 ocr_summary.py --help
```

Python 3.11 or later is required. Unit tests do not need OCRmyPDF, ExifTool,
macOS frameworks, or a running Ollama server. Installing the CLI with
`pipx install .` requires the packaging build dependencies. See README.md for
the separate native OCR and inference dependencies.

## Behavioral requirements

- Keep original paths and filenames. Process mixed batches sequentially and
  continue after individual file failures.
- Create temporary working files beside the input. Replace the original only
  after successful processing and the concurrent-change check. Clean up
  temporary files on normal completion and handled failures.
- Do not leave permanent backups, text sidecars, or XMP sidecars.
- `--dry-run` performs OCR and inference and prints the result without changing
  the input. Normal success is silent; errors go to stderr. `--verbose` enables
  progress and generated metadata.
- Preserve existing PDF text by default. `--redo-ocr` replaces invisible OCR
  text. Write PDF descriptions to Subject and keywords to Keywords.
- Image conversion is for temporary OCR input only. Write metadata to a copy
  of the original format using ExifTool; retain compressed image data. Store
  the description in `XMP-dc:Description-x-default` and keywords in
  `XMP-dc:Subject`. Verify readback before replacing the source.
- Check Ollama availability and actual model generation before the batch.
  Keep the default model `qwen3.5:9b` configurable.
- Keep OCR language independent of output language. Derive output language
  from LANG unless overridden; use English for missing or unusable locales.
- Generate the final summary and keywords in one LLM request. Apply contextual
  OCR correction only to the final prompt, not section condensation requests.
- Do not invent ambiguous facts or include generic OCR-quality disclaimers.
- Preserve exit statuses: 0 success, 1 workflow failure, 2 invalid arguments
  or missing required commands.

## Code and tests

Keep the runtime wrapper limited to the Python standard library. Prefer focused
functions, immutable settings dataclasses, explicit configuration, and type
hints. Use English CLI messages, prompts, documentation, and PEP 257 docstrings
with Google-style sections where useful. Explain decisions in comments.

Add meaningful regression tests for behavioral changes. Run the applicable
tests and update README.md when CLI behavior or configuration changes. Report
what was actually checked; mocked tests do not establish native OCR or model
quality. Do not process a contributor's private documents as test fixtures.

The PDF metadata-only pass uses the null OCR engine and the fpdf2 renderer;
pages without text do not work with the null engine's sandwich renderer.

## Privacy and limitations

Do not commit personal paths, machine details, credentials, private documents,
chat transcripts, or local agent settings. Use synthetic fixtures when needed.
Keep configuration examples generic. Do not add paid services or replace local
inference with remote inference as a default.

Atomic replacement changes the inode; the fingerprint check is not a lock.
Filesystem extended attributes and Finder tags are not explicitly preserved.
Images receive metadata, not a searchable text layer. Summary word budgets are
prompt instructions, not strict post-generation limits. Native OCR and HEIC
decoding require separate checks on macOS; do not imply unit tests verify them.
