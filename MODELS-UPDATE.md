# models 갱신 절차

`stack.yaml`의 `models:` 섹션은 **반드시 썩습니다.** 가격이 바뀌고, 모델이 추가되고,
권고 문구가 바뀝니다 — 실제로 Opus 4.7/4.8의 "effort는 xhigh에서 시작"이
Opus 5에서 "high에서 시작"으로 바뀌었습니다.

그래서 `build.py selftest`가 `models.as_of`를 보고 **90일이 지나면 실패**합니다.
빨간불이 뜨면 이 문서대로 하세요. **처음부터 다시 조사하지 마세요.** 20분이면 끝납니다.

```
AssertionError: models.as_of(2026-08-17)가 93일 지났습니다. MODELS-UPDATE.md 절차로 갱신하세요.
```

---

## 사람이 할 때 — 4단계

### 1) 출처 3곳만 다시 읽습니다

`stack.yaml`의 각 문구에 `source:`가 붙어 있습니다. **그 URL만** 보면 됩니다.

| 무엇을 고치나 | 읽을 곳 |
|---|---|
| `catalog`의 가격·컨텍스트·모델 목록 | https://platform.claude.com/docs/en/about-claude/pricing |
| `catalog`의 `use_for`, `principle` | https://platform.claude.com/docs/en/about-claude/models/choosing-a-model |
| effort 권고 (`warnings` 2번) | https://platform.claude.com/docs/en/build-with-claude/effort |
| 최신 모델 세대의 변경점 | https://platform.claude.com/docs/en/about-claude/models/overview |

### 2) 값을 고칩니다

- **가격은 숫자로** — `price_in: 5` (O), `price_in: "$5"` (X).
  문자열이면 허브 페이지의 "최저가 대비" 배수 계산이 깨지고 selftest가 잡습니다.
- **모델이 추가/은퇴했으면** `catalog` 항목을 넣고 뺍니다. 필수 필드는
  `id` / `name` / `price_in` / `price_out` / `context` / `use_for` 여섯 개 전부입니다.
- **권고 문구가 바뀌었으면** `text`와 함께 `source`도 최신 페이지로 갱신합니다.
  문구만 고치고 출처를 옛 URL로 두면, 다음 사람이 없는 문장을 찾게 됩니다.

### 3) `as_of`를 오늘 날짜로 올립니다

```yaml
as_of: "2026-11-20"    # YYYY-MM-DD, 따옴표 포함
```

**값을 하나도 안 고쳤어도 날짜는 올려야 합니다** — "확인했고 그대로였다"는 것도 정보입니다.
다만 **읽지 않고 날짜만 올리는 건 금지입니다.** 그 순간 이 테스트는 아무것도 지키지 않습니다.

### 4) 검사하고 다시 뽑습니다

```powershell
uv run build.py selftest      # 통과해야 합니다
uv run build.py html          # 허브 페이지 재생성
```

허브 페이지 4번 섹션에서 표와 기준일이 맞는지 눈으로 한 번 봅니다.

---

## 에이전트에게 시킬 때

Claude Code에 이렇게 던지면 됩니다:

```
stackpack의 MODELS-UPDATE.md 절차대로 stack.yaml의 models 섹션을 갱신해줘.
각 문구의 source URL을 실제로 열어서 확인하고, 바뀐 값만 고친 다음
as_of를 오늘 날짜로 올리고 selftest를 통과시켜줘.
확인 못 한 값은 고치지 말고 "확인 실패"로 보고해줘.
```

**에이전트에게 반드시 지키게 할 것 두 가지:**

1. **문서를 실제로 못 읽었으면 값을 바꾸지 말 것.** 그럴듯한 숫자를 채워 넣는 게
   낡은 숫자보다 훨씬 나쁩니다. 낡은 건 `as_of`가 실토하지만, 지어낸 건 아무도 모릅니다.
2. **`as_of`는 실제로 읽은 뒤에만 올릴 것.** 날짜만 올리면 다음 90일을 눈감고 갑니다.

이 두 개 때문에 가격 자동 스크래이핑은 일부러 넣지 않았습니다. HTML 파싱은 문서 개편
한 번에 깨지는데, 깨진 줄 모르고 "자동 갱신됨" 상태로 틀린 값을 커밋하는 게 최악입니다.

---

## selftest가 실제로 지키는 것

`build.py selftest` 8~10번 블록:

| # | 단언 | 깨지는 상황 |
|---|---|---|
| 8 | `as_of`가 90일 이내 | 그냥 방치했을 때 |
| 8 | `catalog` 필수 필드 6개 존재, 가격은 숫자 | 모델 추가하며 필드를 빠뜨렸을 때 |
| 8 | `principle`·`warnings` 모든 문구에 `source` URL | 출처 없는 주장을 얹었을 때 |
| 9 | README 개수 == `stack.yaml` 실제 개수 | 도구를 추가하고 README를 안 고쳤을 때 |
| 10 | `models`가 `skill/SKILL.md`에 없을 것 | 스킬(설치 하네스)을 가격표로 살찌웠을 때 |

각 단언은 **일부러 깨뜨려서 빨간불을 확인한 뒤** 넣었습니다. 새 단언을 추가할 때도
같은 순서로 하세요 — 통과하는 걸 먼저 보면, 그게 무엇을 지키는지 영영 모릅니다.

## 나중에 CI로 올리려면

지금은 사람이 selftest를 돌려야 빨간불을 봅니다. `ci/pages.yml`을
`.github/workflows/`로 옮기면(README 배포 항목 참고) 주간 실행에서 자동으로 터집니다.
`gh` 토큰에 `workflow` 스코프가 필요합니다.
