# Formula for the tap repository flo1o1/homebrew-ocr-summary (Formula/ocr-summary.rb).
class OcrSummary < Formula
  desc "Local Apple OCR summaries and keywords for PDFs and images"
  homepage "https://github.com/flo1o1/ocr-summary"
  url "https://github.com/flo1o1/ocr-summary/archive/refs/tags/v0.5.1.tar.gz"
  sha256 "dacd942e81d1335087ef410fd40e8dcdfab789755f456f49560c2e4d10bd9b26"
  license "MIT"

  depends_on :macos
  depends_on "exiftool"
  depends_on "poppler"
  depends_on "python@3.14"

  def install
    # The wrapper is one standard-library-only file, so no virtualenv is needed.
    libexec.install "ocr_summary.py", "pyproject.toml"
    (bin/"ocr-summary").write <<~SH
      #!/bin/bash
      exec "#{Formula["python@3.14"].opt_bin}/python3.14" "#{libexec}/ocr_summary.py" "$@"
    SH
  end

  def caveats
    <<~EOS
      OCRmyPDF and the AppleOCR plugin must share one environment, so they are
      not formula dependencies. Install them and Ollama separately:
        brew install ollama
        brew install --only-dependencies ocrmypdf
        pipx install 'ocrmypdf>=17'
        pipx inject ocrmypdf 'ocrmypdf-appleocr>=0.4'
    EOS
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/ocr-summary --version")
  end
end
