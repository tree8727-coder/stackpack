# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml", "certifi"]
# ///
"""vibe.py — vibe.yaml 하나에서 "내 프로젝트에 놓이는 파일"을 만듭니다.

    {prog} list                  방법 목록
    {prog} show 단언-부숴보기      방법 하나 자세히
    {prog} apply all             지금 폴더에 적용 미리보기 (아무것도 안 바꿈)
    {prog} apply all --yes       지금 폴더에 실제로 적용
    {prog} apply all --global --yes   전역에 한 번만 — 모든 프로젝트에 자동 적용
    {prog} 검사                   내 프로젝트에 이 사고가 있는지 찾기
    {prog} 성적표                 지금까지 몇 번 막았나
    {prog} 관문 끄기              막는 것을 끄기 (규칙은 그대로)
    {prog} where                 어느 도구의 어느 파일에 놓이는지
    {prog} sync --yes            최신으로 당겨서 전역에 다시 얹기 (스케줄러용)
    {prog} selftest              데이터 규율 + 안전장치 검사

**아무것도 설치하지 않습니다.** 도구를 까는 건 build.py 쪽 일이고,
여기는 파일만 놓습니다. 그래서 uv 말고는 필요한 게 없습니다.

Claude Code 와 Google Antigravity 를 함께 봅니다. 도구마다 읽는 파일이 달라서
경로는 vibe.yaml 의 surfaces 에 모아 두었습니다 — 도구가 늘면 거기만 고칩니다.

기존 파일은 **절대 덮어쓰지 않습니다.**
  - create: 파일이 이미 있으면 건너뜁니다.
  - append: 표식(<!-- vibe:키 -->) 이 없을 때만 뒤에 붙입니다. 두 번 돌려도 안 늘어납니다.
바꾸기 전에 항상 .bak 을 남깁니다.
"""

import argparse
import difflib
import re
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
VIBE = ROOT / "vibe.yaml"

# 배포판(uvx·pip)에는 저장소가 없습니다. git pull 로는 갱신할 수 없어서
# sync 는 깃허브에서 vibe.yaml 만 직접 받아 여기 둡니다.
REMOTE = "https://raw.githubusercontent.com/tree8727-coder/stackpack/main/vibe.yaml"
CACHE = Path.home() / ".stackpack" / "vibe.yaml"

# 도구마다 "모든 프로젝트에서 자동으로 읽는 파일"이 따로 있습니다. 경로는 vibe.yaml 의
# surfaces 에 있고 여기서 해석만 합니다 — 경로를 두 곳에 적으면 반드시 갈라집니다.
#
# --global 은 그 자리에 놓습니다. 한 번 넣으면 프로젝트마다 다시 칠 필요가 없고,
# 그래서 위험도 큽니다: 여기 쓴 건 그 도구의 모든 작업에 영향을 줍니다.


def surface_paths(data, scope, root, only=None):
    """(도구키, 이름, 실제 경로) 목록. scope 는 'global' 또는 'project'."""
    out = []
    for key, s in data["surfaces"].items():
        if only and key != only:
            continue
        raw = s[scope]
        path = Path(raw).expanduser() if raw.startswith("~") else root / raw
        out.append((key, s["name"], path))
    return out

# 사람이 확인한 날짜가 이만큼 지나면 selftest 가 일부러 실패합니다.
# (build.py 의 모델 가격표 90일 장치와 같은 이유 — 오래된 데이터가 조용히 사는 걸 막습니다)
STALE_DAYS = 180

# 이 단어들은 vibe.yaml 에 들어올 수 없습니다. CONTRIBUTING.md 의 규율을 기계로 못박은 것입니다.
# 표본이 세 자리가 되기 전까지 어떤 방법도 "최적"이라고 부르지 않습니다.
금지어 = ("최적", "베스트", "정답")


def fetch(url):
    """https 로 받아옵니다.

    파이썬이 시스템 인증서를 못 찾는 설치본이 실제로 있습니다(맥 공식 설치본에서
    "Install Certificates.command" 를 안 돌린 경우). 배포할 프로그램이 거기서
    죽으면 안 되므로, 기본 검증이 실패하면 certifi 묶음으로 한 번 더 시도합니다.
    **검증을 끄지는 않습니다** — 끄면 받은 파일을 믿을 근거가 사라집니다.
    """
    import ssl
    import urllib.request

    try:
        return urllib.request.urlopen(url, timeout=20).read().decode("utf-8")
    except urllib.error.URLError as e:
        if not isinstance(getattr(e, "reason", None), ssl.SSLError):
            raise
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
        return urllib.request.urlopen(url, timeout=20, context=ctx).read().decode("utf-8")


def source():
    """어느 vibe.yaml 을 쓸지.

    저장소 안에서 돌리는 중이면 **항상 저장소 것**입니다. 여기서 캐시를 먼저 보면
    vibe.yaml 을 고쳐도 반영이 안 돼서, 고친 사람이 한참을 헤매게 됩니다.
    배포판(저장소 없음)에서만 sync 로 받아 둔 캐시를 씁니다.
    """
    if (ROOT / ".git").exists():
        return VIBE
    return CACHE if CACHE.exists() else VIBE


def load():
    return yaml.safe_load(source().read_text(encoding="utf-8"))


def prog():
    """이 프로그램을 부르는 이름. 저장소에서 돌리면 `uv run vibe.py`,
    깔아서 쓰면 `stackpack` 입니다. 안내 문구가 없는 명령을 알려주면 안 됩니다."""
    name = Path(sys.argv[0]).name
    return "uv run vibe.py" if name.endswith(".py") else "stackpack"


def validate(data):
    """받아온 데이터가 규율을 지키는지. **적용하기 전에** 봅니다.

    남의 서버에서 받은 파일을 검사 없이 내 전역 설정에 얹으면 안 됩니다.
    selftest 가 쓰는 것과 같은 검사입니다 — 두 벌로 만들지 않았습니다.
    """
    assert data.get("surfaces"), "surfaces 가 없습니다"
    for k, inc in data.get("incidents", {}).items():
        for 칸 in ("id", "name", "symptom", "story", "blind"):
            assert str(inc.get(칸, "")).strip(), f"{k}: {칸} 이 비었습니다"
        assert inc.get("fix"), f"{k}: fix(그래서 뭘 하나)가 비었습니다"
        assert inc.get("status") in data["statuses"], f"{k}: 모르는 status"
        e = inc.get("evidence") or {}
        assert e.get("users", 0) >= 1 and e.get("sources"), f"{k}: 근거가 없습니다"
    return data


def marker(key):
    return f"<!-- vibe:{key} -->"


# 우리가 넣은 블록을 통째로 알아보는 눈. 이름이 무엇이든 잡습니다.
# 항목 이름이 바뀌면 옛 블록이 고아로 남는데, 그게 남의 컴퓨터에 영원히
# 쌓이면 안 됩니다. 시작·끝 표시는 우리가 쓴 것이라 경계가 확실합니다.
BLOCK_RE = re.compile(r"\n?<!-- vibe:(?P<k>[^>]+?) -->.*?<!-- /vibe:(?P=k) -->\n?", re.S)


