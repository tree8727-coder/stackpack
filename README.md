# stackpack

**허브 페이지 → https://tree8727-coder.github.io/stackpack/**

코딩·바이브코딩 세팅을 한 번에 — **읽는 카탈로그가 아니라 실행되는 카탈로그.**

**코드와 카탈로그는 전부 무료이고 오픈소스(MIT)입니다.** 받아서 쓰고, 고치고,
가져다 파셔도 됩니다. 파는 9,900원은 소프트웨어 값이 아니라 **대신 깔아드리고
1:1로 봐드리는 값**입니다 — 터미널을 안 여는 분들을 위한 것입니다.

쓰는 방법을 알려주고 싶으면 [사용법 제출](../../issues/new?template=사용법-제출.yml)로
보내주세요. 채택되면 이름과 함께 실립니다. 규칙은 [CONTRIBUTING.md](CONTRIBUTING.md).

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
| **vibe** | 내 프로젝트에 **파일을 놓습니다** | `vibe.yaml` | `uv run vibe.py …` |

`vibe` 는 **아무것도 설치하지 않습니다.** 도구를 안 깔아도 됩니다.
사람들이 실제로 쓰는 방법을 `CLAUDE.md` 같은 파일로 내 프로젝트에 얹어줄 뿐입니다.

```powershell
uv run vibe.py list                 # 어떤 방법들이 있나
uv run vibe.py apply all            # 뭐가 바뀌는지 먼저 보여줌 (아무것도 안 바꿈)
uv run vibe.py apply all --yes      # 실제로 적용 (.bak 남김)
```

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
