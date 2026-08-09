# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow"]
# ///
"""content-factory 콤보의 실행 예제 — 슬라이드 JSON → 인스타 카드뉴스 PNG.

    uv run examples/cardnews.py                    슬라이드 예시로 out/에 생성
    uv run examples/cardnews.py slides.json out/   내 JSON으로 생성

입력 형식 (AI에게 이 형태로 달라고 하면 됩니다):
    {"topic": "...", "hashtags": ["#a"], "slides": [{"headline": "...", "body": "...", "color": "#FF00FF"}]}

원본: startup_automation_db/combo_a_content_factory.py — 하드코딩된 슬라이드를 입력 파일로 뺐습니다.
"""

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

SIZE = 1080
FONT = "C:/Windows/Fonts/malgunbd.ttf"  # ponytail: 맑은 고딕 고정. 폰트 바꿀 일 생기면 인자로.

SAMPLE = {
    "topic": "AI로 직원 3명 몫 해내는 1인 창업가 비법",
    "hashtags": ["#1인기업", "#AI자동화", "#stackpack", "#창업", "#n8n"],
    "slides": [
        {"headline": "1인 창업가의\n가장 큰 착각", "body": "모든 걸 혼자 다 해야\n직성이 풀리시나요?", "color": "#FF00FF"},
        {"headline": "직원 대신\nAI 에이전트를 고용하라", "body": "CrewAI와 n8n이 결합되면\n24시간 지치지 않는\n마케팅 팀이 탄생합니다.", "color": "#00FFCC"},
        {"headline": "stackpack\n지금 바로 도입하기", "body": "선착순 10개 업체 대상\n무료 컨설팅을 진행합니다.\n(프로필 링크 확인!)", "color": "#39FF14"},
    ],
}


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def render(slide, path, brand="stackpack"):
    rgb = hex_rgb(slide["color"])
    img = Image.new("RGBA", (SIZE, SIZE), "#0A0A0F")

    glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((100, 100, 800, 800), fill=rgb + (60,))
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(150)))

    panel = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(panel).rounded_rectangle(
        (80, 250, 1000, 830), radius=30, fill=(25, 25, 35, 200), outline=rgb + (150,), width=3
    )
    img = Image.alpha_composite(img, panel)

    try:
        head, body, foot = (ImageFont.truetype(FONT, s) for s in (90, 55, 40))
    except OSError:
        head = body = foot = ImageFont.load_default()
        print("  경고: 맑은 고딕을 못 찾아 기본 폰트를 씁니다.", file=sys.stderr)

    d = ImageDraw.Draw(img)
    d.multiline_text((150, 320), slide["headline"], font=head, fill=slide["color"], spacing=20)
    d.multiline_text((150, 580), slide["body"], font=body, fill="#E0E0E0", spacing=15)
    d.text((150, 960), brand, font=foot, fill="#555555")

    img.convert("RGB").save(path)
    return path


def main(argv):
    data = json.loads(Path(argv[0]).read_text(encoding="utf-8")) if argv else SAMPLE
    out = Path(argv[1] if len(argv) > 1 else "out")
    out.mkdir(parents=True, exist_ok=True)

    files = [str(render(s, out / f"slide_{i}.png")) for i, s in enumerate(data["slides"], 1)]
    for f in files:
        print(f"  {f}")

    # n8n 웹훅에 그대로 던질 수 있는 페이로드
    caption = f"💡 {data['topic']}\n\n슬라이드를 넘겨 확인하세요!\n\n{' '.join(data.get('hashtags', []))}"
    payload = {"action": "AUTO_UPLOAD_INSTAGRAM", "caption": caption, "media_files": files}
    (out / "n8n_payload.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  {out / 'n8n_payload.json'}")
    print(f"\n다음: ffmpeg -framerate 1/3 -i {out}/slide_%d.png -r 30 -pix_fmt yuv420p {out}/shorts.mp4")


def demo():
    import shutil
    import tempfile

    assert hex_rgb("#FF00FF") == (255, 0, 255)
    assert hex_rgb("39FF14") == (57, 255, 20)

    tmp = Path(tempfile.mkdtemp())
    try:
        img_path = render(SAMPLE["slides"][0], tmp / "s.png")
        with Image.open(img_path) as img:  # with 없이 열면 핸들이 남아 unlink가 WinError 32
            assert img.size == (SIZE, SIZE), img.size

        # 입력 JSON 경로 + 페이로드가 connectors/n8n-cardnews.json 이 읽는 모양인지
        src = tmp / "in.json"
        src.write_text(json.dumps(SAMPLE, ensure_ascii=False), encoding="utf-8")
        main([str(src), str(tmp / "payload")])
        payload = json.loads((tmp / "payload/n8n_payload.json").read_text(encoding="utf-8"))
        assert set(payload) >= {"caption", "media_files"}, payload.keys()
        assert len(payload["media_files"]) == len(SAMPLE["slides"])
        assert payload["caption"].strip(), "caption이 비면 커넥터가 예외를 던집니다"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("cardnews demo 통과 (커넥터 페이로드 계약 포함)")


if __name__ == "__main__":
    demo() if "--demo" in sys.argv else main(sys.argv[1:])
