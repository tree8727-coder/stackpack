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

__version__ = "0.1.1"      # ← 버전은 여기 하나뿐입니다. pyproject 가 여기서 읽어 갑니다(P5)

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


# 우리가 누구인지 밝힙니다. 파이썬 기본 이름(Python-urllib)은 봇으로 보고
# 막는 곳이 많습니다 — Cloudflare 가 실제로 403 을 돌려줬습니다.
# curl 로 시험하면 200 이 나와서 **손으로 시험하면 멀쩡해 보입니다.**
UA = f"stackpack/{__version__} (+https://github.com/tree8727-coder/stackpack)"


def _열기(요청, timeout=20):
    """**모든 인터넷 요청이 지나가는 한 곳.**

    파이썬이 시스템 인증서를 못 찾는 설치본이 실제로 있습니다. 그 대비를
    한 군데만 해 뒀더니, 숫자를 보내는 쪽은 그대로 터졌습니다 — 두 벌이
    갈라진 것입니다(P5). 그래서 여기로 모았습니다.
    **검증을 끄지는 않습니다** — 끄면 받은 것을 믿을 근거가 사라집니다.
    """
    import ssl
    import urllib.request

    if isinstance(요청, str):
        요청 = urllib.request.Request(요청)
    요청.add_header("User-Agent", UA)

    try:
        return urllib.request.urlopen(요청, timeout=timeout).read().decode("utf-8")
    except urllib.error.URLError as e:
        if not isinstance(getattr(e, "reason", None), ssl.SSLError):
            raise
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
        return urllib.request.urlopen(요청, timeout=timeout, context=ctx).read().decode("utf-8")


def fetch(url):
    """https 로 받아옵니다.

    파이썬이 시스템 인증서를 못 찾는 설치본이 실제로 있습니다(맥 공식 설치본에서
    "Install Certificates.command" 를 안 돌린 경우). 배포할 프로그램이 거기서
    죽으면 안 되므로, 기본 검증이 실패하면 certifi 묶음으로 한 번 더 시도합니다.
    **검증을 끄지는 않습니다** — 끄면 받은 파일을 믿을 근거가 사라집니다.
    """
    import urllib.parse

    # 주소에 한글이 있으면 파이썬이 못 보냅니다(UnicodeEncodeError). 인코딩합니다.
    # curl 은 알아서 해 주기 때문에 **손으로 시험하면 멀쩡해 보입니다** —
    # 프로그램으로 시험해야 드러납니다.
    쪼갠것 = urllib.parse.urlsplit(url)
    url = urllib.parse.urlunsplit((
        쪼갠것.scheme, 쪼갠것.netloc,
        urllib.parse.quote(쪼갠것.path), 쪼갠것.query, 쪼갠것.fragment))

    return _열기(url)


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
        _열기(요청, timeout=10)     # 보내는 쪽도 같은 문을 씁니다(P5)
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


PLUGIN_DIR = ROOT / "plugin"

# ── 초안 벽 ──────────────────────────────────────────────────────────────────
# 자동으로 만든 것은 **카탈로그와 다른 파일에 삽니다.**
#
# 상태 표시(`status: 초안`)로 막을 수도 있었지만, 표시는 실수로 바뀝니다.
# 파일이 다르면 안 바뀝니다. 초안은 이 컴퓨터의 이 파일에만 있고,
# 규칙 파일에도 스킬에도 플러그인에도 **절대** 들어가지 않습니다.
#
# 초안이 카탈로그로 가는 길은 하나뿐입니다 — **사람이 이슈로 냅니다.**
# 그 길을 자동화하면 «지어내지 않는다» 가 무너집니다.
DRAFTS = Path.home() / ".stackpack" / "초안.yaml"


def 초안_읽기():
    if not DRAFTS.exists():
        return []
    try:
        d = yaml.safe_load(DRAFTS.read_text(encoding="utf-8")) or {}
        return d.get("초안", [])
    except (OSError, yaml.YAMLError):
        return []


def 초안_쓰기(목록):
    DRAFTS.parent.mkdir(parents=True, exist_ok=True)
    DRAFTS.write_text(
        "# 자동으로 만든 초안입니다. **카탈로그가 아닙니다.**\n"
        "# 여기 있는 것은 규칙 파일·스킬·플러그인 어디에도 안 들어갑니다.\n"
        "# 사람이 읽고 이슈로 내야 카탈로그로 갑니다.\n\n"
        + yaml.safe_dump({"초안": 목록}, allow_unicode=True, sort_keys=False),
        encoding="utf-8")


