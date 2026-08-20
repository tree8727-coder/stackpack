# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml", "certifi"]
# ///
"""selftest.py — 이 저장소가 스스로를 검사하는 곳.

vibe.py 에서 떼어냈습니다. 495줄짜리 함수 하나가 1,773줄 파일 안에 있었고,
그 상태에서 문자열 치환으로 고치다 파일을 두 번 깨뜨렸습니다 — 우리 사고 E26 입니다.
우리가 남에게 «800줄 넘으면 쪼개라» 고 하면서 우리가 안 쪼개면 아무도 안 믿습니다.

`Path(__file__)` 을 `Path(vibe.__file__)` 로 바꾼 것이 이 이사의 유일한 함정이었습니다.
그대로 두면 **검사가 자기 자신을 검사하게 되어** 늘 통과합니다(E10 과 같은 병).
"""

import tempfile

import vibe
from vibe import *          # noqa: F401,F403 — 검사 본문이 쓰는 이름을 그대로 씁니다
from vibe import _guard_cmd   # 밑줄 이름은 import * 로 안 옵니다


def _카탈로그_규율(data):
    """사고 기록이 규율을 지키는가 — 단점·증상·고유성·이슈 번호·표본"""
    incidents, statuses = data["incidents"], data["statuses"]

    # 1. 데이터 규율 — validate 와 같은 함수를 씁니다(두 벌로 안 만듭니다)
    validate(data)
    번호 = [inc["id"] for inc in incidents.values()]
    assert len(번호) == len(set(번호)), f"사고 번호가 겹칩니다: {번호}"

    # 1-1b. 「당연어」만 있는 사고는 정보가 0 입니다.
    #        카페 글의 «커피» 처럼, 이 바닥에서 당연히 나오는 말만 있으면 아무것도
    #        안 알려줍니다. 그래서 **고유한 것이 최소 하나** 있어야 합니다 —
    #        숫자(시간·금액·건수) · 파일 이름 · 오류 문구 중 하나.
    #        (달나루 회의록: 자동 생성 페이지가 얇으면 저품질로 분류된다 — 같은 방어선)
    #        영문 식별자(inner_text, fly.toml)도 «고유한 것» 으로 봅니다 —
    #        한국어 문장 안의 ASCII 토막은 거의 항상 그 사고에만 있는 이름입니다.
    고유함 = re.compile(r"\d|[A-Za-z_.]{3,}|`[^`]+`|«[^»]+»")
    for k, inc in incidents.items():
        재료 = inc["story"] + " " + " ".join(inc["fix"])
        assert 고유함.search(재료), (
            f"{k}: 숫자도 파일 이름도 오류 문구도 없습니다 — "
            "당연한 말만 있는 사고는 싣지 않습니다")

    # 1-1b2. 이슈로 들어온 사고는 **그 이슈 번호를 잃으면 안 됩니다.**
    #         제보자가 자기 사고를 못 찾으면 두 번째 제보가 안 옵니다.
    #         실제로 오답노트를 다시 쓰면서 #1~#10 연결이 통째로 끊겼었습니다.
    # «#1» 이 «#10» 을 잡는지 실제로 확인합니다
    가짜 = "#10 본인, ERRORS.md"
    assert not re.search(r"#1(?!\d)", 가짜), "이슈 번호 찾기가 #1 로 #10 을 잡습니다"
    assert re.search(r"#10(?!\d)", 가짜), "이슈 번호 찾기가 #10 을 못 잡습니다"

    이슈있음 = [i["id"] for i in incidents.values()
             if any("#" in s for s in i["evidence"]["sources"])]
    assert 이슈있음, "이슈 번호가 붙은 사고가 하나도 없습니다 — 제보 추적이 끊겼습니다"
    for k, inc in incidents.items():
        번호 = [s for s in inc["evidence"]["sources"] if s.startswith("#")]
        for s in 번호:
            assert re.match(r"^#\d+\b", s), f"{k}: 이슈 번호 모양이 아닙니다 — {s}"

    # 1-1c. 표본이 늘고 있는지 눈에 보이게 합니다. 전부 users:1 이면 그건 한 사람의
    #        기록이지 카탈로그가 아닙니다. (막지는 않습니다 — 사실을 감추면 더 나쁩니다)
    혼자 = sum(1 for i in incidents.values() if i["evidence"]["users"] == 1)
    if 혼자 == len(incidents):
        print(f"  ! 사고 {len(incidents)}건이 전부 users:1 입니다 — 아직 한 사람의 기록입니다")

    # 1-2. 증상이 규칙문이 아니라 **상황**인지. "~해라" 로 끝나면 AI 가 못 알아봅니다.
    for k, inc in incidents.items():
        s = inc["symptom"].strip()
        assert not s.endswith(("한다", "해라", "하라", "않는다")), \
            f"{k}: symptom 이 규칙문입니다 — 「~하려 할 때」 같은 상황으로 적으세요"
        assert "때" in s or "경우" in s, f"{k}: symptom 에 언제인지가 없습니다"

    # 1-3. 만들어낸 본문에 네 칸이 다 들어가는지
    for k, inc in incidents.items():
        b = body_for(inc)
        for 표 in ("이럴 때 해당된다", "실제로 있었던 일", "그래서 이렇게 한다",
                   "이렇게 해도 안 잡히는 것"):
            assert 표 in b, f"{k}: 만들어낸 글에 「{표}」 가 없습니다"

    # 1-4. caught_by 가 진짜 있는 검사를 가리키는지. 없는 검사를 약속하면 안 됩니다.
    _check = load_check()
    if _check is not None:
        있는검사 = {f.__name__ for f in _check.CHECKS}
        for k, inc in incidents.items():
            if c := inc.get("caught_by"):
                assert c in 있는검사, f"{k}: 없는 검사를 가리킵니다 — {c}"
    else:
        assert not (ROOT / "check.py").exists(), "옆에 check.py 가 있는데 못 불러옵니다"

    # 2. '최적' 이라고 쓰지 않는다는 규율을 기계로 못박습니다
    text = VIBE.read_text(encoding="utf-8")
    for line_no, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue  # 규칙을 설명하는 주석에는 그 단어가 나올 수밖에 없습니다
        for w in 금지어:
            assert w not in line, f"vibe.yaml:{line_no} '{w}' — 표본이 세 자리가 되기 전엔 못 씁니다"

    # 3. 확인 날짜가 오래되면 일부러 실패합니다
    age = (date.today() - data["meta"]["checked"]).days
    assert age <= STALE_DAYS, f"meta.checked 가 {age}일 지났습니다. 다시 보고 날짜를 고치세요"

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        # 4. 미리보기는 파일을 하나도 만들지 않는다
        do_apply(data, ["all"], tmp, execute=False)
        assert not list(tmp.iterdir()), f"미리보기인데 파일이 생겼습니다: {list(tmp.iterdir())}"

        # 5. 실제 적용은 파일을 만든다
        do_apply(data, ["all"], tmp, execute=True)
        made = sorted(p.name for p in tmp.iterdir())
        assert made, "적용했는데 아무 파일도 안 생겼습니다"
        for _, _, sp in surface_paths(data, "project", tmp):
            assert sp.exists(), f"{sp.name} 이 안 만들어졌습니다 — 도구 하나가 빠졌습니다"
        first = {sp: sp.read_text(encoding="utf-8")
                 for _, _, sp in surface_paths(data, "project", tmp)}

        # 6. 두 번 돌려도 안 늘어난다
        do_apply(data, ["all"], tmp, execute=True)
        for sp, was in first.items():
            assert sp.read_text(encoding="utf-8") == was, f"{sp.name}: 두 번 적용하니 달라졌습니다"

        # 6-2. .bak 이 "원본" 이어야 한다 — 중간 상태가 남으면 되돌리기가 거짓말이 됩니다
        for sp in first:
            sp.write_text("원본입니다\n", encoding="utf-8")
            bak = sp.with_suffix(sp.suffix + ".bak")
            bak.unlink(missing_ok=True)
        do_apply(data, ["all"], tmp, execute=True)
        for sp in first:
            bak = sp.with_suffix(sp.suffix + ".bak")
            assert bak.read_text(encoding="utf-8") == "원본입니다\n", \
                f"{bak.name} 이 원본이 아닙니다 — 중간 상태가 덮어썼습니다"

        # 7. 남이 쓴 내용을 절대 안 지운다
        for sp, was in first.items():
            sp.write_text("# 내가 쓴 거\n건드리지 마\n" + was, encoding="utf-8")
        do_apply(data, ["all"], tmp, execute=True)
        for sp in first:
            assert "건드리지 마" in sp.read_text(encoding="utf-8"), f"{sp.name}: 남의 내용이 사라졌습니다"



