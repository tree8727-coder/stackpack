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
import fnmatch
import re
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
VIBE = ROOT / "vibe.yaml"

# 배포판(uvx·pip)에는 저장소가 없습니다. git pull 로는 갱신할 수 없어서
# sync 는 깃허브에서 vibe.yaml 만 직접 받아 여기 둡니다.
# **`main` 이 아니라 태그된 판**만 받습니다. main 을 받으면 우리 계정이 털린 날
# 하루 만에 모든 설치본의 AI 규칙이 바뀝니다. 태그는 사람이 일부러 붙여야 합니다.
RELEASES = "https://api.github.com/repos/tree8727-coder/stackpack/releases/latest"
RAW = "https://raw.githubusercontent.com/tree8727-coder/stackpack/{ref}/vibe.yaml"
REMOTE = RAW.format(ref="main")     # 태그가 아직 없을 때만 (그 사실을 말합니다)
많이바뀜 = 0.30                      # 이만큼 넘게 바뀌면 멈추고 사람에게 알립니다
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


INDEX_KEY = "오답노트"

# 규칙 파일에 넣을 최대 줄 수. 이건 취향이 아니라 **지시 예산**입니다 —
# 지시가 늘수록 따르는 정확도가 떨어진다는 것이 측정돼 있습니다
# (IFScale, arXiv 2507.11538 / 다중 제약 10~15%p 하락, arXiv 2407.03978).
# 넘치는 것은 버리지 않고 스킬로 보냅니다.
INDEX_MAX = 12


def index_line(inc):
    """규칙 파일에 들어갈 **한 줄.** 증상 + 그래서 뭘 하나."""
    return f"- **[{inc['id']}]** {inc['symptom']} → {' '.join(inc['fix'][0].split())}"


def 이_프로젝트에_해당되나(inc, 파일이름들):
    """이 사고가 지금 프로젝트에 해당되는가. **파일 이름만 봅니다.**

    내용은 안 읽고, 어디로도 안 보냅니다. 이 컴퓨터에서 «무엇을 넣을지» 를
    좁히는 데만 씁니다. 좁힐수록 규칙 파일이 짧아지고 AI 가 실제로 읽습니다.
    """
    무늬 = inc.get("when")
    if not 무늬:
        return True                      # 표시가 없으면 어디서나 해당
    for 무 in 무늬:
        if 무 == "*":
            return True
        for 이름 in 파일이름들:
            if fnmatch.fnmatch(이름, 무) or fnmatch.fnmatch(이름.lower(), 무.lower()):
                return True
    return False


def 프로젝트_파일이름(root, 최대=4000):
    """파일 «이름» 만 모읍니다. 내용은 안 봅니다."""
    건너뛸것 = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist",
              "build", ".next", "out", "site-packages"}
    이름들 = []
    for p_ in root.rglob("*"):
        if len(이름들) >= 최대:
            break
        if any(part in 건너뛸것 for part in p_.parts):
            continue
        이름들.append(p_.name)
    return 이름들


def 해당되는_사고(data, root):
    이름들 = 프로젝트_파일이름(root)
    고른것 = {k: v for k, v in data["incidents"].items()
            if 이_프로젝트에_해당되나(v, 이름들)}
    return 고른것 or data["incidents"]     # 하나도 안 걸리면 전부 넣습니다


def 내_기록(data):
    """이 컴퓨터에서 어떤 사고가 몇 번 걸렸나. **여기서 밖으로 안 나갑니다.**

    집단 학습(전체에서 자주 걸리는 것)은 서버가 있어야 합니다.
    개인 적응(내가 자주 걸리는 것)은 서버 없이 지금 됩니다 — 그리고 이쪽이
    더 정확합니다. 남이 자주 겪는 것보다 **내가 자주 겪는 것**이 먼저입니다.
    """
    센것 = {}
    if not BLOCK_LOG.exists():
        return 센것
    번호 = {i["id"]: k for k, i in data["incidents"].items()}
    try:
        for line in BLOCK_LOG.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            사고 = json.loads(line).get("사고")
            if 키 := 번호.get(사고):
                센것[키] = 센것.get(키, 0) + 1
    except (OSError, json.JSONDecodeError):
        pass
    return 센것


def index_block(data, 고른것=None):
    """규칙 파일에는 **색인만** 넣습니다.

    전문 21건을 매 세션 통째로 주입하면 토큰만 먹고 안 읽힙니다.
    AI 가 알아봐야 하는 건 «지금이 그 상황인가» 이고, 그건 증상 한 줄이면 됩니다.
    전문은 스킬에 두고 해당될 때만 불러오게 합니다.
    """
    줄 = ["## 남이 이미 당한 사고 — 같은 걸 두 번 하지 않는다", ""]
    줄.append("아래 상황이 오면 **멈추고 해당 항목을 확인한다.** 전문은 `오답노트` 스킬에 있다.")
    줄.append("")
    쓸것 = 고른것 or data["incidents"]
    센것 = 내_기록(data)

    # 기계가 잡는 사고는 **AI 에게 말하지 않습니다.** 관문은 토큰도 지시 예산도
    # 0 인데 100% 확실합니다. 여기 또 적으면 지시만 늘고 정확도는 떨어집니다
    # (IFScale: 지시 밀도가 오르면 임계점 이후 급락).
    자동 = {k: v for k, v in 쓸것.items() if v.get("caught_by")}
    말할것 = {k: v for k, v in 쓸것.items() if not v.get("caught_by")}

    # 심각도 먼저, 그다음 이 컴퓨터에서 걸린 횟수. **드문 것과 안 중요한 것은 다릅니다** —
    # 요금 사고는 개인당 드물게 걸리지만 한 번에 돈이 나갑니다.
    차례 = sorted(말할것.items(),
                key=lambda kv: (kv[1].get("severity") != "높음", -센것.get(kv[0], 0)))
    보일것 = 차례[:INDEX_MAX]
    줄 += [index_line(i) + (f"  ← 여기서 {센것[k]}번 걸림" if 센것.get(k) else "")
          for k, i in 보일것]

    if 자동:
        번호 = " · ".join(sorted(v["id"] for v in 자동.values()))
        줄 += ["", f"위 밖에 **{번호}** 는 관문이 **자동으로 막는다.** 외울 필요 없다."]
    if len(차례) > len(보일것):
        줄 += [f"나머지 {len(차례) - len(보일것)}건은 `오답노트` 스킬에 있다 — "
              "상황이 오면 그때 찾아본다."]
    줄 += ["", f"전문 보기: `stackpack 보기 <항목>` · 내 프로젝트 점검: `stackpack 검사`"]
    return "\n".join(줄)


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

    # 먼저 고아부터 치웁니다. 지금 쓰는 것은 색인 하나뿐이라, 예전에 항목마다
    # 하나씩 넣었던 블록은 전부 고아가 됩니다.
    살릴키 = {INDEX_KEY}
    for _, _, path in surfaces:
        if not path.exists():
            continue
        전 = path.read_text(encoding="utf-8")
        후 = strip_orphans(전, 살릴키)
        if 후 != 전:
            pending[path] = 후
            steps.append((path, 전, 후, "더 안 쓰는 항목을 뺐습니다"))
    # 프로젝트에 넣을 때는 그 프로젝트에 해당되는 것만. 전역은 전부 (어디서 쓸지 모름)
    고른것 = None if scope == "global" else 해당되는_사고(data, root)
    if 실험_상태().get("단계") == "끔":
        # 실험 «끔» 주간 — 규칙만 뺍니다. 관문은 계속 켜져 있습니다.
        return steps
    f = {"mode": "append", "body": index_block(data, 고른것)}
    for _, _, path in surfaces:
        yield_step(steps, pending, path, INDEX_KEY, f)
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


