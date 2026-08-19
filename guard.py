# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""guard.py — AI 가 사고를 치기 **직전에** 막는 관문.

Claude Code 의 PreToolUse 훅으로 붙습니다. AI 가 파일을 쓰거나 명령을 돌리기
전에 이 파일이 먼저 봅니다. 오답노트에 있는 사고면 거기서 막습니다.

    규칙(vibe.yaml)  = 부탁입니다. AI 가 읽고 안 지킬 수도 있습니다.
    검사(check.py)   = 이미 난 사고를 찾습니다. 사람이 돌려야 합니다.
    관문(guard.py)   = **막습니다.** 사람이 아무것도 안 해도 됩니다.

검사 규칙은 check.py 것을 그대로 씁니다. 두 벌로 만들면 갈라집니다(P5).

## 터지면 통과시킵니다 (fail-open)

이 파일이 예외를 내면 **아무것도 막지 않고 조용히 통과**시킵니다.
관문이 고장 나서 남의 편집기를 멈추게 하면, 그 사람은 이걸 지웁니다.
막지 못한 사고보다 못 쓰게 된 도구가 더 나쁩니다.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

LOG = Path.home() / ".stackpack" / "막은기록.jsonl"

# 위험 → 막음, 주의 → 사람에게 물어봄
DENY, ASK = "deny", "escalate"


def _check():
    try:
        from . import check
        return check
    except ImportError:
        pass
    try:
        import check
        return check
    except ImportError:
        return None


def 볼_내용(tool, ti):
    """이번 도구 호출에서 **새로 써질 글**과 그 파일 이름."""
    if tool == "Write":
        return ti.get("file_path", ""), ti.get("content", "")
    if tool in ("Edit", "NotebookEdit"):
        return ti.get("file_path", ""), ti.get("new_string", "")
    if tool == "Bash":
        return "", ti.get("command", "")
    return "", ""


def 판정(tool, ti):
    """(결정, 사고번호, 사유) 또는 None. check.py 의 규칙을 그대로 씁니다."""
    c = _check()
    if c is None:
        return None
    name, text = 볼_내용(tool, ti)
    if not text:
        return None
    lines = text.splitlines()
    base = Path(name).name

    # E5 — .env 를 git 에 올리려 할 때
    if tool == "Bash":
        cmd = " ".join(text.split())
        if "git add" in cmd and (".env" in cmd and not ".env.example" in cmd):
            return (DENY, "E5", ".env 를 git 에 올리려 하고 있습니다. 커밋에 남으면 "
                    "파일을 지워도 히스토리에 남습니다. .gitignore 에 넣으세요.")
        return None

    # E8 — 키·계좌가 파일에 박히려 할 때
    for i, line in c.live_lines(lines):
        for rx, what in c.SECRET_PATTERNS:
            if rx.search(line):
                return (DENY, "E8", f"{what} 로 보이는 값을 {base}:{i} 에 그대로 적으려 "
                        "하고 있습니다. 한 번 올리면 회수가 안 됩니다. 환경변수로 빼세요.")
        if c.looks_like_account(line) and "example" not in line.lower():
            return (DENY, "E8", f"계좌번호로 보이는 값을 {base}:{i} 에 적으려 하고 "
                    "있습니다. 저장소가 아니라 DB 로 보내세요.")

    # E7 — 소스 폴더를 통째로 서빙하려 할 때
    if Path(name).suffix in {".js", ".mjs", ".cjs", ".ts"}:
        for i, line in c.live_lines(lines):
            if c.STATIC_ROOT_RE.search(line):
                return (DENY, "E7", f"{base}:{i} 에서 정적 서빙이 프로젝트 루트를 "
                        "가리킵니다. 소스·설정·백업이 그대로 읽힙니다. public/ 만 여세요.")

    # E13 — 머신을 24시간 켜 두는 설정
    if base == "fly.toml":
        import re as _re
        off = _re.search(r"auto_stop_machines\s*=\s*['\"]?(off|false)", text)
        run = _re.search(r"min_machines_running\s*=\s*(\d+)", text)
        if off and run and int(run.group(1)) >= 1:
            return (DENY, "E13", "머신을 24시간 켜 두는 설정입니다. Fly 무료 체험은 "
                    "「2시간 또는 7일 중 먼저 오는 것」입니다. 03:06 에 배포하고 05시쯤 "
                    "죽은 걸 14시간 뒤에 안 사고가 있었습니다.")

    # E10 — 아무것도 안 보는 검사 (위험까진 아니라 사람에게 물어봅니다)
    low = base.lower()
    if any(k in low for k in ("test", "e2e", "check", "spec")):
        for i, line in c.live_lines(lines):
            if "inner_text(" in line or ".innerText" in line:   # check:ignore
                return (ASK, "E10", f"{base}:{i} 에서 inner_text 로 단언하고 있습니다. "
                        "숨은 요소는 빈 값을 돌려줘서 이 검사는 언제나 통과합니다. "
                        "textContent 로 읽으세요.")
    return None


def 기록(사고, tool, name):
    """무엇을 막았는지만 셉니다. **막은 내용은 안 적습니다** — 그게 바로 비밀입니다."""
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"때": datetime.now().isoformat(timespec="seconds"),
                                "사고": 사고, "도구": tool,
                                "파일": Path(name).name}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def main():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0
        ev = json.loads(raw)
        tool = ev.get("tool_name", "")
        ti = ev.get("tool_input") or {}

        # 우리 자신을 막지 않습니다. 오답노트를 고치는 중일 수 있습니다.
        fp = str(ti.get("file_path", ""))
        if "stackpack" in fp or Path(fp).name in {"vibe.yaml", "check.py", "guard.py", "ERRORS.md"}:
            return 0

        결과 = 판정(tool, ti)
        if 결과 is None:
            return 0
        결정, 사고, 사유 = 결과
        기록(사고, tool, fp)
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": 결정,
            "permissionDecisionReason": f"[{사고}] {사유}  (스택팩 관문 · 끄려면 stackpack 관문 끄기)",
        }}, ensure_ascii=False))
        return 0
    except Exception:
        # 여기서 죽으면 남의 편집기가 멈춥니다. 조용히 통과시킵니다.
        return 0


if __name__ == "__main__":
    sys.exit(main())