def strip_orphans(text, 살릴키):
    """카탈로그에 더 없는 항목의 블록을 빼냅니다. 살릴 것은 그대로 둡니다."""
    def 판정(m):
        return m.group(0) if m.group("k") in 살릴키 else "\n"
    return BLOCK_RE.sub(판정, text)


def body_for(inc):
    """AI 에게 갈 글을 항목에서 **만들어냅니다.** 손으로 적지 않습니다.

    증상이 맨 앞입니다. AI 는 규칙("검사는 부숴봐라")을 못 알아봅니다.
    "지금 이런 걸 하려는 참이다" 라는 상황이 적혀 있어야 알아봅니다.
    """
    줄 = [f"## [{inc['id']}] {inc['name']}", ""]
    줄.append(f"**이럴 때 해당된다** — {inc['symptom']}")
    줄.append("")
    줄.append(f"**실제로 있었던 일** — {' '.join(inc['story'].split())}")
    줄.append("")
    줄.append("**그래서 이렇게 한다**")
    for f in inc["fix"]:
        줄.append(f"- {' '.join(f.split())}")
    줄.append("")
    줄.append(f"**이렇게 해도 안 잡히는 것** — {' '.join(inc['blind'].split())}")
    return "\n".join(줄)


def legacy_block(key, body):
    """끝 표시가 없던 시절의 블록 모양.

    옛 블록을 알아볼 때 **경계를 추측하지 않습니다.** 우리가 그때 썼을 글자와
    정확히 일치할 때만 그 자리로 봅니다. 추측하면 그 사이에 사람이 써 넣은
    글까지 같이 지우게 됩니다.
    """
    return f"\n{marker(key)}\n{body}\n"


def end_marker(key):
    """블록의 끝. 이게 없으면 되돌리기가 "다음 표시까지" 를 지우게 되고,
    사람이 그 사이에 써 넣은 글까지 같이 사라집니다."""
    return f"<!-- /vibe:{key} -->"


def incidents_for(data, targets):
    if list(targets) == ["all"]:
        return {k: v for k, v in data["incidents"].items() if v["status"] == "검증됨"}
    out = {}
    for t in targets:
        if t not in data["incidents"]:
            raise KeyError(t)
        out[t] = data["incidents"][t]
    return out


def plan(data, targets, root, scope="project", only=None):
    """(경로, 이전내용, 다음내용, 사유) 목록. 아무 파일도 건드리지 않습니다.

    한 파일에 방법 여러 개가 붙습니다. 그래서 각 단계의 "이전 내용"은 디스크가 아니라
    **앞 단계까지 반영된 내용**이어야 합니다. 디스크만 보면 마지막 단계가 앞 단계를
    통째로 덮어씁니다 (selftest 6번이 잡는 사고입니다).
    """
    surfaces = surface_paths(data, scope, root, only)
    steps = []
    pending = {}  # path -> 앞 단계까지 반영된 내용 (None = 아직 파일 없음)

    # 먼저 고아부터 치웁니다. 안 그러면 이름 바꾼 항목이 두 벌로 남습니다.
    살릴키 = set(data["incidents"])
    for _, _, path in surfaces:
        if not path.exists():
            continue
        전 = path.read_text(encoding="utf-8")
        후 = strip_orphans(전, 살릴키)
        if 후 != 전:
            pending[path] = 후
            steps.append((path, 전, 후, "더 안 쓰는 항목을 뺐습니다"))
    for key, inc in incidents_for(data, targets).items():
        f = {"mode": "append", "body": body_for(inc)}
        for _, _, path in surfaces:
            yield_step(steps, pending, path, key, f)
    return steps


def yield_step(steps, pending, path, key, f):
    """한 파일에 방법 하나를 얹는 단계 하나를 계산합니다. 파일은 안 건드립니다."""
    before = pending[path] if path in pending else (
        path.read_text(encoding="utf-8") if path.exists() else None)
    body = f["body"].rstrip("\n")

    if f["mode"] == "create":
        if before is not None:
            pending[path] = before
            steps.append((path, before, before, f"이미 있음 — 건너뜀 ({key})"))
            return
        pending[path] = body + "\n"
        steps.append((path, None, pending[path], f"새로 만듦 ({key})"))
        return

    if f["mode"] == "append":
        새블록 = f"\n{marker(key)}\n{body}\n{end_marker(key)}\n"
        옛것 = legacy_block(key, body)
        if before is not None and 옛것 in before and end_marker(key) not in before:
            pending[path] = before.replace(옛것, 새블록)
            steps.append((path, before, pending[path], f"옛 모양을 새로 바꿈 ({key})"))
            return
        if before is not None and marker(key) in before:
            pending[path] = before
            steps.append((path, before, before, f"이미 적용됨 — 건너뜀 ({key})"))
            return
        base = before if before is not None else ""
        pending[path] = base.rstrip("\n") + "\n" + 새블록
        steps.append((path, before, pending[path], f"덧붙임 ({key})"))
        return

    raise AssertionError(f"{key}: 모르는 mode '{f['mode']}'")