def do_sync(execute=False, 강제=False):
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
        # 태그된 판을 먼저 찾습니다
        주소, 어느판 = REMOTE, "main (태그 없음)"
        try:
            정보 = json.loads(fetch(RELEASES))
            if 태그 := 정보.get("tag_name"):
                주소, 어느판 = RAW.format(ref=태그), 태그
        except Exception:
            pass
        assert 주소.startswith("https://"), "평문 http 로는 받지 않습니다"
        if 어느판.startswith("main"):
            print("⚠ 아직 태그된 판이 없어 main 을 받습니다. 태그가 생기면 그것만 받습니다.")
        print(f"받는 중 … {어느판}")
        try:
            raw = fetch(주소)
        except Exception as e:
            print(f"받지 못했습니다: {e}\n지금 있는 것으로 그대로 둡니다.")
            return 1
        # **검사를 통과한 것만** 저장합니다. 받은 걸 바로 얹으면 남의 파일을 믿는 셈입니다.
        try:
            validate(yaml.safe_load(raw))
        except AssertionError as e:
            print(f"받은 파일이 규율을 어깁니다: {e}\n적용하지 않습니다.")
            return 1
        # 한 번에 너무 많이 바뀌면 **적용하지 않고 멈춥니다.**
        # 형식 검사는 「형식이 맞는 나쁜 규칙」 을 못 막습니다. 양이 그걸 대신 봅니다.
        지금것 = source()
        if 지금것.exists():
            옛것 = 지금것.read_text(encoding="utf-8")
            차이 = abs(len(raw) - len(옛것)) / max(len(옛것), 1)
            if 차이 > 많이바뀜:
                print(f"한 번에 {차이:.0%} 가 바뀝니다(기준 {많이바뀜:.0%}). "
                      "적용하지 않고 멈춥니다.")
                print(f"직접 보시려면: {주소}")
                print(f"그래도 받으려면: {prog()} 갱신 --진짜 --많이바뀌어도")
                if not 강제:
                    return 1
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        if CACHE.exists():
            CACHE.with_suffix(".yaml.직전").write_text(
                CACHE.read_text(encoding="utf-8"), encoding="utf-8")
        CACHE.write_text(raw, encoding="utf-8")
        print(f"받았습니다 ({어느판}) → {CACHE}")

    통계_보내기(load())
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


SKILL_DIR = Path.home() / ".claude" / "skills" / "오답노트"


def skill_text(data):
    """스킬 본문. **설명 한 줄만 항상 떠 있고 본문은 해당될 때만 불러옵니다.**
    그래서 21건 전문을 넣어도 평소 토큰을 안 먹습니다."""
    상황 = " · ".join(i["symptom"].replace("때", "때").split(",")[0][:28]
                    for i in list(data["incidents"].values())[:8])
    앞 = (
        "---\n"
        "name: 오답노트\n"
        "description: >-\n"
        "  남이 실제로 당한 사고 " + str(len(data["incidents"])) + "건. 키·계좌를 코드에 적으려 할 때,\n"
        "  .env 를 커밋하려 할 때, 배포 설정을 건드릴 때, 검사를 새로 쓸 때,\n"
        "  수집 결과를 덮어쓸 때, 영상·데이터를 이어붙일 때 이걸 먼저 본다.\n"
        "  «이거 왜 이렇게 됐지» 하는 상황에서도 여기 같은 사고가 있는지 찾는다.\n"
        "---\n\n"
        "# 오답노트\n\n"
        "전부 **실제로 있었던 일**이다. 일반론은 없다.\n"
        "각 항목의 「이렇게 해도 안 잡히는 것」까지 읽어야 한다 — 그게 이 규칙의 한계다.\n\n"
        "내 프로젝트에 이 사고가 있는지 실제로 찾으려면: `stackpack 검사`\n\n"
        "---\n\n"
    )
    return 앞 + "\n\n---\n\n".join(body_for(i) for i in data["incidents"].values()) + "\n"


def do_skill(data, install=True):
    글 = skill_text(data)
    (ROOT / "skill_vibe").mkdir(exist_ok=True)
    (ROOT / "skill_vibe" / "SKILL.md").write_text(글, encoding="utf-8")
    if install:
        SKILL_DIR.mkdir(parents=True, exist_ok=True)
        (SKILL_DIR / "SKILL.md").write_text(글, encoding="utf-8")
    return 0


REPO = "https://github.com/tree8727-coder/stackpack"

# ── 집계 (「초록불 보고서」의 표본) ──────────────────────────────────────────
# **나가는 것은 사고 번호와 횟수뿐입니다.** 코드·파일 이름·경로·대화는 안 나갑니다.
# 무엇이 나갔는지는 `통계` 로 언제든 그대로 볼 수 있고, `통계 끄기` 한 마디로 끝납니다.
#
# 읽기는 이 서버가 아니라 **깃허브의 공개 집계 파일**에서 합니다. 그래서
# 서버가 죽어도 프로그램은 그대로 돌고, 집계를 우리가 조작할 수도 없습니다.
COUNT_URL = "https://stackpack-count.tree8727.workers.dev/v1/count"
STAT_OFF = Path.home() / ".stackpack" / "통계_꺼짐"
INSTALL_ID = Path.home() / ".stackpack" / "설치id"
SENT = Path.home() / ".stackpack" / "보낸것.jsonl"


