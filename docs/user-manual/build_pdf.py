#!/usr/bin/env python3
"""Render the Arabic user manual (README.md) to a print-ready A4 PDF.

Chrome does the typesetting rather than a Python PDF library, for one reason:
Arabic needs contextual letter shaping and right-to-left bidi, and the browser
engine already does both correctly — the same engine that renders the app, so
the manual looks like the product it documents.

Usage:  python3 docs/user-manual/build_pdf.py
Output: docs/user-manual/دليل-المستخدم.pdf
"""

from __future__ import annotations

import base64
import mimetypes
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

import markdown

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "README.md"
HTML_OUT = HERE / ".build" / "manual.html"
PDF_OUT = HERE / "دليل-المستخدم.pdf"

CHROME = Path(
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
)


def github_slug(text: str) -> str:
    """Anchor ids matching GitHub's, so the table of contents links work in both.

    Punctuation is dropped, spaces become hyphens, and Arabic diacritics are
    kept — an em dash surrounded by spaces therefore collapses to two hyphens,
    exactly as GitHub renders it.
    """
    kept = [
        c
        for c in text.strip().lower()
        if c.isalnum() or c in " -_" or unicodedata.category(c).startswith("M")
    ]
    return "".join(kept).replace(" ", "-")


ARABIC = re.compile(r"[؀-ۿ]")


def tag_arabic_code(html: str) -> str:
    """Mark inline code holding Arabic text, so it is not set in LTR monospace."""

    def replace(match: re.Match[str]) -> str:
        inner = match.group(1)
        return f'<code class="ar">{inner}</code>' if ARABIC.search(inner) else match.group(0)

    return re.sub(r"<code>(.*?)</code>", replace, html, flags=re.S)


def inline_images(html: str) -> str:
    """Embed screenshots as data URIs so the PDF never depends on the file tree."""

    def replace(match: re.Match[str]) -> str:
        src = match.group(1)
        path = (HERE / src).resolve()
        if not path.is_file():
            sys.exit(f"missing screenshot: {src}")
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        payload = base64.b64encode(path.read_bytes()).decode("ascii")
        return f'src="data:{mime};base64,{payload}"'

    return re.sub(r'src="([^"]+)"', replace, html)


def add_heading_ids(html: str) -> str:
    """Give every heading a GitHub-style id so internal links resolve as PDF links."""

    def replace(match: re.Match[str]) -> str:
        level, text = match.group(1), match.group(2)
        plain = re.sub(r"<[^>]+>", "", text)
        return f'<h{level} id="{github_slug(plain)}">{text}</h{level}>'

    return re.sub(r"<h([1-6])>(.*?)</h\1>", replace, html, flags=re.S)