def _놓이는_자리(data):
    """규칙이 어느 파일에 놓이는가 — 전역 경로·도구별 분리·갱신 경로"""
    incidents, statuses = data["incidents"], data["statuses"]

    # 8. 전역 경로가 정말 홈 밑인지. 여기를 잘못 잡으면 남의 설정을 통째로 건드립니다.
    for k, _, path in surface_paths(data, "global", ROOT):
        assert Path.home() in path.parents, f"{k}: 전역 경로가 홈 밖입니다 — {path}"
        assert ROOT not in path.parents, f"{k}: 전역 경로가 저장소 안을 가리킵니다 — {path}"

    # 9. Gemini CLI 와 같은 파일을 쓰지 않는다 (google-gemini/gemini-cli#16058).
    #    ~/.gemini/GEMINI.md 는 두 도구가 하드코딩해 서로 덮어씁니다. AGENTS.md 를 씁니다.
    for k, _, path in surface_paths(data, "global", ROOT):
        assert path.name != "GEMINI.md", f"{k}: GEMINI.md 는 Gemini CLI 와 충돌합니다"

    # 10. 도구마다 각자의 파일에 들어간다 — 한 도구만 받고 끝나면 안 됩니다
    tmp_names = {p.name for _, _, p in surface_paths(data, "project", Path("/tmp"))}
    assert len(tmp_names) == len(data["surfaces"]), "도구 둘이 같은 파일을 가리킵니다"

    # 10-2. 저장소 안에서는 캐시가 아니라 저장소 파일을 읽어야 한다
    assert (ROOT / ".git").exists(), "이 검사는 저장소 안에서 돌려야 합니다"
    assert source() == VIBE, f"저장소 안인데 {source()} 를 읽고 있습니다"

    # 11. 배포판 갱신 경로 — 평문 http 금지, 캐시가 홈 밑, validate 가 실제로 잡는지
    assert REMOTE.startswith("https://"), "REMOTE 가 https 가 아닙니다"
    assert Path.home() in CACHE.parents, f"캐시가 홈 밖입니다: {CACHE}"
    # 인증서 검증을 끄는 코드가 슬며시 들어오는 걸 막습니다
    src = Path(vibe.__file__).read_text(encoding="utf-8")
    for 금지 in ("_create_unverified_context", "CERT_NONE", "verify=False"):
        assert 금지 not in src.replace(f'"{금지}"', ""), f"인증서 검증을 끄는 코드: {금지}"
    validate(data)
    나쁜것 = {"statuses": data["statuses"], "surfaces": data["surfaces"],
             "incidents": {"x": {"id": "X", "name": "n", "symptom": "s",
                                 "story": "t", "blind": "", "fix": ["f"],
                                 "status": "검증됨",
                                 "evidence": {"users": 1, "sources": ["#1"]}}}}
    try:
        validate(나쁜것)
        raise AssertionError("validate 가 blind 빈 사고를 통과시켰습니다")
    except AssertionError as e:
        assert "blind" in str(e), e



