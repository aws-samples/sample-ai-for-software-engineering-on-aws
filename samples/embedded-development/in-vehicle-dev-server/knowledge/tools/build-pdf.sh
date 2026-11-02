#!/usr/bin/env bash
# Render vstatd-interface.md to vstatd-interface.pdf, one PDF page per specification page.
# Needs pandoc, a Chromium-based browser (set CHROME if it is not found) and the open fonts Liberation Sans and
# DejaVu Sans Mono (Debian/Ubuntu: fonts-liberation fonts-dejavu-core; elsewhere set FONT_DIR to a folder holding
# their .ttf files). Only these fonts are embedded in the PDF. The PDF title carries the first 8 hex digits of the
# Markdown file's SHA-256, so tools/check_knowledge.py can tell a stale PDF.
# Run from anywhere; writes next to the Markdown file.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
src="$here/vstatd-interface.md"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

command -v pandoc >/dev/null || { echo "pandoc is required" >&2; exit 1; }
chrome="${CHROME:-}"
if [ -z "$chrome" ]; then
  for c in chromium chromium-browser google-chrome google-chrome-stable \
           "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
           "/Applications/Chromium.app/Contents/MacOS/Chromium"; do
    if command -v "$c" >/dev/null 2>&1 || [ -x "$c" ]; then chrome="$c"; break; fi
  done
fi
[ -n "$chrome" ] || { echo "Chromium or Google Chrome is required (set CHROME)" >&2; exit 1; }

font() {  # font <file name>: print the path of the first match in FONT_DIR or the system font folders
  find ${FONT_DIR:+"$FONT_DIR"} /usr/share/fonts /usr/local/share/fonts "$HOME/.fonts" "$HOME/Library/Fonts" \
    -name "$1" -print -quit 2>/dev/null || true
}
sans="$(font LiberationSans-Regular.ttf)"; sans_bold="$(font LiberationSans-Bold.ttf)"
sans_italic="$(font LiberationSans-Italic.ttf)"; mono="$(font DejaVuSansMono.ttf)"
for f in "$sans" "$sans_bold" "$sans_italic" "$mono"; do
  [ -n "$f" ] || { echo "Liberation Sans and DejaVu Sans Mono are required (see the header)" >&2; exit 1; }
done
sha8="$(shasum -a 256 "$src" 2>/dev/null || sha256sum "$src")"; sha8="${sha8:0:8}"

# Each page marker becomes a forced page break.
perl -pe 's{^<!-- pagebreak -->$}{<div class="pagebreak"></div>}' "$src" > "$work/spec.md"

cat > "$work/style.css" <<CSS
@font-face { font-family: "Spec Sans"; src: url("file://$sans"); font-weight: normal; font-style: normal; }
@font-face { font-family: "Spec Sans"; src: url("file://$sans_bold"); font-weight: bold; font-style: normal; }
@font-face { font-family: "Spec Sans"; src: url("file://$sans_italic"); font-weight: normal; font-style: italic; }
@font-face { font-family: "Spec Mono"; src: url("file://$mono"); }
@page { size: A4; margin: 14mm 13mm 12mm 13mm; }
body { font-family: "Spec Sans"; font-size: 9pt; line-height: 1.3;
       max-width: none; margin: 0; padding: 0; }
header#title-block-header { display: none; }
.pagebreak { break-before: page; }
h1 { font-size: 15pt; margin: 0 0 6pt 0; }
h2 { font-size: 12pt; margin: 6pt 0 4pt 0; }
p, li { margin: 2pt 0; }
ul { padding-left: 14pt; }
table { border-collapse: collapse; width: 100%; margin: 3pt 0 6pt 0; table-layout: auto; }
th, td { border: 0.5pt solid #999; padding: 1.5pt 3pt; font-size: 7.5pt; vertical-align: top; }
th { background: #eeeeee; text-align: left; }
td code { font-size: 7pt; word-break: break-all; }
code, pre { font-family: "Spec Mono"; }
code { font-size: 7.5pt; }
pre { font-size: 7.5pt; margin: 3pt 0; }
blockquote { margin: 4pt 0; padding-left: 6pt; border-left: 2pt solid #aaa; color: #444; }
CSS

pandoc "$work/spec.md" -f gfm -t html5 --standalone --metadata title="VSTATD-IF rev 1.3 (source $sha8)" \
  --css "$work/style.css" -o "$work/vstatd-interface.html"
"$chrome" --headless --disable-gpu --no-pdf-header-footer --user-data-dir="$work/profile" \
  --allow-file-access-from-files --print-to-pdf="$here/vstatd-interface.pdf" "file://$work/vstatd-interface.html" \
  >/dev/null 2>&1
echo "wrote $here/vstatd-interface.pdf"