def 설치id():
    """이 설치를 구분하는 난수. **기계 정보에서 만들지 않습니다** —
    기계에서 뽑으면 그건 식별자가 되고, 난수는 그냥 난수입니다."""
    if INSTALL_ID.exists():
        return INSTALL_ID.read_text(encoding="utf-8").strip()
    import uuid
    새 = str(uuid.uuid4())
    INSTALL_ID.parent.mkdir(parents=True, exist_ok=True)
    INSTALL_ID.write_text(새, encoding="utf-8")
    return 새


def 보낼것(data):
    """마지막으로 보낸 뒤에 새로 막힌 것만. 사고 번호와 횟수뿐입니다."""
    마지막 = ""
    if SENT.exists():
        줄 = [l for l in SENT.read_text(encoding="utf-8").splitlines() if l.strip()]
        if 줄:
            try:
                마지막 = json.loads(줄[-1]).get("까지", "")
            except json.JSONDecodeError:
                pass
    센것 = {}
    if BLOCK_LOG.exists():
        for line in BLOCK_LOG.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("때", "") > 마지막:
                센것[r["사고"]] = 센것.get(r["사고"], 0) + 1
    return 센것


AGG_URL = "https://raw.githubusercontent.com/tree8727-coder/stackpack/main/집계.json"
MINE = Path.home() / ".stackpack" / "내사고"


def 집계_받기():
    """공개 집계를 깃허브에서 읽습니다. **우리 서버에 접속하지 않습니다.**"""
    try:
        return json.loads(fetch(AGG_URL))
    except Exception:
        return None


def do_mine(번호=None):
    """내가 낸 사고가 남을 몇 번 구했는지 봅니다.

    제보해도 아무 일이 안 일어나면 아무도 두 번째를 안 냅니다.
    **자기 사고가 남의 컴퓨터에서 일하는 걸 보는 것** — 돈 안 드는 보상 중
    이보다 센 게 없습니다.
    """
    data = load()
    내것 = set()
    if MINE.exists():
        내것 = {l.strip() for l in MINE.read_text(encoding="utf-8").splitlines() if l.strip()}
    if 번호:
        내것.add(번호.lstrip("#"))
        MINE.parent.mkdir(parents=True, exist_ok=True)
        MINE.write_text("\n".join(sorted(내것)) + "\n", encoding="utf-8")

    if not 내것:
        print("\n아직 등록한 제보 번호가 없습니다.")
        print(f"사고를 내신 뒤 이슈 번호를 알려주세요:  {prog()} 내사고 31")
        print(f"제보하기: {REPO}/issues/new?template=사용법-제출.yml")
        return 0

    맞는것 = {}
    for k, inc in data["incidents"].items():
        출처 = " ".join(inc["evidence"]["sources"])
        for n in 내것:
            # «#1» 이 «#10» 을 잡으면 안 됩니다. 부분 문자열로 찾다 오늘만 세 번
            # 당했습니다(E16 · E28). 숫자 끝을 못박습니다.
            if re.search(rf"#{re.escape(n)}(?!\d)", 출처):
                맞는것.setdefault(n, []).append(inc)

    집계 = 집계_받기()
    내기록 = 내_기록(data)
    번호맵 = {i["id"]: k for k, i in data["incidents"].items()}

    print(f"\n등록한 제보: {', '.join('#' + n for n in sorted(내것))}\n")
    if not 맞는것:
        print("  아직 카탈로그에 실리지 않았습니다. 실리면 여기에 나옵니다.")
        return 0

    총 = 0
    for n, 사고들 in sorted(맞는것.items()):
        for inc in 사고들:
            키 = 번호맵[inc["id"]]
            전세계 = (집계 or {}).get(inc["id"])
            내것수 = 내기록.get(키, 0)
            print(f"  #{n} → [{inc['id']}] {inc['name']}")
            if 전세계 is None:
                print(f"        전 세계: (아직 집계가 없습니다)   내 컴퓨터: {내것수}번")
            else:
                총 += 전세계
                print(f"        **전 세계에서 {전세계}번 막았습니다.**   내 컴퓨터: {내것수}번")
    if 집계 is None:
        print("\n  집계 파일이 아직 없습니다. 사람이 쓰기 시작하면 여기에 숫자가 찹니다.")
        print(f"  ({AGG_URL})")
    elif 총:
        print(f"\n  당신이 낸 사고가 남의 컴퓨터에서 **모두 {총}번** 일했습니다.")
        if 집계.get("설치수"):
            print(f"  (지금 {집계['설치수']}명이 쓰고 있습니다)")
    return 0


def do_stats(onoff="상태"):
    data = load()
    if onoff in ("끄기", "off"):
        STAT_OFF.parent.mkdir(parents=True, exist_ok=True)
        STAT_OFF.write_text("꺼짐\n", encoding="utf-8")
        print("통계를 껐습니다. 이제 아무것도 나가지 않습니다.")
        return 0
    if onoff in ("켜기", "on"):
        STAT_OFF.unlink(missing_ok=True)
        print("통계를 켰습니다.")
        return 0

    꺼짐 = STAT_OFF.exists()
    print(f"\n통계: {'꺼짐' if 꺼짐 else '켜짐'}")
    보낼 = 보낼것(data)
    이름 = {i["id"]: i["name"] for i in data["incidents"].values()}
    print("\n다음에 나갈 내용 — **이게 전부입니다.**")
    if not 보낼:
        print("  (보낼 게 없습니다)")
    for 사고, n in sorted(보낼.items()):
        print(f"  {사고}: {n}   ({이름.get(사고, '')})")
    print(f"  설치 ID: {설치id()[:8]}…  (난수입니다. 기계 정보에서 만들지 않았습니다)")
    print("\n안 나가는 것: 코드 · 파일 이름 · 경로 · 대화 · IP · 기계 정보")
    print(f"집계 결과는 공개됩니다: {REPO}/blob/main/집계.json")
    print(f"\n끄려면: {prog()} 통계 끄기")
    return 0