def 초안_만들기(data):
    """되돌림이 한 자리에 몰리면 초안을 만듭니다.

    **되돌림은 «어디» 만 알려주고 «무엇» 은 모릅니다.** 그래서 초안은 사고가
    아니라 «여기를 봐 달라» 는 쪽지입니다. 문장을 지어내지 않고, 센 것만 적습니다.
    """
    if not REVERT_LOG.exists():
        return 0
    센것 = {}
    try:
        for line in REVERT_LOG.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            센것[r["확장자"]] = 센것.get(r["확장자"], 0) + 1
    except (OSError, json.JSONDecodeError):
        return 0

    있던것 = {d.get("확장자") for d in 초안_읽기()}
    목록 = 초안_읽기()
    새로 = 0
    for 확장자, n in 센것.items():
        if n < 3 or 확장자 in 있던것:      # 세 번은 몰려야 «자리» 라고 봅니다
            continue
        목록.append({
            "한줄": f"{확장자} 파일에서 AI 가 쓴 것을 {n}번 되돌렸다",
            "확장자": 확장자,
            "되돌린횟수": n,
            "근거": "되돌림 기록에서 자동으로 셌습니다. 내용은 안 봤습니다.",
            "사람이_채울것": [
                "무슨 일이 있었나 — 무엇을 보고 «이건 아니다» 라고 판단했나",
                "언제 그 일이 나나 — 「~하려 할 때」 로",
                "그래서 다음부터 뭘 다르게 하나",
            ],
        })
        새로 += 1
    if 새로:
        초안_쓰기(목록)
    return 새로


REPORT_DIR = ROOT / "보고서"


def do_report_build(data):
    """「초록불 보고서」를 **만들어냅니다.**

    손으로 쓰면 다음 판에서 죽습니다. 그리고 손으로 쓴 숫자는 어긋납니다(P4).
    사람이 쓰는 것은 해설뿐이고, 숫자와 표는 여기서 나옵니다.
    """
    inc = data["incidents"]
    초록불 = {k: v for k, v in inc.items() if v.get("초록불")}
    자동 = {k: v for k, v in inc.items() if v.get("caught_by")}
    센것 = 내_기록(data)
    막은총 = sum(센것.values())
    상태 = 실험_상태()
    켬, 끔, 주켬, 주끔 = 실험_결과(상태)
    되돌림 = 0
    if REVERT_LOG.exists():
        되돌림 = len([l for l in REVERT_LOG.read_text(encoding="utf-8").splitlines() if l.strip()])
    오늘 = date.today().isoformat()
    # 표본 수를 손으로 적지 않습니다(P4). 데이터에서 셉니다.
    제보자수 = max((v["evidence"]["users"] for v in inc.values()), default=0)

    줄 = [f"# 초록불 보고서 — {오늘}", "",
        "**초록불이 얼마나 자주 거짓말하는가.**", "",
        f"> **표본은 {제보자수}명입니다.** 이 판의 숫자는 거기서 나왔습니다.",
        "> 부풀리지 않고 그대로 적습니다. 표본이 늘면 다음 판에서 늘어납니다.", "",
        "---", "",
        "## 하나. 사고 기록", "",
        f"| | |", "|---|---|",
        f"| 기록된 사고 | **{len(inc)}건** |",
        f"| 그중 «초록불» 계열 | **{len(초록불)}건 ({len(초록불)*100//len(inc)}%)** |",
        f"| 기계가 자동으로 잡는 것 | {len(자동)}건 |",
        f"| 제보자 | **{제보자수}명** |", "",
        "«초록불» 계열이란 — **무언가가 «괜찮다» 고 알려준 뒤에 배신한 사고**입니다.",
        "검사가 통과했다 · 성공 메시지가 찍혔다 · 화면이 멀쩡해 보였다 ·",
        "완료 표시가 있었다 · 30일 남았다고 들었다 · 귀로는 멀쩡히 들렸다.", "",
        "> **세는 방법**: 사고마다 사람이 하나씩 판정해 `vibe.yaml` 의 `초록불` 칸에",
        "> 적었습니다. 단어 매칭이 아닙니다 — 규칙으로 세면 엉뚱한 것을 잡습니다(E16·E28).", "",
        "### 초록불 계열 전체", "", "| 번호 | 무엇이 «괜찮다» 고 했나 |", "|---|---|"]
    줄 += [f"| {v['id']} | {v['name']} |" for v in 초록불.values()]
    줄 += ["", "---", "", "## 둘. 관문이 실제로 막은 것", ""]
    if 막은총:
        이름 = {v["id"]: v["name"] for v in inc.values()}
        줄 += [f"이 컴퓨터에서 **{막은총}번** 막았습니다.", "",
              "| 번호 | 횟수 | 무엇 |", "|---|---|---|"]
        번호맵 = {k: v["id"] for k, v in inc.items()}
        for k, n in sorted(센것.items(), key=lambda x: -x[1]):
            줄.append(f"| {번호맵[k]} | {n} | {이름[번호맵[k]]} |")
    else:
        줄.append("아직 막은 기록이 없습니다.")
    줄 += ["", f"그리고 AI 가 쓴 것을 곧바로 되돌린 일이 **{되돌림}번** 있었습니다.",
          "되돌림은 «어디» 만 알려주고 «무엇» 은 모릅니다 — 그래서 사고로 세지 않습니다.", ""]

    줄 += ["---", "", "## 셋. 규칙이 실제로 듣는가", "",
          "규칙이 효과가 있으면 **AI 가 애초에 시도를 덜 하므로 관문이 덜 울려야** 합니다.",
          "한 주 켜고 한 주 끄면서 «쓰기 100번당 막힘» 으로 셉니다.", ""]
    if 켬 is None or 끔 is None:
        줄 += [f"**아직 답할 수 없습니다.** 규칙 켠 주 {주켬}주 · 끈 주 {주끔}주 모였습니다.",
              "양쪽 2주씩 모이기 전에는 결론을 내지 않습니다.", "",
              "> 내가 아는 한 **AI 규칙 파일이 실제로 듣는지 측정한 사례가 없습니다.**",
              "> 그래서 이 칸이 비어 있는 것 자체가 이 보고서의 이유입니다."]
    else:
        줄 += [f"| 규칙 | 기간 | 쓰기 100번당 막힘 |", "|---|---|---|",
              f"| 켬 | {주켬}주 | {켬:.1f} |", f"| 끔 | {주끔}주 | {끔:.1f} |"]
    줄 += ["", "---", "", "## 넷. 아직 모르는 것", "",
          "- **표본이 1명입니다.** 이 숫자들이 남에게도 그런지 모릅니다.",
          "- 규칙의 효과를 아직 못 쟀습니다(위 셋).",
          "- 초록불 판정은 **사람 판단**입니다. 다른 사람이 세면 다를 수 있습니다.",
          "- 여기 없는 사고는 «없다» 가 아니라 **«우리가 안 당해봤다»** 입니다.", "",
          "---", "",
          f"근거 — `vibe.yaml` (사고 {len(inc)}건) · `~/.stackpack/` 의 로컬 기록.",
          "이 문서는 `vibe.py 보고서` 가 만들어냅니다. 숫자를 손으로 적지 않습니다(P4).",
          f"저장소: {REPO}", ""]

    REPORT_DIR.mkdir(exist_ok=True)
    out = REPORT_DIR / f"초록불-{오늘}.md"
    out.write_text("\n".join(줄), encoding="utf-8")
    print(f"→ {out.relative_to(ROOT)}")
    print(f"  사고 {len(inc)}건 · 초록불 {len(초록불)}건 · 막음 {막은총}번 · 되돌림 {되돌림}번")
    print("  표본 1명. 그대로 적었습니다.")
    return 0


