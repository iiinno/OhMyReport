#!/usr/bin/env python3
"""catalog.html を写し、base.css を <style> に埋め込んだ新しい報告書を作る。

使い方:
  python new_report.py 報告書.html
"""
import sys
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
LINK = '<link rel="stylesheet" href="base.css">'

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if len(sys.argv) != 2:
    sys.exit(__doc__)
out = Path(sys.argv[1])
if out.exists():
    sys.exit(f"すでにある: {out}。上書きしないので、別の名前を指定する")

page = (ASSETS / "catalog.html").read_text(encoding="utf-8")
css = (ASSETS / "base.css").read_text(encoding="utf-8")
assert page.count(LINK) == 1, "catalog.html の link が見つからない"
page = page.replace("<!-- 部品見本。提出する報告書では、この link の代わりに base.css の全文を <style> に入れる -->\n", "")
with out.open("x", encoding="utf-8") as handle:
    handle.write(page.replace(LINK, "<style>\n" + css + "</style>"))
print(f"作成: {out}")
