# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""pack.py — 구매자에게 보낼 zip을 만듭니다.

    uv run pack.py 1.0.0            dist/stackpack-1.0.0.zip 생성
    uv run pack.py 1.0.0 --check    만들지 않고 목록만 확인

손으로 zip을 묶으면 사람마다 다른 파일이 나갑니다. 여기서만 만듭니다.

규칙 하나: **분류되지 않은 파일이 하나라도 있으면 실패합니다.**
새 파일을 만들고 SHIP/KEEP 어느 쪽에도 안 넣으면 여기서 터집니다.
조용히 빠지는 것보다 시끄럽게 멈추는 편이 낫습니다.
"""

import argparse
import hashlib
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / "dist"

# 구매자에게 가는 것 — 이 순서대로 zip에 들어갑니다.
SHIP = [
    "시작하기.cmd",
    "install.ps1",
    "구매자-안내.md",
    "출처.md",
    "build.py",
    "check.py",
    "stack.yaml",
    "MODELS-UPDATE.md",
    "connectors/README.md",
    "connectors/n8n-cardnews.json",
    "examples/cardnews.py",
]

# 저장소에는 있지만 구매자에게는 안 가는 것.
KEEP = [
    "README.md",       # 공개 저장소 설명
    "index.html",      # 생성물 — 허브 페이지는 웹에서 봅니다
    "stars.json",      # 생성물
    "pack.py",         # 이 파일
    "app.py",          # 진단 페이지 생성기 — 무료 유입용
    "app.html",        # 생성물 — gh-pages로 올라갑니다
    "buy.html",        # 생성물 — sell.yaml 있을 때만
    "sell.yaml",       # 개인 송금 링크 — 저장소에도 zip에도 안 들어감
    "sell.example.yaml",
    "ci/pages.yml",    # 배포용
    ".gitignore",
]

# 아예 훑지 않는 경로.
SKIP_DIRS = {".git", "__pycache__", "dist", "out", "skill", ".venv", "venv"}
SKIP_NAMES = {".DS_Store"}

# zip 안의 타임스탬프를 고정합니다. 같은 버전이면 같은 바이트가 나오게.
FIXED_TIME = (2026, 1, 1, 0, 0, 0)


def walk_repo():
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        if set(rel.parts) & SKIP_DIRS:
            continue
        if rel.name in SKIP_NAMES:
            continue
        yield rel.as_posix()


def classify():
    """저장소 파일이 전부 SHIP 또는 KEEP에 들어 있는지 확인합니다."""
    on_disk = set(walk_repo())
    ship, keep = set(SHIP), set(KEEP)

    problems = []

    unknown = sorted(on_disk - ship - keep)
    if unknown:
        problems.append(
            "분류 안 된 파일이 있습니다. pack.py의 SHIP 또는 KEEP에 넣어 주세요:\n"
            + "\n".join(f"    {u}" for u in unknown)
        )

    missing = sorted(ship - on_disk)
    if missing:
        problems.append(
            "SHIP에 적혀 있는데 실제로 없는 파일:\n"
            + "\n".join(f"    {m}" for m in missing)
        )

    both = sorted(ship & keep)
    if both:
        problems.append(
            "SHIP과 KEEP에 동시에 있는 파일:\n"
            + "\n".join(f"    {b}" for b in both)
        )

    return problems


def check_bom():
    """PowerShell 5.1은 BOM 없는 UTF-8을 한글로 못 읽습니다. 깨진 안내문을 보내면 안 됩니다."""
    p = ROOT / "install.ps1"
    if p.read_bytes()[:3] != b"\xef\xbb\xbf":
        return ["install.ps1에 UTF-8 BOM이 없습니다. 윈도우에서 한글이 깨집니다."]
    return []


# 자리표시자를 찾을 파일 종류. JSON·파이썬은 뺍니다 —
# n8n 워크플로의 `"main": [[{...` 같은 배열 중첩을 자리표시자로 오인합니다.
PLACEHOLDER_SUFFIXES = {".md", ".ps1", ".cmd", ".txt", ".yaml", ".yml"}
PLACEHOLDER_RE = re.compile(r"\[\[[^\[\]{]{2,}?\]\]")


def check_placeholders():
    """`[[...]]` 가 남아 있으면 안 됩니다. 계좌번호 자리가 빈 채로 나가면 물건이 안 됩니다."""
    bad = []
    for rel in SHIP:
        p = ROOT / rel
        if p.suffix.lower() not in PLACEHOLDER_SUFFIXES:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if PLACEHOLDER_RE.search(line):
                bad.append(f"    {rel}:{i}  {line.strip()[:60]}")
    if bad:
        return ["채워지지 않은 자리가 있습니다:\n" + "\n".join(bad)]
    return []


def build(version: str) -> Path:
    DIST.mkdir(exist_ok=True)
    out = DIST / f"stackpack-{version}.zip"
    root_name = f"stackpack-{version}"

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in SHIP:
            info = zipfile.ZipInfo(f"{root_name}/{rel}", date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, (ROOT / rel).read_bytes())

    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("version", help="예: 1.0.0")
    ap.add_argument("--check", action="store_true", help="만들지 않고 목록만 확인")
    a = ap.parse_args()

    problems = classify() + check_bom() + check_placeholders()
    if problems:
        print("멈췄습니다.\n")
        for p in problems:
            print(p + "\n")
        return 1

    print(f"보낼 파일 {len(SHIP)}개:")
    total = 0
    for rel in SHIP:
        size = (ROOT / rel).stat().st_size
        total += size
        print(f"    {rel:<32} {size:>8,} B")
    print(f"    {'합계':<32} {total:>8,} B")

    if a.check:
        print("\n--check 라서 만들지 않았습니다.")
        return 0

    out = build(a.version)
    digest = hashlib.sha256(out.read_bytes()).hexdigest()[:16]
    print(f"\n만들었습니다: {out.relative_to(ROOT)}  ({out.stat().st_size:,} B)")
    print(f"sha256: {digest}…")
    print("\n같은 버전을 다시 만들면 이 값이 같아야 합니다. 다르면 내용이 바뀐 겁니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
