# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""집계에서 «몇 명이 겪었나» 를 읽어 카탈로그의 evidence.users 만 고칩니다.

**고치는 칸은 `users` 하나뿐입니다.** 사고 문장(story·symptom·fix·blind)은
절대 안 건드립니다 — 그건 겪은 사람만 쓸 수 있고, 기계가 쓰기 시작하면
«지어내지 않는다» 가 무너집니다.

그리고 **YAML 을 다시 쓰지 않습니다.** 통째로 읽고 쓰면 주석이 전부 날아갑니다.
`users: N` 그 한 줄만 바꿉니다.

이건 저장소 쪽에서만 돕니다. 사용자 컴퓨터의 프로그램은 카탈로그를 못 씁니다.
"""

import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
VIBE = ROOT / "vibe.yaml"
AGG = ROOT / "집계.json"


def main():
    if not AGG.exists():
        print("집계가 없습니다.")
        return 0
    집계 = json.loads(AGG.read_text(encoding="utf-8"))
    사람 = 집계.get("사람") or {}
    if not 사람:
        print("사람 수가 아직 없습니다. 워커가 새 판인지 확인하세요.")
        return 0

    글 = VIBE.read_text(encoding="utf-8")
    d = yaml.safe_load(글)
    번호맵 = {v["id"]: k for k, v in d["incidents"].items()}

    바뀜 = 0
    for 번호, n in 사람.items():
        키 = 번호맵.get(번호)
        if not 키:
            continue                      # 모르는 번호는 무시합니다
        지금 = d["incidents"][키]["evidence"]["users"]
        새것 = max(1, int(n))
        if 새것 <= 지금:
            continue                      # **줄이지 않습니다.** 겪은 사실은 사라지지 않습니다
        # 그 사고 블록 안의 `users:` 한 줄만 바꿉니다
        시작 = 글.index(f"\n  {키}:\n")
        끝 = 글.find("\n  ", 글.index("evidence", 시작))
        끝 = len(글) if 끝 < 0 else 끝
        조각 = 글[시작:끝]
        새조각 = re.sub(r"users: \d+", f"users: {새것}", 조각, count=1)
        if 새조각 != 조각:
            글 = 글[:시작] + 새조각 + 글[끝:]
            바뀜 += 1
            print(f"  {번호}: {지금} → {새것}명")

    if not 바뀜:
        print("바뀔 게 없습니다.")
        return 0

    # 고치고 나서 **다시 읽어 확인합니다.** 사고 문장이 하나라도 달라졌으면 되돌립니다.
    새d = yaml.safe_load(글)
    for 키, v in d["incidents"].items():
        for 칸 in ("id", "name", "symptom", "story", "fix", "blind", "status"):
            if 새d["incidents"][키].get(칸) != v.get(칸):
                print(f"멈춤 — {키} 의 «{칸}» 이 바뀌었습니다. 아무것도 안 고칩니다.")
                return 1
    VIBE.write_text(글, encoding="utf-8")
    print(f"{바뀜}건의 근거를 갱신했습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