def 통계_보내기(data):
    """sync 할 때 조용히 보냅니다. 실패해도 아무 일도 일어나지 않습니다."""
    if STAT_OFF.exists():
        return
    보낼 = 보낼것(data)
    if not 보낼:
        return
    import urllib.request
    몸 = json.dumps({"install": 설치id(), "counts": 보낼}).encode()
    요청 = urllib.request.Request(COUNT_URL, data=몸,
                                headers={"content-type": "application/json"})
    try:
        urllib.request.urlopen(요청, timeout=10).read()
    except Exception:
        return          # 못 보내도 그만입니다. 사용자 작업을 막지 않습니다.
    try:
        SENT.parent.mkdir(parents=True, exist_ok=True)
        with SENT.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"까지": datetime.now().isoformat(timespec="seconds"),
                                "보낸것": 보낼}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def do_send(data):
    """제보를 **타이핑 없이** 보냅니다.

    서버를 두지 않습니다. 서버를 두는 순간 「서버 없음」 이라는 이 프로그램의
    가장 큰 장점이 사라집니다(폐쇄망 고객이 첫 조건으로 보는 것). 대신 로컬에
    쌓인 기록으로 이슈 본문을 만들어 **브라우저에 미리 채워서** 엽니다.
    사람이 할 일은 「제출」 한 번 누르는 것뿐입니다.

    보내는 것: 사고 번호와 횟수뿐입니다. **파일 이름도 코드도 안 들어갑니다.**
    """
    import urllib.parse
    import webbrowser

    if not BLOCK_LOG.exists():
        print("아직 막힌 게 없습니다. 뭔가 막히면 그때 보낼 게 생깁니다.")
        return 0
    센것 = {}
    for line in BLOCK_LOG.read_text(encoding="utf-8").splitlines():
        try:
            센것[json.loads(line)["사고"]] = 센것.get(json.loads(line)["사고"], 0) + 1
        except (json.JSONDecodeError, KeyError):
            continue
    이름 = {i["id"]: i["name"] for i in data["incidents"].values()}
    줄 = [f"- {사고} {이름.get(사고, '')} — {n}번" for 사고, n in sorted(센것.items())]
    본문 = ("스택팩이 제 컴퓨터에서 막은 횟수입니다.\n\n"
          + "\n".join(줄)
          + "\n\n---\n"
          + "이 내용은 `stackpack 보내기` 가 만들었습니다. "
          + "**사고 번호와 횟수뿐이고 파일 이름도 코드도 들어 있지 않습니다.**\n"
          + "보내기 전에 위 내용을 직접 보고 계십니다.\n")

    print("아래 내용으로 브라우저를 엽니다. 「제출」만 누르시면 됩니다.\n")
    print(본문)
    url = (f"{REPO}/issues/new?labels=" + urllib.parse.quote("막은기록")
           + "&title=" + urllib.parse.quote("[기록] 막은 횟수")
           + "&body=" + urllib.parse.quote(본문))
    if len(url) > 8000:
        print("(내용이 너무 길어 브라우저로 못 엽니다. 위 내용을 붙여넣어 주세요.)")
        return 0
    webbrowser.open(url)
    print(f"\n열었습니다. 안 열렸으면 이 주소로:\n{url[:120]}...")
    return 0


CLAUDE_DIR = Path.home() / ".claude"


def 글자_토큰(글):
    """토큰 «추정». 정확한 값이 아니라는 걸 화면에도 적습니다.

    한글은 대략 글자 1.5개, 영문·기호는 4글자가 토큰 하나쯤입니다.
    기계로 정확히 못 재는 값에 정밀한 척하지 않습니다(P3).
    """
    한글 = sum(1 for c in 글 if "\uac00" <= c <= "\ud7a3")
    나머지 = len(글) - 한글
    return int(한글 / 1.5 + 나머지 / 4)


def do_diagnose():
    """매 세션 AI 에게 주입되는 «지시량» 을 잽니다.

    스킬 2,810개를 파는 시장에서 **덜어내라고 말하는 도구가 없습니다.**
    설치를 파는 쪽은 구조적으로 그 말을 할 수 없습니다 — 우리는 팔 게 없어서
    그 말만 할 수 있습니다.
    """
    if not CLAUDE_DIR.exists():
        print("~/.claude 가 없습니다. Claude Code 를 쓰지 않으시는 것 같습니다.")
        return 0

    항목 = []
    주입될글 = []          # 토큰 추정을 두 벌로 만들지 않습니다(P5) — 글자_토큰 하나만 씁니다
    rules = CLAUDE_DIR / "CLAUDE.md"
    if rules.exists():
        글 = rules.read_text(encoding="utf-8", errors="ignore")
        주입될글.append(글)
        항목.append(("규칙 파일", "CLAUDE.md", len(글.splitlines()), len(글)))

    스킬들 = []
    skills = CLAUDE_DIR / "skills"
    if skills.exists():
        for d in sorted(skills.iterdir()):
            f = d / "SKILL.md"
            if not f.is_dir() and f.exists():
                글 = f.read_text(encoding="utf-8", errors="ignore")
                # 스킬은 **설명만** 항상 떠 있고 본문은 필요할 때 불러옵니다.
                머리 = 글.split("---")[1] if 글.startswith("---") and "---" in 글[3:] else 글[:400]
                스킬들.append((d.name, len(글.splitlines()), len(머리), len(글)))
                주입될글.append(머리)

    플러그인 = 0
    pj = CLAUDE_DIR / "plugins" / "installed_plugins.json"
    if pj.exists():
        try:
            안 = json.loads(pj.read_text(encoding="utf-8"))
            플러그인 = sum(len(v) if isinstance(v, (list, dict)) else 1 for v in 안.values()) \
                if isinstance(안, dict) else len(안)
        except (OSError, json.JSONDecodeError, AttributeError):
            플러그인 = 0

    print(f"\n{CLAUDE_DIR} 를 봤습니다. **AI 에게 주입되는 설정 파일만 봅니다** —")
    print("여러분 코드도, 대화도, 작업 기록도 안 봅니다. 그리고 아무것도 안 보냅니다.\n")
    for 이름, 파일, 줄, 자 in 항목:
        print(f"  {이름:<10} {파일:<24} {줄:>5}줄  {자:>7}자  (전부 매 세션 주입)")
    if 스킬들:
        print(f"  스킬       {len(스킬들)}개")
        for 이름, 줄, 머리, 전체 in sorted(스킬들, key=lambda x: -x[2])[:8]:
            print(f"             {이름:<24} {줄:>5}줄  설명 {머리:>5}자  (본문 {전체}자는 필요할 때만)")
        if len(스킬들) > 8:
            print(f"             … 외 {len(스킬들) - 8}개")
    if 플러그인:
        print(f"  플러그인   {플러그인}개")

    전부 = "".join(주입될글)
    추정 = 글자_토큰(전부)
    print(f"\n매 세션 항상 들어가는 양: 약 **{len(전부):,}자 · {추정:,}토큰** (추정입니다)")
    print()
    if 추정 > 3000:
        print("  ! 지시가 많은 편입니다. 지시 밀도가 오르면 따르는 정확도가")
        print("    임계점 이후 급락한다는 측정이 있습니다 (IFScale, arXiv:2507.11538).")
    else:
        print("  괜찮은 편입니다.")
    print()
    print("  줄이는 법 — **지우지 말고 옮기세요.**")
    print("   · 규칙 파일에 긴 설명이 있으면 스킬로 옮깁니다. 스킬은 설명 몇 줄만 항상 뜨고")
    print("     본문은 해당될 때만 불러옵니다. 우리가 307줄 → 31줄로 줄인 방법입니다.")
    print("   · 안 쓰는 스킬은 폴더 이름 앞에 `_` 를 붙여 두면 꺼집니다.")
    print()
    print("  **어떤 스킬을 실제로 쓰는지는 우리가 알 수 없습니다.** 대화를 안 보기 때문입니다.")
    print("  그래서 «안 쓰는 것» 을 대신 골라 드리지 않습니다 — 크기만 보여 드립니다.")
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

    do_skill(data, install=execute)
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
        print(f"(규칙 파일에는 **한 줄 색인만** 넣었습니다 — 전문은 필요할 때만 불러옵니다)")
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


