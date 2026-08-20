// 집계 서버 — Cloudflare Workers 무료 등급.
//
// **받는 것은 사고 번호와 횟수뿐입니다.** 코드·파일 이름·경로·IP·대화 없음.
// 그리고 집계 결과는 깃허브에 공개 파일로 올라가므로 우리도 조작할 수 없습니다.
//
// 사용자는 이 서버에 «읽으러» 오지 않습니다. 읽기는 깃허브에서 합니다.
// 그래서 이 서버가 죽어도 프로그램은 그대로 돕니다.
//
// E13 을 우리가 밟지 않기 위해: 하루 요청 상한을 코드에 박고, 넘으면 조용히 버립니다.
// 무료 등급을 우리 설정으로 태우는 것이 정확히 우리 사고 번호 E13 입니다.

// 상한은 «요청 수» 가 아니라 **KV 쓰기 수**에 걸어야 합니다.
// 처음에 요청 5만으로 잡았는데, 무료 등급의 진짜 한도는 KV 쓰기 하루 1,000회이고
// 요청 하나당 두 번 씁니다 — 5만이면 한도의 100배입니다. **우리 사고 E13 그대로**
// («무료 체험 조건을 안 읽고 우리 설정으로 태웠다»). 조건을 읽고 다시 계산했습니다.
//
//   무료 KV 쓰기 1,000/일  ÷  요청당 2회  =  하루 500요청
//   여유를 두고 400 으로 둡니다. 넘으면 조용히 버립니다(요금이 나갈 길 없음).
//
// **이 숫자는 사람이 확인한 값입니다** — 2026-08-20 확인. 조건은 바뀝니다(E12).
// 오래되면 다시 읽고 이 줄의 날짜를 고치세요.
const 무료_KV쓰기_하루 = 1000;   // 확인 2026-08-20
const 요청당_쓰기 = 2;
const 하루상한 = 400;
const 설치당_하루_최대 = 200;     // 한 설치가 하루에 올릴 수 있는 총 횟수
const 사고번호 = /^[EP][0-9]{1,3}$/;

async function 오늘(env) {
  return new Date().toISOString().slice(0, 10);
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);

    // 집계 읽기 — 깃허브 액션이 하루 한 번 가져갑니다
    if (req.method === "GET" && url.pathname === "/v1/agg") {
      const 날 = await 오늘(env);
      const 값 = await env.KV.get(`agg:${날}`);
      return new Response(값 || "{}", {
        headers: { "content-type": "application/json" },
      });
    }

    if (req.method !== "POST" || url.pathname !== "/v1/count") {
      return new Response("not found", { status: 404 });
    }

    const 날 = await 오늘(env);

    // 하루 상한 — 넘으면 조용히 버립니다. 돈이 나갈 길을 코드로 막습니다 (E13)
    const 집계0 = JSON.parse((await env.KV.get(`agg:${날}`)) || "{}");
    const 총 = 집계0.요청수 || 0;
    if (총 >= 하루상한) return new Response("ok", { status: 202 });
    if (하루상한 * 요청당_쓰기 > 무료_KV쓰기_하루) {
      // 설정이 무료 한도를 넘게 바뀌면 아예 안 받습니다. 코드가 스스로 막습니다.
      return new Response("ok", { status: 202 });
    }

    let 몸;
    try {
      몸 = await req.json();
    } catch {
      return new Response("bad", { status: 400 });
    }

    // 설치 ID 는 클라이언트가 만든 난수입니다. 우리는 그게 누구인지 모릅니다.
    const 설치 = String(몸.install || "").slice(0, 40);
    if (!/^[a-f0-9-]{8,40}$/.test(설치)) return new Response("bad", { status: 400 });

    // 한 설치가 하루에 올릴 수 있는 양을 막습니다 — 숫자를 부풀려 순위를
    // 조작하려는 시도를 여기서 자릅니다. 숫자는 **순서에만** 쓰이고
    // 무엇이 카탈로그에 들어가고 빠지는지는 영원히 사람이 정합니다.
    const 이설치 = parseInt((await env.KV.get(`u:${날}:${설치}`)) || "0", 10);
    if (이설치 >= 설치당_하루_최대) return new Response("ok", { status: 202 });

    const 센것 = 몸.counts || {};
    const 집계 = 집계0;
    let 더함 = 0;
    for (const [사고, n] of Object.entries(센것)) {
      if (!사고번호.test(사고)) continue;                 // 모르는 모양은 버립니다
      const 값 = Math.max(0, Math.min(parseInt(n, 10) || 0, 100));
      if (!값) continue;
      집계[사고] = (집계[사고] || 0) + 값;
      더함 += 값;
    }
    집계.설치수 = (집계.설치수 || 0) + (이설치 === 0 ? 1 : 0);
    집계.요청수 = 총 + 1;

    // 쓰기 두 번. 여기를 늘리면 위의 계산이 틀려집니다.
    await env.KV.put(`agg:${날}`, JSON.stringify(집계), { expirationTtl: 60 * 60 * 24 * 90 });
    await env.KV.put(`u:${날}:${설치}`, String(이설치 + 더함), { expirationTtl: 60 * 60 * 48 });
    return new Response("ok");
  },
};