def _되돌리기와_관문(data):
    """되돌리기가 남의 글을 지키는가, 관문이 막을 것만 막는가"""
    incidents, statuses = data["incidents"], data["statuses"]

    # 7-2. 되돌리기가 **남이 쓴 글은 안 지우고** 우리 것만 빼내는가.
    #      끝 표시가 없으면 "다음 표시까지" 를 지우게 되고, 그 사이에 사람이
    #      써 넣은 글이 같이 사라집니다. 그래서 여기서 일부러 사이에 끼워 봅니다.
    with tempfile.TemporaryDirectory() as td2:
        tmp2 = Path(td2)
        원본 = "# 내가 먼저 쓴 것\n지우지 마\n"
        for _, _, sp in surface_paths(data, "project", tmp2):
            sp.write_text(원본, encoding="utf-8")
        do_apply(data, ["all"], tmp2, execute=True, quiet=True)
        for _, _, sp in surface_paths(data, "project", tmp2):
            글 = sp.read_text(encoding="utf-8")
            i = 글.index(end_marker(INDEX_KEY))
            j = 글.index("\n", i) + 1
            sp.write_text(글[:j] + "\n## 블록 사이에 내가 끼워 넣은 글\n" + 글[j:],
                          encoding="utf-8")
        undo(data, tmp2, "project", execute=True)
        for _, _, sp in surface_paths(data, "project", tmp2):
            남은 = sp.read_text(encoding="utf-8") if sp.exists() else ""
            assert "지우지 마" in 남은, "되돌리기가 남이 먼저 쓴 글을 지웠습니다"
            assert "끼워 넣은 글" in 남은, "되돌리기가 블록 사이의 글을 지웠습니다"
            assert "vibe:" not in 남은, f"되돌렸는데 스택팩 글이 남았습니다: {sp.name}"

    # 7-2b. 끝 표시가 없던 옛 블록도 알아보고 새 모양으로 바꾸는가.
    #       그리고 **글자가 조금이라도 다르면 손대지 않는가** — 옛것인 척하는
    #       남의 글을 지우면 안 됩니다.
    with tempfile.TemporaryDirectory() as td4:
        tmp4 = Path(td4)
        키 = INDEX_KEY
        # 프로젝트 범위는 이제 «해당되는 것만» 넣으므로 기대값도 같은 방식으로 만듭니다
        본문 = index_block(data, 해당되는_사고(data, tmp4)).rstrip("\n")
        옛것 = legacy_block(키, 본문)
        남의것 = f"\n{marker(키)}-비슷한거\n내가 쓴 글\n"
        for _, _, sp in surface_paths(data, "project", tmp4):
            sp.write_text("머리말\n" + 옛것 + 남의것, encoding="utf-8")
        do_apply(data, ["all"], tmp4, execute=True, quiet=True)
        for _, _, sp in surface_paths(data, "project", tmp4):
            글 = sp.read_text(encoding="utf-8")
            assert end_marker(키) in 글, "옛 블록이 새 모양으로 안 바뀌었습니다"
            assert 글.count(marker(키) + "\n") == 1, "옛 블록 옆에 새 블록이 또 붙었습니다"
            assert "내가 쓴 글" in 글, "비슷하게 생긴 남의 글을 건드렸습니다"
        undo(data, tmp4, "project", execute=True)
        for _, _, sp in surface_paths(data, "project", tmp4):
            남은 = sp.read_text(encoding="utf-8") if sp.exists() else ""
            assert "머리말" in 남은 and "내가 쓴 글" in 남은, "되돌리기가 남의 글을 지웠습니다"

    # 7-2c. 이름이 바뀌어 카탈로그에서 사라진 항목(고아)이 남의 파일에 계속
    #       쌓이면 안 됩니다. 적용할 때 치우고, 사람 글은 그대로 둡니다.
    with tempfile.TemporaryDirectory() as td5:
        tmp5 = Path(td5)
        고아 = "\n<!-- vibe:옛날에쓰던항목 -->\n## 옛 내용\n<!-- /vibe:옛날에쓰던항목 -->\n"
        for _, _, sp in surface_paths(data, "project", tmp5):
            sp.write_text("내 글\n" + 고아, encoding="utf-8")
        do_apply(data, ["all"], tmp5, execute=True, quiet=True)
        for _, _, sp in surface_paths(data, "project", tmp5):
            글 = sp.read_text(encoding="utf-8")
            assert "옛날에쓰던항목" not in 글, "고아 블록이 안 치워졌습니다"
            assert "내 글" in 글, "고아를 치우다 사람 글을 지웠습니다"
            assert marker(INDEX_KEY) in 글, "치우기만 하고 새로 안 넣었습니다"
        undo(data, tmp5, "project", execute=True)
        for _, _, sp in surface_paths(data, "project", tmp5):
            남은 = sp.read_text(encoding="utf-8") if sp.exists() else ""
            assert "vibe:" not in 남은, "되돌렸는데 블록이 남았습니다"
            assert "내 글" in 남은, "되돌리기가 사람 글을 지웠습니다"

    # 7-3. 우리가 만든 빈 파일은 되돌릴 때 지웁니다 (쓰레기를 안 남깁니다)
    with tempfile.TemporaryDirectory() as td3:
        tmp3 = Path(td3)
        do_apply(data, ["all"], tmp3, execute=True, quiet=True)
        undo(data, tmp3, "project", execute=True)
        남은파일 = [f.name for f in tmp3.iterdir() if not f.name.endswith(".bak")]
        assert not 남은파일, f"되돌렸는데 파일이 남았습니다: {남은파일}"

    # 11-2. 안내 문구가 실행 이름을 박아두면 깔아 쓰는 사람에게 없는 명령을 알려주게 됩니다
    src = Path(vibe.__file__).read_text(encoding="utf-8")
    # prog() 안의 한 번(정의)만 허용합니다. 두 번째부터는 박아 넣은 것입니다.
    # 찾는 문자열을 이어붙여 만듭니다 — 여기 그대로 적으면 이 검사 자신이 걸립니다.
    needle = "uv run " + "vibe" + ".py"
    쓰인수 = src.count(needle)
    assert 쓰인수 == 2, f"실행 이름이 {쓰인수}번 나옵니다 (정의 2줄만 허용) — prog() 를 쓰세요"

    # 11-3. 관문 — 막아야 할 것을 막고, 멀쩡한 것은 통과시키는가.
    #        둘 다 치명적입니다. 못 막으면 쓸모가 없고, 잘못 막으면 지워집니다.
    g = None
    try:
        from . import guard as g
    except ImportError:
        try:
            import guard as g
        except ImportError:
            pass
    if g is not None:
        막아야 = [
            ("Write", {"file_path": "a/config.py",
                       "content": 'K = "sk-ant-' + "a" * 30 + '"'}, "E8"),
            ("Write", {"file_path": "a/pay.js",
                       "content": "const x = '국민 123456-01-234567';"}, "E8"),  # check:ignore
            ("Write", {"file_path": "a/server.js",
                       "content": "app.use(express.static(__dirname));"}, "E7"),
            ("Write", {"file_path": "a/fly.toml",
                       "content": "auto_stop_machines = 'off'\nmin_machines_running = 1"}, "E13"),
            ("Bash", {"command": "git add .env"}, "E5"),
        ]
        막아야 += [
            ("Bash", {"command": "git add .env"}, "E5"),
            ("Bash", {"command": "cd app && git add src/.env"}, "E5"),
            ("Bash", {"command": "git add -A; git add .env.production"}, "E5"),
        ]
        for tool, ti, 사고 in 막아야:
            r = g.판정(tool, ti)
            assert r is not None, f"관문이 {사고} 를 못 막았습니다: {ti}"
            assert r[1] == 사고, f"관문이 {사고} 를 {r[1]} 로 봤습니다"
            assert r[0] == "deny", f"{사고} 는 막아야 합니다 (지금 {r[0]})"

        영상 = [
            ("ffmpeg -ss 24.1 -i cam2.mp4 -t 12 out.mp4", "E29"),
            ("ffmpeg -i in.wav -af loudnorm=I=-16 out.wav", "E30"),
        ]
        for 명령, 사고 in 영상:
            r = g.판정("Bash", {"command": 명령})
            assert r and r[1] == 사고, f"관문이 {사고} 를 못 봤습니다: {명령}"
            assert r[0] == "escalate", f"{사고} 는 막지 말고 물어봐야 합니다 (오탐이 지워지게 만듭니다)"
        for 멀쩡 in ("ffmpeg -ss 20 -i a.mp4 -filter_complex trim=start=4 -frames:v 300 o.mp4",
                    "ffmpeg -i in.wav -af loudnorm=I=-16,aresample=48000 o.wav",
                    "ffmpeg -i a.mp4 -c copy b.mp4"):
            assert g.판정("Bash", {"command": 멀쩡}) is None, f"관문이 멀쩡한 걸 막았습니다: {멀쩡}"

        물어봐야 = g.판정("Write", {"file_path": "a/test_e2e.py",
                                  "content": 'A("x" not in pg.inner_text("#b"))'})
        assert 물어봐야 and 물어봐야[0] == "escalate", "E10 은 사람에게 물어봐야 합니다"

        통과해야 = [
            # 오탐으로 실제 커밋이 막혔던 것들 — 명령 안에 «.env» 라는 글자가
            # 무관하게 들어 있어도 막으면 안 됩니다. 오탐 나는 도구는 지워집니다.
            ("Bash", {"command": "git add -A && git commit -m '.env 를 gitignore 에 넣었다'"}),
            ("Bash", {"command": "echo '.env 설명' > 문서.md && git add 문서.md"}),
            ("Bash", {"command": "git add .env.example"}),
            ("Bash", {"command": "git status && grep -r .env ."}),
            ("Write", {"file_path": "a/README.md", "content": "# 안녕하세요\n설명입니다."}),
            ("Write", {"file_path": "a/app.py", "content": "KEY = os.environ['K']"}),
            ("Bash", {"command": "git add ."}),
            ("Bash", {"command": "npm test"}),
            ("Write", {"file_path": "a/.env.example", "content": "KEY=여기에_본인_키"}),
            ("Write", {"file_path": "a/fly.toml",
                       "content": "auto_stop_machines = 'on'\nmin_machines_running = 0"}),
        ]
        for tool, ti in 통과해야:
            r = g.판정(tool, ti)
            assert r is None, f"관문이 멀쩡한 걸 막았습니다: {ti} → {r}"

        # 터지면 통과시켜야 합니다. 관문이 편집기를 멈추게 하면 사람은 이걸 지웁니다.
        assert g.판정("Write", {"file_path": None, "content": None}) is None or True
        import io, contextlib
        오염 = io.StringIO()
        with contextlib.redirect_stdout(오염):
            sys.stdin = io.StringIO("이건 JSON 이 아닙니다")
            rc = g.main()
            sys.stdin = sys.__stdin__
        assert rc == 0 and not 오염.getvalue().strip(), "쓰레기 입력에 관문이 죽었습니다"



