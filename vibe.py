# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""vibe.py — vibe.yaml 하나에서 "내 프로젝트에 놓이는 파일"을 만듭니다.

    uv run vibe.py list                  방법 목록
    uv run vibe.py show 단언-부숴보기      방법 하나 자세히
    uv run vibe.py apply all             지금 폴더에 적용 미리보기 (아무것도 안 바꿈)
    uv run vibe.py apply all --yes       지금 폴더에 실제로 적용
    uv run vibe.py apply all --global --yes   ~/.claude/ 에 한 번만 — 모든 프로젝트에 자동 적용
    uv run vibe.py selftest              데이터 규율 + 안전장치 검사

**아무것도 설치하지 않습니다.** 도구를 까는 건 build.py 쪽 일이고,
여기는 파일만 놓습니다. 그래서 uv 말고는 필요한 게 없습니다.

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

# Claude Code 가 **모든 프로젝트에서 자동으로 읽는** 파일이 여기 있습니다.
# --global 은 프로젝트 폴더 대신 여기에 놓습니다 — 한 번 넣으면 프로젝트마다
# 다시 칠 필요가 없습니다. 그래서 위험도 큽니다: 여기 쓴 건 전부에 영향을 줍니다.
GLOBAL = Path.home() / ".claude"

# 사람이 확인한 날짜가 이만큼 지나면 selftest 가 일부러 실패합니다.
# (build.py 의 모델 가격표 90일 장치와 같은 이유 — 오래된 데이터가 조용히 사는 걸 막습니다)
STALE_DAYS = 180

# 이 단어들은 vibe.yaml 에 들어올 수 없습니다. CONTRIBUTING.md 의 규율을 기계로 못박은 것입니다.
# 표본이 세 자리가 되기 전까지 어떤 방법도 "최적"이라고 부르지 않습니다.
금지어 = ("최적", "베스트", "정답")


def load():
    return yaml.safe_load(VIBE.read_text(encoding="utf-8"))


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


def plan(data, targets, root):
    """(경로, 이전내용, 다음내용, 사유) 목록. 아무 파일도 건드리지 않습니다.

    한 파일에 방법 여러 개가 붙습니다. 그래서 각 단계의 "이전 내용"은 디스크가 아니라
    **앞 단계까지 반영된 내용**이어야 합니다. 디스크만 보면 마지막 단계가 앞 단계를
    통째로 덮어씁니다 (selftest 6번이 잡는 사고입니다).
    """
    steps = []
    pending = {}  # path -> 앞 단계까지 반영된 내용 (None = 아직 파일 없음)
    for key, r in recipes_for(data, targets).items():
        for f in r.get("files", []):
            path = root / f["path"]
            if path in pending:
                before = pending[path]
            else:
                before = path.read_text(encoding="utf-8") if path.exists() else None
            body = f["body"].rstrip("\n")
            if f["mode"] == "create":
                if before is not None:
                    steps.append((path, before, before, f"이미 있음 — 건너뜀 ({key})"))
                    pending[path] = before
                    continue
                pending[path] = body + "\n"
                steps.append((path, None, pending[path], f"새로 만듦 ({key})"))
            elif f["mode"] == "append":
                block = f"\n{marker(key)}\n{body}\n"
                if before is not None and marker(key) in before:
                    steps.append((path, before, before, f"이미 적용됨 — 건너뜀 ({key})"))
                    pending[path] = before
                    continue
                base = before if before is not None else ""
                pending[path] = base.rstrip("\n") + "\n" + block
                steps.append((path, before, pending[path], f"덧붙임 ({key})"))
            else:
                raise AssertionError(f"{key}: 모르는 mode '{f['mode']}'")
    return steps


def do_apply(data, targets, root, execute=False):
    steps = plan(data, targets, root)
    changed, touched = 0, set()
    for path, before, after, why in steps:
        rel = path.name if path.parent == root else str(path)
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
            if before is not None:
                path.with_suffix(path.suffix + ".bak").write_text(before, encoding="utf-8")
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
        first = (tmp / "CLAUDE.md").read_text(encoding="utf-8")

        # 6. 두 번 돌려도 안 늘어난다
        do_apply(data, ["all"], tmp, execute=True)
        assert (tmp / "CLAUDE.md").read_text(encoding="utf-8") == first, "두 번 적용하니 내용이 달라졌습니다"

        # 7. 남이 쓴 내용을 절대 안 지운다
        (tmp / "CLAUDE.md").write_text("# 내가 쓴 거\n건드리지 마\n" + first, encoding="utf-8")
        do_apply(data, ["all"], tmp, execute=True)
        assert "건드리지 마" in (tmp / "CLAUDE.md").read_text(encoding="utf-8"), "남의 내용이 사라졌습니다"

    # 8. --global 이 가리키는 곳이 정말 홈 밑인지 (여기를 잘못 잡으면 남의 설정을 건드립니다)
    assert GLOBAL == Path.home() / ".claude", f"전역 경로가 이상합니다: {GLOBAL}"
    assert ROOT not in GLOBAL.parents and GLOBAL != ROOT, "전역 경로가 저장소 안을 가리킵니다"

    검증됨 = sum(1 for r in recipes.values() if r["status"] == "검증됨")
    print(f"\n통과. 방법 {len(recipes)}개 (검증됨 {검증됨}) · 확인 {age}일 전")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="방법 목록")
    sub.add_parser("selftest", help="데이터 규율 + 안전장치 검사")
    psh = sub.add_parser("show", help="방법 하나 자세히")
    psh.add_argument("key")
    pa = sub.add_parser("apply", help="내 프로젝트에 적용")
    pa.add_argument("targets", nargs="+", help="방법 키 / all (all = 검증됨 전부)")
    pa.add_argument("--yes", action="store_true", help="실제로 적용 (없으면 미리보기)")
    pa.add_argument("--dir", default=".", help="적용할 폴더 (기본: 지금 폴더)")
    pa.add_argument("--global", dest="glob", action="store_true",
                    help="~/.claude/ 에 놓아 모든 프로젝트에 자동 적용 (--dir 대신)")
    a = p.parse_args()

    data = load()
    try:
        if a.cmd == "list":
            return do_list(data)
        if a.cmd == "show":
            return do_show(data, a.key)
        if a.cmd == "selftest":
            return do_selftest(data)
        if a.glob:
            GLOBAL.mkdir(parents=True, exist_ok=True)
            print(f"전역 적용 → {GLOBAL}/  (모든 프로젝트에 자동으로 읽힙니다)\n")
            return do_apply(data, a.targets, GLOBAL, execute=a.yes)
        return do_apply(data, a.targets, Path(a.dir).resolve(), execute=a.yes)
    except KeyError as k:
        print(f"모르는 키: {k}\n있는 것: {', '.join(data['recipes'])}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
