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
    for key, r in recipes_for(data, targets).items():
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
    for key, r in data["recipes"].items():
        e = r["evidence"]
        print(f"\n{key}  [{r['status']}]  {e['users']}명 · 최장 {e['longest']}")
        print(f"  {r['name']}")
        print(f"  단점: {r['cons']}")
    print(f"\n{len(data['recipes'])}개. 자세히: {prog()} show <키>")
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
        for key, r in data["recipes"].items():
            s, e = marker(key), end_marker(key)
            while s in after and e in after:
                i, j = after.index(s), after.index(e) + len(e)
                if j < i:            # 짝이 안 맞으면 건드리지 않습니다
                    break
                after = after[:i] + after[j:]
            for f in r.get("files", []):   # 끝 표시가 없던 시절 것
                옛것 = legacy_block(key, f["body"].rstrip("\n"))
                after = after.replace(옛것, "")
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

    총 = 0
    for key in 쓰는것:
        s = data["surfaces"][key]
        path = Path(s["global"]).expanduser()
        if execute:
            path.parent.mkdir(parents=True, exist_ok=True)
        steps = plan(data, ["all"], ROOT, "global", key)
        총 += sum(1 for _, b, a, _ in steps if b != a)
        do_apply(data, ["all"], ROOT, execute=execute, scope="global", only=key, quiet=True)

    print()
    if 총 == 0:
        print("이미 다 돼 있습니다. 아무것도 안 했습니다.")
    else:
        print(f"끝났습니다. 방법 {총}개를 넣었습니다.")
        print("이제 AI가 알아서 읽습니다. 더 하실 건 없습니다.")
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
            i = 글.index(end_marker(next(iter(recipes))))
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
        키 = next(iter(recipes))
        본문 = recipes[키]["files"][0]["body"].rstrip("\n")
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

    검증됨 = sum(1 for r in recipes.values() if r["status"] == "검증됨")
    도구 = ", ".join(s["name"] for s in data["surfaces"].values())
    print(f"\n통과. 방법 {len(recipes)}개 (검증됨 {검증됨}) · 도구 {도구} · 확인 {age}일 전")
    return 0


# 한글 이름 → 원래 명령. 어려운 영어를 외우게 하지 않으려는 것뿐이고,
# 영어 이름도 그대로 둡니다. 아는 사람은 하던 대로 씁니다.
별명 = {
    "되돌리기": "undo", "지우기": "undo",
    "목록": "list", "보기": "show",
    "어디": "where", "어디에": "where",
    "갱신": "sync", "최신": "sync",
    "자동": "auto",
}


def main():
    argv = sys.argv[1:]

    # 아무것도 안 붙이고 그냥 실행 → 알아서 다 합니다. 이게 기본입니다.
    if not argv:
        data = load()
        rc = do_auto(data, execute=True)
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
    pu = sub.add_parser("undo", help="넣었던 것 전부 빼기")
    pu.add_argument("--yes", action="store_true", help="실제로 빼기")
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
        if a.cmd == "show":
            return do_show(data, a.key)
        if a.cmd == "undo":
            return undo(data, ROOT, "global", execute=a.yes)
        if a.cmd == "auto":
            return do_auto_cmd(a.onoff)
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
        print(f"그런 건 없습니다: {k}\n있는 것: {', '.join(data['recipes'])}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
