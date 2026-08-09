# connectors

`examples/`가 만든 결과물을 실제 서비스로 흘려보내는 조각들.

## n8n-cardnews.json

`examples/cardnews.py`가 뱉는 `n8n_payload.json`을 받는 n8n 워크플로입니다.

```
cardnews.py → n8n_payload.json → [웹훅] → 검증 → 슬라이드 있음? → 발행
```

### 쓰는 법

1. n8n 실행: `n8n start` → http://localhost:5678
2. 좌상단 메뉴 → **Import from File** → 이 JSON 선택
3. 웹훅 노드에서 **Test URL** 복사
4. 카드뉴스 만들고 payload 던지기:

```powershell
uv run examples/cardnews.py
http POST http://localhost:5678/webhook-test/cardnews < out/n8n_payload.json
```

(`http`가 없으면 `uv run build.py install httpie --yes`)

### ⚠️ 발행 노드는 비어 있습니다

마지막 노드는 **DRY_RUN 로그만 남깁니다.** 일부러 그렇게 뒀습니다.

인스타그램 자동 발행은 비즈니스 계정 + Facebook 앱 + 장기 토큰이 필요하고,
설정이 사람마다 달라서 여기 하드코딩하면 아무 데서도 안 돌아갑니다.
게다가 검토 없이 SNS에 자동으로 글이 올라가는 건 되돌리기 어렵습니다.

교체 방법 세 가지 — **3번을 권합니다**:

| 방식 | 필요한 것 | 비고 |
|---|---|---|
| 1. Instagram Graph API | 비즈니스 계정, FB 앱, 토큰 | 완전 자동. 설정이 제일 무겁습니다 |
| 2. Buffer / Later | 계정, API 키 | 예약 발행. 중간 난이도 |
| 3. Telegram/Slack으로 나에게 전송 | 봇 토큰 하나 | **눈으로 보고 직접 올림. 사고 안 남** |

### 검증 상태

JSON 구조(노드 타입·연결 그래프)는 자동 검사합니다:

```powershell
uv run build.py selftest
```

다만 **실제 n8n 인스턴스에 import해서 돌려본 적은 없습니다.** n8n 미설치 상태라서요.
`n8n start` 후 import해보시고 안 되면 알려주세요.
