# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""stackpack — stack.yaml 하나에서 허브 페이지 / 설치기 / 스킬을 뽑아냅니다.

    uv run build.py html                 허브 페이지(index.html) 생성
    uv run build.py stars                깃허브 별점 수집 → stars.json
    uv run build.py install content-factory       설치 명령 미리보기 (실행 안 함)
    uv run build.py install content-factory --yes 실제 설치 실행
    uv run build.py skill                Claude Code 스킬 생성
    uv run build.py selftest             데이터 정합성 + 안전장치 검사

stack.yaml은 절대 덮어쓰지 않습니다. 자동 수집 데이터는 stars.json에만 씁니다.
"""

import argparse
import html
import json
import os
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
STACK = ROOT / "stack.yaml"
STARS = ROOT / "stars.json"


def load():
    return yaml.safe_load(STACK.read_text(encoding="utf-8"))


def load_stars():
    return json.loads(STARS.read_text(encoding="utf-8")) if STARS.exists() else {}


def fmt_stars(n):
    if not n:
        return ""
    return f"{n // 1000}K+" if n >= 1000 else str(n)


# ─── 설치 ────────────────────────────────────────────────────────────────────

def resolve(data, key):
    """키 하나 → 도구 키 목록. 도구면 자기 자신, 콤보면 멤버들, all이면 전부."""
    if key == "all":
        return list(data["tools"])
    if key in data["tools"]:
        return [key]
    if key in data["combos"]:
        return list(data["combos"][key]["tools"])
    raise KeyError(key)


def commands_for(data, keys):
    """도구 키 목록 → 실행할 명령 줄 목록. 중복 줄은 순서를 지키며 한 번만."""
    out, seen = [], set()
    for k in keys:
        for line in (data["tools"][k].get("install") or "").splitlines():
            line = line.strip()
            if line and line not in seen:
                seen.add(line)
                out.append(line)
    return out


def _powershell(cmd):
    return subprocess.run(
        ["powershell", "-NoProfile", "-Command", cmd], check=False
    ).returncode


def do_install(data, targets, execute=False, runner=_powershell):
    """execute=False면 runner를 절대 호출하지 않습니다. selftest가 이걸 검증합니다."""
    tool_keys = []
    for t in targets:
        for k in resolve(data, t):
            if k not in tool_keys:
                tool_keys.append(k)

    cmds = commands_for(data, tool_keys)
    label = ", ".join(data["tools"][k]["name"] for k in tool_keys)
    print(f"대상 {len(tool_keys)}개: {label}\n")

    if not execute:
        print("[미리보기] 아래 명령이 순서대로 실행됩니다. 실제 실행은 --yes 를 붙이세요.\n")
        for c in cmds:
            print(f"  {c}")
        return 0

    print(f"[실행] PowerShell로 {len(cmds)}개 명령을 실행합니다.\n")
    failed = []
    for i, c in enumerate(cmds, 1):
        print(f"  ({i}/{len(cmds)}) {c}")
        if runner(c) != 0:
            failed.append(c)
            print("      ↑ 실패 — 계속 진행합니다.")
    if failed:
        print(f"\n{len(failed)}개 실패:")
        for c in failed:
            print(f"  {c}")
        return 1
    print("\n전부 성공했습니다.")
    return 0


# ─── 별점 ────────────────────────────────────────────────────────────────────

def _fetch_one(repo):
    headers = {"User-Agent": "stackpack"}
    if token := os.environ.get("GITHUB_TOKEN"):  # CI에선 익명 요청이 자주 403 납니다
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}", headers=headers)
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read())["stargazers_count"]


def do_stars(data):
    previous = load_stars()  # 실패 시 되돌릴 값 — 루프 밖에서 한 번만 읽습니다
    targets = [(k, t) for k, t in data["tools"].items() if t.get("repo")]
    stars = {"_fetched": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    with ThreadPoolExecutor(max_workers=8) as pool:
        fetched = list(pool.map(lambda kt: _safe(kt[1]["repo"]), targets))

    for (key, t), (n, err) in zip(targets, fetched):
        if n is not None:
            stars[key] = n
            print(f"  {t['name']:<16} {n:>8,}")
        else:
            if key in previous:  # 레이트리밋·오프라인 — 이전 값을 유지합니다
                stars[key] = previous[key]
            print(f"  {t['name']:<16} {'실패':>8}  ({err})")

    STARS.write_text(json.dumps(stars, indent=2), encoding="utf-8")
    print(f"\n→ {STARS.name}  ({len(stars) - 1}/{len(targets)})")
    return 0


def _safe(repo):
    try:
        return _fetch_one(repo), None
    except Exception as e:
        return None, type(e).__name__


# ─── 허브 페이지 ─────────────────────────────────────────────────────────────

CSS = """
:root{--bg:#0A0A0F;--panel:rgba(20,20,25,.7);--cyan:#00FFCC;--magenta:#FF00FF;
--lime:#39FF14;--amber:#FFA500;--text:#E0E0E0;--dim:#888899;--line:rgba(255,255,255,.1)}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:'Pretendard','Malgun Gothic',sans-serif;
margin:0;padding:40px 24px;background-image:radial-gradient(circle at 50% 0%,rgba(0,255,204,.1),transparent 50%)}
.wrap{max-width:1100px;margin:0 auto}
h1{text-align:center;font-size:2.6em;color:#fff;text-shadow:0 0 12px var(--cyan);letter-spacing:2px;margin:0 0 6px}
.sub{text-align:center;color:var(--dim);margin-bottom:8px}
.stamp{text-align:center;color:var(--dim);font-size:.8em;font-family:monospace;margin-bottom:50px}
h2{border-bottom:1px dashed var(--dim);padding-bottom:10px;margin:60px 0 28px;color:var(--cyan);
font-weight:400;letter-spacing:1px;text-transform:uppercase;font-size:1.15em}
.combo{background:linear-gradient(135deg,rgba(20,20,30,.8),rgba(10,10,15,.9));border:1px solid var(--line);
border-left:4px solid var(--magenta);padding:24px;margin-bottom:18px;border-radius:8px;transition:.25s}
.combo:hover{border-left-color:var(--cyan);box-shadow:0 0 30px rgba(0,255,204,.15)}
.combo h3{margin:0 0 4px;font-size:1.25em;font-weight:600}
.role{font-size:.75em;background:var(--magenta);padding:3px 8px;border-radius:3px;color:#fff}
.diff{font-size:.75em;border:1px solid var(--dim);padding:2px 8px;border-radius:3px;color:var(--dim);margin-left:6px}
.chain{font-family:monospace;color:var(--cyan);margin:16px 0;padding:14px;background:rgba(0,0,0,.5);
border-radius:6px;border:1px dashed var(--line);text-align:center;text-shadow:0 0 5px var(--cyan)}
.combo p{color:#bbb;line-height:1.7;margin:12px 0}
pre{background:#000;padding:14px;border-radius:6px;border-left:3px solid var(--lime);color:var(--lime);
font-family:'Consolas',monospace;font-size:.85em;overflow-x:auto;margin:10px 0;white-space:pre-wrap;
word-break:break-all;cursor:pointer;user-select:all}
pre:hover{background:#050505}
.hint{color:var(--dim);font-size:.8em;margin:6px 0 0}
.hint code{font-size:1.05em;color:var(--cyan);background:rgba(0,255,204,.08);
border:1px solid rgba(0,255,204,.2);padding:2px 7px;border-radius:3px}
.saves span{font-size:.75em;color:var(--lime);border:1px solid rgba(57,255,20,.3);padding:2px 8px;
border-radius:10px;margin-right:6px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:18px}
.tier{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px;
backdrop-filter:blur(10px);position:relative;overflow:hidden}
.tier::before{content:'';position:absolute;top:0;left:0;width:100%;height:2px;background:var(--tc);box-shadow:0 0 15px var(--tc)}
.tier h3{margin:0 0 6px;font-size:1.2em;color:var(--tc);font-weight:500}
.tier .d{color:var(--dim);font-size:.85em;margin-bottom:16px}
.chip{display:inline-block;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.2);
padding:5px 11px;border-radius:4px;margin:4px 4px 0 0;font-size:.85em;cursor:pointer;transition:.15s}
.chip:hover{background:var(--cyan);color:#000;border-color:var(--cyan);box-shadow:0 0 8px var(--cyan)}
.chip b{font-weight:400;color:var(--dim);font-size:.85em;margin-left:5px}
.chip:hover b{color:#044}
.step{display:flex;gap:16px;align-items:flex-start;padding:14px 0;border-bottom:1px solid var(--line)}
.step .n{flex:0 0 42px;height:42px;border-radius:50%;background:rgba(0,255,204,.1);border:1px solid var(--cyan);
display:flex;align-items:center;justify-content:center;color:var(--cyan);font-family:monospace}
.step .t{font-weight:600}
.step .m{color:var(--dim);font-size:.85em;margin-top:2px}
.step .c{margin-top:6px}
.step .c a{color:var(--magenta);text-decoration:none;font-size:.8em;margin-right:10px}
.step .c a:hover{text-decoration:underline}
#modal{display:none;position:fixed;inset:0;z-index:100;background:rgba(0,0,0,.85);backdrop-filter:blur(5px);padding:20px;overflow-y:auto}
.mbox{background:#111116;margin:6vh auto;padding:30px;border:1px solid var(--cyan);max-width:640px;
border-radius:8px;box-shadow:0 0 40px rgba(0,255,204,.25);position:relative}
.close{position:absolute;top:14px;right:20px;color:#aaa;font-size:28px;cursor:pointer;line-height:1}
.close:hover{color:var(--magenta)}
.mbox h2{border:0;margin:0 0 2px;padding:0;color:var(--cyan);font-size:1.6em;text-transform:none}
.mbox .tl{color:#ccc;margin:0 0 14px}
.lb{color:var(--dim);font-size:.75em;letter-spacing:1px;margin:18px 0 4px}
.mbox .lb{color:var(--magenta)}
.mtxt{line-height:1.7;color:#bbb}
.mbox a{color:var(--dim);font-size:.85em}
footer{text-align:center;color:var(--dim);font-size:.8em;margin-top:70px;line-height:1.8}
"""

JS = """
const T=%(tools)s;
function show(k){const t=T[k];if(!t)return;
 document.getElementById('mName').textContent=t.name;
 document.getElementById('mTag').textContent=t.tagline;
 document.getElementById('mWhat').textContent=t.what;
 document.getElementById('mWhy').textContent=t.why;
 document.getElementById('mInstall').textContent=t.install||'(설치 불필요)';
 document.getElementById('mRun').textContent=t.run||'-';
 const g=document.getElementById('mGit');
 if(t.repo){g.href='https://github.com/'+t.repo;g.textContent='github.com/'+t.repo+(t.stars?'  ★ '+t.stars:'');g.style.display='';}
 else g.style.display='none';
 document.getElementById('modal').style.display='block';}
function hide(){document.getElementById('modal').style.display='none';}
onclick=e=>{if(e.target.id==='modal')hide();
 if(e.target.tagName==='PRE'){navigator.clipboard?.writeText(e.target.textContent);
  const o=e.target.style.borderLeftColor;e.target.style.borderLeftColor='#FF00FF';
  setTimeout(()=>e.target.style.borderLeftColor=o,300);}};
onkeydown=e=>{if(e.key==='Escape')hide();};
"""


def do_html(data):
    stars = load_stars()
    tools, combos, tiers = data["tools"], data["combos"], data["tiers"]
    e = html.escape

    # 콤보: 설치 명령은 멤버 도구에서 파생 — 여기에 손으로 적는 곳은 없습니다.
    combo_html = ""
    for key, c in combos.items():
        chain = " ➔ ".join(tools[t]["name"] for t in c["tools"])
        install = "\n".join(commands_for(data, c["tools"]))
        saves = "".join(f"<span>{e(s)}</span>" for s in c.get("saves", []))
        combo_html += f"""
    <div class="combo" id="{e(key)}">
      <h3>{e(c['name'])}</h3>
      <span class="role">{e(c.get('role',''))}</span><span class="diff">{e(c.get('difficulty',''))}</span>
      <div class="chain">{e(chain)}</div>
      <p>{e(c['desc'])}</p>
      <div class="lb">설치 (클릭하면 복사)</div>
      <pre>{e(install)}</pre>
      <div class="lb">실행</div>
      <pre>{e(c.get('run',''))}</pre>
      <p class="hint">또는 한 줄로: <code>uv run build.py install {e(key)} --yes</code></p>
      <p class="hint">AI 프롬프트: {e(c.get('prompt',''))}</p>
      <div class="saves" style="margin-top:12px">{saves}</div>
    </div>"""

    tier_html = ""
    for tk, tier in tiers.items():
        chips = ""
        for k, t in tools.items():
            if t.get("tier") != tk:
                continue
            s = fmt_stars(stars.get(k))
            chips += f'<span class="chip" onclick="show(\'{e(k)}\')">{t.get("icon","")} {e(t["name"])}{f"<b>★{s}</b>" if s else ""}</span>'
        tier_html += f"""
      <div class="tier" style="--tc:{tier['color']}">
        <h3>{e(tier['name'])}</h3><div class="d">{e(tier['desc'])}</div><div>{chips}</div>
      </div>"""

    guide_html = ""
    for g in data["guide"]:
        links = "".join(
            f"<a href='#{e(c)}'>{e(combos[c]['name'])}</a>" for c in g.get("combos", [])
        )
        guide_html += f"""
      <div class="step"><div class="n">{g['step']}</div><div>
        <div class="t">{e(g['icon'])} {e(g['phase'])} <span class="diff">{e(g['duration'])}</span></div>
        <div class="m">{e(g['desc'])}</div><div class="c">{links}</div>
      </div></div>"""

    js_tools = {
        k: {
            "name": t["name"], "tagline": t.get("tagline", ""), "what": t.get("what", ""),
            "why": t.get("why", ""), "install": (t.get("install") or "").strip(),
            "run": t.get("run", ""), "repo": t.get("repo"), "stars": fmt_stars(stars.get(k)),
        }
        for k, t in tools.items()
    }
    fetched = stars.get("_fetched")
    stamp = f"★ 깃허브 별점 {fetched[:10]} 기준" if fetched else "별점 미수집 — uv run build.py stars"

    page = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(data['meta']['title'])} — {e(data['meta']['subtitle'])}</title><style>{CSS}</style></head><body><div class="wrap">
<h1>{e(data['meta']['title'])}</h1>
<div class="sub">{e(data['meta']['subtitle'])} · 도구 {len(tools)}개 · 콤보 {len(combos)}개</div>
<div class="stamp">{e(stamp)}</div>

<h2>1. 콤보 — 조합 하나 = 업무 하나</h2>{combo_html}

<h2>2. 아키텍처 — 도구를 클릭하면 설치법이 나옵니다</h2>
<div class="grid">{tier_html}</div>

<h2>3. 창업 단계별 도입 순서</h2>{guide_html}

<div id="modal"><div class="mbox"><span class="close" onclick="hide()">&times;</span>
  <h2 id="mName"></h2><p class="tl" id="mTag"></p>
  <div class="lb">무엇인가</div><p class="mtxt" id="mWhat"></p>
  <div class="lb">왜 쓰는가</div><p class="mtxt" id="mWhy"></p>
  <div class="lb">설치 (클릭하면 복사)</div><pre id="mInstall"></pre>
  <div class="lb">실행</div><pre id="mRun"></pre>
  <p style="margin-top:16px"><a id="mGit" target="_blank" rel="noopener"></a></p>
</div></div>

<footer>stack.yaml에서 자동 생성됨 · 도구를 추가하려면 stack.yaml만 고치세요<br>
uv run build.py html | stars | install &lt;키&gt; [--yes] | skill</footer>
</div><script>{JS % {'tools': json.dumps(js_tools, ensure_ascii=False)}}</script></body></html>"""

    out = ROOT / "index.html"
    out.write_text(page, encoding="utf-8")
    print(f"→ {out.name}  (도구 {len(tools)}, 콤보 {len(combos)}, 별점 {'있음' if stars else '없음'})")
    return 0


# ─── Claude Code 스킬 ────────────────────────────────────────────────────────

def do_skill(data, install=False):
    tools, combos = data["tools"], data["combos"]
    rows = "\n".join(
        f"| `{k}` | {c['name']} | {' + '.join(tools[t]['name'] for t in c['tools'])} | {c['desc'].strip().splitlines()[0]} |"
        for k, c in combos.items()
    )
    tool_rows = "\n".join(
        f"| `{k}` | {t['name']} | {t.get('tagline','')} | {t.get('difficulty','')} |"
        for k, t in tools.items()
    )
    body = f"""---
name: stackpack
description: 1인 창업 AI 자동화 스택 카탈로그. 어떤 오픈소스 도구를 깔지, 어떤 조합으로 업무를 자동화할지 물을 때 사용. 설치까지 직접 실행할 수 있음. 트리거 - "무슨 툴 깔지", "자동화하고 싶은데", "콘텐츠 자동 생성", "경쟁사 조사 자동화", "로컬 AI", "회계 자동화", "터미널 세팅".
---

# stackpack

도구 {len(tools)}개, 검증된 조합 {len(combos)}개. 원본 데이터는 `{STACK}`.

## 설치 실행 방법

```
uv run {ROOT / 'build.py'} install <키>        # 미리보기 (실행 안 함)
uv run {ROOT / 'build.py'} install <키> --yes  # 실제 설치
```

키는 아래 표의 콤보 키 또는 도구 키. `all`도 됩니다.
**항상 미리보기를 먼저 보여주고 사용자 확인을 받은 뒤 `--yes`를 붙이세요.**
콤보 설치 명령은 멤버 도구에서 자동으로 합쳐지므로 직접 조합하지 마세요.

## 콤보 — 목적에서 시작하기

| 키 | 이름 | 구성 | 하는 일 |
|---|---|---|---|
{rows}

## 도구

| 키 | 이름 | 한 줄 설명 | 난이도 |
|---|---|---|---|
{tool_rows}

## 규칙

- 사용자가 목적("영상 만들고 싶어")을 말하면 도구가 아니라 **콤보**를 먼저 제안하세요.
- 도구를 추가·수정할 일이 생기면 `stack.yaml`만 고치고 `build.py html`을 다시 돌리세요.
  HTML이나 이 스킬 파일을 직접 고치면 다음 빌드에 덮어써집니다.
- 별점이 오래됐으면 `uv run {ROOT / 'build.py'} stars`.
"""
    out = ROOT / "skill" / "SKILL.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(body, encoding="utf-8")
    print(f"→ {out.relative_to(ROOT)}")

    if install:
        dest = Path.home() / ".claude" / "skills" / "stackpack" / "SKILL.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body, encoding="utf-8")
        print(f"→ {dest}  (Claude Code 재시작 후 사용 가능)")
    else:
        print("   ~/.claude/skills/ 에 설치하려면: --install")
    return 0


# ─── 자체 검사 ───────────────────────────────────────────────────────────────

def do_selftest(data):
    tools, combos = data["tools"], data["combos"]

    # 1. 참조 무결성 — v9에서 도구가 조용히 사라졌던 사고를 여기서 잡습니다
    for ck, c in combos.items():
        for t in c["tools"]:
            assert t in tools, f"콤보 {ck} → 없는 도구 '{t}'"
    for g in data["guide"]:
        for c in g.get("combos", []):
            assert c in combos, f"가이드 {g['step']}단계 → 없는 콤보 '{c}'"
    for k, t in tools.items():
        assert t.get("tier") in data["tiers"], f"도구 {k} → 없는 티어 '{t.get('tier')}'"

    # 2. 중복 제거가 순서를 지키는지
    cmds = commands_for(data, ["playwright", "browser-use"])
    assert len(cmds) == len(set(cmds)), f"중복 명령이 남았습니다: {cmds}"
    assert cmds[0].startswith("winget install astral-sh.uv"), cmds

    # 3. 미리보기는 어떤 경우에도 명령을 실행하지 않는다
    def boom(cmd):
        raise AssertionError(f"미리보기 모드인데 실행됐습니다: {cmd}")

    do_install(data, ["all"], execute=False, runner=boom)

    # 4. --yes일 때는 실제로 runner를 부른다
    called = []
    do_install(data, ["fzf"], execute=True, runner=lambda c: called.append(c) or 0)
    assert called == ["winget install junegunn.fzf"], called

    print(f"\n통과: 도구 {len(tools)}, 콤보 {len(combos)}, 가이드 {len(data['guide'])}단계")
    return 0


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("html", help="허브 페이지 생성")
    sub.add_parser("stars", help="깃허브 별점 수집")
    sub.add_parser("selftest", help="데이터 정합성 + 안전장치 검사")
    pi = sub.add_parser("install", help="도구·콤보 설치")
    pi.add_argument("targets", nargs="+", help="콤보 키 / 도구 키 / all")
    pi.add_argument("--yes", action="store_true", help="실제로 실행 (없으면 미리보기)")
    ps = sub.add_parser("skill", help="Claude Code 스킬 생성")
    ps.add_argument("--install", action="store_true", help="~/.claude/skills/ 에 설치")
    a = p.parse_args()

    data = load()
    if a.cmd == "html":
        return do_html(data)
    if a.cmd == "stars":
        return do_stars(data)
    if a.cmd == "selftest":
        return do_selftest(data)
    if a.cmd == "skill":
        return do_skill(data, a.install)
    try:
        return do_install(data, a.targets, execute=a.yes)
    except KeyError as k:
        print(f"모르는 키: {k}\n콤보: {', '.join(data['combos'])}\n도구: {', '.join(data['tools'])}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
