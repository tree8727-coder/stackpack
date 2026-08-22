// 받는 열쇠 규칙이 **실제로 거르는지** 시험합니다.
//
// 배포 관문이 처음엔 «그 줄이 있는가» 만 봤습니다. 규칙을 아무거나 받게
// 망가뜨려도 줄은 그대로라 통과했습니다 — 우리 E10(아무것도 안 보는 검사)입니다.
// 그래서 규칙을 불러와 **직접 넣어 봅니다.**
import { 사고번호 } from "./worker.js";

const 받아야 = ["E8", "P3", "E13", "R:.py", "R:.ipynb", "R:기타", "T:git", "T:ffmpeg", "T:기타"];
const 버려야 = [
  "해킹", "R:/etc/passwd", "R:", "T:", "T:/bin/sh", "T:rm -rf /",
  "E8; DROP TABLE", "../../etc", "설치수", "사람",
  "T:" + "a".repeat(40), "R:.verylongextension",
];

let 틀림 = 0;
for (const k of 받아야) if (!사고번호.test(k)) { console.error(`  ✗ «${k}» 를 버립니다`); 틀림++; }
for (const k of 버려야) if (사고번호.test(k)) { console.error(`  ✗ «${k}» 를 받습니다`); 틀림++; }
if (틀림) { console.error(`열쇠 규칙이 ${틀림}건 틀렸습니다`); process.exit(1); }
console.log(`  ✓ 열쇠 규칙 — 받을 것 ${받아야.length}개 받고, 버릴 것 ${버려야.length}개 버립니다`);