STYLE = """
@page {
  size: A4;
  margin: 17mm 15mm 17mm 15mm;
}

:root {
  --ink: #0f172a;
  --muted: #475569;
  --line: #e2e8f0;
  --brand: #065f46;
  --brand-soft: #ecfdf5;
  --accent: #0369a1;
  --accent-soft: #f0f9ff;
}

* { box-sizing: border-box; }

html {
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
  /* A printed page is white. Say so, or a dark-mode viewer inverts the
     document when the HTML is opened directly in a browser. */
  color-scheme: light;
  background: #fff;
}

body {
  background: #fff;
  font-family: "Tajawal", "Geeza Pro", "Al Bayan", sans-serif;
  direction: rtl;
  text-align: right;
  color: var(--ink);
  font-size: 10.5pt;
  line-height: 1.85;
  margin: 0;
}

/* ---------- Title page ---------- */
.cover {
  height: 247mm;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  text-align: center;
  page-break-after: always;
}
.cover .mark { font-size: 54pt; line-height: 1; margin-bottom: 10mm; }
.cover h1 {
  font-size: 30pt;
  font-weight: 800;
  color: var(--brand);
  margin: 0 0 4mm;
  border: 0;
  padding: 0;
}
.cover .sub { font-size: 13pt; color: var(--muted); font-weight: 500; }
.cover .rule {
  width: 60mm;
  height: 3px;
  background: var(--brand);
  border-radius: 2px;
  margin: 9mm 0;
}
.cover .meta { font-size: 10pt; color: var(--muted); line-height: 2.1; }

/* ---------- Headings ---------- */
h1 {
  font-size: 20pt;
  font-weight: 800;
  color: var(--brand);
  border-bottom: 2.5px solid var(--brand);
  padding-bottom: 3mm;
  margin: 0 0 7mm;
}
h2 {
  font-size: 16pt;
  font-weight: 800;
  color: var(--brand);
  margin: 0 0 6mm;
  padding-bottom: 2.5mm;
  border-bottom: 1.5px solid var(--line);
  page-break-before: always;
  page-break-after: avoid;
}
h2:first-of-type { page-break-before: avoid; }
h3 {
  font-size: 12.5pt;
  font-weight: 700;
  color: var(--ink);
  margin: 7mm 0 3mm;
  page-break-after: avoid;
}
h4 { font-size: 11pt; font-weight: 700; margin: 5mm 0 2mm; page-break-after: avoid; }

p { margin: 0 0 3.5mm; }
strong { font-weight: 700; }

/* ---------- Worked examples ---------- */
h3.example {
  background: var(--brand-soft);
  border-inline-start: 4px solid var(--brand);
  color: var(--brand);
  padding: 3mm 4mm;
  border-radius: 0 6px 6px 0;
  margin-top: 8mm;
}

/* ---------- Tables ---------- */
table {
  width: 100%;
  border-collapse: collapse;
  margin: 4mm 0 6mm;
  font-size: 9.5pt;
  page-break-inside: avoid;
}
thead { background: var(--brand); }
th {
  color: #fff;
  font-weight: 700;
  text-align: right;
  padding: 2.4mm 3mm;
  border: 1px solid var(--brand);
}
td {
  padding: 2.2mm 3mm;
  border: 1px solid var(--line);
  vertical-align: top;
}
tbody tr:nth-child(even) { background: #f8fafc; }

/* ---------- Screenshots ---------- */
img {
  max-width: 100%;
  height: auto;
  display: block;
  margin: 4mm auto 6mm;
  border: 1px solid var(--line);
  border-radius: 8px;
  page-break-inside: avoid;
}

/* ---------- Callouts ---------- */
blockquote {
  margin: 4mm 0;
  padding: 3mm 4mm;
  background: var(--accent-soft);
  border-inline-start: 4px solid var(--accent);
  border-radius: 0 6px 6px 0;
  color: #0c4a6e;
  page-break-inside: avoid;
}
blockquote p:last-child { margin-bottom: 0; }

/* ---------- Lists ---------- */
ul, ol { margin: 0 0 4mm; padding-inline-start: 6mm; }
li { margin-bottom: 1.6mm; }

/* ---------- Code / flow diagrams ---------- */
pre {
  background: #f1f5f9;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 3mm 4mm;
  direction: ltr;
  text-align: center;
  /* The flow diagrams are Arabic prose, not code — a monospace fallback tracks
     the letters far too wide. Bidi still lays each step out right-to-left. */
  font-family: inherit;
  font-size: 9.5pt;
  font-weight: 500;
  overflow: visible;
  white-space: pre-wrap;
  page-break-inside: avoid;
}
pre code { font-family: inherit; }
code { font-family: "SFMono-Regular", Menlo, monospace; font-size: 9pt; }
p code, li code, td code {
  background: #f1f5f9;
  padding: 0.4mm 1.2mm;
  border-radius: 3px;
  direction: ltr;
  display: inline-block;
}
/* Monospace and forced LTR suit an SKU or an account code; they mangle an
   Arabic value typed into a field. Those keep the highlight and nothing else. */
p code.ar, li code.ar, td code.ar {
  font-family: inherit;
  font-size: inherit;
  font-weight: 700;
  direction: rtl;
}

hr { border: 0; border-top: 1px solid var(--line); margin: 6mm 0; }
a { color: var(--accent); text-decoration: none; }

/* The separator rules between chapters would otherwise land alone on a page. */
h2 + hr, hr + h2 { display: none; }
"""

TEMPLATE = """<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<title>دليل استخدام نظام إدارة التوزيع</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;800&display=swap" rel="stylesheet">
<style>{style}</style>
</head>
<body>
<section class="cover">
  <div class="mark">📦</div>
  <h1>دليل استخدام<br>نظام إدارة التوزيع</h1>
  <div class="sub">نظام تخطيط موارد لشركات بيع وتوزيع المواد الغذائية بالجملة</div>
  <div class="rule"></div>
  <div class="meta">
    الإصدار الأول<br>
    {count} فصلاً · {shots} لقطة شاشة · أمثلة عملية بالأرقام
  </div>
</section>
{body}
</body>
</html>
"""


def main() -> None:
    if not SOURCE.is_file():
        sys.exit(f"source not found: {SOURCE}")
    if not CHROME.is_file():
        sys.exit(f"Chrome not found at {CHROME}")

    text = SOURCE.read_text(encoding="utf-8")
    # The cover replaces the document's own title block.
    text = re.sub(r"\A# .*?\n---\n", "", text, count=1, flags=re.S)

    body = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "sane_lists", "attr_list"],
    )
    body = add_heading_ids(body)
    # Worked examples carry a wrench so they stand out when skimming.
    body = re.sub(r'<h3 id="([^"]*)">(🔧[^<]*)', r'<h3 class="example" id="\1">\2', body)
    body = tag_arabic_code(body)
    body = inline_images(body)

    # Numbered chapters only — the contents listing is an h2 too.
    chapters = len(re.findall(r"<h2 [^>]*>\s*\d+\.", body))
    shots = len(re.findall(r"<img ", body))

    HTML_OUT.parent.mkdir(exist_ok=True)
    HTML_OUT.write_text(
        TEMPLATE.format(style=STYLE, body=body, count=chapters, shots=shots),
        encoding="utf-8",
    )

    print(f"rendering {chapters} chapters and {shots} screenshots…")
    subprocess.run(
        [
            str(CHROME),
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            "--no-first-run",
            "--no-pdf-header-footer",
            # Fonts and layout need time to settle before the page is printed.
            "--virtual-time-budget=20000",
            f"--print-to-pdf={PDF_OUT}",
            HTML_OUT.as_uri(),
        ],
        check=True,
        capture_output=True,
    )

    size_mb = PDF_OUT.stat().st_size / 1_048_576
    print(f"wrote {PDF_OUT.name} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