def _설정과_배포(data):
    """설정·색인·감지·배포·실험·진단·통계, 그리고 문서의 숫자"""
    incidents, statuses = data["incidents"], data["statuses"]

    # 11-4. 관문 켜기/끄기가 남의 설정을 안 건드리는가. 그리고 명령줄에 주석을
    #        붙이지 않는가 — 윈도우에서는 `#` 이 주석이 아니라 인자가 됩니다.
    cmd = _guard_cmd()
    assert "#" not in cmd, f"훅 명령에 주석이 붙었습니다 (윈도우에서 깨집니다): {cmd}"

    # 11-4d. 훅은 **사용자 전역에만** 씁니다. 프로젝트 설정에 훅을 심으면,
    #        그 저장소를 여는 남의 AI 가 우리 코드를 실행하게 됩니다.
    #        2026-02 에 바로 그 경로로 CVE 가 났습니다(.claude/settings.json 훅).
    assert SETTINGS == Path.home() / ".claude" / "settings.json", \
        f"설정 경로가 사용자 전역이 아닙니다: {SETTINGS}"
    # 찾는 글자를 이어붙여 만듭니다. 그대로 적으면 이 검사 자신이 걸립니다
    # — E27 을 여기서 또 밟았습니다.
    src_v = Path(vibe.__file__).read_text(encoding="utf-8")
    for 조각 in (("settings.local", ".json"), ("Path.cwd()", ' / ".claude"')):
        금지 = "".join(조각)
        assert src_v.count(금지) <= 1, f"프로젝트 설정을 건드리는 코드가 있습니다: {금지}"

    # 11-4e. 되돌림 기록에 **원문이 안 들어가는지**. 들어가면 그 파일이 새는 순간 코드가 샙니다.
    g2 = None
    try:
        from . import guard as g2
    except ImportError:
        try:
            import guard as g2
        except ImportError:
            pass
    if g2 is not None:
        import inspect as _i2
        기록소스 = _i2.getsource(g2.쓴것_기록) + _i2.getsource(g2.되돌림_확인)
        for 조각 in (("cont", "ent"), ("new_", "string"), ("old_", "string")):
            금지 = "".join(조각)
            assert 금지 not in 기록소스, f"되돌림 기록이 원문을 남기려 합니다: {금지}"
        assert "지문(" in 기록소스, "되돌림 기록이 해시를 안 씁니다"

    # 11-4b. 규칙 파일에 들어가는 색인이 **짧아야** 합니다. 전문을 매 세션 주입하면
    #         토큰만 먹고 안 읽힙니다 — 재원이 지적한 바로 그 문제입니다.
    색인 = index_block(data)
    assert len(색인.splitlines()) <= len(incidents) + 10, \
        f"색인이 {len(색인.splitlines())}줄입니다 — 전문이 새어 들어갔습니다"
    for 표 in ("실제로 있었던 일", "이렇게 해도 안 잡히는 것"):
        assert 표 not in 색인, f"색인에 전문({표})이 들어갔습니다"

    # 11-4f. 순서를 바꾸다가 사고를 **빠뜨리면 안 됩니다.** 개인 적응이 카탈로그를
    #        조용히 줄이는 순간, 그건 개선이 아니라 손실입니다.
    가짜기록 = {"E8": 5, "E13": 2}
    번호맵 = {i["id"]: k for k, i in incidents.items()}
    for 아이디 in 가짜기록:
        assert 아이디 in 번호맵, f"검사가 없는 사고 번호를 씁니다: {아이디}"
    색인줄 = [l for l in index_block(data).splitlines() if l.startswith("- **[")]
    assert len(색인줄) <= INDEX_MAX, \
        f"색인이 {len(색인줄)}줄입니다 — 지시 예산 {INDEX_MAX} 을 넘었습니다"
    # 예산 자체에도 상한을 둡니다. 상수를 키우면 위 검사가 무력해지므로,
    # 늘리려면 이 줄을 일부러 고쳐야 합니다 — 그때 근거를 대야 합니다.
    assert INDEX_MAX <= 15, (
        f"지시 예산이 {INDEX_MAX} 입니다. 지시가 늘수록 따르는 정확도가 떨어진다는 "
        "측정이 있습니다(IFScale arXiv:2507.11538, 다중 제약 10~15%p arXiv:2407.03978). "
        "늘리려면 그보다 나은 근거가 필요합니다.")
    # 색인에서 뺀 것은 **버린 게 아니라 스킬에 있어야** 합니다. 조용히 사라지면 손실입니다.
    스킬2 = skill_text(data)
    for k, inc in incidents.items():
        assert inc["name"] in 스킬2, f"{k} 가 색인에서도 스킬에서도 빠졌습니다"
    # 심각한 것이 먼저 나와야 합니다 — 드문 것과 안 중요한 것은 다릅니다
    높은것 = [i["id"] for i in incidents.values()
            if i.get("severity") == "높음" and not i.get("caught_by")]
    if 높은것 and 색인줄:
        assert any(h in 색인줄[0] for h in 높은것), \
            f"심각도 높은 사고가 첫 줄에 없습니다: {색인줄[0][:40]}"

    # 11-4c2. 도메인 사고가 남의 색인을 오염시키지 않는지. 코딩만 하는 사람에게
    #          영상 사고가 뜨면 그건 지시 예산을 훔치는 것입니다.
    with tempfile.TemporaryDirectory() as td6:
        코딩만 = Path(td6)
        (코딩만 / "app.py").write_text("x = 1\n", encoding="utf-8")
        (코딩만 / "package.json").write_text("{}\n", encoding="utf-8")
        고른것 = 해당되는_사고(data, 코딩만)
        # 이름을 직접 박습니다. «영상 전용인지» 를 무늬로 추론하려다 한 번 틀렸습니다 —
        # when 에 *.sh 가 섞여 있어서 분류가 빗나갔고, 검사가 조용히 통과했습니다.
        영상만 = ["시크위치로-영상만-밀림", "라우드놈-뒤-리샘플-누락", "받은-파일이-깨져-있었다"]
        for k in 영상만:
            assert k in incidents, f"검사가 없는 사고를 가리킵니다: {k}"
            assert k not in 고른것, (
                f"코딩만 하는 프로젝트(app.py · package.json)에 «{k}» 가 들어갑니다 — "
                "when 으로 걸러야 합니다")
        assert len(고른것) < len(incidents), "감지가 아무것도 못 걸러냅니다"

    # 11-4c. 프로젝트 감지는 **파일 이름만** 봅니다. 내용을 읽으면 안 됩니다.
    import inspect as _ins
    소스 = _ins.getsource(프로젝트_파일이름) + _ins.getsource(이_프로젝트에_해당되나)
    for 금지 in ("read_text", "read_bytes", "open("):
        assert 금지 not in 소스, f"프로젝트 감지가 파일 내용을 읽고 있습니다: {금지}"
    # 그리고 스킬에는 전문이 다 있어야 합니다
    스킬 = skill_text(data)
    for k, inc in incidents.items():
        assert inc["name"] in 스킬, f"스킬에 {k} 가 빠졌습니다"
    assert 스킬.startswith("---\nname: "), "스킬에 머리말이 없습니다"

    # 11-4g. 자동 배포 안전장치 — 여기가 제일 큰 위험입니다. 매일 받아서 남의 AI
    #         규칙에 자동으로 넣고 있으므로, 우리가 털리면 하루 만에 퍼집니다.
    import inspect as _i3
    동기소스 = _i3.getsource(do_sync)
    assert "releases/latest" in RELEASES, "태그된 판을 찾지 않습니다"
    assert "많이바뀜" in 동기소스, "한 번에 크게 바뀌는 것을 막지 않습니다"
    assert ".직전" in 동기소스, "직전 판을 남기지 않습니다"
    assert 0 < 많이바뀜 < 1, f"변경 상한이 이상합니다: {많이바뀜}"

    # 11-4h. 실험이 거짓말을 못 하게 합니다. 우리에게 유리한 결과가 나오도록
    #         설계가 기울면, 그 측정은 안 하느니만 못합니다.
    import inspect as _i4
    실험소스 = _i4.getsource(실험_진행) + _i4.getsource(실험_결과)

    # ① 작업량으로 나눠야 합니다. 횟수만 세면 바쁜 주가 이겼다고 나옵니다
    assert "쓰기" in 실험소스, "작업량으로 정규화하지 않습니다"
    # 쓰기 수를 일부러 다르게 둡니다. 같게 두면 «나누는지» 를 구분할 수 없습니다.
    켬, 끔, _, _ = 실험_결과({"기간": [
        {"단계": "켬", "막힘": 2, "쓰기": 200},   # 1.0
        {"단계": "끔", "막힘": 9, "쓰기": 100}]})  # 9.0
    assert abs(켬 - 1) < 1e-9 and abs(끔 - 9) < 1e-9, \
        f"작업량으로 안 나누고 있습니다 (켬 {켬}, 끔 {끔} — 기대 1, 9)"

    # ② 실험 «끔» 주간에도 **관문은 켜져 있어야** 합니다. 안전이 내려가면 안 됩니다
    끔소스 = _i4.getsource(plan)
    assert "관문은 계속 켜져" in 끔소스, "실험이 관문까지 끄고 있습니다"
    assert "hook_off" not in 끔소스 and "schedule_off" not in 끔소스, \
        "실험이 관문·자동갱신을 건드립니다"

    # ③ 양쪽 자료가 2주씩 모이기 전에는 결론을 내지 않습니다
    assert "각 2주가 안 돼" in _i4.getsource(do_report), "표본이 적을 때 결론을 냅니다"

    # 11-4i. 진단기가 «남의 것» 을 안 보는지. 우리가 볼 것은 AI 에게 주입되는
    #         설정 파일뿐입니다. 대화 기록이나 프로젝트 코드를 보기 시작하면
    #         「서버 없음·대화 안 봄」 이라는 우리 문장이 거짓말이 됩니다.
    import inspect as _i5
    진단소스 = _i5.getsource(do_diagnose)
    for 조각 in (("trans", "cripts"), ("hist", "ory.jsonl"), ("sess", "ions")):
        금지 = "".join(조각)
        assert 금지 not in 진단소스, f"진단기가 대화 기록을 봅니다: {금지}"
    # 토큰 추정은 한 곳에서만 합니다(P5)
    assert "/ 1.7" not in 진단소스, "토큰 추정이 두 벌입니다 — 글자_토큰 하나만 쓰세요"
    assert "글자_토큰(" in 진단소스, "진단기가 공용 추정 함수를 안 씁니다"

    # 11-4j. 나가는 것이 «사고 번호와 횟수» 뿐인지. 여기가 새면 이 프로젝트의
    #         모든 문장이 거짓말이 됩니다.
    import inspect as _i6
    보내기소스 = _i6.getsource(보낼것) + _i6.getsource(통계_보내기) + _i6.getsource(설치id)
    # 「content」 를 통째로 막았더니 content-type **헤더**를 잡았습니다 — 우리 E16 과
    # 같은 병(규칙이 엉뚱한 걸 잡음)이라, 기계 정보를 뽑는 함수 이름만 정확히 봅니다.
    # 무엇이 실제로 나가는지는 아래 «열쇠» 검사가 못박습니다 — 그쪽이 본검사입니다.
    for 조각 in (("Path.cw", "d()"), ("plat", "form."), ("get", "node"),
                 ("uname", "()"), ("hostn", "ame")):
        금지 = "".join(조각)
        assert 금지 not in 보내기소스, f"보내기가 기계 정보를 씁니다: {금지}"
    # 보내는 몸통에 counts·install 말고 다른 열쇠가 있으면 안 됩니다
    본문 = re.search(r'json\.dumps\(\{([^}]*)\}\)\.encode', 보내기소스)
    assert 본문, "보내는 내용을 확인할 수 없습니다"
    열쇠 = set(re.findall(r'"(\w+)":', 본문.group(1)))
    assert 열쇠 == {"install", "counts"}, f"보내는 열쇠가 늘었습니다: {열쇠}"
    # 설치 ID 는 난수여야 합니다 — 기계에서 뽑으면 식별자가 됩니다
    assert "uuid" in _i6.getsource(설치id), "설치 ID 가 난수가 아닙니다"
    # 끌 수 있어야 합니다
    assert "STAT_OFF.exists()" in _i6.getsource(통계_보내기), "통계를 끌 수 없습니다"

    # 11-6. 플러그인이 카탈로그와 갈라지지 않는지. 플러그인은 **만들어내는 것**이라
    #        손으로 고치면 두 벌이 됩니다(P5). 그리고 갈라진 채 마켓에 올라가면
    #        남의 컴퓨터에서 낡은 사고가 돕니다.
    권 = vibe.PLUGIN_DIR
    if 권.exists():
        import yaml as _y
        플카탈로그 = _y.safe_load((권 / "hooks" / "vibe.yaml").read_text(encoding="utf-8"))
        assert set(플카탈로그["incidents"]) == set(incidents), \
            "플러그인 안의 카탈로그가 저장소와 다릅니다 — 다시 만드세요: 플러그인"
        for 파일 in ("guard.py", "check.py"):
            assert (권 / "hooks" / 파일).read_text(encoding="utf-8") == \
                (ROOT / 파일).read_text(encoding="utf-8"), \
                f"플러그인 안의 {파일} 이 원본과 다릅니다"
        훅 = json.loads((권 / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        명 = 훅["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        assert "CLAUDE_PLUGIN_ROOT" in 명, "플러그인 훅이 플러그인 경로를 안 씁니다"
        assert "#" not in 명, "훅 명령에 주석이 붙었습니다 (윈도우에서 깨집니다)"
        스킬 = (권 / "skills" / "오답노트" / "SKILL.md").read_text(encoding="utf-8")
        for k, inc in incidents.items():
            assert inc["name"] in 스킬, f"플러그인 스킬에 {k} 가 빠졌습니다"

    # 11-5. 문서에 적은 사고 건수가 실제와 맞는가.
    #        P4 가 바로 이것입니다 — 손으로 맞춘 숫자는 반드시 어긋납니다.
    #        우리가 파는 규칙을 우리가 어기면 카탈로그 전체가 우스워집니다.
    n = len(incidents)
    for 문서 in ("README.md", "사용법.md", "pyproject.toml"):
        f = ROOT / 문서
        if not f.exists():
            continue
        글 = f.read_text(encoding="utf-8")
        틀린것 = re.findall(r"사고 (\d+)건|사고 (\d+)건으로|(\d+)건 중 \d+건은", 글)
        for 짝 in 틀린것:
            for 숫자 in 짝:
                if 숫자 and int(숫자) != n:
                    raise AssertionError(
                        f"{문서} 에 사고가 {숫자}건이라고 적혀 있는데 실제는 {n}건입니다")

    # 12. 배포 설정 — 여기가 어긋나면 남한테는 깨진 채로 나갑니다
    pyproject = ROOT / "pyproject.toml"
    if pyproject.exists():          # 배포판 안에는 없습니다
        import tomllib
        cfg = tomllib.load(pyproject.open("rb"))

        # 12-1. 휠에 vibe.yaml 이 안 담기면 배포판은 첫 실행부터 죽습니다
        inc = cfg["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
        for 필수 in ("vibe.py", "vibe.yaml"):
            assert 필수 in inc, f"휠에 {필수} 가 안 담깁니다 (force-include)"
        assert inc["vibe.yaml"].rsplit("/", 1)[0] == inc["vibe.py"].rsplit("/", 1)[0], \
            "vibe.yaml 이 vibe.py 옆에 안 담깁니다 — ROOT 로 못 찾습니다"

        # 12-2. 의존성이 두 곳에 적혀 있습니다(스크립트 헤더 · pyproject).
        #       복붙된 두 벌은 반드시 갈라집니다. 여기서 대조합니다.
        src = Path(vibe.__file__).read_text(encoding="utf-8")
        header = re.search(r'# dependencies = \[(.*?)\]', src).group(1)
        헤더deps = sorted(x.strip().strip('"\'') for x in header.split(","))
        assert 헤더deps == sorted(cfg["project"]["dependencies"]), \
            f"의존성이 갈라졌습니다: 헤더 {헤더deps} vs pyproject {cfg['project']['dependencies']}"

        # 12-3. 진입점이 실제로 있는 함수를 가리키는지
        ep = cfg["project"]["scripts"]["stackpack"]
        mod, fn = ep.split(":")
        assert mod.endswith(".vibe") and fn in globals(), f"진입점이 이상합니다: {ep}"



def run(data):
    """검사를 넷으로 나눠 부릅니다.

    한 함수가 495줄이었습니다. 우리가 남에게 «200줄 넘으면 쪼개라» 고 하면서
    우리가 안 쪼개면 그 기준은 아무도 안 믿습니다(E26).
    """
    _카탈로그_규율(data)
    _놓이는_자리(data)
    _되돌리기와_관문(data)
    _설정과_배포(data)

    validate(data)
    검증됨 = sum(1 for r in data["incidents"].values() if r["status"] == "검증됨")
    검사있음 = sum(1 for i in data["incidents"].values() if i.get("caught_by"))
    도구 = ", ".join(s["name"] for s in data["surfaces"].values())
    age = (date.today() - data["meta"]["checked"]).days
    print(f"\n통과. 사고 {len(data['incidents'])}건 (검증됨 {검증됨}, "
          f"자동검사 {검사있음}) · 도구 {도구} · 확인 {age}일 전")
    return 0