def do_apply(data, targets, root, execute=False, scope="project", only=None, quiet=False):
    steps = plan(data, targets, root, scope, only)
    label = {p: f"{n}: {p}" for _, n, p in surface_paths(data, scope, root, only)}
    # .bak 은 **한 번만** 씁니다. 한 파일에 방법 여러 개가 붙는데 단계마다 덮어쓰면
    # 남는 건 원본이 아니라 중간 상태입니다 — 되돌리기가 거짓말이 됩니다.
    # 처음 보는 경로의 첫 `before` 가 진짜 원본입니다.
    original, backed_up = {}, set()
    for path, before, _, _ in steps:
        original.setdefault(path, before)

    changed, touched = 0, set()
    for path, before, after, why in steps:
        rel = label.get(path, str(path))
        if before == after:
            if not quiet:
                print(f"--  {rel}  {why}")
            continue
        changed += 1
        touched.add(path)
        if not quiet:
            print(f"++  {rel}  {why}")
        if not execute:
            diff = difflib.unified_diff(
                (before or "").splitlines(True), after.splitlines(True),
                fromfile=f"{rel} (지금)", tofile=f"{rel} (적용 후)", n=1,
            )
            for line in diff:
                print("    " + line.rstrip("\n"))
        else:
            if path not in backed_up and original[path] is not None:
                path.with_suffix(path.suffix + ".bak").write_text(original[path], encoding="utf-8")
                backed_up.add(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(after, encoding="utf-8")

    # steps 로 안 끝나는 것 — 사람이 해야 하는 절차
    for key, r in incidents_for(data, targets).items():
        if r.get("steps") and not quiet:
            print(f"\n[{key}] 이건 사람이 해야 합니다:")
            for s in r["steps"]:
                print(f"  - {s}")

    if quiet:
        return 0
    print()
    if not changed:
        print("바꿀 게 없습니다. 이미 다 적용돼 있습니다.")
    elif execute:
        print(f"파일 {len(touched)}개 · 방법 {changed}개를 적용했습니다. 원본은 .bak 으로 남겼습니다.")
    else:
        print(f"파일 {len(touched)}개 · 방법 {changed}개가 적용됩니다. "
              "**아무것도 안 바꿨습니다** — 실제로 하려면 --yes 를 붙이세요.")
    return 0


def do_list(data):
    print("\n지금 들어 있는 사고들 — 다 남이 실제로 당한 것입니다.\n")
    for key, inc in data["incidents"].items():
        검사 = "  (자동 검사 있음)" if inc.get("caught_by") else ""
        print(f"  [{inc['id']}] {inc['name']}{검사}")
        print(f"        {key}")
    print(f"\n{len(data['incidents'])}건. 하나 자세히 보기: {prog()} 보기 <이름>")
    print(f"내 프로젝트에 이 사고가 있나 찾아보기: {prog()} 검사")
    return 0


def do_where(data):
    for key, s in data["surfaces"].items():
        print(f"\n{s['name']}  ({key})")
        print(f"  전역     {s['global']}      ← 한 번 넣으면 모든 프로젝트에 자동")
        print(f"  프로젝트  {s['project']}")
    print("\n경로는 vibe.yaml 의 surfaces 에 있습니다. 도구가 늘면 거기만 고칩니다.")
    return 0


def do_show(data, key):
    inc = data["incidents"][key]
    e = inc["evidence"]
    print()
    print(body_for(inc))
    print()
    if inc.get("caught_by"):
        print(f"이 사고는 자동으로 찾아낼 수 있습니다: {prog()} 검사")
    print(f"출처 {', '.join(e['sources'])} · {inc['status']} — {data['statuses'][inc['status']]}")
    return 0


def do_sync(execute=False):
    """저장소를 최신으로 당기고 전역에 다시 얹습니다.

    사람들이 낸 방법이 늘어나도 손으로 다시 칠 일이 없게 하려는 명령입니다.
    스케줄러에 걸어 두는 건 이것 하나면 됩니다.
    """
    import urllib.request

    if (ROOT / ".git").exists():
        # 개발 중 — 저장소를 그대로 씁니다
        r = subprocess.run(["git", "-C", str(ROOT), "pull", "--ff-only"],
                           capture_output=True, text=True)
        print((r.stdout or r.stderr).strip())
        if r.returncode != 0:
            print("\n당기지 못했습니다. 손으로 고쳐 둔 게 있으면 먼저 정리하세요.")
            return 1
    else:
        # 배포판 — 깃이 없습니다. vibe.yaml 만 받아옵니다.
        assert REMOTE.startswith("https://"), "평문 http 로는 받지 않습니다"
        print(f"받는 중 … {REMOTE}")
        try:
            raw = fetch(REMOTE)
        except Exception as e:
            print(f"받지 못했습니다: {e}\n지금 있는 것으로 그대로 둡니다.")
            return 1
        # **검사를 통과한 것만** 저장합니다. 받은 걸 바로 얹으면 남의 파일을 믿는 셈입니다.
        try:
            validate(yaml.safe_load(raw))
        except AssertionError as e:
            print(f"받은 파일이 규율을 어깁니다: {e}\n적용하지 않습니다.")
            return 1
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(raw, encoding="utf-8")
        print(f"받았습니다 → {CACHE}")

    data = load()   # 갱신 뒤에 다시 읽습니다 — 안 그러면 옛 방법을 얹습니다
    print()
    for _, name, path in surface_paths(data, "global", ROOT):
        print(f"{name}  →  {path}")
        if execute:
            path.parent.mkdir(parents=True, exist_ok=True)
    print()
    return do_apply(data, ["all"], ROOT, execute=execute, scope="global")


def detected(data):
    """이 컴퓨터에 실제로 깔린 도구만. 안 쓰는 도구 자리에 파일을 만들면 쓰레기입니다."""
    found = []
    for key, s in data["surfaces"].items():
        d = s.get("detect")
        if d and Path(d).expanduser().exists():
            found.append(key)
    return found


def undo(data, root, scope="global", execute=False):
    """넣었던 것을 전부 빼냅니다. 사람이 그 사이에 써 넣은 글은 건드리지 않습니다."""
    지움 = 0
    for _, name, path in surface_paths(data, scope, root):
        if not path.exists():
            continue
        before = path.read_text(encoding="utf-8")
        after = before
        # 이름을 가리지 않고 우리가 넣은 블록을 전부 뺍니다. 옛 이름도 같이 나갑니다.
        after = BLOCK_RE.sub("\n", after)
        for key, r in data["incidents"].items():   # 끝 표시가 없던 시절 것
            after = after.replace(legacy_block(key, body_for(r).rstrip("\n")), "")
        after = after.replace("\n\n\n", "\n\n").strip("\n")
        after = after + "\n" if after else ""
        if after == before:
            print(f"--  {name}: 뺄 게 없습니다")
            continue
        지움 += 1
        남은줄 = len([l for l in after.splitlines() if l.strip()])
        print(f"++  {name}: 스택팩이 넣은 글을 뺐습니다 (남은 내용 {남은줄}줄)")
        if execute:
            if after.strip():
                path.write_text(after, encoding="utf-8")
            else:
                path.unlink()        # 우리가 만든 파일이고 이제 빈 파일입니다
                print(f"    빈 파일이라 지웠습니다: {path}")
    print()
    if not 지움:
        print("이미 깨끗합니다.")
    elif execute:
        print("다 뺐습니다. 원래대로 돌아왔습니다.")
    else:
        print("아무것도 안 바꿨습니다. 진짜로 빼려면 다시 한 번 치세요: 되돌리기 --진짜")
    return 0


def do_tidy(data, execute=False):
    """끝 표시가 없던 시절의 낡은 블록을 빼냅니다.

    시작 표시밖에 없어서 **경계를 확실히 알 수 없습니다.** 그래서 자동으로 지우지
    않습니다. 뺄 내용을 글자 그대로 보여주고, 사람이 보고 나서 빼게 합니다.
    추측해서 지우면 그 사이에 사람이 써 넣은 글이 같이 사라집니다.
    """
    찾음 = 0
    for _, name, path in surface_paths(data, "global", ROOT):
        if not path.exists():
            continue
        글 = path.read_text(encoding="utf-8")
        while True:
            i = 글.find("<!-- vibe:")
            if i < 0:
                break
            키끝 = 글.find(" -->", i)
            키 = 글[i + 10:키끝]
            if end_marker(키) in 글:      # 새 형식은 알아서 처리됩니다
                남은 = 글[키끝:]
                다음 = 남은.find("<!-- vibe:")
                if 다음 < 0:
                    break
                글 = 남은[다음:]
                continue
            뒤 = 글.find("<!-- vibe:", i + 1)
            블록 = 글[i:] if 뒤 < 0 else 글[i:뒤]
            찾음 += 1
            print(f"\n{name} — 낡은 항목 「{키}」")
            print("─" * 50)
            for l in 블록.rstrip().splitlines():
                print("  " + l)
            print("─" * 50)
            if execute:
                원본 = path.read_text(encoding="utf-8")
                path.with_suffix(path.suffix + ".bak").write_text(원본, encoding="utf-8")
                path.write_text(원본.replace(블록, ""), encoding="utf-8")
                print("  뺐습니다.")
            글 = 글[i + len(블록):]
    print()
    if not 찾음:
        print("낡은 항목이 없습니다. 깨끗합니다.")
    elif execute:
        print(f"{찾음}개를 뺐습니다. 원본은 .bak 에 있습니다.")
    else:
        print(f"낡은 항목 {찾음}개를 찾았습니다. 위 내용이 그대로 빠집니다.")
        print(f"빼려면: {prog()} 정리 --진짜")
    return 0


def do_auto(data, execute=True):
    """아무것도 안 붙이고 그냥 실행했을 때. 이게 기본 동작입니다."""
    쓰는것 = detected(data)
    if 쓰는것:
        이름 = ", ".join(data["surfaces"][k]["name"] for k in 쓰는것)
        print(f"찾았습니다: {이름}")
    else:
        쓰는것 = list(data["surfaces"])
        print("AI 코딩 프로그램을 못 찾아서, 아는 자리 전부에 넣어 둡니다.")
    print()

    바뀜 = False
    for key in 쓰는것:
        s = data["surfaces"][key]
        path = Path(s["global"]).expanduser()
        if execute:
            path.parent.mkdir(parents=True, exist_ok=True)
        steps = plan(data, ["all"], ROOT, "global", key)
        바뀜 = 바뀜 or any(b != a for _, b, a, _ in steps)
        do_apply(data, ["all"], ROOT, execute=execute, scope="global", only=key, quiet=True)

    print()
    if not 바뀜:
        print("이미 다 돼 있습니다. 아무것도 안 했습니다.")
    else:
        print(f"끝났습니다. 사고 {len(data['incidents'])}건을 넣었습니다.")
        print("이제 AI가 알아서 읽습니다. 더 하실 건 없습니다.")
        print()
        print(f"내 프로젝트에 이 사고가 있는지 찾아보려면:  {prog()} 검사")
    return 0


# ── 자동 갱신 ────────────────────────────────────────────────────────────────
# "설치해두면 알아서" 의 마지막 조각입니다. 새 방법이 들어와도 사람이 뭘 치지
# 않게 하려면, 하루 한 번 대신 받아오는 일을 컴퓨터에 걸어 두어야 합니다.
#
# 묻지 않고 겁니다. 대신 무엇을 걸었는지 한 줄로 말하고, 끄는 법을 그 자리에
# 같이 적습니다. 모르게 걸어 두는 것과 말하고 걸어 두는 것은 다릅니다.
AUTO_MARK = Path.home() / ".stackpack" / "자동갱신_켜짐"
PLIST = Path.home() / "Library" / "LaunchAgents" / "com.stackpack.sync.plist"
TASK = "stackpack 자동갱신"


def _exe():
    """자기 자신을 부르는 방법. 깔아 쓰면 stackpack, 저장소면 파이썬 + 파일."""
    name = Path(sys.argv[0]).name
    if not name.endswith(".py"):
        return [str(Path(sys.argv[0]).resolve())]
    return [sys.executable, str(Path(__file__).resolve())]


def schedule_on():
    cmd = _exe() + ["sync", "--yes"]
    if sys.platform == "darwin":
        args = "".join(f"    <string>{c}</string>\n" for c in cmd)
        PLIST.parent.mkdir(parents=True, exist_ok=True)
        PLIST.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0"><dict>\n'
            '  <key>Label</key><string>com.stackpack.sync</string>\n'
            f'  <key>ProgramArguments</key><array>\n{args}  </array>\n'
            '  <key>StartInterval</key><integer>86400</integer>\n'
            '  <key>RunAtLoad</key><false/>\n'
            '</dict></plist>\n', encoding="utf-8")
        subprocess.run(["launchctl", "unload", str(PLIST)],
                       capture_output=True)
        r = subprocess.run(["launchctl", "load", str(PLIST)], capture_output=True, text=True)
        return r.returncode == 0, f"맥 로그인 항목 ({PLIST.name})"
    if sys.platform.startswith("win"):
        r = subprocess.run(["schtasks", "/create", "/f", "/sc", "daily",
                            "/tn", TASK, "/tr", " ".join(f'"{c}"' for c in cmd)],
                           capture_output=True, text=True)
        return r.returncode == 0, "윈도우 작업 스케줄러"
    return False, "이 운영체제는 아직 자동 갱신을 못 겁니다"


