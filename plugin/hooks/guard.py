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
import re
import sys
from datetime import datetime
from pathlib import Path

LOG = Path.home() / ".stackpack" / "막은기록.jsonl"

# AI 가 쓴 것을 사람이 곧 되돌리면, 그건 «AI 가 여기서 틀렸다» 는 가장 강한 신호입니다.
# 사람이 한 글자도 안 써도 잡힙니다. 이게 새 사고를 자동으로 찾는 유일한 길입니다.
#
# **내용은 저장하지 않습니다.** 글자를 해시로 바꿔 «같은 것인가» 만 봅니다.
# 해시로는 원문을 되살릴 수 없습니다 — 그래서 이 파일이 새어도 코드가 새지 않습니다.
WRITES = Path.home() / ".stackpack" / "쓴것.jsonl"
REVERTS = Path.home() / ".stackpack" / "되돌린것.jsonl"
되돌림_시간 = 60 * 60          # 이 안에 지워지면 «되돌림» 으로 봅니다

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
    #
    # 명령 전체에서 «git add» 와 «.env» 를 따로 찾으면 안 됩니다. 한 줄에 여러
    # 명령이 붙어 있거나 문서 본문에 «.env» 라는 글자가 있으면 엉뚱하게 막습니다 —
    # 실제로 이 저장소의 커밋이 그렇게 한 번 막혔습니다(E16 과 같은 병).
    # 그래서 **git add 로 시작하는 토막만** 보고, 거기서 **인자 하나가 정확히**
    # .env 인지 봅니다. 오탐이 나는 도구는 지워집니다.
    if tool == "Bash":
        import shlex
        for 토막 in re.split(r"&&|\|\||;|\n|\|", text):
            토막 = 토막.strip()
            if not 토막.startswith("git "):
                continue
            try:
                말 = shlex.split(토막)
            except ValueError:
                continue
            if len(말) < 3 or 말[1] != "add":
                continue
            for 인자 in 말[2:]:
                이름 = Path(인자).name
                if 이름 == ".env" or (이름.startswith(".env.")
                                     and not 이름.endswith((".example", ".sample", ".template"))):
                    return (DENY, "E5", f"{인자} 를 git 에 올리려 하고 있습니다. 커밋에 "
                            "남으면 파일을 지워도 히스토리에 남습니다. .gitignore 에 넣으세요.")
        # E29 · E30 — ffmpeg 명령. 막지 않고 **물어봅니다** — 의도적으로 그렇게
        # 쓰는 경우가 있고, 오탐으로 막으면 도구가 지워집니다(E28).
        for 토막 in c.FFMPEG_RE.findall(text):
            if c._시크사고(토막):
                return (ASK, "E29", "-ss 가 -i 앞에만 있습니다. 키프레임 단위로 건너뛰어 "
                        "영상만 늦게 시작하고, 이어붙이면 이음매마다 쌓입니다. "
                        "우리는 96프레임(3.2초)까지 벌어져 참가자 얼굴이 샜습니다. "
                        "-ss (t-4) 뒤에 trim=start=4 로 정확히 자르세요.")
            if "loudnorm" in 토막 and "aresample" not in 토막:
                return (ASK, "E30", "loudnorm 뒤에 aresample 이 없습니다. 표본율이 올라간 채 "
                        "96kHz 로 나가는데 귀로는 안 들립니다. aresample=48000 을 붙이세요.")
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