def do_draft(번호=None):
    """이 컴퓨터에 쌓인 초안을 봅니다. 카탈로그와 섞이지 않습니다."""
    목록 = 초안_읽기()
    if not 목록:
        print("\n초안이 없습니다.")
        print("AI 가 쓴 것을 되돌리는 일이 쌓이면 여기에 «아직 이름 없는 사고» 후보가 생깁니다.")
        return 0
    if 번호 is None:
        print(f"\n초안 {len(목록)}건 — **카탈로그가 아닙니다.** 이 컴퓨터에만 있습니다.\n")
        for i, d in enumerate(목록, 1):
            print(f"  {i}. {d.get('한줄', '(제목 없음)')}")
            print(f"     {d.get('근거', '')}")
        print(f"\n하나 보기: {prog()} 초안 1")
        print("이슈로 내면 카탈로그로 갑니다. 자동으로는 안 갑니다.")
        return 0
    try:
        d = 목록[int(번호) - 1]
    except (ValueError, IndexError):
        print(f"1 ~ {len(목록)} 중에서 고르세요.")
        return 1
    print()
    for k, v in d.items():
        print(f"{k}: {v}")
    print(f"\n이 초안은 **아무 곳에도 안 들어갑니다.** 이슈로 내주세요:")
    print(f"  {REPO}/issues/new?template=사용법-제출.yml")
    return 0


