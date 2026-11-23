"""Gera o relatório técnico em PDF a partir de docs/relatorio/*.md.

Junta os capítulos por ordem (00 a 10), converte Markdown -> HTML, desenha os diagramas
Mermaid no browser e imprime em PDF com o Chrome/Edge em modo headless.

    pip install markdown
    python scripts/build-report.py            # -> docs/relatorio/relatorio.pdf

Precisa de rede (carrega o mermaid.js de um CDN) e de Chrome ou Edge instalado.
"""
import datetime
import html
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "relatorio"
OUT = SRC / "relatorio.pdf"
BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "google-chrome", "chromium", "chromium-browser", "microsoft-edge",
]

CSS = """
@page { size: A4; margin: 18mm 16mm 18mm 16mm; }
body { font-family: "Segoe UI", system-ui, sans-serif; font-size: 10.5pt; line-height: 1.5; color: #1a1a1a; }
h1 { font-size: 20pt; border-bottom: 2px solid #1f4e79; padding-bottom: 4px; color: #1f4e79; page-break-before: always; }
h1.first { page-break-before: avoid; }
h2 { font-size: 14pt; color: #1f4e79; margin-top: 18pt; }
h3 { font-size: 12pt; margin-top: 14pt; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0; font-size: 9pt; page-break-inside: auto; }
th, td { border: 1px solid #b7c4d1; padding: 4px 6px; vertical-align: top; text-align: left; }
th { background: #e8eef5; }
tr { page-break-inside: avoid; }
code { font-family: Consolas, "Cascadia Mono", monospace; font-size: 8.8pt; background: #f2f4f7; padding: 0 2px; }
pre { background: #f2f4f7; padding: 8px; font-size: 8.5pt; white-space: pre-wrap; word-break: break-word; }
pre code { background: none; padding: 0; }
pre.mermaid { background: none; text-align: center; }
a { color: #1f4e79; text-decoration: none; }
.cover { height: 250mm; display: flex; flex-direction: column; justify-content: center; text-align: center; }
.cover h1 { border: none; font-size: 28pt; page-break-before: avoid; }
.cover p { font-size: 13pt; margin: 4pt 0; }
.toc { page-break-before: always; }
.toc li { margin: 3pt 0; }
"""


def chapters() -> list[Path]:
    return sorted(p for p in SRC.glob("[0-9][0-9]-*.md"))


def to_html(md_text: str) -> str:
    md_text = re.sub(r"(?m)^(#+ .*?) \(rascunho\)\s*$", r"\1", md_text)        # títulos finais
    md_text = re.sub(r"(?m)^\(exportar .*\)\s*$", "", md_text)                   # notas de trabalho
    body = markdown.markdown(md_text, extensions=["tables", "fenced_code", "sane_lists"])
    # Blocos ```mermaid -> <pre class="mermaid"> (desenhados pelo mermaid.js)
    return re.sub(r'<pre><code class="language-mermaid">(.*?)</code></pre>',
                  lambda m: f'<pre class="mermaid">{m.group(1)}</pre>', body, flags=re.S)


def build_html() -> str:
    parts, toc = [], []
    for i, path in enumerate(chapters()):
        text = path.read_text(encoding="utf-8")
        title = re.search(r"(?m)^# (.+?)(?: \(rascunho\))?\s*$", text)
        toc.append(title.group(1) if title else path.stem)
        chapter = to_html(text)
        if i == 0:
            chapter = chapter.replace("<h1>", '<h1 class="first">', 1)
        parts.append(f'<section id="c{i}">{chapter}</section>')
    today = datetime.date.today().strftime("%d/%m/%Y")
    cover = f"""<div class="cover">
      <h1>Global-Scale System</h1>
      <p>Plataforma distribuída de transações financeiras internacionais</p>
      <p>Relatório técnico — Exame Prático Laboratorial</p>
      <p>Sistemas Distribuídos e Paralelos · ISUTC · LECC 31</p>
      <p style="margin-top:30pt">{today}</p></div>"""
    toc_html = '<div class="toc"><h2>Índice</h2><ol>' + "".join(
        f'<li><a href="#c{i}">{html.escape(t)}</a></li>' for i, t in enumerate(toc)) + "</ol></div>"
    first = parts[0].replace('<h1 class="first">', "<h1>", 1)      # depois do índice: nova página
    return f"""<!doctype html><html lang="pt"><head><meta charset="utf-8"><title>Global-Scale System</title>
<style>{CSS}</style>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script>
</head><body>{cover}{toc_html}{first}{''.join(parts[1:])}
<script>mermaid.initialize({{startOnLoad: true, theme: "neutral", flowchart: {{useMaxWidth: true}}}});</script>
</body></html>"""


def browser() -> str:
    for b in BROWSERS:
        if Path(b).exists() or shutil.which(b):
            return b
    sys.exit("Chrome ou Edge não encontrado")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "relatorio.html"
        page.write_text(build_html(), encoding="utf-8")
        subprocess.run([browser(), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        "--virtual-time-budget=15000", f"--user-data-dir={tmp}/profile",
                        f"--print-to-pdf={OUT}", page.as_uri()], check=True, capture_output=True, timeout=180)
    print(f"PDF gerado: {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KiB, {len(chapters())} capítulos)")


if __name__ == "__main__":
    main()