# ── 실험: 규칙이 진짜 듣는가 ──────────────────────────────────────────────────
# 규칙(글)이 AI 행동을 바꾸는지 아무도 측정한 적이 없습니다. 우리는 잴 수 있습니다.
#
# 규칙이 효과가 있으면 **AI 가 애초에 시도를 덜 하므로 관문이 덜 울려야** 합니다.
# 그래서 규칙을 한 주 켜고 한 주 끄면서 관문 발동을 셉니다.
#
# 작업량이 주마다 다른 게 가장 큰 함정이라, 횟수가 아니라 **쓰기 100번당 막힘**
# 으로 봅니다. 쓴 횟수는 관문이 이미 세고 있습니다(내용 없이 개수만).
#
# **관문은 실험 중에도 항상 켜져 있습니다.** 껐다 켜는 것은 규칙(글)뿐이라,
# 안전이 내려가는 구간은 없습니다.
EXP = Path.home() / ".stackpack" / "실험.json"
WRITE_LOG = Path.home() / ".stackpack" / "쓴것.jsonl"
한주 = 7 * 24 * 3600


def 실험_상태():
    if not EXP.exists():
        return {"단계": "켬", "시작": datetime.now().isoformat(timespec="seconds"), "기간": []}
    try:
        return json.loads(EXP.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"단계": "켬", "시작": datetime.now().isoformat(timespec="seconds"), "기간": []}


def 센다(로그, 부터, 까지):
    n = 0
    if not 로그.exists():
        return 0
    try:
        for line in 로그.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            때 = r.get("때") or r.get("t")
            if 때 and 부터 <= 때 <= 까지:
                n += 1
    except (OSError, json.JSONDecodeError):
        pass
    return n


def 실험_넘길때가_됐나(상태):
    try:
        지난 = (datetime.now() - datetime.fromisoformat(상태["시작"])).total_seconds()
    except (ValueError, KeyError):
        return False
    return 지난 >= 한주


