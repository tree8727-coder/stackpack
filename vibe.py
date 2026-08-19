# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml", "certifi"]
# ///
"""vibe.py — vibe.yaml 하나에서 "내 프로젝트에 놓이는 파일"을 만듭니다.

    uv run vibe.py list                  방법 목록
    uv run vibe.py show 단언-부숴보기      방법 하나 자세히
    uv run vibe.py apply all             지금 폴더에 적용 미리보기 (아무것도 안 바꿈)
    uv run vibe.py apply all --yes       지금 폴더에 실제로 적용
    uv run vibe.py apply all --global --yes   전역에 한 번만 — 모든 프로젝트에 자동 적용
    uv run vibe.py where                 어느 도구의 어느 파일에 놓이는지
    uv run vibe.py sync --yes            최신으로 당겨서 전역에 다시 얹기 (스케줄러용)
    uv run vibe.py selftest              데이터 규율 + 안전장치 검사

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


def validate(data):
    """받아온 데이터가 규율을 지키는지. **적용하기 전에** 봅니다.

    남의 서버에서 받은 파일을 검사 없이 내 전역 설정에 얹으면 안 됩니다.
    selftest 가 쓰는 것과 같은 검사입니다 — 두 벌로 만들지 않았습니다.
    """
    assert data.get("surfaces"), "surfaces 가 없습니다"
    for k, r in data.get("recipes", {}).items():
        assert r.get("cons", "").strip(), f"{k}: 단점(cons)이 비었습니다"
        assert r.get("status") in data["statuses"], f"{k}: 모르는 status"
        e = r.get("evidence") or {}
        assert e.get("users", 0) >= 1 and e.get("sources"), f"{k}: 근거가 없습니다"
        for f in r.get("files", []):
            assert f.get("to") == "rules", f"{k}: 모르는 to '{f.get('to')}'"
            assert f.get("mode") in ("create", "append"), f"{k}: 모르는 mode"
    return data


def marker(key):
    return f"<!-- vibe:{key} -->"


def recipes_for(data, targets):
    if list(targets) == ["all"]:
        return {k: v for k, v in data["recipes"].items() if v["status"] == "검증됨"}
    out = {}
    for t in targets:
        if t not in data["recipes"]:
            raise KeyError(t)
        out[t] = data["recipes"][t]
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
    for key, r in recipes_for(data, targets).items():
        for f in r.get("files", []):
            assert f.get("to") == "rules", f"{key}: 모르는 to '{f.get('to')}'"
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
        if before is not None and marker(key) in before:
            pending[path] = before
            steps.append((path, before, before, f"이미 적용됨 — 건너뜀 ({key})"))
            return
        base = before if before is not None else ""
        pending[path] = base.rstrip("\n") + "\n" + f"\n{marker(key)}\n{body}\n"
        steps.append((path, before, pending[path], f"덧붙임 ({key})"))
        return

    raise AssertionError(f"{key}: 모르는 mode '{f['mode']}'")


def do_apply(data, targets, root, execute=False, scope="project", only=None):
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
            print(f"--  {rel}  {why}")
            continue
        changed += 1
        touched.add(path)
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
    for key, r in recipes_for(data, targets).items():
        if r.get("steps"):
            print(f"\n[{key}] 이건 사람이 해야 합니다:")
            for s in r["steps"]:
                print(f"  - {s}")

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
    for key, r in data["recipes"].items():
        e = r["evidence"]
        print(f"\n{key}  [{r['status']}]  {e['users']}명 · 최장 {e['longest']}")
        print(f"  {r['name']}")
        print(f"  단점: {r['cons']}")
    print(f"\n{len(data['recipes'])}개. 자세히: uv run vibe.py show <키>")
    return 0


def do_where(data):
    for key, s in data["surfaces"].items():
        print(f"\n{s['name']}  ({key})")
        print(f"  전역     {s['global']}      ← 한 번 넣으면 모든 프로젝트에 자동")
        print(f"  프로젝트  {s['project']}")
    print("\n경로는 vibe.yaml 의 surfaces 에 있습니다. 도구가 늘면 거기만 고칩니다.")
    return 0


def do_show(data, key):
    r = data["recipes"][key]
    e = r["evidence"]
    print(f"{key}\n{'─' * 40}")
    print(f"{r['name']}\n")
    print(f"왜:   {r['why']}")
    print(f"단점: {r['cons']}")
    print(f"대상: {r['target']}")
    print(f"근거: {e['users']}명 · 최장 {e['longest']} · 출처 {', '.join(e['sources'])}")
    print(f"상태: {r['status']} — {data['statuses'][r['status']]}\n")
    for f in r.get("files", []):
        print(f"[{f['path']}] ({f['mode']})")
        print("\n".join("  " + l for l in f["body"].rstrip("\n").splitlines()))
        print()
    for s in r.get("steps", []):
        print(f"  - {s}")
    return 0


def do_sync(execute=False):
    """저장소를 최신으로 당기고 전역에 다시 얹습니다.

    사람들이 낸 방법이 늘어나도 손으로 다시 칠 일이 없게 하려는 명령입니다.
    스케줄러에 걸어 두는 건 이것 하나면 됩니다.
    """
    import subprocess
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


def do_selftest(data):
    import tempfile

    recipes, statuses = data["recipes"], data["statuses"]

    # 1. 데이터 규율 — 단점 없는 방법, 근거 없는 방법은 실을 수 없습니다
    for k, r in recipes.items():
        assert r.get("cons", "").strip(), f"{k}: 단점(cons)이 비었습니다"
        assert r.get("status") in statuses, f"{k}: 모르는 status '{r.get('status')}'"
        e = r.get("evidence") or {}
        assert e.get("users", 0) >= 1, f"{k}: evidence.users 가 없습니다"
        assert e.get("sources"), f"{k}: evidence.sources 가 비었습니다"
        assert r.get("files") or r.get("steps"), f"{k}: 하는 게 아무것도 없습니다"

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
             "recipes": {"x": {"cons": "", "status": "검증됨",
                               "evidence": {"users": 1, "sources": ["#1"]}}}}
    try:
        validate(나쁜것)
        raise AssertionError("validate 가 단점 빈 방법을 통과시켰습니다")
    except AssertionError as e:
        assert "단점" in str(e), e

    검증됨 = sum(1 for r in recipes.values() if r["status"] == "검증됨")
    도구 = ", ".join(s["name"] for s in data["surfaces"].values())
    print(f"\n통과. 방법 {len(recipes)}개 (검증됨 {검증됨}) · 도구 {도구} · 확인 {age}일 전")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="방법 목록")
    sub.add_parser("where", help="어느 도구의 어느 파일에 놓이는지")
    psy = sub.add_parser("sync", help="최신으로 당겨서 전역에 다시 얹기")
    psy.add_argument("--yes", action="store_true", help="실제로 적용 (없으면 미리보기)")
    sub.add_parser("selftest", help="데이터 규율 + 안전장치 검사")
    psh = sub.add_parser("show", help="방법 하나 자세히")
    psh.add_argument("key")
    pa = sub.add_parser("apply", help="내 프로젝트에 적용")
    pa.add_argument("targets", nargs="+", help="방법 키 / all (all = 검증됨 전부)")
    pa.add_argument("--yes", action="store_true", help="실제로 적용 (없으면 미리보기)")
    pa.add_argument("--dir", default=".", help="적용할 폴더 (기본: 지금 폴더)")
    pa.add_argument("--global", dest="glob", action="store_true",
                    help="도구의 전역 규칙 파일에 놓아 모든 프로젝트에 자동 적용")
    pa.add_argument("--only", help="도구 하나만 (claude-code / antigravity)")
    a = p.parse_args()

    if a.cmd == "sync":
        return do_sync(execute=a.yes)

    data = load()
    try:
        if a.cmd == "list":
            return do_list(data)
        if a.cmd == "where":
            return do_where(data)
        if a.cmd == "show":
            return do_show(data, a.key)
        if a.cmd == "selftest":
            return do_selftest(data)
        if a.only and a.only not in data["surfaces"]:
            raise KeyError(a.only)
        scope = "global" if a.glob else "project"
        root = Path(a.dir).resolve()
        for _, name, path in surface_paths(data, scope, root, a.only):
            print(f"{name}  →  {path}")
            if a.yes:
                path.parent.mkdir(parents=True, exist_ok=True)
        print("전역입니다 — 모든 프로젝트에서 자동으로 읽힙니다.\n" if a.glob
              else "이 폴더에만 적용됩니다.\n")
        return do_apply(data, a.targets, root, execute=a.yes, scope=scope, only=a.only)
    except KeyError as k:
        print(f"모르는 키: {k}\n있는 것: {', '.join(data['recipes'])}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
