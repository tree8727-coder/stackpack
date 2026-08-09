# stackpack

**허브 페이지 → https://tree8727-coder.github.io/stackpack/**

1인 창업 AI 자동화 스택 — **읽는 카탈로그가 아니라 실행되는 카탈로그.**

도구 27개, 콤보 8개. 전부 `stack.yaml` 하나에서 나옵니다.

```
stack.yaml  ←  유일한 진실. 손으로만 편집.
    │
    ├─ uv run build.py html          → index.html (허브 페이지)
    ├─ uv run build.py stars         → stars.json (깃허브 별점)
    ├─ uv run build.py install <키>  → 실제 설치 (--yes 없으면 미리보기)
    └─ uv run build.py skill         → skill/SKILL.md (Claude Code 스킬)
```

`uv`만 있으면 됩니다 (`winget install astral-sh.uv`). 나머지 의존성은 uv가 알아서 받습니다.

## 쓰는 법

```powershell
uv run build.py html                          # 허브 페이지 열기
uv run build.py install content-factory       # 뭐가 깔릴지 먼저 확인
uv run build.py install content-factory --yes # 실제 설치
uv run build.py skill --install               # Claude Code가 대신 깔게 하기
uv run examples/cardnews.py                   # 콤보 실행 예제
```

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

- 콤보/가이드가 참조하는 도구·콤보가 실재하는지
- 명령 중복 제거가 순서를 지키는지
- **미리보기 모드가 어떤 경우에도 명령을 실행하지 않는지**

## 파일

| 파일 | 역할 |
|---|---|
| `stack.yaml` | 도구·콤보·가이드 데이터. 여기만 고치면 됩니다 |
| `build.py` | 렌더러 + 설치기 + 스킬 생성기 + 자체 검사 |
| `examples/cardnews.py` | content-factory 콤보의 실행 예제 |
| `index.html` | 생성물 — 직접 고치지 마세요 |
| `stars.json` | 생성물 — `build.py stars`가 씁니다 |
| `skill/SKILL.md` | 생성물 — `build.py skill`이 씁니다 |

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