def 실험_진행(꺼짐=False):
    """한 주가 지났으면 단계를 뒤집고 지난 기간을 기록합니다."""
    상태 = 실험_상태()
    if 꺼짐 or not 실험_넘길때가_됐나(상태):
        return 상태
    이제 = datetime.now().isoformat(timespec="seconds")
    상태["기간"].append({
        "단계": 상태["단계"], "부터": 상태["시작"], "까지": 이제,
        "막힘": 센다(BLOCK_LOG, 상태["시작"], 이제),
        "쓰기": 센다(WRITE_LOG, 상태["시작"], 이제),
    })
    상태["단계"] = "끔" if 상태["단계"] == "켬" else "켬"
    상태["시작"] = 이제
    try:
        EXP.parent.mkdir(parents=True, exist_ok=True)
        EXP.write_text(json.dumps(상태, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
    return 상태


def 실험_결과(상태):
    """(켬 비율, 끔 비율, 켬 주수, 끔 주수). 비율 = 쓰기 100번당 막힘."""
    합 = {"켬": [0, 0], "끔": [0, 0]}
    주 = {"켬": 0, "끔": 0}
    for k in 상태.get("기간", []):
        if k["단계"] in 합:
            합[k["단계"]][0] += k["막힘"]
            합[k["단계"]][1] += k["쓰기"]
            주[k["단계"]] += 1
    def 율(x):
        return None if x[1] == 0 else x[0] * 100 / x[1]
    return 율(합["켬"]), 율(합["끔"]), 주["켬"], 주["끔"]


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
REVERT_LOG = Path.home() / ".stackpack" / "되돌린것.jsonl"


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

    # 되돌림 — 아직 이름 없는 사고의 후보입니다
    if REVERT_LOG.exists():
        되돌림 = [json.loads(l) for l in REVERT_LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
        if 되돌림:
            확장자별 = {}
            for r in 되돌림:
                확장자별[r["확장자"]] = 확장자별.get(r["확장자"], 0) + 1
            print(f"\n그리고 AI 가 쓴 것을 곧바로 되돌린 적이 {len(되돌림)}번 있습니다.")
            for e, n in sorted(확장자별.items(), key=lambda x: -x[1])[:5]:
                print(f"  {n:>3}번   {e}")
            print("  → 여기가 «아직 이름 없는 사고» 가 숨어 있는 자리입니다.")
            print("     내용은 안 남깁니다. 무엇을 되돌렸는지가 아니라 «얼마나 자주» 만 셉니다.")
    상태 = 실험_상태()
    켬, 끔, 주켬, 주끔 = 실험_결과(상태)
    print(f"\n[실험] 지금은 규칙 «{상태['단계']}» 주간입니다. (관문은 항상 켜져 있습니다)")
    if 켬 is None or 끔 is None:
        모자란 = "규칙 끈 주" if 끔 is None else "규칙 켠 주"
        print(f"  아직 «{모자란}» 자료가 없습니다. 한 주씩 번갈아 모으는 중입니다.")
    else:
        print(f"  규칙 켠 주 ({주켬}주):  쓰기 100번당 {켬:.1f}번 막힘")
        print(f"  규칙 끈 주 ({주끔}주):  쓰기 100번당 {끔:.1f}번 막힘")
        차 = 끔 - 켬
        if 주켬 < 2 or 주끔 < 2:
            print("  → 아직 각 2주가 안 돼 판단하지 않습니다.")
        elif 차 > 0:
            print(f"  → 규칙이 켜진 주에 {차:.1f}만큼 덜 막혔습니다. 규칙이 일하고 있습니다.")
        elif 차 < 0:
            print(f"  → 규칙이 켜진 주에 오히려 {-차:.1f}만큼 더 막혔습니다. 규칙이 안 듣는 것일 수 있습니다.")
        else:
            print("  → 차이가 없습니다.")

    print(f"\n기록은 이 컴퓨터에만 있습니다 ({BLOCK_LOG.parent}). 아무 데도 안 보냅니다.")
    return 0


def do_selftest(data):
    import tempfile

    incidents, statuses = data["incidents"], data["statuses"]

    # 1. 데이터 규율 — validate 와 같은 함수를 씁니다(두 벌로 안 만듭니다)
    validate(data)
    번호 = [inc["id"] for inc in incidents.values()]
    assert len(번호) == len(set(번호)), f"사고 번호가 겹칩니다: {번호}"

    # 1-1b. 「당연어」만 있는 사고는 정보가 0 입니다.
    #        카페 글의 «커피» 처럼, 이 바닥에서 당연히 나오는 말만 있으면 아무것도
    #        안 알려줍니다. 그래서 **고유한 것이 최소 하나** 있어야 합니다 —
    #        숫자(시간·금액·건수) · 파일 이름 · 오류 문구 중 하나.
    #        (달나루 회의록: 자동 생성 페이지가 얇으면 저품질로 분류된다 — 같은 방어선)
    #        영문 식별자(inner_text, fly.toml)도 «고유한 것» 으로 봅니다 —
    #        한국어 문장 안의 ASCII 토막은 거의 항상 그 사고에만 있는 이름입니다.
    고유함 = re.compile(r"\d|[A-Za-z_.]{3,}|`[^`]+`|«[^»]+»")
    for k, inc in incidents.items():
        재료 = inc["story"] + " " + " ".join(inc["fix"])
        assert 고유함.search(재료), (
            f"{k}: 숫자도 파일 이름도 오류 문구도 없습니다 — "
            "당연한 말만 있는 사고는 싣지 않습니다")

    # 1-1b2. 이슈로 들어온 사고는 **그 이슈 번호를 잃으면 안 됩니다.**
    #         제보자가 자기 사고를 못 찾으면 두 번째 제보가 안 옵니다.
    #         실제로 오답노트를 다시 쓰면서 #1~#10 연결이 통째로 끊겼었습니다.
    # «#1» 이 «#10» 을 잡는지 실제로 확인합니다
    가짜 = "#10 본인, ERRORS.md"
    assert not re.search(r"#1(?!\d)", 가짜), "이슈 번호 찾기가 #1 로 #10 을 잡습니다"
    assert re.search(r"#10(?!\d)", 가짜), "이슈 번호 찾기가 #10 을 못 잡습니다"

    이슈있음 = [i["id"] for i in incidents.values()
             if any("#" in s for s in i["evidence"]["sources"])]
    assert 이슈있음, "이슈 번호가 붙은 사고가 하나도 없습니다 — 제보 추적이 끊겼습니다"
    for k, inc in incidents.items():
        번호 = [s for s in inc["evidence"]["sources"] if s.startswith("#")]
        for s in 번호:
            assert re.match(r"^#\d+\b", s), f"{k}: 이슈 번호 모양이 아닙니다 — {s}"

    # 1-1c. 표본이 늘고 있는지 눈에 보이게 합니다. 전부 users:1 이면 그건 한 사람의
    #        기록이지 카탈로그가 아닙니다. (막지는 않습니다 — 사실을 감추면 더 나쁩니다)
    혼자 = sum(1 for i in incidents.values() if i["evidence"]["users"] == 1)
    if 혼자 == len(incidents):
        print(f"  ! 사고 {len(incidents)}건이 전부 users:1 입니다 — 아직 한 사람의 기록입니다")

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
            i = 글.index(end_marker(INDEX_KEY))
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
        키 = INDEX_KEY
        # 프로젝트 범위는 이제 «해당되는 것만» 넣으므로 기대값도 같은 방식으로 만듭니다
        본문 = index_block(data, 해당되는_사고(data, tmp4)).rstrip("\n")
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
            assert marker(INDEX_KEY) in 글, "치우기만 하고 새로 안 넣었습니다"
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
        막아야 += [
            ("Bash", {"command": "git add .env"}, "E5"),
            ("Bash", {"command": "cd app && git add src/.env"}, "E5"),
            ("Bash", {"command": "git add -A; git add .env.production"}, "E5"),
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
            # 오탐으로 실제 커밋이 막혔던 것들 — 명령 안에 «.env» 라는 글자가
            # 무관하게 들어 있어도 막으면 안 됩니다. 오탐 나는 도구는 지워집니다.
            ("Bash", {"command": "git add -A && git commit -m '.env 를 gitignore 에 넣었다'"}),
            ("Bash", {"command": "echo '.env 설명' > 문서.md && git add 문서.md"}),
            ("Bash", {"command": "git add .env.example"}),
            ("Bash", {"command": "git status && grep -r .env ."}),
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

    # 11-4d. 훅은 **사용자 전역에만** 씁니다. 프로젝트 설정에 훅을 심으면,
    #        그 저장소를 여는 남의 AI 가 우리 코드를 실행하게 됩니다.
    #        2026-02 에 바로 그 경로로 CVE 가 났습니다(.claude/settings.json 훅).
    assert SETTINGS == Path.home() / ".claude" / "settings.json", \
        f"설정 경로가 사용자 전역이 아닙니다: {SETTINGS}"
    # 찾는 글자를 이어붙여 만듭니다. 그대로 적으면 이 검사 자신이 걸립니다
    # — E27 을 여기서 또 밟았습니다.
    src_v = Path(__file__).read_text(encoding="utf-8")
    for 조각 in (("settings.local", ".json"), ("Path.cwd()", ' / ".claude"')):
        금지 = "".join(조각)
        assert src_v.count(금지) <= 1, f"프로젝트 설정을 건드리는 코드가 있습니다: {금지}"

    # 11-4e. 되돌림 기록에 **원문이 안 들어가는지**. 들어가면 그 파일이 새는 순간 코드가 샙니다.
    g2 = None
    try:
        from . import guard as g2
    except ImportError:
        try:
            import guard as g2
        except ImportError:
            pass
    if g2 is not None:
        import inspect as _i2
        기록소스 = _i2.getsource(g2.쓴것_기록) + _i2.getsource(g2.되돌림_확인)
        for 조각 in (("cont", "ent"), ("new_", "string"), ("old_", "string")):
            금지 = "".join(조각)
            assert 금지 not in 기록소스, f"되돌림 기록이 원문을 남기려 합니다: {금지}"
        assert "지문(" in 기록소스, "되돌림 기록이 해시를 안 씁니다"

    # 11-4b. 규칙 파일에 들어가는 색인이 **짧아야** 합니다. 전문을 매 세션 주입하면
    #         토큰만 먹고 안 읽힙니다 — 재원이 지적한 바로 그 문제입니다.
    색인 = index_block(data)
    assert len(색인.splitlines()) <= len(incidents) + 10, \
        f"색인이 {len(색인.splitlines())}줄입니다 — 전문이 새어 들어갔습니다"
    for 표 in ("실제로 있었던 일", "이렇게 해도 안 잡히는 것"):
        assert 표 not in 색인, f"색인에 전문({표})이 들어갔습니다"

    # 11-4f. 순서를 바꾸다가 사고를 **빠뜨리면 안 됩니다.** 개인 적응이 카탈로그를
    #        조용히 줄이는 순간, 그건 개선이 아니라 손실입니다.
    가짜기록 = {"E8": 5, "E13": 2}
    번호맵 = {i["id"]: k for k, i in incidents.items()}
    for 아이디 in 가짜기록:
        assert 아이디 in 번호맵, f"검사가 없는 사고 번호를 씁니다: {아이디}"
    색인줄 = [l for l in index_block(data).splitlines() if l.startswith("- **[")]
    assert len(색인줄) <= INDEX_MAX, \
        f"색인이 {len(색인줄)}줄입니다 — 지시 예산 {INDEX_MAX} 을 넘었습니다"
    # 예산 자체에도 상한을 둡니다. 상수를 키우면 위 검사가 무력해지므로,
    # 늘리려면 이 줄을 일부러 고쳐야 합니다 — 그때 근거를 대야 합니다.
    assert INDEX_MAX <= 15, (
        f"지시 예산이 {INDEX_MAX} 입니다. 지시가 늘수록 따르는 정확도가 떨어진다는 "
        "측정이 있습니다(IFScale arXiv:2507.11538, 다중 제약 10~15%p arXiv:2407.03978). "
        "늘리려면 그보다 나은 근거가 필요합니다.")
    # 색인에서 뺀 것은 **버린 게 아니라 스킬에 있어야** 합니다. 조용히 사라지면 손실입니다.
    스킬2 = skill_text(data)
    for k, inc in incidents.items():
        assert inc["name"] in 스킬2, f"{k} 가 색인에서도 스킬에서도 빠졌습니다"
    # 심각한 것이 먼저 나와야 합니다 — 드문 것과 안 중요한 것은 다릅니다
    높은것 = [i["id"] for i in incidents.values()
            if i.get("severity") == "높음" and not i.get("caught_by")]
    if 높은것 and 색인줄:
        assert any(h in 색인줄[0] for h in 높은것), \
            f"심각도 높은 사고가 첫 줄에 없습니다: {색인줄[0][:40]}"

    # 11-4c. 프로젝트 감지는 **파일 이름만** 봅니다. 내용을 읽으면 안 됩니다.
    import inspect as _ins
    소스 = _ins.getsource(프로젝트_파일이름) + _ins.getsource(이_프로젝트에_해당되나)
    for 금지 in ("read_text", "read_bytes", "open("):
        assert 금지 not in 소스, f"프로젝트 감지가 파일 내용을 읽고 있습니다: {금지}"
    # 그리고 스킬에는 전문이 다 있어야 합니다
    스킬 = skill_text(data)
    for k, inc in incidents.items():
        assert inc["name"] in 스킬, f"스킬에 {k} 가 빠졌습니다"
    assert 스킬.startswith("---\nname: "), "스킬에 머리말이 없습니다"

    # 11-4g. 자동 배포 안전장치 — 여기가 제일 큰 위험입니다. 매일 받아서 남의 AI
    #         규칙에 자동으로 넣고 있으므로, 우리가 털리면 하루 만에 퍼집니다.
    import inspect as _i3
    동기소스 = _i3.getsource(do_sync)
    assert "releases/latest" in RELEASES, "태그된 판을 찾지 않습니다"
    assert "많이바뀜" in 동기소스, "한 번에 크게 바뀌는 것을 막지 않습니다"
    assert ".직전" in 동기소스, "직전 판을 남기지 않습니다"
    assert 0 < 많이바뀜 < 1, f"변경 상한이 이상합니다: {많이바뀜}"

    # 11-4h. 실험이 거짓말을 못 하게 합니다. 우리에게 유리한 결과가 나오도록
    #         설계가 기울면, 그 측정은 안 하느니만 못합니다.
    import inspect as _i4
    실험소스 = _i4.getsource(실험_진행) + _i4.getsource(실험_결과)

    # ① 작업량으로 나눠야 합니다. 횟수만 세면 바쁜 주가 이겼다고 나옵니다
    assert "쓰기" in 실험소스, "작업량으로 정규화하지 않습니다"
    # 쓰기 수를 일부러 다르게 둡니다. 같게 두면 «나누는지» 를 구분할 수 없습니다.
    켬, 끔, _, _ = 실험_결과({"기간": [
        {"단계": "켬", "막힘": 2, "쓰기": 200},   # 1.0
        {"단계": "끔", "막힘": 9, "쓰기": 100}]})  # 9.0
    assert abs(켬 - 1) < 1e-9 and abs(끔 - 9) < 1e-9, \
        f"작업량으로 안 나누고 있습니다 (켬 {켬}, 끔 {끔} — 기대 1, 9)"

    # ② 실험 «끔» 주간에도 **관문은 켜져 있어야** 합니다. 안전이 내려가면 안 됩니다
    끔소스 = _i4.getsource(plan)
    assert "관문은 계속 켜져" in 끔소스, "실험이 관문까지 끄고 있습니다"
    assert "hook_off" not in 끔소스 and "schedule_off" not in 끔소스, \
        "실험이 관문·자동갱신을 건드립니다"

    # ③ 양쪽 자료가 2주씩 모이기 전에는 결론을 내지 않습니다
    assert "각 2주가 안 돼" in _i4.getsource(do_report), "표본이 적을 때 결론을 냅니다"

    # 11-4i. 진단기가 «남의 것» 을 안 보는지. 우리가 볼 것은 AI 에게 주입되는
    #         설정 파일뿐입니다. 대화 기록이나 프로젝트 코드를 보기 시작하면
    #         「서버 없음·대화 안 봄」 이라는 우리 문장이 거짓말이 됩니다.
    import inspect as _i5
    진단소스 = _i5.getsource(do_diagnose)
    for 조각 in (("trans", "cripts"), ("hist", "ory.jsonl"), ("sess", "ions")):
        금지 = "".join(조각)
        assert 금지 not in 진단소스, f"진단기가 대화 기록을 봅니다: {금지}"
    # 토큰 추정은 한 곳에서만 합니다(P5)
    assert "/ 1.7" not in 진단소스, "토큰 추정이 두 벌입니다 — 글자_토큰 하나만 쓰세요"
    assert "글자_토큰(" in 진단소스, "진단기가 공용 추정 함수를 안 씁니다"

    # 11-4j. 나가는 것이 «사고 번호와 횟수» 뿐인지. 여기가 새면 이 프로젝트의
    #         모든 문장이 거짓말이 됩니다.
    import inspect as _i6
    보내기소스 = _i6.getsource(보낼것) + _i6.getsource(통계_보내기) + _i6.getsource(설치id)
    # 「content」 를 통째로 막았더니 content-type **헤더**를 잡았습니다 — 우리 E16 과
    # 같은 병(규칙이 엉뚱한 걸 잡음)이라, 기계 정보를 뽑는 함수 이름만 정확히 봅니다.
    # 무엇이 실제로 나가는지는 아래 «열쇠» 검사가 못박습니다 — 그쪽이 본검사입니다.
    for 조각 in (("Path.cw", "d()"), ("plat", "form."), ("get", "node"),
                 ("uname", "()"), ("hostn", "ame")):
        금지 = "".join(조각)
        assert 금지 not in 보내기소스, f"보내기가 기계 정보를 씁니다: {금지}"
    # 보내는 몸통에 counts·install 말고 다른 열쇠가 있으면 안 됩니다
    본문 = re.search(r'json\.dumps\(\{([^}]*)\}\)\.encode', 보내기소스)
    assert 본문, "보내는 내용을 확인할 수 없습니다"
    열쇠 = set(re.findall(r'"(\w+)":', 본문.group(1)))
    assert 열쇠 == {"install", "counts"}, f"보내는 열쇠가 늘었습니다: {열쇠}"
    # 설치 ID 는 난수여야 합니다 — 기계에서 뽑으면 식별자가 됩니다
    assert "uuid" in _i6.getsource(설치id), "설치 ID 가 난수가 아닙니다"
    # 끌 수 있어야 합니다
    assert "STAT_OFF.exists()" in _i6.getsource(통계_보내기), "통계를 끌 수 없습니다"

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
    "진단": "diagnose", "무게": "diagnose",
    "통계": "stats",
    "내사고": "mine", "기여": "mine",
    "보내기": "send", "제보": "send",
}


def main():
    argv = sys.argv[1:]

    # 아무것도 안 붙이고 그냥 실행 → 알아서 다 합니다. 이게 기본입니다.
    if not argv:
        실험_진행()
        data = load()
        rc = do_auto(data, execute=True)
        if (Path.home() / ".claude").exists():
            ok, _ = hook_on()
            if ok:
                print()
                print("그리고 **막습니다** — AI 가 키를 코드에 적거나 .env 를 올리려 하면")
                print("그 자리에서 멈춥니다. 사람이 뭘 누를 필요 없습니다.")
                print(f"막은 횟수 보기: {prog()} 성적표   ·   끄기: {prog()} 관문 끄기")
        print(f"기록 보내기(타이핑 없이): {prog()} 보내기")
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
    sub.add_parser("send", help="막은 기록을 이슈로 보내기 (타이핑 없이)")
    sub.add_parser("diagnose", help="매 세션 주입되는 지시량 재기")
    pst2 = sub.add_parser("stats", help="무엇이 나가는지 보기 / 끄기")
    pst2.add_argument("onoff", nargs="?", default="상태")
    pm = sub.add_parser("mine", help="내가 낸 사고가 남을 몇 번 구했나")
    pm.add_argument("번호", nargs="?", help="이슈 번호 (예: 31)")
    pt = sub.add_parser("tidy", help="낡은 형식 항목 빼기")
    pt.add_argument("--yes", action="store_true")
    sub.add_parser("guard", help="(훅이 부르는 것)")
    pau = sub.add_parser("auto", help="자동 갱신 켜기/끄기")
    pau.add_argument("onoff", nargs="?", default="상태", help="켜기 / 끄기")
    psy = sub.add_parser("sync", help="최신 방법 받아서 다시 넣기")
    psy.add_argument("--yes", action="store_true")
    psy.add_argument("--많이바뀌어도", dest="force_big", action="store_true",
                     help="한 번에 크게 바뀌어도 받기")
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
        return do_sync(execute=a.yes, 강제=a.force_big)

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
        if a.cmd == "mine":
            return do_mine(a.번호)
        if a.cmd == "stats":
            return do_stats(a.onoff)
        if a.cmd == "diagnose":
            return do_diagnose()
        if a.cmd == "send":
            return do_send(data)
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
