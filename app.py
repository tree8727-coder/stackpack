# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""app.py — 터미널 없이 열 수 있는 진단 페이지(app.html)를 만듭니다.

    uv run app.py            app.html 생성
    uv run app.py --check    만들지 않고 데이터만 검사

허브 페이지(index.html)는 31개를 **다 보여줍니다**. 이 페이지는 반대로
세 번 눌러서 **안 깔아도 되는 27개를 걷어냅니다.** 인스타에서 오는 사람은
PowerShell을 안 열기 때문에, 결제 앞단에 터미널이 필요 없는 접점이 하나 필요합니다.

설치 명령은 여기서 다시 만들지 않습니다. `build.commands_for` 를 그대로 씁니다 —
중복 제거 규칙이 두 벌이 되는 순간 둘이 갈라집니다.
"""

import argparse
import html
import json
import sys
from pathlib import Path

import build

ROOT = Path(__file__).parent
OUT = ROOT / "app.html"
CREDITS = ROOT / "출처.md"
BUY = ROOT / "buy.html"
SELL = ROOT / "sell.yaml"

# sell.yaml 에 반드시 있어야 하는 것들. 하나라도 비면 buy.html 을 만들지 않습니다 —
# 결제 수단이 반쯤 빈 페이지가 배포되는 게 제일 나쁩니다.
SELL_KEYS = ("kakaopay", "account", "kakao_openchat", "seller", "price", "checked")

# 송금 링크가 살아 있는지는 **기계로 확인할 수 없습니다.**
# 만료돼도 같은 리다이렉트 껍데기에 HTTP 200 이 옵니다 — 여기서 「링크 살아있나」
# 검사기를 만들면 항상 통과하는 가짜 검사가 됩니다(E10 과 같은 병).
# 그래서 사람이 직접 확인한 날짜를 적게 하고, 오래되면 페이지를 만들지 않습니다.
# 모델 가격표가 90일 지나면 selftest 가 일부러 실패하는 것과 같은 장치입니다.
CHECK_MAX_DAYS = 14

# 저장소가 없는 도구. 웹 서비스라 원래 없는 것만 여기 적습니다.
# 새 도구를 repo 없이 넣으면 여기 적기 전까지 검사가 막습니다 —
# 출처 없는 도구가 조용히 목록에 끼는 것을 막는 게 목적입니다.
NO_REPO_OK = {"notebooklm": "구글 서비스 — 공개 저장소가 없습니다"}


def collect(data):
    """콤보마다 도구·명령·절감항목을 미리 계산해 브라우저로 넘길 형태로 만듭니다."""
    combos = []
    for key, c in data["combos"].items():
        tool_keys = build.resolve(data, key)
        combos.append({
            "key": key,
            "name": c["name"],
            "role": c.get("role", "기타"),
            "difficulty": c.get("difficulty", "중급"),
            "desc": c.get("desc", ""),
            "saves": c.get("saves", []),
            "tools": [
                {
                    "key": k,
                    "name": data["tools"][k]["name"],
                    "tagline": data["tools"][k].get("tagline", ""),
                    # 만든 사람에게 가는 길. 이게 없으면 안내판이 아니라 렉카가 된다.
                    "repo": data["tools"][k].get("repo"),
                }
                for k in tool_keys
            ],
            "commands": build.commands_for(data, tool_keys),
        })
    return combos


def verify(data, combos):
    """조용히 비어 나가는 것을 막습니다. 하나라도 어긋나면 페이지를 만들지 않습니다."""
    problems = []

    if len(combos) != len(data["combos"]):
        problems.append(f"콤보 수가 다릅니다: {len(combos)} vs {len(data['combos'])}")

    for c in combos:
        if not c["tools"]:
            problems.append(f"[{c['key']}] 도구가 하나도 없습니다")
        if not c["commands"]:
            problems.append(f"[{c['key']}] 설치 명령이 비었습니다")
        for cmd in c["commands"]:
            if not cmd.strip():
                problems.append(f"[{c['key']}] 빈 명령 줄이 있습니다")

    roles = {c["role"] for c in combos}
    if len(roles) < 2:
        problems.append("역할이 하나뿐입니다 — 첫 질문이 무의미해집니다")

    diffs = {c["difficulty"] for c in combos}
    unknown = diffs - {"초급", "중급", "고급"}
    if unknown:
        problems.append(f"모르는 난이도: {sorted(unknown)}")

    for r in sorted(roles):
        if not [c for c in combos if c["role"] == r]:
            problems.append(f"역할 '{r}'에 콤보가 없습니다")

    # 출처 없는 도구가 목록에 끼면 막습니다. 만든 사람에게 가는 길이 없는 채로
    # 돈을 받는 게 반발의 진짜 원인이라, 이건 문구가 아니라 검사로 지킵니다.
    for k, v in data["tools"].items():
        if not v.get("repo") and k not in NO_REPO_OK:
            problems.append(
                f"[{k}] 원 저장소(repo)가 없습니다. "
                f"저장소를 적거나, 없는 이유를 app.py의 NO_REPO_OK에 적어 주세요"
            )

    return problems


def load_sell():
    """sell.yaml 을 읽고 검사합니다. (설정, 문제목록) 을 돌려줍니다.

    없으면 (None, []) — 아직 팔 준비가 안 된 것이지 잘못된 게 아닙니다.
    있는데 어딘가 비면 (None, 문제들) — 이때는 만들지 않습니다.
    """
    if not SELL.exists():
        return None, []

    import yaml
    cfg = yaml.safe_load(SELL.read_text(encoding="utf-8")) or {}
    problems = []

    for k in SELL_KEYS:
        v = cfg.get(k)
        if v is None or (isinstance(v, str) and not v.strip()):
            problems.append(f"sell.yaml 에 '{k}' 가 비었습니다")

    for k in ("kakaopay", "kakao_openchat"):
        v = str(cfg.get(k, ""))
        if v and not v.startswith("https://"):
            problems.append(f"sell.yaml 의 '{k}' 가 https:// 로 시작하지 않습니다")
        if "여기에" in v or "본인" in v:
            problems.append(f"sell.yaml 의 '{k}' 가 예시값 그대로입니다")

    if "여기에" in str(cfg.get("account", "")) or "○○" in str(cfg.get("account", "")):
        problems.append("sell.yaml 의 'account' 가 예시값 그대로입니다")

    price = cfg.get("price")
    if not isinstance(price, int) or price <= 0:
        problems.append("sell.yaml 의 'price' 는 0보다 큰 정수여야 합니다")

    # 링크를 사람이 마지막으로 열어 본 날.
    checked = cfg.get("checked")
    if checked is not None:
        from datetime import date, datetime
        if isinstance(checked, str):
            try:
                checked = datetime.strptime(checked.strip(), "%Y-%m-%d").date()
            except ValueError:
                problems.append("sell.yaml 의 'checked' 는 YYYY-MM-DD 여야 합니다")
                checked = None
        elif isinstance(checked, datetime):
            checked = checked.date()
        elif not isinstance(checked, date):
            problems.append("sell.yaml 의 'checked' 를 날짜로 읽지 못했습니다")
            checked = None

        if checked is not None:
            today = date.today()
            if checked > today:
                problems.append(f"sell.yaml 의 'checked'({checked}) 가 미래입니다")
            else:
                age = (today - checked).days
                if age > CHECK_MAX_DAYS:
                    problems.append(
                        f"송금 링크를 확인한 지 {age}일 됐습니다 (기준 {CHECK_MAX_DAYS}일). "
                        f"링크를 직접 열어 금액이 뜨는지 보고 'checked' 를 오늘로 고치세요 — "
                        f"만료된 링크는 열어봐야만 알 수 있습니다"
                    )
                else:
                    cfg["_checked_age"] = age

    return (None, problems) if problems else (cfg, [])


def write_credits(data) -> str:
    """31개 전부의 출처를 한 파일로. 유료 zip에도 같이 들어갑니다."""
    lines = [
        "# 출처",
        "",
        "스택팩이 소개하는 도구는 **전부 남이 만든 것이고, 전부 무료**입니다.",
        "우리가 만든 것이 아니고, 우리는 이 도구들로부터 한 푼도 받지 않습니다.",
        "",
        "각 도구의 라이선스는 해당 저장소를 따릅니다. 쓰기 전에 한 번 보세요.",
        "쓸 만했다면 저장소에 별을 눌러주는 게 만든 사람에게 가는 유일한 값입니다.",
        "",
        "| 도구 | 하는 일 | 만든 곳 |",
        "|---|---|---|",
    ]
    for k, v in data["tools"].items():
        repo = v.get("repo")
        where = f"[{repo}](https://github.com/{repo})" if repo else NO_REPO_OK.get(k, "—")
        lines.append(f"| {v['name']} | {v.get('tagline','')} | {where} |")

    lines += [
        "",
        "---",
        "",
        "## 그럼 스택팩은 무엇에 값을 매기나",
        "",
        "**위 목록에는 값을 매기지 않습니다.** `stack.yaml`은 공개돼 있고,",
        "허브 페이지와 진단 페이지에서 누구나 무료로 봅니다.",
        "이 zip 안에 든 `stack.yaml`도 그 공개본과 같은 파일입니다.",
        "",
        "값을 매기는 건 우리가 쓴 것뿐입니다.",
        "",
        "- `build.py` — 내 PC에 뭐가 깔렸는지 대조하고, 미리보기를 기본값으로 두고,",
        "  콤보 설치 명령을 그때그때 만들어 내고, 스스로를 검사합니다",
        "- `install.ps1` — 처음 여는 사람이 두 번 클릭으로 여기까지 오게 합니다",
        "- `connectors/`, `examples/` — 결과물을 실제 서비스로 흘려보내는 부분",
        "- 그리고 막혔을 때 답하는 사람",
        "",
        "도구 목록이 아니라 **그 목록을 내 PC에서 돌아가게 만드는 부분**을 파는 겁니다.",
        "",
        f"*이 파일은 `stack.yaml`에서 자동으로 만들어집니다 — 도구 {len(data['tools'])}개. 손으로 고치지 마세요.*",
        "",
    ]
    text = "\n".join(lines)
    CREDITS.write_text(text, encoding="utf-8")
    return text


RANK = {"초급": 1, "중급": 2, "고급": 3}


def fallback_cases(combos):
    """빈 화면이 나오는 조합을 세어 돌려줍니다.

    브라우저는 결과가 0개면 그 역할의 제일 쉬운 묶음 하나를 대신 보여줍니다.
    그 분기가 실제로 쓰이는 조합이 몇 개인지 눈에 보여야, 데이터가 바뀌어
    분기가 죽거나 반대로 절반이 대체 결과가 되는 걸 알아챕니다.
    """
    cases = []
    for r in sorted({c["role"] for c in combos}):
        same = [c for c in combos if c["role"] == r]
        for ceiling in (1, 2, 3):
            if not [c for c in same if RANK.get(c["difficulty"], 9) <= ceiling]:
                cases.append((r, ceiling))
    return cases


PAGE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>내 스택 진단 — stackpack</title>
<meta name="description" content="세 번 눌러서 31개 중 나에게 필요한 것만 남깁니다. 설치 명령까지 무료입니다.">
<style>
:root{
  --bg:#F1F2F0;--card:#fff;--rule:#D0D4CF;--rule-soft:#E4E7E3;
  --ink:#14171A;--ink2:#414A4C;--muted:#6C7673;--accent:#0D6466;--accent-soft:#DCEAE9;
  --term:#10171C;--term-ink:#C9D6DE;--term-ok:#5FD1A0;
  --sans:'Pretendard Variable',Pretendard,'Apple SD Gothic Neo',system-ui,-apple-system,'Segoe UI',sans-serif;
  --mono:ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:dark){:root{
  --bg:#0B0E0F;--card:#14181A;--rule:#293030;--rule-soft:#1E2324;
  --ink:#E9EDEB;--ink2:#B3BDBA;--muted:#828C89;--accent:#5FBDBD;--accent-soft:#12302F;
  --term:#080C0F;
}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
  font-size:16px;line-height:1.65;-webkit-font-smoothing:antialiased;word-break:keep-all}
.wrap{max-width:46rem;margin:0 auto;padding:3rem 1.25rem 5rem}
.kicker{font-family:var(--mono);font-size:.7rem;letter-spacing:.15em;text-transform:uppercase;color:var(--muted);margin:0}
h1{font-size:clamp(1.9rem,5vw,2.7rem);line-height:1.1;letter-spacing:-.035em;font-weight:800;margin:.5rem 0 0;text-wrap:balance}
.lede{margin-top:.9rem;color:var(--ink2);max-width:32rem}
.step{margin-top:2.5rem;background:var(--card);border:1px solid var(--rule);padding:1.3rem 1.4rem 1.4rem}
.step h2{margin:0 0 .2rem;font-size:1.05rem;font-weight:800;letter-spacing:-.02em}
.step .q{font-family:var(--mono);font-size:.66rem;letter-spacing:.13em;text-transform:uppercase;color:var(--muted)}
.opts{margin-top:1rem;display:grid;grid-template-columns:repeat(auto-fit,minmax(11rem,1fr));gap:.6rem}
button.opt{font:inherit;text-align:left;cursor:pointer;background:var(--bg);color:var(--ink);
  border:1px solid var(--rule);padding:.7rem .85rem;border-radius:3px;transition:none}
button.opt:hover{border-color:var(--accent)}
button.opt[aria-pressed="true"]{background:var(--accent-soft);border-color:var(--accent);color:var(--accent);font-weight:700}
button.opt:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
button.opt .sub{display:block;font-size:.78rem;color:var(--muted);font-weight:400;margin-top:.1rem}
button.opt[aria-pressed="true"] .sub{color:var(--accent)}
#result{margin-top:2.5rem}
.hit{background:var(--card);border:1px solid var(--rule);border-left:3px solid var(--accent);padding:1.3rem 1.4rem 1.4rem;margin-bottom:1rem}
.hit h3{margin:0;font-size:1.15rem;letter-spacing:-.025em}
.hit .meta{font-family:var(--mono);font-size:.68rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-top:.3rem}
.hit p.desc{margin:.7rem 0 0;font-size:.92rem;color:var(--ink2)}
ul.tools{list-style:none;margin:.9rem 0 0;padding:0;display:flex;flex-direction:column;gap:.35rem}
ul.tools li{font-size:.9rem}
ul.tools b{font-weight:700}
ul.tools span{color:var(--muted)}
ul.tools a.src{font-family:var(--mono);font-size:.76rem;color:var(--accent);text-decoration:none;
  border-bottom:1px solid var(--accent-soft);white-space:nowrap}
ul.tools a.src:hover{border-bottom-color:var(--accent)}
ul.tools a.src:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.credit{margin-top:1.6rem;background:var(--card);border:1px solid var(--rule);padding:1rem 1.2rem;font-size:.9rem;color:var(--ink2)}
.credit b{color:var(--ink)}
.cmds{margin-top:1rem;background:var(--term);border-radius:4px;overflow:hidden}
.cmds-bar{display:flex;align-items:center;gap:.6rem;padding:.5rem .8rem;border-bottom:1px solid rgba(255,255,255,.08);
  font-family:var(--mono);font-size:.66rem;color:#64798A;letter-spacing:.08em}
.cmds pre{margin:0;padding:.85rem 1rem;overflow-x:auto;font-family:var(--mono);font-size:.79rem;line-height:1.9;color:var(--term-ink)}
button.copy{margin-left:auto;font:inherit;font-family:var(--mono);font-size:.66rem;letter-spacing:.08em;
  cursor:pointer;background:transparent;border:1px solid #33414B;color:#8FA3B0;padding:.15rem .5rem;border-radius:2px}
button.copy:hover{border-color:var(--term-ok);color:var(--term-ok)}
button.copy:focus-visible{outline:2px solid var(--term-ok);outline-offset:2px}
.cut{margin-top:1.6rem;background:var(--accent-soft);border-left:3px solid var(--accent);padding:1rem 1.2rem;font-size:.93rem;color:var(--ink2)}
.cut b{color:var(--ink)}
.foot{margin-top:2.5rem;padding-top:1.2rem;border-top:1px solid var(--rule);font-size:.83rem;color:var(--muted);
  display:flex;flex-direction:column;gap:.35rem}
.foot a{color:var(--accent)}
.hidden{display:none}
</style>
</head>
<body>
<div class="wrap">
  <p class="kicker">stackpack · 무료</p>
  <h1>31개를 다 깔 필요는 없다.</h1>
  <p class="lede">세 번 누르면 지금 당신에게 필요한 것만 남습니다.
    설치 명령까지 그대로 드립니다. 가입도 이메일도 없습니다.</p>

  <div class="step">
    <span class="q">질문 1</span>
    <h2>무엇을 하려고 하시나요?</h2>
    <div class="opts" id="q1"></div>
  </div>

  <div class="step">
    <span class="q">질문 2</span>
    <h2>터미널은 얼마나 편하신가요?</h2>
    <div class="opts" id="q2"></div>
  </div>

  <div id="result" class="hidden"></div>

  <div class="foot">
    <span>도구 __NTOOLS__개 · 콤보 __NCOMBOS__개 전부 보기 → <a href="./">허브 페이지</a></span>
    <span>이 페이지는 <code>stack.yaml</code> 하나에서 만들어집니다. 손으로 고친 곳이 없습니다.</span>
  </div>
</div>

<script>
const COMBOS = __DATA__;
const state = {role:null, ceiling:null};
const RANK = {"초급":1, "중급":2, "고급":3};

function h(s){return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

function makeBtn(label, sub, onClick){
  const b = document.createElement('button');
  b.className = 'opt'; b.type = 'button'; b.setAttribute('aria-pressed','false');
  b.innerHTML = h(label) + (sub ? '<span class="sub">' + h(sub) + '</span>' : '');
  b.addEventListener('click', () => {
    [...b.parentElement.children].forEach(x => x.setAttribute('aria-pressed','false'));
    b.setAttribute('aria-pressed','true');
    onClick();
    render();
  });
  return b;
}

const roles = [...new Set(COMBOS.map(c => c.role))];
const q1 = document.getElementById('q1');
roles.forEach(r => {
  const n = COMBOS.filter(c => c.role === r).length;
  q1.appendChild(makeBtn(r, n + '개 묶음', () => { state.role = r; }));
});

const q2 = document.getElementById('q2');
[['처음이다','초급 묶음만',1],['좀 써봤다','중급까지',2],['괜찮다','전부 보여줘',3]]
  .forEach(([l,s,v]) => q2.appendChild(makeBtn(l, s, () => { state.ceiling = v; })));

function render(){
  const box = document.getElementById('result');
  if (!state.role || !state.ceiling) { box.className = 'hidden'; return; }

  let hits = COMBOS.filter(c => c.role === state.role && RANK[c.difficulty] <= state.ceiling);
  let note = '';
  if (!hits.length) {
    hits = COMBOS.filter(c => c.role === state.role)
                 .sort((a,b) => RANK[a.difficulty] - RANK[b.difficulty]).slice(0,1);
    note = '<p class="desc">이 역할에는 그 난이도 묶음이 없어서, 제일 쉬운 것 하나를 보여드립니다.</p>';
  }

  const shown = new Set();
  hits.forEach(c => c.tools.forEach(t => shown.add(t.key)));
  const cut = __NTOOLS__ - shown.size;

  box.className = '';
  box.innerHTML = hits.map((c, i) => `
    <div class="hit">
      <h3>${h(c.name)}</h3>
      <div class="meta">${h(c.role)} · ${h(c.difficulty)} · 도구 ${c.tools.length}개${c.saves.length ? ' · 아끼는 것: ' + c.saves.map(h).join(', ') : ''}</div>
      <p class="desc">${h(c.desc)}</p>
      <ul class="tools">${c.tools.map(t => `<li><b>${h(t.name)}</b> <span>— ${h(t.tagline)}</span>${
        t.repo ? ` <a class="src" href="https://github.com/${h(t.repo)}" target="_blank" rel="noopener">${h(t.repo)}</a>` : ''
      }</li>`).join('')}</ul>
      <div class="cmds">
        <div class="cmds-bar"><span>PowerShell에 그대로 붙여넣기</span>
          <button class="copy" type="button" data-i="${i}">복사</button></div>
        <pre id="cmd-${i}">${c.commands.map(h).join('\\n')}</pre>
      </div>
    </div>`).join('') + note + `
    <div class="cut">
      <b>${cut}개는 안 깔아도 됩니다.</b> 방금 걷어낸 게 그겁니다.<br>
      다음은 <b>이 중에 이미 깔린 게 뭔지</b>입니다. 그건 PC를 직접 봐야 알 수 있어서
      <a href="./#buy">스택팩</a>이 대신 확인해 드립니다.
    </div>
    <div class="credit">
      <b>위 도구는 전부 남이 만든 것이고, 전부 무료입니다.</b>
      우리가 만든 게 아니고, 우리는 여기에 한 푼도 못 받습니다.
      이름 옆 링크가 만든 사람의 저장소입니다 — 쓸 만했으면 거기 별을 눌러주세요.
      각 도구의 라이선스는 해당 저장소를 따릅니다.<br>
      스택팩이 돈을 받는 부분은 <b>이 목록이 아니라, 내 PC에 뭐가 깔렸는지 대조하고 안전하게 설치해주는 프로그램</b>입니다.
    </div>`;

  box.querySelectorAll('button.copy').forEach(btn => {
    btn.addEventListener('click', async () => {
      const text = document.getElementById('cmd-' + btn.dataset.i).textContent;
      try { await navigator.clipboard.writeText(text); btn.textContent = '복사됨'; }
      catch { btn.textContent = '직접 선택해 주세요'; }
      setTimeout(() => { btn.textContent = '복사'; }, 1800);
    });
  });
}
</script>
</body>
</html>
"""


