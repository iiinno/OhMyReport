#!/usr/bin/env python3
"""完成した報告書と検査生成物を保存用フォルダへ複製する。

使い方:
  python archive_report.py 報告書.html
  python archive_report.py 報告書.html --shots 写しの保存先
  python archive_report.py 報告書.html --shots 写しの保存先 --dest 保存先
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

DEFAULT_DEST = os.environ.get("OHMYREPORT_ARCHIVE_DIR")
VERSION_DIR = re.compile(r"v(\d+)$", re.I)
SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_artifacts(report: Path, shots: Path | None) -> list[Path]:
    files = [report]
    if shots:
        pattern = re.compile(re.escape(report.stem) + r"\.(?:pdf|(?:desktop|mobile)\.\d+\.png)$")
        files.extend(
            path
            for path in sorted(shots.iterdir())
            if path.is_file() and not path.is_symlink() and pattern.fullmatch(path.name)
        )

    unique = {}
    for path in files:
        unique[path.resolve()] = path
    return sorted(unique.values(), key=lambda path: path.name)


def content_hashes(files: list[Path]) -> dict[str, str]:
    hashes = {}
    for path in files:
        if path.name in hashes:
            raise SystemExit(f"同じ名前の成果物が複数ある: {path.name}")
        hashes[path.name] = sha256(path)
    return hashes


def skill_version() -> str:
    text = SKILL_MD.read_text(encoding="utf-8")
    frontmatter = re.match(r"---\s*\n(.*?)\n---", text, re.S)
    if not frontmatter:
        raise SystemExit(f"SKILL.md の frontmatter がない: {SKILL_MD}")
    match = re.search(r'^\s{2}version:\s*["\']([^"\']+)', frontmatter.group(1), re.M)
    return match.group(1) if match else "unknown"


def same_artifacts(target: Path, expected: dict[str, str]) -> bool:
    if not target.is_dir():
        return False
    actual = {
        path.name: sha256(path)
        for path in target.iterdir()
        if path.is_file() and path.name != "archive-info.json"
    }
    return actual == expected


def version_dir(root: Path) -> Path:
    if VERSION_DIR.fullmatch(root.name):
        return root
    candidates = [
        path
        for path in root.iterdir()
        if path.is_dir() and VERSION_DIR.fullmatch(path.name)
    ]
    if not candidates:
        return root
    return max(candidates, key=lambda path: int(VERSION_DIR.fullmatch(path.name).group(1)))


def write_bundle(
    target: Path,
    files: list[Path],
    hashes: dict[str, str],
    report: Path,
    version: str,
) -> None:
    for source in files:
        shutil.copy2(source, target / source.name)
        if sha256(target / source.name) != hashes[source.name]:
            raise SystemExit(f"保存中に成果物が変わった: {source.name}")
    manifest = {
        "skill": "report-design",
        "skill_version": version,
        "source_report": report.name,
        "artifacts": [
            {"name": name, "sha256": hashes[name]} for name in sorted(hashes)
        ],
    }
    (target / "archive-info.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def archive(
    report: Path,
    shots: Path | None,
    dest_root: Path,
    version: str,
) -> tuple[Path, bool]:
    files = collect_artifacts(report, shots)
    hashes = content_hashes(files)
    dest_root.mkdir(parents=True, exist_ok=True)
    target_root = version_dir(dest_root)
    target_root.mkdir(parents=True, exist_ok=True)

    preferred = target_root / report.stem
    if preferred.exists():
        if same_artifacts(preferred, hashes):
            return preferred, False
    else:
        target = preferred
        temp_dir = Path(tempfile.mkdtemp(prefix=".archive-tmp-", dir=target_root))
        try:
            write_bundle(temp_dir, files, hashes, report, version)
            temp_dir.replace(target)
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
        return target, True

    group_digest = hashlib.sha256()
    for name, digest in sorted(hashes.items()):
        group_digest.update(name.encode("utf-8"))
        group_digest.update(b"\0")
        group_digest.update(digest.encode("ascii"))
        group_digest.update(b"\0")
    target = target_root / f"{report.stem}-{group_digest.hexdigest()[:12]}"
    if same_artifacts(target, hashes):
        return target, False
    if target.exists():
        raise SystemExit(f"保存先に異なる内容の成果物がある: {target}")

    temp_dir = Path(tempfile.mkdtemp(prefix=".archive-tmp-", dir=target_root))
    try:
        write_bundle(temp_dir, files, hashes, report, version)
        temp_dir.replace(target)
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
    return target, True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="完成した報告書の HTML")
    parser.add_argument("--shots", type=Path, help="lint_report.py の --shots 保存先")
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST,
                        help="保存用フォルダ。環境変数 OHMYREPORT_ARCHIVE_DIR でも指定できる")
    parser.add_argument("--skill-version", default=skill_version(), help="SKILL.md の version")
    args = parser.parse_args()

    if args.dest is None:
        parser.error("--dest または OHMYREPORT_ARCHIVE_DIR で保存先を指定する")
    if args.report.is_symlink():
        parser.error("報告書にシンボリックリンクは指定できない")
    if not args.report.is_file():
        raise SystemExit(f"報告書がない: {args.report}")
    if args.shots and not args.shots.is_dir():
        raise SystemExit(f"画面の写しの保存先がない: {args.shots}")

    target, created = archive(
        args.report.resolve(),
        args.shots.resolve() if args.shots else None,
        args.dest.resolve(),
        args.skill_version,
    )
    state = "保存" if created else "保存済み"
    print(f"{state}: {target}")


if __name__ == "__main__":
    main()
