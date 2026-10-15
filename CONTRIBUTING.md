# Contributing

Contributions from people working with or without coding assistants are
welcome. Read README.md for installation and supported behavior, and AGENTS.md
for the project conventions and constraints.

## Development setup

Use Python 3.11 or later. From a repository checkout, run:

```sh
python3 ocr_summary.py --help
python3 -m unittest discover -s tests -v
```

The wrapper has no third-party Python runtime dependencies. Unit tests mock
external commands and Ollama; they can run without native OCR dependencies.
To install the console command from the checkout:

```sh
pipx install .
```

After changes, refresh that installation with `pipx install --force .`, or run
`python3 ocr_summary.py` directly. Follow README.md for the external dependencies
needed to process documents on macOS.

## Making a change

1. Open an issue for substantial behavior changes so the intended result can
   be discussed. Small fixes can be submitted directly.
2. Make a focused change on a branch, preserving original-file safety, quiet
   operation, and dry-run behavior.
3. Add regression coverage when behavior changes. Update documentation for
   new options, dependencies, or user-visible behavior.
4. Run the test suite and check CLI help.
5. Submit a pull request explaining the problem, the resulting behavior, and
   the validation performed. State any checks that remain unverified.

Keep code, prompts, CLI text, and documentation in English. Follow the existing
type hints, immutable configuration classes, and docstring conventions.

## Working with coding assistants

AGENTS.md holds the shared project instructions. CLAUDE.md imports that file
for Claude Code. With other tools, ask the assistant to read AGENTS.md before
changing code if it does not load the file automatically.

Provide the intended behavior and relevant error output in your request.
Review generated changes and their tests before submitting them. No personal
chat history, account configuration, or specific development machine is needed
to work on this project. Keep local preferences outside tracked project files.

## Native integration checks

On macOS, use synthetic or public sample files for representative PDF, JPEG,
PNG, and HEIC inputs. Start with `--dry-run`. Use disposable copies for tests
that write metadata, because normal processing replaces inputs in place.

Check that the descriptions and keywords can be read back, that images retain
their compressed image data, and that failures leave originals unchanged.
ExifTool's ImageDataHash can help compare image payloads. Mocked unit tests do
not validate native decoding, OCR accuracy, or a model's summary quality.

`tests/test_pdf_integration.py` automates one of these checks for PDFs. It draws
two synthetic image-only PDFs, runs `ocr-summary *.pdf` on them with the real
OCRmyPDF, AppleOCR, and Poppler, and mocks only Ollama. It asserts a silent run
with status 0, that the OCR text layer contains the expected words, that Subject
holds the mocked summary, and that no temporary files, backups, or sidecars
remain. It skips itself without macOS, the native tools, Pillow, or Helvetica,
so it needs a Pillow-capable interpreter, for example:

```sh
python3 -m venv .venv && .venv/bin/pip install pillow
.venv/bin/python -m unittest tests.test_pdf_integration -v
```

It does not cover images, `--redo-ocr`, or model quality. GitHub Actions does
not run it; the unit-test job uses Ubuntu, where it always skips.

Do not submit private documents, photographs with personal metadata, machine
paths, credentials, or complete chat logs. Generate sanitized fixtures if a
reproduction needs files. The default ignore rules exclude document and image
inputs; deliberately review any fixture before adding it to version control.

## Publication privacy

Before committing, inspect the staged files and diff. Keep `.env`, local agent
settings, generated files, and operating-system metadata out of the repository.
Git commits also contain author information: choose your intended public author
name and, if desired, your GitHub-provided noreply email before creating commits.
See [GitHub's commit email documentation](https://docs.github.com/en/account-and-profile/how-tos/email-preferences/setting-your-commit-email-address).

## License

This project is licensed under MIT. Submit code and documentation that you have
the right to contribute under the project license; identify any incorporated
third-party material and its license.

## Releasing

Bump `version` in `pyproject.toml`, commit, then push a matching tag such as
`v0.5.0`. `.github/workflows/release.yml` tests, builds the unsigned arm64
PyInstaller binary, and attaches it with a checksum to a GitHub release. Then
update the URL and sha256 in `packaging/homebrew/ocr-summary.rb` and copy it
to the tap repository.
