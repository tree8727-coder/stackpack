# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""check.py — 배포 직전 점검. 우리가 실제로 당한 것만 봅니다.

    uv run check.py .              지금 폴더 점검
    uv run check.py ../my-app      다른 폴더 점검
    uv run check.py --selftest     검사기 자체를 검사 (픽스처로)

검사 항목은 전부 `ERRORS.md` 의 실제 사고에서 나왔습니다. 일반론이 아닙니다.
찾은 것마다 사고 번호가 붙습니다 — 어떤 일이 실제로 있었는지 읽어보라는 뜻입니다.

**여기서 못 찾았다고 안전한 게 아닙니다.** 우리가 당해 본 것만 봅니다.
그 문장을 결과 맨 아래에 항상 찍습니다.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
    ".next", "out", "backups", ".pytest_cache", "site-packages",
}
MAX_BYTES = 400_000          # 이보다 큰 파일은 소스가 아니라고 봅니다
TEXT_SUFFIXES = {
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".toml", ".yaml", ".yml",
    ".json", ".sh", ".ps1", ".env", ".ini", ".cfg", ".txt", ".md", ".html",
}


# 줄 안에 이 표시가 있으면 모든 검사가 건너뜁니다.
# 패턴을 적어 둔 파일(이 파일이 그렇습니다), 테스트 픽스처, 문서의 예시가
# 잡히면 오탐입니다. 다만 **끄는 흔적이 코드에 남아야** 합니다 — 조용히 못 끕니다.
IGNORE_MARK = "check:ignore"


def live_lines(lines):
    """억제 표시가 없는 줄만 (줄번호, 내용) 으로 돌려줍니다."""
    return [(i, ln) for i, ln in enumerate(lines, 1) if IGNORE_MARK not in ln]


class Finding:
    def __init__(self, code, level, where, what, why, fix):
        self.code, self.level = code, level
        self.where, self.what, self.why, self.fix = where, what, why, fix


# ─── 검사들 ──────────────────────────────────────────────────────────────────
# 각 검사는 (findings 리스트에 append) 하고 끝냅니다.

SECRET_PATTERNS = [
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"), "Anthropic API 키"),
    (re.compile(r"\bsk-[A-Za-z0-9]{32,}"), "OpenAI 형식 API 키"),
    (re.compile(r"\bghp_[A-Za-z0-9]{30,}"), "GitHub 개인 토큰"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"), "Slack 토큰"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS 액세스 키"),
]

# 계좌번호: 은행명이 같은 줄에 있고 숫자 덩어리가 붙어 있을 때만. (E8)
#
# 「우리」는 은행 이름이자 대명사다. 라켓온 문서의 `## 27. … 우리 설계 (2026-08-17)` 이
# 「우리은행 + 계좌번호」로 읽혔다 — 날짜를 계좌로 본 것이다.
# 그래서 ① 우리는 「우리은행」일 때만 ② 숫자를 다 붙여서 10자리 이상일 때만
# ③ 날짜 모양이면 버린다. 오탐이 나는 검사기는 아무도 안 쓴다.
ACCOUNT_RE = re.compile(
    r"(국민|신한|우리은행|하나|농협|기업|카카오뱅크|토스뱅크|새마을|우체국|SC제일)"
    r"\D{0,12}(\d[\d\-\s]{8,})"
)
# 날짜만 걸러내야 한다. 처음엔 `\d{4}-\d{1,2}-\d{1,2}` 로 썼다가
# 진짜 계좌 `123456-01-234567` 안의 `3456-01-23` 을 날짜로 읽어 놓쳤다.
# 앞뒤로 숫자가 붙어 있지 않고, 연도 모양(19xx/20xx)일 때만 날짜로 본다.
DATE_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}\s*[-.]\s*\d{1,2}\s*[-.]\s*\d{1,2}(?!\d)")
ENV_TEMPLATE_SUFFIXES = (".example", ".sample", ".template", ".dist")


def looks_like_account(line: str) -> bool:
    m = ACCOUNT_RE.search(line)
    if not m:
        return False
    if DATE_RE.search(m.group(0)):
        return False
    return len(re.sub(r"\D", "", m.group(2))) >= 10

STATIC_ROOT_RE = re.compile(
    r"express\.static\(\s*(__dirname|['\"]\.['\"]|['\"]\./?['\"]|process\.cwd\(\))\s*[,)]"
)


