# stackpack

**허브 페이지 → https://tree8727-coder.github.io/stackpack/**

**내 AI가 사고 치기 전에 막는 관문.** 남이 이미 당한 사고 23건으로 만든 오답노트.

세 층으로 막습니다 — **규칙**(AI가 읽음) · **검사**(내 프로젝트를 훑음) · **관문**(그 자리에서 차단).

> **우리도 지금 걸립니다.** `uv run check.py .` 를 이 저장소에 돌리면 E26(덩어리가
> 너무 큼)이 네 건 나옵니다 — `vibe.py` 1,255줄, `do_selftest` 308줄 등. 고치는 중입니다.
> 우리가 안 걸리게 기준을 맞추면 그 기준은 아무도 안 믿습니다.

**규칙이 실제로 듣는지 재고 있습니다.** 한 주 켜고 한 주 끄면서 관문 발동을
「쓰기 100번당 막힘」으로 셉니다. 관문은 실험 중에도 항상 켜져 있어 안전이
내려가는 구간이 없습니다. 결과가 불리하게 나와도 그대로 공개합니다 —
`uv run vibe.py 성적표`.

규칙 파일에는 **최대 12줄**만 들어갑니다. 지시가 늘수록 AI 가 따르는 정확도가
떨어지기 때문입니다([IFScale](https://arxiv.org/pdf/2507.11538)). 관문이 자동으로
막는 사고는 아예 안 적습니다 — 관문은 지시 예산이 0 인데 100% 확실합니다.

색인은 **그 컴퓨터에서 실제로 걸린 사고를 위로** 올립니다. 순위를 맞추는 기록도
밖으로 안 나갑니다. 전체 통계에 따른 순위 조정과 낡은 항목 은퇴는 서버가 있어야
하므로 아직 없습니다. **새 사고를 스스로 찾는 것은 원리상 불가능합니다** —
되돌림은 어디인지만 알려주고 무엇인지는 사람만 씁니다.

**서버가 없습니다.** 코드도 대화도 밖으로 한 줄 안 나갑니다. 나가는 통신은
사고 목록을 받아오는 것 하나뿐입니다.

**전부 무료이고 오픈소스(MIT)입니다.** 받아서 쓰고, 고치고, 가져다 파셔도 됩니다.
파는 것도, 받는 것도 없습니다.

대신 **쓰는 방법을 알려주세요.** 여기서 자라는 건 도구 목록이 아니라
사람들이 실제로 쓰는 방법 쪽입니다.
[사용법 제출](../../issues/new?template=사용법-제출.yml) · 규칙은 [CONTRIBUTING.md](CONTRIBUTING.md)

**한 달에 한 번 당근 모임에서 직접 모읍니다.** 와서 화면 보여주고 가면 됩니다.

도구 31개, 콤보 9개. 전부 `stack.yaml` 하나에서 나옵니다.

(이 숫자는 `build.py selftest`가 `stack.yaml` 실제 개수와 대조합니다. 손으로 안 맞춰도 됩니다 — 틀리면 터집니다.)

```
stack.yaml  ←  유일한 진실. 손으로만 편집.
    │
    ├─ uv run build.py html          → index.html (허브 페이지)
    ├─ uv run build.py stars         → stars.json (깃허브 별점)
    ├─ uv run build.py install <키>  → 실제 설치 (--yes 없으면 미리보기)
    └─ uv run build.py skill         → skill/SKILL.md (Claude Code 스킬)
```

`uv`만 있으면 됩니다 (`winget install astral-sh.uv`). 나머지 의존성은 uv가 알아서 받습니다.

## 두 축

| | 하는 일 | 진실 | 명령 |
|---|---|---|---|
| **stack** | 프로그램을 깝니다 | `stack.yaml` | `uv run build.py …` |
| **vibe** | 실제로 당한 사고를 AI 에게 알려주고 **막습니다** | `vibe.yaml` · `ERRORS.md` | `uv run vibe.py …` |

`vibe` 는 **아무것도 설치하지 않습니다.** 도구를 안 깔아도 됩니다.
사람들이 실제로 쓰는 방법을 `CLAUDE.md` 같은 파일로 내 프로젝트에 얹어줄 뿐입니다.

> **처음 오셨나요?** → [사용법.md](사용법.md) 를 보세요. 쉬운 말로만 적었습니다.

### 깔기 — 한 줄

```powershell
uvx stackpack
```

이게 전부입니다. 붙일 것도, 누를 것도, 고를 것도 없습니다.
깔려 있는 도구만 찾아서 넣고, 새 방법은 하루 한 번 알아서 받아옵니다.

되돌리는 것도 한 마디입니다 — `uvx stackpack 되돌리기 --진짜`.

`uv` 만 있으면 됩니다(`winget install astral-sh.uv` · 맥은 `brew install uv`).
저장소를 받을 필요도, 파이썬을 따로 깔 필요도 없습니다.

> 아직 PyPI 에 올리기 전입니다. 그전까지는 저장소를 받아 `uv run vibe.py …` 로 쓰세요.

**한 번만 넣고 끝내려면** (권장) — 도구마다 "모든 프로젝트에서 자동으로 읽는 파일"이
있습니다. 거기 넣으면 프로젝트마다 다시 칠 일이 없습니다.

| 도구 | 전역 (한 번만) | 프로젝트 |
|---|---|---|
| Claude Code | `~/.claude/CLAUDE.md` | `CLAUDE.md` |
| Google Antigravity | `~/.gemini/AGENTS.md` | `AGENTS.md` |

Antigravity 전역은 `GEMINI.md` 가 **아니라** `AGENTS.md` 입니다.
`~/.gemini/GEMINI.md` 는 Gemini CLI 가 같은 경로를 하드코딩해 두어 서로 덮어씁니다
([gemini-cli#16058](https://github.com/google-gemini/gemini-cli/issues/16058)).
selftest 가 그 파일 이름을 아예 막습니다.

```powershell
uv run vibe.py where                         # 어디에 놓이는지 먼저 보기
uv run vibe.py apply all --global            # 뭐가 들어가는지 보여줌 (안 바꿈)
uv run vibe.py apply all --global --yes      # 넣기. 이후 두 도구 모두 자동 적용
uv run vibe.py apply all --global --yes --only claude-code   # 한 도구만
```

**계속 최신으로 두려면** — 사람들이 낸 방법이 늘어도 손댈 일이 없게:

```powershell
uv run vibe.py sync --yes        # 최신 방법을 받아서 전역에 다시 얹음
```

이 한 줄을 스케줄러에 걸어 두면 됩니다
(윈도우: 작업 스케줄러 / 맥: `launchd` · `cron`).

저장소 안에서 돌리면 `git pull`, 배포판(저장소 없음)에서는 깃허브에서 `vibe.yaml` 만
받아 `~/.stackpack/` 에 둡니다. **받은 파일은 검사를 통과해야 저장됩니다** — 남의
서버에서 받은 걸 검사 없이 내 전역 설정에 얹지 않습니다.

**이 프로젝트에만** 넣고 싶으면 `--global` 을 빼면 됩니다.

```powershell
uv run vibe.py list                 # 어떤 방법들이 있나
uv run vibe.py show 단언-부숴보기     # 하나 자세히
uv run vibe.py apply all            # 뭐가 바뀌는지 먼저 보여줌 (아무것도 안 바꿈)
uv run vibe.py apply all --yes      # 실제로 적용 (.bak 남김)
```

되돌리려면 규칙 파일에서 `<!-- vibe:키 -->` 블록을 지우거나, 옆에 남은 `.bak` 으로
되돌리면 됩니다. `.bak` 은 **적용 전 원본**입니다 — 한 파일에 방법이 여러 개 붙어도
한 번만 씁니다 (매 단계 덮어쓰면 중간 상태가 남아 되돌리기가 거짓말이 됩니다).

기존 파일은 **절대 덮어쓰지 않습니다.** 이미 있으면 건너뛰고, 덧붙일 때는 표식을 남겨
두 번 돌려도 안 늘어납니다. 이건 `uv run vibe.py selftest` 가 매번 실제로 확인합니다.

## 쓰는 법

```powershell
uv run build.py status                        # 내 PC에 뭐가 이미 깔려 있나
uv run build.py status content-factory        # 이 콤보만
uv run build.py install content-factory --skip-installed        # 없는 것만 미리보기
uv run build.py install content-factory --skip-installed --yes  # 실제 설치
uv run build.py html                          # 허브 페이지 다시 만들기
uv run build.py skill --install               # Claude Code가 대신 깔게 하기
uv run examples/cardnews.py                   # 콤보 실행 예제
```

`status`를 먼저 돌리세요. 이미 깔린 걸 다시 까는 게 제일 흔한 낭비입니다.

```
OK ripgrep (rg)     ripgrep 15.2.0 (rev e89fff89ac)
-- n8n              없음
?  Dify             확인 불가

설치됨 16 / 없음 9 / 확인불가 6
```

"확인 불가"는 CLI가 없는 도구입니다(웹 서비스·도커·파이썬 라이브러리). 없다는 뜻이 아닙니다.

`install`은 **미리보기가 기본값**입니다. `--yes`를 붙여야 실행됩니다.
실행은 PowerShell을 통해 이뤄집니다 (`Add-Content $PROFILE` 같은 명령 때문).

## 설계 원칙 하나

**콤보의 설치 명령은 어디에도 적혀 있지 않습니다.** 멤버 도구의 `install`을
순서대로 이어붙이고 중복 줄을 제거해 자동 생성합니다.

이전 `data_pipeline_v1~v10.py`는 콤보마다 `install_cmd`를 손으로 복붙했고,
버전을 올릴 때마다 파일 전체를 복사하다 v8→v9에서 도구 9개가 조용히 사라졌습니다.
`build.py selftest`가 그 종류의 사고를 잡습니다.

```powershell
uv run build.py selftest
```

- 콤보/가이드가 참조하는 도구·콤보·커넥터·예제 파일이 실재하는지
- 명령 중복 제거가 순서를 지키는지
- **미리보기 모드가 어떤 경우에도 명령을 실행하지 않는지**
- **`status`의 확인 명령에 설치 동사(`install`/`clone`/`docker run`)가 섞이지 않았는지**
- 커넥터 노드 그래프에 끊긴 노드가 없는지, `cardnews.py` 출력 필드와 맞는지
- **모델 가격표(`models`)가 90일 넘게 안 갱신됐는지** — 넘으면 실패합니다 ([MODELS-UPDATE.md](MODELS-UPDATE.md))
- README의 도구·콤보 개수가 `stack.yaml` 실제와 맞는지
- 모델 섹션이 허브 페이지 밖(`skill/SKILL.md`)으로 새어나가지 않았는지

`uv run examples/cardnews.py --demo`는 페이로드가 커넥터가 읽는 모양인지까지 검사합니다.

## 파일

| 파일 | 역할 |
|---|---|
| `stack.yaml` | 도구·콤보·가이드·모델 데이터. 여기만 고치면 됩니다 |
| `MODELS-UPDATE.md` | `models` 섹션 갱신 절차 (90일마다 selftest가 요구) |
| `build.py` | 렌더러 + 설치기 + 스킬 생성기 + 자체 검사 |
| `examples/cardnews.py` | content-factory 콤보의 실행 예제 |
| `connectors/` | 예제 출력을 실제 서비스로 흘려보내는 n8n 워크플로 |
| `ci/pages.yml` | 보관 중인 CI 워크플로 (아래 배포 항목 참고) |
| `index.html` | 생성물 — 직접 고치지 마세요 |
| `stars.json` | 생성물 — `build.py stars`가 씁니다 |
| `skill/SKILL.md` | 생성물 — `build.py skill`이 씁니다 |

## 공개 페이지 세 장

| 파일 | 무엇 | 생성 |
|---|---|---|
| `index.html` | 허브 — 도구 31개 전부 | `build.py html` |
| `app.html` | 진단 — 세 번 눌러 필요한 것만 (무료) | `app.py` |
| `buy.html` | 구매 — 카카오페이 + 계좌 | `app.py` (`sell.yaml` 있을 때만) |

`sell.yaml` 은 개인 송금 링크라 저장소에 안 올라갑니다. `sell.example.yaml` 을 복사해 채우세요.

**송금 링크가 살아 있는지는 기계로 확인할 수 없습니다.** 만료돼도 같은 페이지에 200 이 옵니다.
그래서 `checked` 에 사람이 직접 열어 본 날짜를 적게 하고, **14일이 지나면 `buy.html` 을 만들지 않습니다.**
확인하는 법은 `sell.example.yaml` 주석에 있습니다.

## 배포

`main`은 소스만, `gh-pages`는 빌드된 `index.html`만 담습니다. Pages는 `gh-pages`를 서빙합니다.

**지금은 수동입니다.** `gh` 토큰에 `workflow` 스코프가 없어 CI를 등록하지 못했습니다.
워크플로 파일은 `ci/pages.yml`에 그대로 보관돼 있습니다.

CI로 전환 (권장, 한 번만 하면 끝):

```powershell
gh auth refresh -h github.com -s workflow    # 별도 터미널에서 (브라우저 인증)
mkdir .github\workflows; git mv ci\pages.yml .github\workflows\
git commit -am "ci: Pages 자동 빌드" ; git push
```

전환하면 push할 때마다 자동 빌드되고, **매주 월요일 별점이 자동 갱신**됩니다.
그전까지의 수동 재배포:

```powershell
uv run build.py stars; uv run build.py html
git worktree add -f ..\stackpack-pages gh-pages
Copy-Item index.html ..\stackpack-pages\
cd ..\stackpack-pages; git add -A; git commit -m deploy; git push
cd ..\stackpack; git worktree remove -f ..\stackpack-pages
```

## 출처

`startup_automation_db/data_pipeline_v7~v10.py`에서 데이터를 병합 복구했습니다.
원본 폴더는 그대로 두었습니다.

## 라이선스

이 저장소의 코드와 문서는 **MIT**입니다 ([LICENSE](LICENSE)).
소개하는 도구 31개는 전부 남이 만든 것이고 각자의 라이선스를 따릅니다 — [출처.md](출처.md).

## PyPI 에 올리기

토큰을 만들지 않습니다. **PyPI 가 깃허브를 직접 믿게** 해 두었습니다
(`.github/workflows/publish.yml`). 토큰이 없으면 새어 나갈 토큰도 없습니다.

처음 한 번만 PyPI 쪽에서 등록하면 됩니다.

1. [pypi.org](https://pypi.org) 가입 → 2단계 인증 켜기
2. [신뢰 게시자 추가](https://pypi.org/manage/account/publishing/) 에서 **«아직 없는 프로젝트»** 로 등록
   - PyPI Project Name `stackpack`
   - Owner `tree8727-coder` · Repository `stackpack`
   - Workflow name `publish.yml` · Environment `pypi`
3. 올릴 때

```powershell
git tag v0.1.0
git push origin v0.1.0
```

태그가 올라가면 검사를 먼저 돌리고, 통과해야 배포합니다.