BUY_PAGE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>사기 — stackpack</title>
<meta name="description" content="우리가 14번 당한 걸 당신 프로젝트에서 찾아주는 점검기. __PRICE__원.">
<style>
:root{
  --bg:#F1F2F0;--card:#fff;--rule:#D0D4CF;--ink:#14171A;--ink2:#414A4C;--muted:#6C7673;
  --accent:#0D6466;--accent-soft:#DCEAE9;--warn:#8C4A18;--warn-soft:#F4E5D9;--pay:#1B1B1B;
  --sans:'Pretendard Variable',Pretendard,'Apple SD Gothic Neo',system-ui,-apple-system,'Segoe UI',sans-serif;
  --mono:ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:dark){:root{
  --bg:#0B0E0F;--card:#14181A;--rule:#293030;--ink:#E9EDEB;--ink2:#B3BDBA;--muted:#828C89;
  --accent:#5FBDBD;--accent-soft:#12302F;--warn:#D89152;--warn-soft:#33230F;--pay:#F4E24C;
}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:16px;
  line-height:1.66;-webkit-font-smoothing:antialiased;word-break:keep-all}
.wrap{max-width:44rem;margin:0 auto;padding:3rem 1.25rem 5rem}
.kicker{font-family:var(--mono);font-size:.7rem;letter-spacing:.15em;text-transform:uppercase;color:var(--muted);margin:0}
h1{font-size:clamp(1.9rem,5vw,2.6rem);line-height:1.12;letter-spacing:-.035em;font-weight:800;margin:.5rem 0 0;text-wrap:balance}
.lede{margin-top:1rem;color:var(--ink2)}
h2{font-size:1.05rem;font-weight:800;letter-spacing:-.02em;margin:2.6rem 0 .8rem}
p{margin:0}
.box{background:var(--card);border:1px solid var(--rule);padding:1.2rem 1.3rem}
.pay{margin-top:2rem;background:var(--card);border:1px solid var(--rule);padding:1.5rem 1.4rem;text-align:center}
.price{font-size:2.4rem;font-weight:800;letter-spacing:-.04em;font-variant-numeric:tabular-nums}
.price small{font-size:1rem;font-weight:500;color:var(--muted)}
a.btn{display:block;margin:1.1rem auto 0;max-width:20rem;background:#FEE500;color:#191600;
  text-decoration:none;font-weight:800;font-size:1.05rem;padding:.85rem 1rem;border-radius:6px}