def 명령도구(text):
    """막힌 명령의 **도구 이름 하나.** 인자도 경로도 옵션도 안 봅니다.

    «어떤 분야에서 사고가 나는가» 를 알기 위한 것이지 «이 사람이 뭘 쓰는가» 가
    아닙니다. 그래서 **관문이 실제로 걸린 명령만** 여기 들어옵니다.
    """
    import shlex
    # 자리만 옮기는 명령은 «도구» 가 아닙니다. `cd app && git add .env` 에서
    # 첫 토막을 잡으면 «cd» 가 나와 신호가 사라집니다 — 실제로 그렇게 나왔습니다.
    # 두 가지를 갈라야 합니다.
    #   토막째 건너뛴다 — `cd app` 은 명령이 아니라 자리 옮기기입니다.
    #                    단어만 건너뛰면 «app» 을 도구로 잡습니다(실제로 그랬습니다).
    #   단어만 건너뛴다 — `sudo docker …` 에서 진짜 도구는 docker 입니다.
    토막통째 = {"cd", "pushd", "popd", "export", "source", ".", "set", "unset"}
    감싸는것 = {"sudo", "time", "nohup", "exec", "env", "xargs"}
    for 토막 in re.split(r"&&|\|\||;|\n|\|", text or ""):
        토막 = 토막.strip()
        if not 토막:
            continue
        try:
            말 = shlex.split(토막)
        except ValueError:
            continue
        if Path(말[0]).name in 토막통째:
            continue
        for 낱말 in 말:
            이름 = Path(낱말).name
            if "=" in 낱말 or 이름 in 감싸는것:
                continue                  # FOO=1 · sudo 같은 것은 건너뜁니다
            return 이름
    return ""


def 기록(사고, tool, name, 도구=""):
    """무엇을 막았는지만 셉니다. **막은 내용은 안 적습니다** — 그게 바로 비밀입니다."""
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            줄 = {"때": datetime.now().isoformat(timespec="seconds"),
                 "사고": 사고, "도구": tool, "파일": Path(name).name}
            if 도구:
                줄["명령도구"] = 도구
            f.write(json.dumps(줄, ensure_ascii=False) + "\n")
    except OSError:
        pass


def 지문(글):
    """글자를 해시로. 원문은 남기지 않습니다."""
    import hashlib
    return hashlib.sha256(" ".join(글.split()).encode()).hexdigest()[:16]


def 쓴것_기록(tool, name, 글):
    try:
        WRITES.parent.mkdir(parents=True, exist_ok=True)
        with WRITES.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": datetime.now().isoformat(timespec="seconds"),
                                "지문": 지문(글), "줄수": len(글.splitlines()),
                                "확장자": Path(name).suffix or "(없음)"},
                               ensure_ascii=False) + "\n")
    except OSError:
        pass


def 되돌림_확인(name, 사라지는글):
    """방금 AI 가 쓴 것이 지워지는 중인가. 맞으면 기록만 하고 막지는 않습니다."""
    if not WRITES.exists() or not 사라지는글.strip():
        return
    찾는지문 = 지문(사라지는글)
    이제 = datetime.now()
    try:
        for line in reversed(WRITES.read_text(encoding="utf-8").splitlines()[-300:]):
            r = json.loads(line)
            if r["지문"] != 찾는지문:
                continue
            지난초 = (이제 - datetime.fromisoformat(r["t"])).total_seconds()
            if 0 <= 지난초 <= 되돌림_시간:
                REVERTS.parent.mkdir(parents=True, exist_ok=True)
                with REVERTS.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(
                        {"t": 이제.isoformat(timespec="seconds"),
                         "확장자": r["확장자"], "줄수": r["줄수"],
                         "몇초만에": int(지난초)}, ensure_ascii=False) + "\n")
            return
    except (OSError, json.JSONDecodeError, ValueError):
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

        # 되돌림 감지 — 막는 것과 별개로 항상 봅니다
        try:
            if tool in ("Edit", "NotebookEdit") and ti.get("old_string"):
                되돌림_확인(fp, str(ti["old_string"]))
            _, 쓰는글 = 볼_내용(tool, ti)
            if tool in ("Write", "Edit", "NotebookEdit") and 쓰는글:
                쓴것_기록(tool, fp, 쓰는글)
        except Exception:
            pass

        결과 = 판정(tool, ti)
        if 결과 is None:
            return 0
        결정, 사고, 사유 = 결과
        기록(사고, tool, fp, 명령도구(ti.get("command", "")) if tool == "Bash" else "")
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
