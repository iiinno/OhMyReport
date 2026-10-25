#!/usr/bin/env python3
"""report-design の HTML 報告書を実際に描画して検査する。

使い方:
  python lint_report.py report.html
  python lint_report.py report.html --shots out/   # 画面の写しと PDF も作る
  python lint_report.py report.html --json

標準ライブラリと、PC に入っている Chrome / Edge / Chromium だけで動く。
ブラウザの場所は環境変数 CHROME で指定できる。
誤りが1件でもあれば終了コード 1 を返す。
"""
import argparse
import html
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from html.parser import HTMLParser

HERE = Path(__file__).resolve().parent
BASE_CSS = HERE.parent / "assets" / "base.css"
CHECKS_JS = HERE / "lint_checks.js"
SCRIPT_NONCE = secrets.token_urlsafe(24)
CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
    f"script-src 'nonce-{SCRIPT_NONCE}'; base-uri 'none'; form-action 'none'"
)


class StaticReportParser(HTMLParser):
    def handle_starttag(self, tag, attrs):
        if tag in {"script", "iframe", "frame", "object", "embed", "base", "link"}:
            raise ValueError(f"Static report cannot contain <{tag}>")
        for key, value in attrs:
            if key.startswith("on") or key == "srcdoc":
                raise ValueError(f"Active HTML attribute is not allowed: {key}")
            if tag == "meta" and key == "http-equiv" and (value or "").lower() == "refresh":
                raise ValueError("Meta refresh is not allowed")

    handle_startendtag = handle_starttag


def validate_static_report(src):
    parser = StaticReportParser()
    parser.feed(src.read_text(encoding="utf-8"))
    parser.close()