a.btn:hover{filter:brightness(.96)}
a.btn:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
.alt{margin-top:.9rem;font-size:.88rem;color:var(--muted)}
.alt code{font-family:var(--mono);font-size:.92em;color:var(--ink)}
.or{display:flex;align-items:center;gap:.8rem;margin:1.1rem auto 0;max-width:20rem;color:var(--muted);font-size:.8rem}
.or::before,.or::after{content:"";flex:1;height:1px;background:var(--rule)}
.acct{margin-top:.9rem;font-size:.95rem}
.acct code{display:inline-block;margin-top:.25rem;font-family:var(--mono);font-size:.95em;
  background:var(--accent-soft);color:var(--ink);padding:.35rem .6rem;border-radius:4px}
ol.steps{margin:.6rem 0 0;padding-left:1.2rem;display:flex;flex-direction:column;gap:.45rem;font-size:.95rem}
ul.plain{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:.5rem}
ul.plain li{display:grid;grid-template-columns:1.3rem 1fr;gap:.5rem;font-size:.93rem}
ul.plain .x{font-family:var(--mono);color:var(--muted)}
ul.plain .d{display:block;font-size:.83rem;color:var(--muted)}
.warn{background:var(--warn-soft);border-left:3px solid var(--warn);padding:1rem 1.2rem;font-size:.92rem;color:var(--ink2)}
.free{background:var(--accent-soft);border-left:3px solid var(--accent);padding:1rem 1.2rem;font-size:.93rem;color:var(--ink2)}
.free a,.foot a{color:var(--accent)}
.foot{margin-top:3rem;padding-top:1.2rem;border-top:1px solid var(--rule);font-size:.82rem;color:var(--muted);
  display:flex;flex-direction:column;gap:.3rem}