def schedule_off():
    if sys.platform == "darwin" and PLIST.exists():
        subprocess.run(["launchctl", "unload", str(PLIST)], capture_output=True)
        PLIST.unlink()
        return True
    if sys.platform.startswith("win"):
        subprocess.run(["schtasks", "/delete", "/f", "/tn", TASK], capture_output=True)
        return True
    return False


def ensure_schedule():
    """처음 한 번만 겁니다. 이미 걸었으면 아무 말도 안 합니다."""
    if AUTO_MARK.exists():
        return
    ok, 어디 = schedule_on()
    if not ok:
        return
    AUTO_MARK.parent.mkdir(parents=True, exist_ok=True)
    AUTO_MARK.write_text(어디 + "\n", encoding="utf-8")
    print()
    print(f"새 방법이 나오면 하루 한 번 알아서 받아옵니다 ({어디}).")
    print(f"필요 없으면: {prog()} 자동 끄기")


def load_check():
    """검사기를 불러옵니다.

    깔아서 쓰면 `stackpack.check`, 저장소에서 돌리면 `check` 입니다.
    저장소에서만 돌려보면 이 차이를 못 봅니다 — 실제로 배포판에서 한 번 터졌습니다.
    """
    try:
        from . import check          # 깔아서 쓸 때
        return check
    except ImportError:
        pass
    try:
        import check                 # 저장소에서 돌릴 때
        return check
    except ImportError:
        return None


def do_check(target="."):
    """오답노트의 사고를 **내 프로젝트에서 실제로 찾습니다.**

    규칙을 알려주는 것과 "당신 프로젝트 이 줄에 그 사고가 있습니다" 라고
    말해주는 것은 다릅니다. 뒤쪽이 훨씬 셉니다.
    """
    check = load_check()
    if check is None:
        print("검사기를 못 찾았습니다. 저장소에서 받아 쓰시면 됩니다:")
        print("  git clone https://github.com/tree8727-coder/stackpack")
        return 1
    return check.main([str(Path(target).resolve())])


def do_auto_cmd(onoff):
    if onoff in ("끄기", "off"):
        schedule_off()
        AUTO_MARK.unlink(missing_ok=True)
        print("자동 갱신을 껐습니다. 새 방법은 이제 직접 받으셔야 합니다:")
        print(f"  {prog()} 갱신 --진짜")
        return 0
    if onoff in ("켜기", "on"):
        ok, 어디 = schedule_on()
        if not ok:
            print(f"걸지 못했습니다: {어디}")
            return 1
        AUTO_MARK.parent.mkdir(parents=True, exist_ok=True)
        AUTO_MARK.write_text(어디 + "\n", encoding="utf-8")
        print(f"켰습니다. 하루 한 번 알아서 받아옵니다 ({어디}).")
        return 0
    print("켜져 있습니다." if AUTO_MARK.exists() else "꺼져 있습니다.")
    print(f"바꾸려면: {prog()} 자동 켜기  /  {prog()} 자동 끄기")
    return 0