def temporary_html(src, prefix, text):
    fd, name = tempfile.mkstemp(prefix=prefix, suffix=".html", dir=src.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    return Path(name)

MODES = {
    # A4 縦、左右の余白 14mm を引いた本文幅は 182mm = 688px
    "desktop": (1280, 900),
    "mobile": (390, 844),
    "print": (688, 1000),
}

SCREEN_SIZES = [14, 16, 18, 24, 32, 48, 64]
SCREEN_EXTRA = [40]  # 幅の狭い画面の H1 だけに使う
PRINT_SIZES = [9, 9.5, 10.5, 13, 18, 28, 36]  # pt

VAGUE_HEADINGS = [
    "概要", "詳細", "ポイント", "重要事項", "考察", "インサイト", "展望", "今後の展望",
    "まとめ", "次のステップ", "可能性", "課題", "問題点", "結果", "方法", "はじめに", "おわりに",
]
BANNED_TITLE = [
    "の全貌", "徹底解説", "完全ガイド", "を読み解く", "新時代の", "未来を切り拓く", "革新的な",
    "の可能性を探る", "から見えてきたもの", "深掘り", "重要なインサイト",
    "Key Takeaways", "What this means", "Why it matters", "What's next", "The big picture",
]
ENGLISH_LABELS = [
    "Insights?", "Overview", "Deep Dive", "Key Findings?", "Evidence Flow",
    "Executive (Summary|Conclusion)", "Highlights?", "Takeaways?", "Summary",
]
PRODUCTION = [
    "指示に従い", "は禁止とした", "今回は[^。]{0,20}を使わない", "前版から", "この要件を満たすため",
    # ファイル名や道具の名前は、技術文書では正当な主題になるので入れない。言い回しの型だけを見る
    "AIっぽ", "SVGで実装", "(黄金|白銀)比で配置", "検査を通すため", "デザインの都合で",
]
ABSTRACT_BANNED = ["詳しく解説します", "多角的に", "紐解", "見ていきます"]


def load_tokens():
    css = BASE_CSS.read_text(encoding="utf-8")
    root = re.search(r":root\s*\{(.*?)\n\}", css, re.S).group(1)
    tokens = {}
    for name, val in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", root):
        tokens[name] = re.sub(r"\s+", " ", val.strip())
    return tokens


def find_browser():
    env = os.environ.get("CHROME")
    if env and Path(env).exists():
        return env
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge"):
        p = shutil.which(name)
        if p:
            return p
    sys.exit("Chrome / Edge / Chromium が見つからない。環境変数 CHROME にパスを入れて再実行する。")


PRINT_EMULATION = """
function __rdEmulatePrint(){
  function walk(list){
    for (const r of Array.from(list)) {
      if (r.media && r.cssRules) {
        const m = r.media.mediaText;
        if (/print/.test(m)) r.media.mediaText = "all";
        else if (/screen/.test(m)) r.media.mediaText = "not all";
      }
      if (r.cssRules) walk(r.cssRules);
    }
  }
  for (const s of Array.from(document.styleSheets)) {
    try {
      if (s.media && s.media.mediaText) {
        if (/print/.test(s.media.mediaText)) s.media.mediaText = "all";
        else if (/screen/.test(s.media.mediaText)) s.media.mediaText = "not all";
      }
      walk(s.cssRules);
    } catch (e) {}
  }
}
"""


def run_browser(browser, args, timeout=120):
    with tempfile.TemporaryDirectory(prefix="rdlint-profile-") as prof:
        cmd = [
            browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
            "--hide-scrollbars", "--allow-file-access-from-files", f"--user-data-dir={prof}",
        ] + args
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        if r.returncode != 0:
            raise RuntimeError(f"Browser exited with code {r.returncode}")
        return r.stdout.decode("utf-8", "replace")


def with_injection(src: Path, head_extra: str, body_extra: str, tag: str) -> Path:
    """検査用の写しを同じフォルダに作る。相対パスの CSS や画像をそのまま読ませるため。"""
    text = src.read_text(encoding="utf-8")
    policy = '<meta http-equiv="Content-Security-Policy" content="' + html.escape(CSP, quote=True) + '">'
    head = re.search(r"<head\b[^>]*>", text, re.I)
    pos = head.end() if head else 0
    text = text[:pos] + policy + text[pos:]
    if head_extra:
        m = re.search(r"</head>", text, re.I)
        text = text[:m.start()] + head_extra + text[m.start():] if m else head_extra + text
    if body_extra:
        m = None
        for m in re.finditer(r"</body>", text, re.I):
            pass
        text = text[:m.start()] + body_extra + text[m.start():] if m else text + body_extra
    return temporary_html(src, f".rdlint-{tag}-", text)


# Chrome のヘッドレスは幅 500px 未満の窓を作れない。それより狭い幅は iframe で再現する
MIN_WINDOW = 500


def narrow_wrapper(page: Path, w: int, h: int, shift: int) -> Path:
    doc = (
        '<!doctype html><meta charset="utf-8"><body style="margin:0;background:#888">'
        f'<div style="position:relative;top:-{shift}px"><iframe src="{html.escape(page.name, quote=True)}" '
        f'style="display:block;width:{w}px;height:{h}px;border:0"></iframe></div>'
        "<script>addEventListener('message',function(e){var p=document.createElement('pre');"
        "p.id='__rdlint_out';p.textContent=e.data;document.body.appendChild(p);});</script>"
    )
    return temporary_html(page, ".rdlint-wrap-", doc)


def lint_mode(browser, src: Path, mode: str, cfg: dict):
    w, h = MODES[mode]
    conf = dict(cfg, mode=mode)
    js = (
        f'<script nonce="{SCRIPT_NONCE}" id="__rdlint_script">window.__RDLINT_CFG=' + json.dumps(conf, ensure_ascii=False) + ";"
        + PRINT_EMULATION
        + "window.addEventListener('load',function(){"
        + ("__rdEmulatePrint();" if mode == "print" else "")
        + "document.fonts.ready.then(function(){" + CHECKS_JS.read_text(encoding="utf-8") + "});});</script>"
    )
    tmp = with_injection(src, "", js, mode)
    wrap = None
    try:
        if w < MIN_WINDOW:
            wrap = narrow_wrapper(tmp, w, h, 0)
            dom = run_browser(browser, [f"--window-size={MIN_WINDOW},{h}", "--virtual-time-budget=8000", "--dump-dom", wrap.as_uri()])
        else:
            dom = run_browser(browser, [f"--window-size={w},{h}", "--virtual-time-budget=8000", "--dump-dom", tmp.as_uri()])
    finally:
        tmp.unlink(missing_ok=True)
        if wrap:
            wrap.unlink(missing_ok=True)
    found = re.findall(r'<pre id="__rdlint_out">(\{.*?)</pre>', dom, re.S)
    if not found:
        return {"mode": mode, "width": w, "height": h, "issues": [
            {"rule": "X0", "level": "error", "msg": "検査スクリプトが結果を返さなかった。HTML の構文かスクリプトの誤りを確かめる", "where": ""}]}
    return json.loads(html.unescape(found[-1]))


def take_shots(browser, src: Path, outdir: Path, heights: dict):
    secured = with_injection(src, "", "", "capture")
    try:
        return capture_shots(browser, secured, outdir, heights, src.stem)
    finally:
        secured.unlink(missing_ok=True)


def capture_shots(browser, src: Path, outdir: Path, heights: dict, stem: str):
    """画面の写しを縦 1600px ごとに切って保存し、PDF も作る。"""
    outdir.mkdir(parents=True, exist_ok=True)
    made = []
    slice_h = 1600
    for mode in ("desktop", "mobile"):
        w = MODES[mode][0]
        total = max(heights.get(mode, slice_h), 1)
        n = math.ceil(total / slice_h)
        for i in range(n):
            png = outdir / f"{stem}.{mode}.{i + 1:02d}.png"
            if w < MIN_WINDOW:
                # 右側の灰色の帯は窓の最小幅の余り。本文は左の w px
                wrap = narrow_wrapper(src.resolve(), w, total, i * slice_h)
                try:
                    run_browser(browser, [f"--window-size={MIN_WINDOW},{slice_h}", "--virtual-time-budget=4000", f"--screenshot={png}", wrap.as_uri()])
                finally:
                    wrap.unlink(missing_ok=True)
            else:
                style = f'<style id="__rdlint_shift">html{{position:relative;top:-{i * slice_h}px}}</style>'
                tmp = with_injection(src, style, "", f"shot{i}")
                try:
                    run_browser(browser, [f"--window-size={w},{slice_h}", "--virtual-time-budget=4000", f"--screenshot={png}", tmp.as_uri()])
                finally:
                    tmp.unlink(missing_ok=True)
            if png.exists():
                made.append(png)
    pdf = outdir / f"{stem}.pdf"
    run_browser(browser, ["--no-pdf-header-footer", "--virtual-time-budget=4000", f"--print-to-pdf={pdf}", src.resolve().as_uri()])
    if pdf.exists():
        made.append(pdf)
    return made


def main():
    ap = argparse.ArgumentParser(description="report-design の HTML 報告書を描画して検査する")
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--shots", type=Path, help="画面の写し（PNG）と PDF を保存するフォルダ")
    ap.add_argument("--json", action="store_true", help="結果を JSON で出す")
    ap.add_argument("--modes", default="desktop,mobile,print")
    a = ap.parse_args()
    # エージェントが読む前提なので、端末の文字コードに関係なく UTF-8 で出す
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    tokens = load_tokens()
    palette = sorted({v.upper() for v in tokens.values() if re.fullmatch(r"#[0-9A-Fa-f]{6}", v)})
    cfg = {
        "tokens": tokens,
        "palette": palette,
        "accent": [tokens["--accent"], tokens["--accent-ink"]],
        "paper": tokens["--paper"],
        "screenSizes": SCREEN_SIZES,
        "screenExtra": SCREEN_EXTRA,
        "printSizes": [round(p * 96 / 72, 3) for p in PRINT_SIZES],
        "vagueHeadings": VAGUE_HEADINGS,
        "bannedTitle": BANNED_TITLE,
        "englishLabels": ENGLISH_LABELS,
        "production": PRODUCTION,
        "abstractBanned": ABSTRACT_BANNED,
    }
    modes = [m.strip() for m in a.modes.split(",")]
    if not modes or any(m not in MODES for m in modes):
        ap.error("--modes must contain desktop, mobile, or print")
    for src in a.files:
        try:
            validate_static_report(src)
        except (OSError, ValueError) as exc:
            ap.error(str(exc))
    browser = find_browser()

    report, errors = [], 0
    for f in a.files:
        f = f.resolve()
        if not f.exists():
            sys.exit(f"ファイルがない: {f}")
        results = [lint_mode(browser, f, m, cfg) for m in modes]
        entry = {"file": str(f), "results": results}
        if a.shots:
            heights = {r["mode"]: r["height"] for r in results}
            entry["shots"] = [str(p) for p in take_shots(browser, f, a.shots, heights)]
        report.append(entry)
        errors += sum(1 for r in results for i in r["issues"] if i["level"] == "error")

    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for entry in report:
            print(entry["file"])
            for r in entry["results"]:
                e = sum(1 for i in r["issues"] if i["level"] == "error")
                w = sum(1 for i in r["issues"] if i["level"] == "warn")
                print(f"  [{r['mode']} {r['width']}px] 誤り {e} / 注意 {w}")
                for i in sorted(r["issues"], key=lambda i: (i["level"] != "error", i["rule"])):
                    mark = "E" if i["level"] == "error" else "W"
                    print(f"    {mark} {i['rule']} {i['msg']}")
                    if i["where"]:
                        print(f"        {i['where']}")
            for s in entry.get("shots", []):
                print(f"  写し: {s}")
        print(f"誤り 合計 {errors} 件" if errors else "誤りなし")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