code{font-family:var(--mono);font-size:.88em}
</style>
</head>
<body>
<div class="wrap">
  <p class="kicker">stackpack</p>
  <h1>우리가 14번 당한 걸<br>당신 프로젝트에서 찾아줍니다.</h1>
  <p class="lede">
    AI로 앱을 만들면 빨라집니다. 부수는 것도 빨라집니다.
    테니스 앱 하나 만들면서 사고를 14번 냈고 — 로그인 안 해도 남의 계좌가 보였고,
    <code>.env</code>가 그대로 읽혔고, 서버 무료 크레딧을 설정 한 줄 때문에 두 시간에 태웠습니다.
    <strong>그 14개를 검사로 만들었습니다.</strong>
  </p>

  <div class="pay">
    <div class="price">__PRICE_FMT__<small>원</small></div>
    <p class="alt" style="margin-top:.2rem">한 번 사면 끝. 자동결제 없음 · 7일 무조건 환불</p>
    <a class="btn" href="__KAKAOPAY__" target="_blank" rel="noopener">카카오페이로 보내기</a>
    <div class="or"><span>또는</span></div>
    <p class="acct"><b>계좌이체</b><br><code>__ACCOUNT__</code></p>
    <p class="alt">위 버튼이 안 열리거나 「사용할 수 없는 송금코드」가 뜨면
      <b>계좌로 보내주세요.</b> 링크는 가끔 만료됩니다 — 그때도 주문은 그대로 받습니다.</p>
  </div>

  <h2>보내신 뒤에</h2>
  <div class="box">
    <ol class="steps">
      <li><a href="__OPENCHAT__" target="_blank" rel="noopener">이 카톡방</a>에 <b>보내신 이름</b>만 남겨주세요.</li>
      <li>확인하고 zip을 보내드립니다. 사람이 직접 확인해서 직접 보냅니다 — 조금 걸릴 수 있습니다.</li>
      <li>설치하다 막히면 그 방에서 그대로 물어보시면 됩니다.</li>
    </ol>
  </div>

  <h2>무엇을 받나</h2>
  <div class="box">
    <ul class="plain">
      <li><span class="x">·</span><span><b>점검기</b> — 배포 직전에 돌립니다. 찾은 것마다 우리 사고 번호가 붙습니다.
        <span class="d">비밀이 커밋에 들어갔나 · 소스가 통째로 열렸나 · 무료 크레딧을 태우는 설정인가 ·
          지키는 것 없이 통과하는 가짜 검사가 있나</span></span></li>
      <li><span class="x">·</span><span><b>설치·실행 스킬</b> — 클로드 코드에 넣으면, 하려는 일에 필요한 도구를 찾아 깔고 실행까지 합니다.
        <span class="d">미리보기가 기본값이라 동의 없이는 아무것도 깔리지 않습니다</span></span></li>
      <li><span class="x">·</span><span><b>막혔을 때 답하는 사람</b> — 창을 캡처해 보내면 하루 안에 답합니다.</span></li>
    </ul>
  </div>

  <h2>안 사도 되는 것</h2>
  <div class="free">
    도구 목록·조합·설치 명령은 <b>전부 무료</b>입니다.
    <a href="./app.html">진단 페이지</a>에서 세 번 누르면 필요한 것만 골라 명령까지 복사해 갑니다.
    도구 31개는 전부 남이 만든 것이고 전부 무료입니다 — <a href="./출처.md">출처</a>.<br>
    <b>값을 매긴 건 목록이 아니라 우리가 쓴 프로그램입니다.</b>
  </div>

  <h2>이런 분껜 안 맞습니다</h2>
  <div class="box">
    <ul class="plain">
      <li><span class="x">✕</span><span>터미널을 한 번도 열어본 적이 없다<span class="d">클릭으로 쓰는 프로그램이 아닙니다.</span></span></li>
      <li><span class="x">✕</span><span>맥·리눅스를 쓴다<span class="d">설치기가 지금은 윈도우 전용입니다. 점검기는 어디서든 돕니다.</span></span></li>
      <li><span class="x">✕</span><span>세금계산서·현금영수증이 필요하다<span class="d">아래를 보세요.</span></span></li>
    </ul>
  </div>

  <h2>미리 말씀드릴 것</h2>
  <div class="warn">
    <b>사업자 등록 전입니다.</b> 현금영수증과 세금계산서를 지금은 드릴 수 없습니다.
    필요하시면 사지 마세요.<br><br>
    <b>후기가 없습니다.</b> 아직 산 사람이 없어서 있는 척하지 않겠습니다.
    그래서 <b>7일 안에는 이유를 묻지 않고 전액 돌려드립니다.</b>
    디지털 파일이라 회수할 방법이 없다는 걸 압니다. 신뢰가 없는 쪽이 낼 몫이라고 봅니다.<br><br>
    <b>점검기가 조용하다고 안전한 게 아닙니다.</b> 우리가 당해 본 것만 봅니다. 그 문장을 결과에도 찍습니다.
  </div>

  <div class="foot">
    <span>파는 사람: __SELLER__ · 문의: <a href="__OPENCHAT__" target="_blank" rel="noopener">카카오톡 오픈채팅</a></span>
    <span><a href="./">허브 페이지</a> · <a href="./app.html">무료 진단</a> · <a href="https://github.com/tree8727-coder/stackpack">소스</a></span>
  </div>