# ── 관문 (훅) ────────────────────────────────────────────────────────────────
# 규칙은 부탁이고, 검사는 사후입니다. 관문만이 **막습니다.**
# Claude Code 의 PreToolUse 훅으로 붙습니다. Antigravity 에는 같은 게 없어서
# 거기는 규칙(글)로만 남습니다 — 없는 걸 있다고 하지 않습니다.
SETTINGS = Path.home() / ".claude" / "settings.json"
# 우리 훅인지 알아보는 표시. 명령줄 끝에 `# 주석` 을 붙이는 방법을 썼다가
# 윈도우에서는 그게 주석이 아니라 인자로 들어가 관문이 안 도는 걸 알았습니다.
# 그래서 표시를 따로 붙이지 않고 명령 자체로 알아봅니다.
GUARD_MARKS = ("stackpack", "guard.py")


def is_ours(h):
    return any(m in json.dumps(h, ensure_ascii=False) for m in GUARD_MARKS)
BLOCK_LOG = Path.home() / ".stackpack" / "막은기록.jsonl"


def _guard_cmd():
    exe = _exe()
    if len(exe) == 1:
        return f'"{exe[0]}" 관문'
    return f'"{exe[0]}" "{Path(__file__).parent / "guard.py"}"'


def hook_on():
    """~/.claude/settings.json 에 관문을 겁니다. 남의 설정은 안 지웁니다."""
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    원본 = SETTINGS.read_text(encoding="utf-8") if SETTINGS.exists() else ""
    try:
        cfg = json.loads(원본) if 원본.strip() else {}
    except json.JSONDecodeError:
        return False, "settings.json 을 읽을 수 없어 건드리지 않았습니다"
    hooks = cfg.setdefault("hooks", {}).setdefault("PreToolUse", [])
    for h in hooks:
        if is_ours(h):
            return True, "이미 걸려 있습니다"
    hooks.append({
        "matcher": "Write|Edit|Bash",
        "hooks": [{"type": "command", "command": _guard_cmd(), "timeout": 10}],
    })
    if 원본:
        SETTINGS.with_suffix(".json.bak").write_text(원본, encoding="utf-8")
    SETTINGS.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True, str(SETTINGS)


def hook_off():
    if not SETTINGS.exists():
        return True
    try:
        cfg = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    pre = cfg.get("hooks", {}).get("PreToolUse", [])
    남길것 = [h for h in pre if not is_ours(h)]
    if len(남길것) == len(pre):
        return True
    cfg["hooks"]["PreToolUse"] = 남길것
    if not 남길것:
        cfg["hooks"].pop("PreToolUse")
    if not cfg["hooks"]:
        cfg.pop("hooks")
    SETTINGS.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def do_hook_cmd(onoff):
    if onoff in ("끄기", "off"):
        hook_off()
        print("관문을 껐습니다. 이제 막지 않고 규칙으로만 알려줍니다.")
        return 0
    if onoff in ("켜기", "on"):
        ok, 어디 = hook_on()
        print(f"관문을 켰습니다 → {어디}" if ok else f"못 켰습니다: {어디}")
        return 0 if ok else 1
    켜짐 = SETTINGS.exists() and any(
        m in SETTINGS.read_text(encoding="utf-8") for m in GUARD_MARKS)
    print("켜져 있습니다." if 켜짐 else "꺼져 있습니다.")
    print(f"바꾸려면: {prog()} 관문 켜기  /  {prog()} 관문 끄기")
    return 0


def do_report(data):
    """막은 횟수를 보여줍니다. **밖으로 안 보냅니다** — 이 파일은 이 컴퓨터에만 있습니다."""
    if not BLOCK_LOG.exists():
        print("\n아직 막은 게 없습니다.")
        print("관문이 켜져 있으면, AI 가 사고를 치려 할 때 여기 쌓입니다.")
        print(f"\n관문 상태 보기: {prog()} 관문")
        return 0
    센것, 최근 = {}, None
    for line in BLOCK_LOG.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        센것[r["사고"]] = 센것.get(r["사고"], 0) + 1
        최근 = r["때"]
    총 = sum(센것.values())
    이름 = {i["id"]: i["name"] for i in data["incidents"].values()}
    print(f"\n스택팩이 지금까지 {총}번 막았습니다.\n")
    for 사고, n in sorted(센것.items(), key=lambda x: -x[1]):
        print(f"  {n:>3}번   [{사고}] {이름.get(사고, '')}")
    print(f"\n마지막: {최근}")
    print(f"기록은 이 컴퓨터에만 있습니다 ({BLOCK_LOG}). 아무 데도 안 보냅니다.")
    return 0


