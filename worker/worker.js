// 집계 서버 — Cloudflare Workers 무료 등급.
//
// **받는 것은 사고 번호와 횟수뿐입니다.** 코드·파일 이름·경로·IP·대화 없음.
// 집계 결과는 깃허브에 공개 파일로 올라가므로 우리도 조작할 수 없습니다.
//
// 사용자는 이 서버에 «읽으러» 오지 않습니다. 읽기는 깃허브에서 합니다.
// 그래서 이 서버가 죽어도 프로그램은 그대로 돕니다.
//
// ── 왜 «읽고 고쳐 쓰기» 를 안 하나 ───────────────────────────────────────────
// 처음엔 집계 하나를 읽어서 더하고 다시 쓰는 방식이었습니다. KV 는 쓴 것이
// 읽기에 반영되기까지 시간이 걸려서, 두 번째 요청이 **첫 요청의 숫자를 못 보고
// 통째로 덮어썼습니다.** 실제로 시험 중에 E8:2 · E5:1 이 사라졌습니다.
// 우리 사고 E3(빈 결과가 좋은 데이터를 덮어씀)와 같은 병입니다.
//
// 그래서 **덧쓰기만 합니다.** 설치마다 자기 칸에만 쓰고, 합치는 것은 읽을 때
// 합니다. 서로의 것을 건드리지 않으니 잃을 수가 없습니다.
// 덤으로 쓰기가 요청당 두 번에서 **한 번**으로 줄어 무료 한도가 두 배가 됐습니다.

// 상한은 «요청 수» 가 아니라 **KV 쓰기 수**에 걸어야 합니다.
// 무료 등급의 한도는 KV 쓰기 하루 1,000회이고 이제 요청당 한 번 씁니다.
// **확인 2026-08-20.** 조건은 바뀝니다(E12) — 오래되면 다시 읽고 날짜를 고치세요.
const 무료_KV쓰기_하루 = 1000;
const 요청당_쓰기 = 1;
const 하루상한 = 800;              // 1000 ÷ 1, 여유 두고

const 설치당_하루_최대 = 200;
// 받는 열쇠는 두 가지뿐입니다.
//   E8 · P3  — 아는 사고 번호
//   R:.py    — 그 종류 파일에서 되돌린 횟수 (**확장자만**. 파일 이름도 경로도 없음)
// 이 모양이 아니면 버립니다. 자유 텍스트는 애초에 들어올 수 없습니다.
const 사고번호 = /^([EP][0-9]{1,3}|R:(\.[a-z0-9]{1,6}|기타))$/;

function 오늘() {
  return new Date().toISOString().slice(0, 10);
}

async function 집계하기(env, 날) {
  // 흩어진 칸을 읽을 때 합칩니다. 아무것도 덮어쓰지 않습니다.
  //
  // 횟수와 **사람 수**를 따로 냅니다. 한 사람이 열 번 걸린 것과 열 사람이 한 번씩
  // 걸린 것은 완전히 다른 이야기인데, 합만 보면 구분이 안 됩니다.
  // 카탈로그의 `evidence.users` 가 이 «사람 수» 에서 자랍니다.
  const 합 = {};
  const 사람 = {};
  let 설치수 = 0;
  let cursor;
  do {
    const 목록 = await env.KV.list({ prefix: `c:${날}:`, cursor });
    for (const k of 목록.keys) {
      const 값 = await env.KV.get(k.name, "json");
      if (!값) continue;
      설치수 += 1;
      for (const [사고, n] of Object.entries(값)) {
        if (!사고번호.test(사고)) continue;
        합[사고] = (합[사고] || 0) + n;
        사람[사고] = (사람[사고] || 0) + 1;      // 이 설치가 이 사고를 겪었다 = 1명
      }
    }
    cursor = 목록.list_complete ? null : 목록.cursor;
  } while (cursor);
  합.설치수 = 설치수;
  합.사람 = 사람;            // 사고마다 «몇 명이 겪었나»
  return 합;
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const 날 = 오늘();

    if (req.method === "GET" && url.pathname === "/v1/agg") {
      return new Response(JSON.stringify(await 집계하기(env, 날)), {
        headers: { "content-type": "application/json" },
      });
    }

    if (req.method !== "POST" || url.pathname !== "/v1/count") {
      return new Response("not found", { status: 404 });
    }

    // 설정이 무료 한도를 넘게 바뀌면 코드가 스스로 아무것도 안 받습니다 (E13)
    if (하루상한 * 요청당_쓰기 > 무료_KV쓰기_하루) {
      return new Response("ok", { status: 202 });
    }

    let 몸;
    try {
      몸 = await req.json();
    } catch {
      return new Response("bad", { status: 400 });
    }

    // 설치 ID 는 클라이언트가 만든 난수입니다. 우리는 그게 누구인지 모릅니다.
    const 설치 = String(몸.install || "");
    if (!/^[a-f0-9-]{8,40}$/.test(설치)) return new Response("bad", { status: 400 });

    const 내칸 = `c:${날}:${설치}`;
    const 이전 = (await env.KV.get(내칸, "json")) || {};
    let 총 = 0;
    for (const n of Object.values(이전)) 총 += n;
    if (총 >= 설치당_하루_최대) return new Response("ok", { status: 202 });

    // **자기 칸에만 씁니다.** 남의 숫자를 건드리지 않으므로 잃을 수가 없습니다.
    const 센것 = 몸.counts || {};
    for (const [사고, n] of Object.entries(센것)) {
      if (!사고번호.test(사고)) continue;                 // 모르는 모양은 버립니다
      const 값 = Math.max(0, Math.min(parseInt(n, 10) || 0, 100));
      if (!값) continue;
      이전[사고] = (이전[사고] || 0) + 값;
    }
    await env.KV.put(내칸, JSON.stringify(이전), { expirationTtl: 60 * 60 * 24 * 90 });
    return new Response("ok");
  },
};
