# OCR Summary

A small macOS command-line tool that extracts text from PDFs and images with
Apple OCR, generates a summary and keywords with a local Ollama model, and
stores the result inside the original file's metadata.

Supported inputs are **PDF, JPEG (.jpg/.jpeg), PNG, HEIC, and HEIF**. PDFs receive
an OCR text layer, Subject, and Keywords. Images keep their original format and
compressed image data; the description and keyword list are embedded as XMP.

Successful runs replace each input at its existing path. No permanent copies,
XMP sidecars, or text sidecars are created. Normal operation is silent; errors go to stderr.
Use `--dry-run` to inspect the generated summary without changing the input file.

The interface and prompts are in English. OCR defaults to German (`deu`). The
summary language is derived from `$LANG` unless explicitly overridden. For
example, `de_DE.UTF-8` selects German (`de-DE`). Both languages can be changed
on the command line.

## Features

- Apple Live Text OCR through OCRmyPDF and its AppleOCR plugin.
- Local summaries and keywords using `qwen3.5:9b` by default, with an optional model override.
- Existing PDF text preserved by default; optional replacement of invisible OCR text.
- Mixed PDF and image batches processed sequentially; a failed file does not stop the batch.
- Ollama availability and model generation checked before processing the batch.
- Long documents summarized in sections, then condensed into a final summary.
- Temporary files cleaned up and originals replaced only after successful processing.
- Image metadata read back and checked before the original is replaced.
- Optional `--skip-processed` to leave files with an embedded description and keywords untouched.
- Dry-run and verbose modes, suitable for manual use and scheduled jobs.
- Standard-library-only Python script; no additional Python packages for the wrapper.

## Requirements