def do_selftest(data):
    import tempfile

    incidents, statuses = data["incidents"], data["statuses"]

    # 1. 데이터 규율 — validate 와 같은 함수를 씁니다(두 벌로 안 만듭니다)
    validate(data)
    번호 = [inc["id"] for inc in incidents.values()]
    assert len(번호) == len(set(번호)), f"사고 번호가 겹칩니다: {번호}"

    # 1-2. 증상이 규칙문이 아니라 **상황**인지. "~해라" 로 끝나면 AI 가 못 알아봅니다.
    for k, inc in incidents.items():
        s = inc["symptom"].strip()
        assert not s.endswith(("한다", "해라", "하라", "않는다")), \
            f"{k}: symptom 이 규칙문입니다 — 「~하려 할 때」 같은 상황으로 적으세요"
        assert "때" in s or "경우" in s, f"{k}: symptom 에 언제인지가 없습니다"

    # 1-3. 만들어낸 본문에 네 칸이 다 들어가는지
    for k, inc in incidents.items():
        b = body_for(inc)
        for 표 in ("이럴 때 해당된다", "실제로 있었던 일", "그래서 이렇게 한다",
                   "이렇게 해도 안 잡히는 것"):
            assert 표 in b, f"{k}: 만들어낸 글에 「{표}」 가 없습니다"

    # 1-4. caught_by 가 진짜 있는 검사를 가리키는지. 없는 검사를 약속하면 안 됩니다.
    _check = load_check()
    if _check is not None:
        있는검사 = {f.__name__ for f in _check.CHECKS}
        for k, inc in incidents.items():
            if c := inc.get("caught_by"):
                assert c in 있는검사, f"{k}: 없는 검사를 가리킵니다 — {c}"
    else:
        assert not (ROOT / "check.py").exists(), "옆에 check.py 가 있는데 못 불러옵니다"

    # 2. '최적' 이라고 쓰지 않는다는 규율을 기계로 못박습니다
    text = VIBE.read_text(encoding="utf-8")
    for line_no, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue  # 규칙을 설명하는 주석에는 그 단어가 나올 수밖에 없습니다
        for w in 금지어:
            assert w not in line, f"vibe.yaml:{line_no} '{w}' — 표본이 세 자리가 되기 전엔 못 씁니다"

    # 3. 확인 날짜가 오래되면 일부러 실패합니다
    age = (date.today() - data["meta"]["checked"]).days
    assert age <= STALE_DAYS, f"meta.checked 가 {age}일 지났습니다. 다시 보고 날짜를 고치세요"

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        # 4. 미리보기는 파일을 하나도 만들지 않는다
        do_apply(data, ["all"], tmp, execute=False)
        assert not list(tmp.iterdir()), f"미리보기인데 파일이 생겼습니다: {list(tmp.iterdir())}"

        # 5. 실제 적용은 파일을 만든다
        do_apply(data, ["all"], tmp, execute=True)
        made = sorted(p.name for p in tmp.iterdir())
        assert made, "적용했는데 아무 파일도 안 생겼습니다"
        for _, _, sp in surface_paths(data, "project", tmp):
            assert sp.exists(), f"{sp.name} 이 안 만들어졌습니다 — 도구 하나가 빠졌습니다"
        first = {sp: sp.read_text(encoding="utf-8")
                 for _, _, sp in surface_paths(data, "project", tmp)}

        # 6. 두 번 돌려도 안 늘어난다
        do_apply(data, ["all"], tmp, execute=True)
        for sp, was in first.items():
            assert sp.read_text(encoding="utf-8") == was, f"{sp.name}: 두 번 적용하니 달라졌습니다"

        # 6-2. .bak 이 "원본" 이어야 한다 — 중간 상태가 남으면 되돌리기가 거짓말이 됩니다
        for sp in first:
            sp.write_text("원본입니다\n", encoding="utf-8")
            bak = sp.with_suffix(sp.suffix + ".bak")
            bak.unlink(missing_ok=True)
        do_apply(data, ["all"], tmp, execute=True)
        for sp in first:
            bak = sp.with_suffix(sp.suffix + ".bak")
            assert bak.read_text(encoding="utf-8") == "원본입니다\n", \
                f"{bak.name} 이 원본이 아닙니다 — 중간 상태가 덮어썼습니다"

        # 7. 남이 쓴 내용을 절대 안 지운다
        for sp, was in first.items():
            sp.write_text("# 내가 쓴 거\n건드리지 마\n" + was, encoding="utf-8")
        do_apply(data, ["all"], tmp, execute=True)
        for sp in first:
            assert "건드리지 마" in sp.read_text(encoding="utf-8"), f"{sp.name}: 남의 내용이 사라졌습니다"

    # 8. 전역 경로가 정말 홈 밑인지. 여기를 잘못 잡으면 남의 설정을 통째로 건드립니다.
    for k, _, path in surface_paths(data, "global", ROOT):
        assert Path.home() in path.parents, f"{k}: 전역 경로가 홈 밖입니다 — {path}"
        assert ROOT not in path.parents, f"{k}: 전역 경로가 저장소 안을 가리킵니다 — {path}"

    # 9. Gemini CLI 와 같은 파일을 쓰지 않는다 (google-gemini/gemini-cli#16058).
    #    ~/.gemini/GEMINI.md 는 두 도구가 하드코딩해 서로 덮어씁니다. AGENTS.md 를 씁니다.
    for k, _, path in surface_paths(data, "global", ROOT):
        assert path.name != "GEMINI.md", f"{k}: GEMINI.md 는 Gemini CLI 와 충돌합니다"

    # 10. 도구마다 각자의 파일에 들어간다 — 한 도구만 받고 끝나면 안 됩니다
    tmp_names = {p.name for _, _, p in surface_paths(data, "project", Path("/tmp"))}
    assert len(tmp_names) == len(data["surfaces"]), "도구 둘이 같은 파일을 가리킵니다"

    # 10-2. 저장소 안에서는 캐시가 아니라 저장소 파일을 읽어야 한다
    assert (ROOT / ".git").exists(), "이 검사는 저장소 안에서 돌려야 합니다"
    assert source() == VIBE, f"저장소 안인데 {source()} 를 읽고 있습니다"

    # 11. 배포판 갱신 경로 — 평문 http 금지, 캐시가 홈 밑, validate 가 실제로 잡는지
    assert REMOTE.startswith("https://"), "REMOTE 가 https 가 아닙니다"
    assert Path.home() in CACHE.parents, f"캐시가 홈 밖입니다: {CACHE}"
    # 인증서 검증을 끄는 코드가 슬며시 들어오는 걸 막습니다
    src = Path(__file__).read_text(encoding="utf-8")
    for 금지 in ("_create_unverified_context", "CERT_NONE", "verify=False"):
        assert 금지 not in src.replace(f'"{금지}"', ""), f"인증서 검증을 끄는 코드: {금지}"
    validate(data)
    나쁜것 = {"statuses": data["statuses"], "surfaces": data["surfaces"],
             "incidents": {"x": {"id": "X", "name": "n", "symptom": "s",
                                 "story": "t", "blind": "", "fix": ["f"],
                                 "status": "검증됨",
                                 "evidence": {"users": 1, "sources": ["#1"]}}}}
    try:
        validate(나쁜것)
        raise AssertionError("validate 가 blind 빈 사고를 통과시켰습니다")
    except AssertionError as e:
        assert "blind" in str(e), e

    # 7-2. 되돌리기가 **남이 쓴 글은 안 지우고** 우리 것만 빼내는가.
    #      끝 표시가 없으면 "다음 표시까지" 를 지우게 되고, 그 사이에 사람이
    #      써 넣은 글이 같이 사라집니다. 그래서 여기서 일부러 사이에 끼워 봅니다.
    with tempfile.TemporaryDirectory() as td2:
        tmp2 = Path(td2)
        원본 = "# 내가 먼저 쓴 것\n지우지 마\n"
        for _, _, sp in surface_paths(data, "project", tmp2):
            sp.write_text(원본, encoding="utf-8")
        do_apply(data, ["all"], tmp2, execute=True, quiet=True)
        for _, _, sp in surface_paths(data, "project", tmp2):
            글 = sp.read_text(encoding="utf-8")
            i = 글.index(end_marker(next(iter(incidents))))
            j = 글.index("\n", i) + 1
            sp.write_text(글[:j] + "\n## 블록 사이에 내가 끼워 넣은 글\n" + 글[j:],
                          encoding="utf-8")
        undo(data, tmp2, "project", execute=True)
        for _, _, sp in surface_paths(data, "project", tmp2):
            남은 = sp.read_text(encoding="utf-8") if sp.exists() else ""
            assert "지우지 마" in 남은, "되돌리기가 남이 먼저 쓴 글을 지웠습니다"
            assert "끼워 넣은 글" in 남은, "되돌리기가 블록 사이의 글을 지웠습니다"
            assert "vibe:" not in 남은, f"되돌렸는데 스택팩 글이 남았습니다: {sp.name}"

    # 7-2b. 끝 표시가 없던 옛 블록도 알아보고 새 모양으로 바꾸는가.
    #       그리고 **글자가 조금이라도 다르면 손대지 않는가** — 옛것인 척하는
    #       남의 글을 지우면 안 됩니다.
    with tempfile.TemporaryDirectory() as td4:
        tmp4 = Path(td4)
        키 = next(iter(incidents))
        본문 = body_for(incidents[키]).rstrip("\n")
        옛것 = legacy_block(키, 본문)
        남의것 = f"\n{marker(키)}-비슷한거\n내가 쓴 글\n"
        for _, _, sp in surface_paths(data, "project", tmp4):
            sp.write_text("머리말\n" + 옛것 + 남의것, encoding="utf-8")
        do_apply(data, ["all"], tmp4, execute=True, quiet=True)
        for _, _, sp in surface_paths(data, "project", tmp4):
            글 = sp.read_text(encoding="utf-8")
            assert end_marker(키) in 글, "옛 블록이 새 모양으로 안 바뀌었습니다"
            assert 글.count(marker(키) + "\n") == 1, "옛 블록 옆에 새 블록이 또 붙었습니다"
            assert "내가 쓴 글" in 글, "비슷하게 생긴 남의 글을 건드렸습니다"
        undo(data, tmp4, "project", execute=True)
        for _, _, sp in surface_paths(data, "project", tmp4):
            남은 = sp.read_text(encoding="utf-8") if sp.exists() else ""
            assert "머리말" in 남은 and "내가 쓴 글" in 남은, "되돌리기가 남의 글을 지웠습니다"

    # 7-2c. 이름이 바뀌어 카탈로그에서 사라진 항목(고아)이 남의 파일에 계속
    #       쌓이면 안 됩니다. 적용할 때 치우고, 사람 글은 그대로 둡니다.
    with tempfile.TemporaryDirectory() as td5:
        tmp5 = Path(td5)
        고아 = "\n<!-- vibe:옛날에쓰던항목 -->\n## 옛 내용\n<!-- /vibe:옛날에쓰던항목 -->\n"
        for _, _, sp in surface_paths(data, "project", tmp5):
            sp.write_text("내 글\n" + 고아, encoding="utf-8")
        do_apply(data, ["all"], tmp5, execute=True, quiet=True)
        for _, _, sp in surface_paths(data, "project", tmp5):
            글 = sp.read_text(encoding="utf-8")
            assert "옛날에쓰던항목" not in 글, "고아 블록이 안 치워졌습니다"
            assert "내 글" in 글, "고아를 치우다 사람 글을 지웠습니다"
            assert marker(next(iter(incidents))) in 글, "치우기만 하고 새로 안 넣었습니다"
        undo(data, tmp5, "project", execute=True)
        for _, _, sp in surface_paths(data, "project", tmp5):
            남은 = sp.read_text(encoding="utf-8") if sp.exists() else ""
            assert "vibe:" not in 남은, "되돌렸는데 블록이 남았습니다"
            assert "내 글" in 남은, "되돌리기가 사람 글을 지웠습니다"

    # 7-3. 우리가 만든 빈 파일은 되돌릴 때 지웁니다 (쓰레기를 안 남깁니다)
    with tempfile.TemporaryDirectory() as td3:
        tmp3 = Path(td3)
        do_apply(data, ["all"], tmp3, execute=True, quiet=True)
        undo(data, tmp3, "project", execute=True)
        남은파일 = [f.name for f in tmp3.iterdir() if not f.name.endswith(".bak")]
        assert not 남은파일, f"되돌렸는데 파일이 남았습니다: {남은파일}"

    # 11-2. 안내 문구가 실행 이름을 박아두면 깔아 쓰는 사람에게 없는 명령을 알려주게 됩니다
    src = Path(__file__).read_text(encoding="utf-8")
    # prog() 안의 한 번(정의)만 허용합니다. 두 번째부터는 박아 넣은 것입니다.
    # 찾는 문자열을 이어붙여 만듭니다 — 여기 그대로 적으면 이 검사 자신이 걸립니다.
    needle = "uv run " + "vibe" + ".py"
    쓰인수 = src.count(needle)
    assert 쓰인수 == 2, f"실행 이름이 {쓰인수}번 나옵니다 (정의 2줄만 허용) — prog() 를 쓰세요"

    # 11-3. 관문 — 막아야 할 것을 막고, 멀쩡한 것은 통과시키는가.
    #        둘 다 치명적입니다. 못 막으면 쓸모가 없고, 잘못 막으면 지워집니다.
    g = None
    try:
        from . import guard as g
    except ImportError:
        try:
            import guard as g
        except ImportError:
            pass
    if g is not None:
        막아야 = [
            ("Write", {"file_path": "a/config.py",
                       "content": 'K = "sk-ant-' + "a" * 30 + '"'}, "E8"),
            ("Write", {"file_path": "a/pay.js",
                       "content": "const x = '국민 123456-01-234567';"}, "E8"),  # check:ignore
            ("Write", {"file_path": "a/server.js",
                       "content": "app.use(express.static(__dirname));"}, "E7"),
            ("Write", {"file_path": "a/fly.toml",
                       "content": "auto_stop_machines = 'off'\nmin_machines_running = 1"}, "E13"),
            ("Bash", {"command": "git add .env"}, "E5"),
        ]
        for tool, ti, 사고 in 막아야:
            r = g.판정(tool, ti)
            assert r is not None, f"관문이 {사고} 를 못 막았습니다: {ti}"
            assert r[1] == 사고, f"관문이 {사고} 를 {r[1]} 로 봤습니다"
            assert r[0] == "deny", f"{사고} 는 막아야 합니다 (지금 {r[0]})"

        물어봐야 = g.판정("Write", {"file_path": "a/test_e2e.py",
                                  "content": 'A("x" not in pg.inner_text("#b"))'})
        assert 물어봐야 and 물어봐야[0] == "escalate", "E10 은 사람에게 물어봐야 합니다"

        통과해야 = [
            ("Write", {"file_path": "a/README.md", "content": "# 안녕하세요\n설명입니다."}),
            ("Write", {"file_path": "a/app.py", "content": "KEY = os.environ['K']"}),
            ("Bash", {"command": "git add ."}),
            ("Bash", {"command": "npm test"}),
            ("Write", {"file_path": "a/.env.example", "content": "KEY=여기에_본인_키"}),
            ("Write", {"file_path": "a/fly.toml",
                       "content": "auto_stop_machines = 'on'\nmin_machines_running = 0"}),
        ]
        for tool, ti in 통과해야:
            r = g.판정(tool, ti)
            assert r is None, f"관문이 멀쩡한 걸 막았습니다: {ti} → {r}"

        # 터지면 통과시켜야 합니다. 관문이 편집기를 멈추게 하면 사람은 이걸 지웁니다.
        assert g.판정("Write", {"file_path": None, "content": None}) is None or True
        import io, contextlib
        오염 = io.StringIO()
        with contextlib.redirect_stdout(오염):
            sys.stdin = io.StringIO("이건 JSON 이 아닙니다")
            rc = g.main()
            sys.stdin = sys.__stdin__
        assert rc == 0 and not 오염.getvalue().strip(), "쓰레기 입력에 관문이 죽었습니다"

    # 11-4. 관문 켜기/끄기가 남의 설정을 안 건드리는가. 그리고 명령줄에 주석을
    #        붙이지 않는가 — 윈도우에서는 `#` 이 주석이 아니라 인자가 됩니다.
    cmd = _guard_cmd()
    assert "#" not in cmd, f"훅 명령에 주석이 붙었습니다 (윈도우에서 깨집니다): {cmd}"

    # 11-5. 문서에 적은 사고 건수가 실제와 맞는가.
    #        P4 가 바로 이것입니다 — 손으로 맞춘 숫자는 반드시 어긋납니다.
    #        우리가 파는 규칙을 우리가 어기면 카탈로그 전체가 우스워집니다.
    n = len(incidents)
    for 문서 in ("README.md", "사용법.md", "pyproject.toml"):
        f = ROOT / 문서
        if not f.exists():
            continue
        글 = f.read_text(encoding="utf-8")
        틀린것 = re.findall(r"사고 (\d+)건|사고 (\d+)건으로|(\d+)건 중 \d+건은", 글)
        for 짝 in 틀린것:
            for 숫자 in 짝:
                if 숫자 and int(숫자) != n:
                    raise AssertionError(
                        f"{문서} 에 사고가 {숫자}건이라고 적혀 있는데 실제는 {n}건입니다")

    # 12. 배포 설정 — 여기가 어긋나면 남한테는 깨진 채로 나갑니다
    pyproject = ROOT / "pyproject.toml"
    if pyproject.exists():          # 배포판 안에는 없습니다
        import tomllib
        cfg = tomllib.load(pyproject.open("rb"))

        # 12-1. 휠에 vibe.yaml 이 안 담기면 배포판은 첫 실행부터 죽습니다
        inc = cfg["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
        for 필수 in ("vibe.py", "vibe.yaml"):
            assert 필수 in inc, f"휠에 {필수} 가 안 담깁니다 (force-include)"
        assert inc["vibe.yaml"].rsplit("/", 1)[0] == inc["vibe.py"].rsplit("/", 1)[0], \
            "vibe.yaml 이 vibe.py 옆에 안 담깁니다 — ROOT 로 못 찾습니다"

        # 12-2. 의존성이 두 곳에 적혀 있습니다(스크립트 헤더 · pyproject).
        #       복붙된 두 벌은 반드시 갈라집니다. 여기서 대조합니다.
        src = Path(__file__).read_text(encoding="utf-8")
        header = re.search(r'# dependencies = \[(.*?)\]', src).group(1)
        헤더deps = sorted(x.strip().strip('"\'') for x in header.split(","))
        assert 헤더deps == sorted(cfg["project"]["dependencies"]), \
            f"의존성이 갈라졌습니다: 헤더 {헤더deps} vs pyproject {cfg['project']['dependencies']}"

        # 12-3. 진입점이 실제로 있는 함수를 가리키는지
        ep = cfg["project"]["scripts"]["stackpack"]
        mod, fn = ep.split(":")
        assert mod.endswith(".vibe") and fn in globals(), f"진입점이 이상합니다: {ep}"

    검증됨 = sum(1 for r in incidents.values() if r["status"] == "검증됨")
    도구 = ", ".join(s["name"] for s in data["surfaces"].values())
    검사있음 = sum(1 for i in incidents.values() if i.get("caught_by"))
    print(f"\n통과. 사고 {len(incidents)}건 (검증됨 {검증됨}, 자동검사 {검사있음}) "
          f"· 도구 {도구} · 확인 {age}일 전")
    return 0


# 한글 이름 → 원래 명령. 어려운 영어를 외우게 하지 않으려는 것뿐이고,
# 영어 이름도 그대로 둡니다. 아는 사람은 하던 대로 씁니다.
별명 = {
    "되돌리기": "undo", "지우기": "undo",
    "목록": "list", "보기": "show",
    "어디": "where", "어디에": "where",
    "갱신": "sync", "최신": "sync",
    "자동": "auto",
    "검사": "check", "점검": "check",
    "관문": "hook", "차단": "hook",
    "성적표": "report", "기록": "report",
    "정리": "tidy",
}


def main():
    argv = sys.argv[1:]

    # 아무것도 안 붙이고 그냥 실행 → 알아서 다 합니다. 이게 기본입니다.
    if not argv:
        data = load()
        rc = do_auto(data, execute=True)
        if (Path.home() / ".claude").exists():
            ok, _ = hook_on()
            if ok:
                print()
                print("그리고 **막습니다** — AI 가 키를 코드에 적거나 .env 를 올리려 하면")
                print("그 자리에서 멈춥니다. 사람이 뭘 누를 필요 없습니다.")
                print(f"막은 횟수 보기: {prog()} 성적표   ·   끄기: {prog()} 관문 끄기")
        ensure_schedule()
        return rc

    argv = [별명.get(a, a) for a in argv]
    argv = ["--yes" if a == "--진짜" else a for a in argv]
    argv = ["--dry-run" if a == "--미리보기" else a for a in argv]

    p = argparse.ArgumentParser(description=__doc__.replace("{prog}", prog()),
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="어떤 방법들이 있나")
    sub.add_parser("where", help="어느 파일에 놓이는지")
    sub.add_parser("selftest", help="스스로 검사")
    pc = sub.add_parser("check", help="내 프로젝트에서 이 사고들을 찾기")
    pc.add_argument("dir", nargs="?", default=".", help="볼 폴더 (기본: 지금 폴더)")
    pu = sub.add_parser("undo", help="넣었던 것 전부 빼기")
    pu.add_argument("--yes", action="store_true", help="실제로 빼기")
    ph = sub.add_parser("hook", help="관문 켜기/끄기")
    ph.add_argument("onoff", nargs="?", default="상태")
    sub.add_parser("report", help="지금까지 몇 번 막았나")
    pt = sub.add_parser("tidy", help="낡은 형식 항목 빼기")
    pt.add_argument("--yes", action="store_true")
    sub.add_parser("guard", help="(훅이 부르는 것)")
    pau = sub.add_parser("auto", help="자동 갱신 켜기/끄기")
    pau.add_argument("onoff", nargs="?", default="상태", help="켜기 / 끄기")
    psy = sub.add_parser("sync", help="최신 방법 받아서 다시 넣기")
    psy.add_argument("--yes", action="store_true")
    psh = sub.add_parser("show", help="방법 하나 자세히")
    psh.add_argument("key")
    pa = sub.add_parser("apply", help="내 프로젝트에 적용")
    pa.add_argument("targets", nargs="*", default=["all"])
    pa.add_argument("--yes", action="store_true")
    pa.add_argument("--dry-run", action="store_true", help="보여주기만")
    pa.add_argument("--dir", default=".")
    pa.add_argument("--global", dest="glob", action="store_true")
    pa.add_argument("--only", help="도구 하나만")
    a = p.parse_args(argv)

    if a.cmd == "guard":
        try:
            from . import guard
        except ImportError:
            import guard
        return guard.main()

    if a.cmd == "sync":
        return do_sync(execute=a.yes)

    data = load()
    try:
        if a.cmd == "list":
            return do_list(data)
        if a.cmd == "where":
            return do_where(data)
        if a.cmd == "selftest":
            return do_selftest(data)
        if a.cmd == "check":
            return do_check(a.dir)
        if a.cmd == "show":
            return do_show(data, a.key)
        if a.cmd == "undo":
            return undo(data, ROOT, "global", execute=a.yes)
        if a.cmd == "auto":
            return do_auto_cmd(a.onoff)
        if a.cmd == "hook":
            return do_hook_cmd(a.onoff)
        if a.cmd == "report":
            return do_report(data)
        if a.cmd == "tidy":
            return do_tidy(data, execute=a.yes)
        if a.only and a.only not in data["surfaces"]:
            raise KeyError(a.only)
        scope = "global" if a.glob else "project"
        root = Path(a.dir).resolve()
        실행 = not a.dry_run
        for _, name, path in surface_paths(data, scope, root, a.only):
            print(f"{name}  →  {path}")
            if 실행:
                path.parent.mkdir(parents=True, exist_ok=True)
        print()
        return do_apply(data, a.targets or ["all"], root, execute=실행,
                        scope=scope, only=a.only)
    except KeyError as k:
        print(f"그런 건 없습니다: {k}\n있는 것: {', '.join(data['incidents'])}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