def scan_files(root: Path):
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if set(p.relative_to(root).parts) & SKIP_DIRS:
            continue
        if p.suffix.lower() not in TEXT_SUFFIXES and p.name != ".env":
            continue
        try:
            if p.stat().st_size > MAX_BYTES:
                continue
            yield p, p.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue


def check_env_tracked(root: Path, findings):
    """E5 — `.env` 가 저장소에 딸려 들어가 있었다."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files"],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return
    if out.returncode != 0:
        return
    for line in out.stdout.splitlines():
        name = Path(line).name
        # .env.example 같은 템플릿은 일부러 커밋하는 파일이다. 이걸 잡으면 오탐이다.
        if name.endswith(ENV_TEMPLATE_SUFFIXES):
            continue
        if name == ".env" or name.startswith(".env."):
            findings.append(Finding(
                "E5", "위험", line,
                "`.env` 가 git 에 추적되고 있습니다",
                "커밋에 남으면 지워도 히스토리에 남습니다. 공개 저장소면 그대로 노출입니다.",
                f"git rm --cached {line}  그리고 .gitignore 에 추가. 이미 밀었다면 키를 새로 발급하세요.",
            ))


def check_gitignore(root: Path, findings):
    """E5 — 막을 수 있었는데 .gitignore 에 없었다."""
    gi = root / ".gitignore"
    if not (root / ".git").exists():
        return
    text = gi.read_text(encoding="utf-8") if gi.exists() else ""
    if not re.search(r"^\s*\.env", text, re.M):
        findings.append(Finding(
            "E5", "주의", ".gitignore",
            ".gitignore 에 `.env` 규칙이 없습니다",
            "지금은 파일이 없어도, 나중에 만들면 그대로 커밋됩니다.",
            ".gitignore 에 `.env` 와 `.env.*` 를 추가하세요.",
        ))


def check_static_root(root: Path, findings):
    """E7 — 정적 서빙이 소스 폴더를 통째로 열어 뒀다."""
    for p, lines in scan_files(root):
        if p.suffix not in {".js", ".mjs", ".cjs", ".ts"}:
            continue
        for i, line in live_lines(lines):
            if STATIC_ROOT_RE.search(line):
                findings.append(Finding(
                    "E7", "위험", f"{p.relative_to(root)}:{i}",
                    "정적 서빙이 프로젝트 루트를 가리킵니다",
                    "소스·설정·백업이 그대로 읽힙니다. 공개 터널을 열고서야 알았던 사고입니다.",
                    "`public/` 같은 전용 폴더만 서빙하세요.",
                ))


def check_secrets(root: Path, findings):
    """E8 — 비밀이 소스에 박혀 있었다."""
    for p, lines in scan_files(root):
        rel = p.relative_to(root)
        for i, line in live_lines(lines):
            for rx, what in SECRET_PATTERNS:
                if rx.search(line):
                    findings.append(Finding(
                        "E8", "위험", f"{rel}:{i}",
                        f"{what} 로 보이는 값이 소스에 있습니다",
                        "한 번 밀면 회수가 안 됩니다. 크롤러가 공개 저장소를 먼저 봅니다.",
                        "환경변수로 빼고, 이미 밀었다면 키를 폐기하고 새로 발급하세요.",
                    ))
                    break
            if looks_like_account(line) and "example" not in line.lower():
                findings.append(Finding(
                    "E8", "위험", f"{rel}:{i}",
                    "계좌번호로 보이는 값이 소스에 있습니다",
                    "우리는 로그인 안 한 사람에게 주최자 계좌가 통째로 보였습니다.",
                    "저장소가 아니라 DB로 옮기고, 응답에서 누구에게 보이는지 다시 보세요.",
                ))


def check_fly_free_tier(root: Path, findings):
    """E13 — 무료 체험을 우리 설정으로 두 시간 만에 태웠다."""
    for p, lines in scan_files(root):
        if p.name != "fly.toml":
            continue
        text = "\n".join(lines)
        auto_off = re.search(r"auto_stop_machines\s*=\s*['\"]?(off|false)['\"]?", text)
        min_run = re.search(r"min_machines_running\s*=\s*(\d+)", text)
        if auto_off and min_run and int(min_run.group(1)) >= 1:
            findings.append(Finding(
                "E13", "위험", str(p.relative_to(root)),
                "머신을 24시간 켜 두는 설정입니다",
                "Fly 무료 체험은 「VM 2시간 또는 7일 중 먼저 오는 것」입니다. "
                "우리는 03:06 에 배포하고 05시쯤 죽은 걸 14시간 뒤에 알았습니다.",
                "auto_stop_machines 를 켜고 min_machines_running 을 0 으로. "
                "콜드 스타트가 싫어서 껐다면, 그 대비책을 이미 만들어 놓고 껐던 건 아닌지 보세요.",
            ))


def check_hidden_assert(root: Path, findings):
    """E10 — 숨긴 요소를 inner_text 로 보면 검사가 항상 통과한다."""
    for p, lines in scan_files(root):
        name = p.name.lower()
        if not ("test" in name or "e2e" in name or "check" in name or "spec" in name):
            continue
        for i, line in live_lines(lines):
            if "inner_text(" in line or ".innerText" in line:   # check:ignore
                findings.append(Finding(
                    "E10", "주의", f"{p.relative_to(root)}:{i}",
                    "검사가 `inner_text` 로 단언하고 있습니다",
                    "숨은 요소(display:none)는 `\"\"` 를 돌려줍니다. "
                    "`\"문구\" not in \"\"` 는 언제나 참이라, 지키는 것 없이 통과합니다.",
                    "`textContent` 로 DOM 을 직접 읽으세요. 그리고 그 단언이 지키려는 코드를 "
                    "한 줄 주석 처리하고 한 번 돌려서, 진짜 터지는지 보세요.",
                ))


# 한 덩어리가 이만큼 넘으면 «고치기 어려운 코드» 로 봅니다. (E26)
# 이 숫자는 우리가 실제로 아파 본 지점입니다 — vibe.py 가 1,181줄, do_selftest 가
# 308줄까지 자랐고, 그 상태에서 문자열 치환으로 고치다 함수 안쪽을 건드려 파일이 깨졌습니다.
# **우리 저장소가 먼저 걸립니다.** 우리가 안 걸리는 기준은 아무도 안 믿습니다.
MAX_FUNC_LINES = 200
MAX_FILE_LINES = 800


def check_too_big(root: Path, findings):
    """E26 — 한 덩어리가 너무 커져서 고칠 때마다 엉뚱한 곳이 같이 바뀐다."""
    import ast as _ast

    for p, lines in scan_files(root):
        rel = p.relative_to(root)
        if len(lines) > MAX_FILE_LINES:
            findings.append(Finding(
                "E26", "주의", str(rel),
                f"파일이 {len(lines)}줄입니다 (기준 {MAX_FILE_LINES})",
                "AI 는 파일을 «구조» 가 아니라 «글자» 로 고칩니다. 커질수록 같은 글자가 여러 번 "
                "나오고, 한 곳을 고치려던 치환이 다른 곳까지 바꿉니다.",
                "역할이 다른 덩어리를 파일로 분리하세요. 옮기기만 해도 다음 수정이 쉬워집니다.",
            ))
        if p.suffix != ".py":
            continue
        try:
            tree = _ast.parse("\n".join(lines))
        except SyntaxError:
            continue
        for n in _ast.walk(tree):
            if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                길이 = (n.end_lineno or n.lineno) - n.lineno
                if 길이 > MAX_FUNC_LINES:
                    findings.append(Finding(
                        "E26", "주의", f"{rel}:{n.lineno}",
                        f"함수 `{n.name}` 이 {길이}줄입니다 (기준 {MAX_FUNC_LINES})",
                        "이 안에서 뭘 고치려면 전부 읽어야 합니다. 사람도 AI 도 마찬가지입니다.",
                        "하는 일 단위로 쪼개세요. 이름이 안 떠오르는 덩어리가 있으면 "
                        "그게 아직 정리가 안 된 부분입니다.",
                    ))


# ffmpeg 명령을 «토막» 단위로 봅니다. 명령 전체에서 글자를 찾으면 무관한 것을
# 막습니다 — E28 에서 그렇게 우리 커밋이 막혔습니다.
FFMPEG_RE = re.compile(r"\bffmpeg\b[^\n;&|]*")


def _시크사고(명령: str) -> bool:
    """-ss 가 -i 앞에만 있고 trim 으로 정확히 자르지 않는가. (E29)"""
    if "-i" not in 명령:
        return False
    앞 = 명령.split("-i", 1)[0]
    if "-ss" not in 앞:
        return False
    # 뒤에서 정확히 자르면 괜찮습니다
    return "trim=" not in 명령 and "atrim=" not in 명령


def check_ffmpeg_seek(root: Path, findings):
    """E29 — -ss 를 -i 앞에만 써서 영상만 밀린다."""
    for p, lines in scan_files(root):
        for i, line in live_lines(lines):
            for 토막 in FFMPEG_RE.findall(line):
                if _시크사고(토막):
                    findings.append(Finding(
                        "E29", "주의", f"{p.relative_to(root)}:{i}",
                        "`-ss` 가 `-i` 앞에만 있습니다",
                        "키프레임 단위로 건너뛰어 영상만 늦게 시작합니다. 이어붙이면 "
                        "이음매마다 쌓여 우리는 누적 96프레임(3.2초)까지 벌어졌고, "
                        "모자이크 정책이 화면과 어긋나 참가자 얼굴이 샜습니다.",
                        "2단계 시크를 쓰세요 — `-ss (t-4) -i SRC` 뒤에 "
                        "`trim=start=4` / `atrim=start=4`. 그리고 `-frames:v N` 으로 프레임 수를 못박으세요.",
                    ))
                    break


def check_loudnorm(root: Path, findings):
    """E30 — loudnorm 뒤에 aresample 이 없으면 96kHz 로 나간다."""
    for p, lines in scan_files(root):
        for i, line in live_lines(lines):
            for 토막 in FFMPEG_RE.findall(line):
                if "loudnorm" in 토막 and "aresample" not in 토막:
                    findings.append(Finding(
                        "E30", "주의", f"{p.relative_to(root)}:{i}",
                        "`loudnorm` 뒤에 `aresample` 이 없습니다",
                        "loudnorm 은 내부에서 표본율을 올립니다. 그대로 두면 96kHz 로 "
                        "나가는데 플레이어에서는 멀쩡히 들려서 배포 직전까지 모릅니다.",
                        "`aresample=48000` 을 붙이고, 내보낸 뒤 `ffprobe` 로 표본율을 확인하세요.",
                    ))
                    break


CHECKS = [
    check_too_big, check_ffmpeg_seek, check_loudnorm,
    check_env_tracked, check_gitignore, check_static_root,
    check_secrets, check_fly_free_tier, check_hidden_assert,
]


def run_checks(root: Path):
    findings = []
    for fn in CHECKS:
        fn(root, findings)
    return findings


# ─── 출력 ────────────────────────────────────────────────────────────────────

def report(root: Path, findings) -> int:
    print(f"점검: {root}")
    print(f"검사 {len(CHECKS)}가지 — 전부 우리가 실제로 당한 사고에서 나왔습니다.\n")

    if not findings:
        print("  찾은 것 없음.\n")
    else:
        danger = [f for f in findings if f.level == "위험"]
        for f in findings:
            mark = "!!" if f.level == "위험" else "! "
            print(f"  {mark} [{f.code}] {f.where}")
            print(f"       {f.what}")
            print(f"       왜: {f.why}")
            print(f"       고치기: {f.fix}\n")
        print(f"  위험 {len(danger)} / 주의 {len(findings) - len(danger)}\n")

    print("  ── 여기서 못 찾았다고 안전한 게 아닙니다. 우리가 당해 본 것만 봅니다. ──")
    if findings:
        print(f"     오탐이면 그 줄 끝에 `{IGNORE_MARK}` 를 적으세요. 끈 흔적이 코드에 남습니다.")
    return 1 if any(f.level == "위험" for f in findings) else 0


# ─── 자체 검사 ───────────────────────────────────────────────────────────────

def selftest() -> int:
    """검사기가 진짜로 잡는지, 그리고 멀쩡한 코드를 안 잡는지 둘 다 봅니다.

    한쪽만 보면 반쪽입니다. 다 잡는 검사기는 아무 말도 안 하는 검사기와 같습니다.
    """
    import tempfile

    fails = []

    def case(name, files, expect_codes, git=False):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for rel, body in files.items():
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(body, encoding="utf-8")
            if git:
                subprocess.run(["git", "init", "-q", str(root)], check=False,
                               capture_output=True)
                subprocess.run(["git", "-C", str(root), "add", "-A"], check=False,
                               capture_output=True)
            got = {f.code for f in run_checks(root)}
            if got != expect_codes:
                fails.append(f"  {name}: 기대 {sorted(expect_codes)} / 실제 {sorted(got)}")
            else:
                print(f"  OK  {name}  →  {sorted(got) or '아무것도 안 잡음'}")

    # 잡아야 하는 것들
    case("E7 루트 정적 서빙",
         {"server.js": "app.use(express.static(__dirname));\n"}, {"E7"})
    case("E8 API 키",
         {"cfg.py": "KEY = 'sk-ant-abcdefghijklmnopqrstuvwxyz0123'\n"}, {"E8"})  # check:ignore
    case("E8 계좌번호",
         {"pay.js": "const acct = '국민 123456-01-234567';\n"}, {"E8"})  # check:ignore
    case("E13 fly 무료티어 소각",
         {"fly.toml": "auto_stop_machines = 'off'\nmin_machines_running = 1\n"}, {"E13"})
    case("E10 숨은 요소 단언",
         {"test_e2e.py": 'A("오래" not in pg.inner_text("#boot"))\n'}, {"E10"})  # check:ignore
    case("E5 .env 추적 + gitignore 없음",
         {".env": "SECRET=1\n", "a.py": "x = 1\n"}, {"E5"}, git=True)

    # 잡으면 안 되는 것들 — 오탐이 나면 아무도 안 씁니다
    case("멀쩡한 정적 서빙",
         {"server.js": "app.use(express.static('public'));\n"}, set())
    case("예시 키 문자열",
         {"README.md": "키는 sk-로 시작합니다\n"}, set())
    case("fly 무료티어 안전 설정",
         {"fly.toml": "auto_stop_machines = 'stop'\nmin_machines_running = 0\n"}, set())
    case("테스트 아닌 파일의 inner_text",
         {"app.js": "el.innerText = '안녕';\n"}, set())  # check:ignore
    case("계좌 예시",
         {"docs.md": "예: 국민 123456-01-234567 (example)\n"}, set())  # check:ignore
    # 아래 둘은 라켓온에 실제로 돌려보고 나온 오탐이다. 고친 뒤 픽스처로 박아 둔다.
    case("오탐: 「우리 설계 (2026-08-17)」",
         {"doc.md": "## 27. 경쟁 앱 1점 리뷰 36건 -> 우리 설계 (2026-08-17)\n"}, set())
    case("오탐: .env.example 템플릿",
         {".env.example": "SECRET=\n", ".gitignore": ".env\n"}, set(), git=True)
    # .env 가 있어도 .gitignore 로 막혀 있으면 git 이 추적하지 않는다 → 아무것도 안 잡는 게 정답.
    # 처음엔 여기서 E5 가 나올 거라 적었다가, 픽스처가 그 기대가 틀렸다고 알려줬다.
    case("억제 표시 없으면 잡는다",
         {"a.js": "app.use(express.static(__dirname));\n"}, {"E7"})
    case("억제 표시 있으면 안 잡는다",
         {"a.js": "app.use(express.static(__dirname));  // check:ignore\n"}, set())
    case("제대로 막아 둔 .env",
         {".env": "S=1\n", ".gitignore": ".env\n"}, set(), git=True)

    print()
    if fails:
        print(f"{len(fails)}개 실패:")
        for f in fails:
            print(f)
        return 1
    print("전부 통과.")
    return 0


def main(argv=None) -> int:
    # argv 를 받습니다. vibe.py 의 `검사` 명령이 이 함수를 그대로 부릅니다 —
    # 검사 로직을 두 벌로 만들지 않으려는 것입니다(P5).
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", nargs="?", default=".", help="점검할 폴더 (기본: 지금 폴더)")
    ap.add_argument("--selftest", action="store_true", help="검사기 자체를 검사")
    a = ap.parse_args(argv)

    if a.selftest:
        return selftest()

    root = Path(a.path).resolve()
    if not root.is_dir():
        print(f"폴더가 아닙니다: {root}")
        return 2
    return report(root, run_checks(root))


if __name__ == "__main__":
    sys.exit(main())