def do_plugin(data):
    """플러그인을 **만들어냅니다.** 손으로 적으면 카탈로그와 두 벌이 됩니다(P5).

    마켓에서 설치를 누르면 관문(훅)과 오답노트(스킬)가 같이 들어옵니다.
    그 뒤로는 명령이 없습니다.

    **규칙 색인은 안 들어갑니다.** 플러그인은 남의 CLAUDE.md 를 못 건드리고,
    건드려서도 안 됩니다. 대신 스킬 설명이 «언제 해당되는지» 를 들고 있고,
    자동 차단 6건은 훅이 지시 예산 0 으로 처리합니다.
    """
    권 = PLUGIN_DIR
    (권 / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (권 / "hooks").mkdir(exist_ok=True)
    (권 / "skills" / "오답노트").mkdir(parents=True, exist_ok=True)

    막는것 = sorted(i["id"] for i in data["incidents"].values() if i.get("caught_by"))
    설명 = ("AI 가 사고를 치기 직전에 막습니다. 키·계좌를 코드에 적으려 할 때, "
          ".env 를 커밋하려 할 때, 배포 설정을 건드릴 때, 검사를 새로 쓸 때, "
          "수집 결과를 덮어쓸 때 멈춰 세웁니다. "
          f"남이 실제로 당한 사고 {len(data['incidents'])}건 "
          f"(그중 {len(막는것)}건은 자동 차단: {' '.join(막는것)}). "
          "«이거 왜 이렇게 됐지» 하는 상황에서도 같은 사고가 있는지 찾습니다.")

    (권 / ".claude-plugin" / "plugin.json").write_text(json.dumps({
        "name": "stackpack",
        "description": 설명,
        "version": __version__,
        "author": {"name": "달나루"},
        "homepage": REPO,
        "license": "MIT",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    (권 / "hooks" / "hooks.json").write_text(json.dumps({
        "description": "스택팩 관문 — 아는 사고를 치기 직전에 막습니다",
        "hooks": {"PreToolUse": [{
            "matcher": "Write|Edit|Bash",
            "hooks": [{"type": "command",
                       "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/guard.py"',
                       "timeout": 10}],
        }]},
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 관문과 검사기와 카탈로그는 **복사**합니다. 원본은 저장소 뿌리 하나뿐입니다.
    for 파일 in ("guard.py", "check.py"):
        (권 / "hooks" / 파일).write_text(
            (ROOT / 파일).read_text(encoding="utf-8"), encoding="utf-8")
    (권 / "hooks" / "vibe.yaml").write_text(
        source().read_text(encoding="utf-8"), encoding="utf-8")
    (권 / "skills" / "오답노트" / "SKILL.md").write_text(skill_text(data), encoding="utf-8")

    (권 / ".claude-plugin" / "marketplace.json").write_text(json.dumps({
        "name": "stackpack",
        "description": "AI 가 사고 치기 전에 막는 관문 — 실제로 당한 사고로 만든 오답노트",
        "owner": {"name": "달나루"},
        "plugins": [{"name": "stackpack", "description": 설명,
                     "author": {"name": "달나루"}, "source": "./"}],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"플러그인을 만들었습니다 → {권}/")
    print(f"  사고 {len(data['incidents'])}건 · 자동 차단 {len(막는것)}건")
    print()
    print("쓰는 사람은 Claude Code 에서 이렇게만 하면 됩니다:")
    print(f"  /plugin marketplace add {REPO.split('//')[1]}")
    print("  /plugin install stackpack")
    print("  → 관문과 오답노트가 같이 들어갑니다. 그 뒤로 명령 없습니다.")
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
    새초안 = 초안_만들기(data)
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
    if 새초안:
        print()
        print(f"그리고 «아직 이름 없는 사고» 후보 {새초안}건이 생겼습니다: {prog()} 초안")
        print("  (자동으로 만든 쪽지입니다. 카탈로그에는 안 들어갑니다)")
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
    # **보내는 것을 첫 화면에서 알립니다.** 코드가 자동으로 보내는데 말하지 않으면
    # 그건 우리가 만드는 가짜 안심입니다. 묻지는 않되(마찰), 반드시 알립니다.
    if not STAT_OFF.exists():
        print()
        print("그때 «어떤 사고가 몇 번 막혔는지» 숫자도 함께 보냅니다.")
        print("  보내는 것: 사고 번호와 횟수, 그리고 난수 설치 ID — 그게 전부입니다.")
        print("  안 보내는 것: 코드 · 파일 이름 · 경로 · 대화 · IP · 기계 정보")
        print(f"  나갈 내용 그대로 보기: {prog()} 통계   ·   끄기: {prog()} 통계 끄기")


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
    """검사는 selftest.py 에 있습니다. 여기서는 부르기만 합니다."""
    try:
        from . import selftest
    except ImportError:
        import selftest
    return selftest.run(data)


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
    "플러그인": "plugin",
    "초안": "draft",
    "보고서": "report-build",
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
    sub.add_parser("plugin", help="Claude Code 플러그인 만들기")
    sub.add_parser("report-build", help="초록불 보고서 만들기")
    pd = sub.add_parser("draft", help="이 컴퓨터에 쌓인 초안 보기")
    pd.add_argument("번호", nargs="?")
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
        if a.cmd == "report-build":
            return do_report_build(data)
        if a.cmd == "draft":
            return do_draft(a.번호)
        if a.cmd == "plugin":
            return do_plugin(data)
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