</div>
</body>
</html>
"""


def write_buy(cfg) -> str:
    page = (BUY_PAGE
            .replace("__KAKAOPAY__", html.escape(str(cfg["kakaopay"]), quote=True))
            .replace("__OPENCHAT__", html.escape(str(cfg["kakao_openchat"]), quote=True))
            .replace("__ACCOUNT__", html.escape(str(cfg["account"])))
            .replace("__SELLER__", html.escape(str(cfg["seller"])))
            .replace("__PRICE_FMT__", f"{int(cfg['price']):,}")
            .replace("__PRICE__", str(int(cfg["price"]))))
    BUY.write_text(page, encoding="utf-8")
    return page


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="만들지 않고 데이터만 검사")
    a = ap.parse_args()

    data = build.load()
    combos = collect(data)

    problems = verify(data, combos)
    if problems:
        print("멈췄습니다.\n")
        for p in problems:
            print(f"  {p}")
        return 1

    n_tools = len(data["tools"])
    print(f"검사 통과 — 콤보 {len(combos)}개, 도구 {n_tools}개, "
          f"역할 {len({c['role'] for c in combos})}종")
    for c in combos:
        print(f"    {c['key']:<16} {c['role']:<10} {c['difficulty']:<4} "
              f"도구 {len(c['tools'])} 명령 {len(c['commands'])}")

    fb = fallback_cases(combos)
    total = len({c["role"] for c in combos}) * 3
    print(f"\n대체 결과로 넘어가는 조합 {len(fb)}/{total}개"
          + (" — 브라우저의 대체 분기가 여기서 쓰입니다:" if fb else " (대체 분기는 지금 안 쓰입니다)"))
    for r, ceiling in fb:
        print(f"    {r} × 난이도{ceiling}")

    if a.check:
        print("\n--check 라서 만들지 않았습니다.")
        return 0

    page = (PAGE
            .replace("__DATA__", json.dumps(combos, ensure_ascii=False))
            .replace("__NTOOLS__", str(n_tools))
            .replace("__NCOMBOS__", str(len(combos))))
    OUT.write_text(page, encoding="utf-8")
    credits = write_credits(data)
    linked = sum(1 for v in data["tools"].values() if v.get("repo"))
    print(f"\n만들었습니다: {OUT.name}  ({len(page.encode('utf-8')):,} B)")
    print(f"           : {CREDITS.name}  ({len(credits.encode('utf-8')):,} B) "
          f"— 저장소 링크 {linked}/{n_tools}, 링크 없음 {n_tools - linked}개는 사유 명시됨")

    cfg, sell_problems = load_sell()
    if sell_problems:
        BUY.unlink(missing_ok=True)          # 반쯤 빈 결제 페이지가 남아 있지 않게
        print("\n결제 페이지를 만들지 않았습니다:")
        for p in sell_problems:
            print(f"    {p}")
        print("    (고치고 다시 돌리세요. 기존 buy.html 은 지웠습니다.)")
        return 1
    if cfg is None:
        # sell.yaml 을 내렸는데 낡은 결제 페이지가 남아 배포되면, 죽은 링크로 돈을 받는 꼴이 된다.
        existed = BUY.exists()
        BUY.unlink(missing_ok=True)
        print(f"           : {BUY.name} 은 만들지 않았습니다 — sell.yaml 이 없습니다."
              + ("  (남아 있던 예전 것은 지웠습니다)" if existed else ""))
        print("             팔 준비가 되면: cp sell.example.yaml sell.yaml 후 값을 채우세요.")
    else:
        buy = write_buy(cfg)
        print(f"           : {BUY.name}  ({len(buy.encode('utf-8')):,} B) "
              f"— {int(cfg['price']):,}원, 카카오페이 링크 포함")
    return 0


if __name__ == "__main__":
    sys.exit(main())