- macOS 13 or later for the selected Live Text recognition mode.
- Python 3.11 or later.
- [OCRmyPDF](https://ocrmypdf.readthedocs.io/en/latest/installation.html) 17 or later.
- [OCRmyPDF-AppleOCR](https://github.com/mkyt/OCRmyPDF-AppleOCR) 0.4 or later,
  installed into the same Python environment as OCRmyPDF.
- Poppler's `pdftotext` command, and `pdfinfo` when using `--skip-processed` with PDFs.
- [ExifTool](https://exiftool.org/) for writing image metadata.
- macOS `sips` (already included) for temporary image conversion.
- [Ollama](https://ollama.com/) running locally, with the selected model downloaded.
- Read access to the input file and write access to its containing directory, including
  for dry runs, which create temporary working files there.

Model memory use depends on model size, context size, and other running applications. If
memory is tight, use `--model qwen3.5:4b` after downloading that model.

This tool uses Apple's proprietary OCR frameworks included with macOS. The
wrapper and AppleOCR plugin are open source; no paid OCR subscription is required.

## Installation

Download or clone this repository, then open a terminal in its directory.

Install the command-line dependencies with Homebrew and pipx:

```sh
brew install python pipx poppler ollama exiftool
brew install --only-dependencies ocrmypdf
pipx install 'ocrmypdf>=17'
pipx inject ocrmypdf 'ocrmypdf-appleocr>=0.4'
pipx ensurepath --prepend
```

Install OCR Summary from this repository directory:

```sh
pipx install .
```

The tool then runs as `ocr-summary`, without specifying a script path. To update
an existing installation from this checkout, use `pipx install --force .`.
Alternatively, run `./ocr-summary` or `python3 ocr_summary.py` directly from the
repository without installing this wrapper.

Open a new terminal so PATH changes take effect. If you previously installed
OCRmyPDF itself through Homebrew, remove that competing installation while
keeping its dependencies:

```sh
HOMEBREW_NO_AUTOREMOVE=1 brew uninstall ocrmypdf
```

Run that removal command only when the Homebrew formula is actually installed.
Check which OCRmyPDF will run:

```sh
command -v ocrmypdf
ocrmypdf --version
ocrmypdf --help
```

The selected executable should be the pipx installation, normally under
`~/.local/bin`. Help output should include `--appleocr-recognition-mode`.

Start Ollama as a background service and download the default model:

```sh
brew services start ollama
ollama pull qwen3.5:9b
```

If Ollama is already running, keep using that instance. Alternatively, run
`ollama serve` in a separate terminal. Setup downloads require internet access;
document processing defaults to the local endpoint at `127.0.0.1:11434` and bypasses
configured HTTP proxies. Setting `--ollama-url` to a remote server sends extracted
document text to that server.

## Quick start

Preview the summary first. This performs OCR and model inference on temporary
files, prints the filename, summary, and keywords, and leaves the original unchanged:

```sh
ocr-summary --dry-run "Workshop notes.pdf"
```

Process a PDF and replace it at its original path:

```sh
ocr-summary "Workshop notes.pdf"
```

Process one image, preserving its original image format:

```sh
ocr-summary --dry-run "Flipchart.heic"
ocr-summary "Flipchart.heic"
```

Process a mixed batch of explicitly named inputs:

```sh
ocr-summary "Workshop notes.pdf" "Flipchart.jpg" "Whiteboard.png" "Notes.heic"
```

Process all matching PDFs in the current directory:

```sh
ocr-summary ./*.pdf
```

Pass several files explicitly, with the same settings applied to every file:

```sh
ocr-summary -l deu -l eng --summary-language German "Workshop notes.pdf" "Project review.pdf"
```

Or preview all matching PDFs:

```sh
ocr-summary --dry-run --ocr-language deu+eng --summary-language German ./*.pdf
```

Matching is performed by your shell; processing is not recursive. Files are
processed sequentially, and failures do not prevent later files from being attempted.

## Options

```text
ocr-summary [options] FILE [FILE ...]
```

All settings have defaults. Use `--help` to see their current values.

### OCR and PDF output

| Option | Default | Behavior |
| --- | --- | --- |
| `-l`, `--ocr-language`, `--language CODE` | `deu` | Three-letter OCR codes; repeat the option or join codes with `+`. |
| `--recognition-mode MODE` | `livetext` | Choose `livetext`, `accurate`, or `fast`. |
| `--disable-language-correction` | Off | Disable Apple OCR's language correction. |
| `--pdf-renderer RENDERER` | `sandwich` | Choose `sandwich` or `fpdf2`. |
| `--jobs N` | `4` | Number of parallel OCR workers. |
| `--output-type TYPE` | `pdf` | Choose `pdf`, `pdfa`, `pdfa-1`, `pdfa-2`, or `pdfa-3`. |
| `--optimize LEVEL` | `0` | OCRmyPDF optimization level, from `0` through `3`. |
| `--ocrmypdf-command PATH` | `ocrmypdf` | Executable name or path, without embedded arguments. |
| `--pdftotext-command PATH` | `pdftotext` | Executable name or path, without embedded arguments. |
| `--pdfinfo-command PATH` | `pdfinfo` | Executable name or path, without embedded arguments; used only by `--skip-processed`. |
| `--command-timeout SECONDS` | Unlimited | Timeout for each OCR, extraction, or metadata subprocess. |

Languages are passed separately to the AppleOCR plugin: `-l deu+eng` becomes
`-l deu -l eng`. An explicit language selection replaces the default; repeated
codes are deduplicated. Availability depends on the installed macOS version and
recognition mode. See the [AppleOCR language documentation](https://github.com/mkyt/OCRmyPDF-AppleOCR#supported-languages).

For automatic language detection, select `und` on its own and use `accurate` or
`fast`; `livetext` does not support automatic detection:

```sh
ocr-summary -l und --recognition-mode accurate "Workshop notes.pdf"
```

PDF/A conversion and higher optimization levels can require additional
OCRmyPDF dependencies. The defaults use ordinary PDF output with optimization
disabled. The output and optimization settings apply to both PDF-writing passes.

### Images

| Option | Default | Behavior |
| --- | --- | --- |
| `--image-dpi N` | `300` | Resolution assigned to the temporary PNG used for OCR. |
| `--sips-command PATH` | `sips` | Native macOS image conversion executable name or path. |
| `--exiftool-command PATH` | `exiftool` | Image metadata executable name or path. |

Conversion creates a temporary PNG and OCR PDF; neither replaces the original
image. The original JPEG, PNG, HEIC, or HEIF is copied for metadata writing.
No OCR text layer is embedded in image formats.

### Ollama

| Option | Default | Behavior |
| --- | --- | --- |
| `--model NAME` | `qwen3.5:9b` | Installed Ollama model to use. |
| `--ollama-url URL` | `http://127.0.0.1:11434` | Server base URL; `/api/generate` is appended. |
| `--timeout SECONDS` | `1800` | Timeout for each model request. |
| `--context-tokens N` | `8192` | Model context size in tokens. |
| `--max-response-tokens N` | `1536` | Maximum generated tokens per request; must be smaller than the context size. |
| `--temperature NUMBER` | `0.2` | Sampling temperature between `0` and `2`. |
| `--keep-alive VALUE` | `10m` | Retention duration such as `30s` or `1h`; `0` unloads, `-1` keeps the model loaded. |
| `--think`, `--no-think` | Off | Enable or disable thinking, where the chosen model supports it. |

### Summarization

| Option | Default | Behavior |
| --- | --- | --- |
| `--summary-language NAME`, `--output-language NAME` | Derived from `$LANG` | Output name or language tag for final and intermediate summaries; an explicit value overrides the environment. |
| `--summary-words N` | `150` | Requested maximum final summary words. |
| `--section-summary-words N` | `100` | Requested maximum words per intermediate summary. |
| `--section-chars N` | `6000` | Maximum input characters per section. |
| `--max-summary-rounds N` | `10` | Maximum condensation rounds before reporting a failure. |
| `--keyword-count N` | `10` | Maximum keywords generated together with the final summary. |

Word limits are model instructions. Character counts are not token counts;
choose section size and context size together so the input, instructions, and
response fit. Larger context sizes increase memory use. With thinking enabled,
the response token budget must also accommodate the model's thinking.

Without an explicit output language, POSIX locales are converted to language
tags, dropping encoding and modifier suffixes: `de_DE.UTF-8` becomes `de-DE`,
and `en_GB.UTF-8` becomes `en-GB`. When `$LANG` is unset, malformed, `C`, or
`POSIX`, the fallback is English. This does not change the process locale or
the OCR language. For cron jobs, set `LANG=de_DE.UTF-8` in the environment or
pass `--output-language German` explicitly.

The model is instructed to summarize only supported document content and omit
unreadable details. It is instructed to exclude comments about OCR quality,
uncertainty, legibility, missing information, and the summarization process.
Obvious OCR errors may be corrected in the final summary only when the intended form
is unambiguous from context, using recurring spellings as supporting evidence.
Names, numbers, dates, and facts must not be invented; unclear details are
omitted. OCR correction is requested only for the final summary; intermediate
summaries do not receive correction instructions. The PDF's OCR text layer is
not rewritten by the LLM.
If it returns no usable summary, the script reports an error and preserves the
original file. These content instructions apply to all summary requests; they
are not a deterministic filter for every possible model response.

### Execution

| Option | Behavior |
| --- | --- |
| `-v`, `--verbose` | Show progress, subprocess output, section-condensation details, and the summary. |
| `--redo-ocr` | Replace an existing invisible PDF OCR text layer while preserving visible text; ignored for images. |
| `--retry-timeout SECONDS` | Longest wait per outage when a network volume becomes unreachable, default `3600`; `0` fails the file immediately. |
| `--retry-interval SECONDS` | Pause between availability checks while waiting, default `30`. |
| `--skip-processed` | Skip files that already have both a description and keywords: PDF Subject and Keywords, or image `XMP-dc:Description` and `XMP-dc:Subject`. Skipped files get no OCR or model request and are reported only with `--verbose`. |
| `--dry-run` | Print each filename, summary, and keyword list without modifying the originals. |
| `--version` | Print the program and Python version, then exit. |
| `-h`, `--help` | Show command-line help. |

Options can be combined:

```sh
ocr-summary --dry-run --redo-ocr --verbose "Workshop notes.pdf"
```

macOS AppleDouble companion files (`._name.pdf`, created on SMB, exFAT, and NAS volumes) are
skipped automatically and reported only with `--verbose`, so `find . -name "*.pdf"` works on such
volumes.

`--skip-processed` checks only whether both fields are filled, not who wrote
them, so files you described manually are skipped too. Use it for scheduled runs
over a folder. To process a skipped file again, run it without the option; the
existing description and keywords are replaced.

### Network volumes

If the directory of a file becomes unreachable while a batch runs (for example a
disconnected SMB share), the script prints a warning to stderr, checks the
directory every `--retry-interval` seconds, and repeats the interrupted file from
the start once it returns. The original is replaced atomically, so an interrupted
file is still intact. Files already finished earlier in the batch are not touched
again. If the replacement had already completed when the connection dropped, the
changed file is detected and not processed a second time.

Waiting starts only for a directory that was reachable earlier in the same run, so a
mistyped path or a volume that was never mounted still fails at once. If the volume
does not return within `--retry-timeout`, that file fails, later files on the
unreachable volume fail without waiting again, and the exit status is 1. To
continue later, run the same command again with `--skip-processed`; it skips
everything that already has a description and keywords. An outage can leave a
`.ocr-summary-*` working directory beside the input that could not be cleaned up;
delete it manually.

## How it works

Before any OCR, the script finds the configured OCRmyPDF and pdftotext commands
and, when images are supplied, sips and ExifTool,
queries the Ollama server for the selected model's capabilities, and performs a
short generation request using the configured context size. Missing models,
embedding-only models, connection failures, and model loading or generation
errors stop the batch before any file is processed. The check runs once per
invocation, including dry runs, and is silent unless verbose mode is enabled.
It does not download models or start Ollama automatically.

The short check verifies generation, rather than summary quality. A model or
server can still fail later, and structured summary responses are validated
separately during document processing.

1. For images, macOS converts the input to a temporary PNG for OCR. For PDFs,
   the original is used as the OCR input. OCRmyPDF creates a temporary searchable
   PDF using the selected Apple OCR settings.
2. `pdftotext` extracts the entire working PDF's text, including existing digital
   text for PDF inputs.
3. Long text is summarized in sections when needed. One final structured Ollama
   request generates both a description and a keyword list. The contextual OCR
   correction rule applies only to that final request.
4. For PDFs, OCRmyPDF writes Subject and Keywords without another OCR pass.
   For images, ExifTool writes embedded XMP to an original-format working copy,
   then the script reads back the description and keyword list to verify them.
5. The script checks whether the source's inode, size, or modification time
   changed, preserves permission bits, and atomically replaces it on the same
   filesystem. Temporary files are cleaned up.

### Metadata fields

| Input | Summary | Keywords |
| --- | --- | --- |
| PDF | Document Info `Subject` (with OCRmyPDF metadata handling) | Document Info `Keywords` |
| JPEG, PNG, HEIC, HEIF | Embedded `XMP-dc:Description-x-default` | Embedded `XMP-dc:Subject` array |

XMP description stores Unicode text. XMP Subject is a list of keywords, unlike
PDF Subject, which contains the summary. These are standard XMP fields supported
by [ExifTool](https://exiftool.org/TagNames/XMP.html). Embedding support for PNG and
HEIC is documented in the [PNG tags](https://exiftool.org/TagNames/PNG.html) and
[QuickTime/HEIC tags](https://exiftool.org/TagNames/QuickTime.html) references.

Generated summaries and keyword lists replace the corresponding existing values.
Other metadata, such as camera settings, dates, orientation, and color profiles,
is retained by ExifTool. Existing localized XMP description values are retained
when the default-language description is updated. File-system metadata such as
Finder tags is a separate concern. Search applications differ in which embedded
metadata fields they index.

Inspect an image's generated metadata:

```sh
exiftool -G1 -XMP-dc:Description -XMP-dc:Subject "Flipchart.heic"
```

Without `--redo-ocr`, pages containing text are skipped entirely by OCR. A page
with a digital caption and a photographed flipchart may therefore need
`--redo-ocr` to recognize the image as well.

The existing PDF Subject and Keywords are overwritten. The script does not request changes to
Title or Author. Input path and filename stay the same, but replacement changes the
file's inode; Finder tags, extended attributes, and inode-based references are
not guaranteed to survive.

If OCR, extraction, summarization, or metadata writing fails, the original is
not replaced. Temporary working files are removed on normal completion and
handled errors. A forced process termination can leave a temporary directory.

OCR quality and summary accuracy depend on the source images and model. Section
summarization can omit details. The requested word limit is an instruction to the
model, rather than a strict validation rule.

## Scheduled execution

The script prints nothing on success by default. Errors go to stderr, and the
exit status is nonzero if any file fails. A dry run deliberately prints summaries
even without verbose mode.

| Exit status | Meaning |
| --- | --- |
| `0` | All requested files succeeded. |
| `1` | The Ollama preflight failed, or at least one file failed. Per-file failures do not stop the remaining files. |
| `2` | Invalid arguments or a required command missing from PATH. |

Example crontab entry for an Apple Silicon Homebrew installation:

```cron
0 3 * * * /absolute/path/to/ocr-summary /absolute/path/to/pdfs/*.pdf
```

Replace the example paths with your own and quote paths that contain spaces.
Ollama must already be running, and macOS must allow the scheduler to access the
documents. The script adds common Homebrew and pipx locations to its own PATH.

Every invocation processes every supplied file again; there is no automatic
tracking of previously summarized files. Schedule runs far enough apart to avoid
overlap. The change check is not a lock between concurrent runs.

## Troubleshooting

- **AppleOCR options missing:** check `command -v ocrmypdf` and confirm that the
  plugin was injected into the environment of the executable being used.
- **Ollama preflight or request failed:** start the local server and verify that
  `ollama list` contains the requested model.
- **Model does not support text generation:** select a completion model such as
  `qwen3.5:9b`; an embedding model such as `bge-m3` cannot summarize documents.
- **Photographed text was skipped:** try `--dry-run --redo-ocr` when a page already
  contains digital text or an old OCR layer.
- **Need different languages:** use `-l eng`, `-l deu -l eng`, or `-l deu+eng`
  for OCR and `--summary-language German` for summaries. To detect OCR language
  automatically, use `-l und --recognition-mode accurate`.
- **Cannot write temporary files:** check permissions on the input's parent directory.
- **HEIC conversion failed:** macOS `sips` must be able to decode the source. A
  damaged or unsupported image, or restricted access to native codecs, stops
  processing without changing the original.
- **Image has no readable text:** this is an OCR workflow, not visual scene
  description. No usable extracted text means no metadata is written.
- **Image metadata verification failed:** the original is preserved; check
  ExifTool's format support and use verbose mode for diagnostics.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow and
[AGENTS.md](AGENTS.md) for shared coding-assistant instructions.
[CLAUDE.md](CLAUDE.md) imports those instructions for Claude Code.

Run the tests from the repository root:

```sh
python3 -m unittest discover -s tests -v
```

Tests mock OCR and Ollama and verify dry-run behavior, error handling, metadata
arguments, image routing and readback, keyword validation, configuration forwarding and validation, batch processing, output
modes, timeouts, Ollama preflight failures, and preservation of originals. They
do not require OCRmyPDF, Poppler, or a running model. GitHub Actions runs the suite
on Python 3.11 and 3.14. Real OCR and model quality must be checked separately on
macOS with representative documents. Image metadata has also been round-trip
checked with real JPG, PNG, and HEIC files using ExifTool, with matching image-data
hashes before and after metadata writing. Full native Apple OCR and HEIC decoding
integration remain unverified; perform a dry run with representative inputs on
macOS before scheduling a batch.

Contributions are welcome. Keep functions focused, preserve quiet operation and
dry-run guarantees, and include a regression test for behavioral changes.

### Code documentation

Module, configuration classes, and workflow functions use English docstrings.
The documentation follows PEP 257 conventions and Google-style sections such as
`Args`, `Returns`, `Yields`, `Raises`, and `Attributes` where useful. Type hints
describe types; docstrings explain behavior, side effects, and constraints.
Comments explain implementation decisions rather than repeat the code.
This style follows the guidance in
[Real Python's documentation guide](https://realpython.com/documenting-python-code/).

Inspect the documentation using Python's built-in tools, without installing a
documentation package:

```sh
python3 -m pydoc ocr_summary
```

Or use `help(ocr_summary.process)` after importing the module in Python.
Importing the module does not process files or contact Ollama. CLI usage and
installation remain documented in this README and in `--help`.

## License

[MIT](LICENSE). Copyright notices use the collective name
"OCR Summary contributors". Dependencies, downloaded models, and macOS
frameworks remain subject to their respective licenses.
