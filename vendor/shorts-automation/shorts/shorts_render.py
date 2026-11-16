#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shorts_render.py — '완성형' 세로 쇼츠(번인 MP4) 렌더러.
프리미어 '쇼츠' 템플릿을 이식(2026-07, 프리미어 화면 실측 + 지정 스펙):

  · 얼굴: 웹캠 크롭 → 풀와이드, 세로 중앙 + 위아래 여백 동일(각 MARGIN px)
  · 제목: Paperlogy 9Black 106~118(글자수 적응), 2줄, 1줄 흰색 + 강조줄 노랑, 상단 밴드
  · 자막: Noto Sans KR Black 90, 얼굴 아래, 흰색+외곽선, 7자 이내 '맥락' 단위(직립)
  · 워터마크: WATERMARK 문구, MaruBuriOTF SemiBold 기울임 70, 하단 여백 중앙

폰트는 engine/assets/fonts 에 번들(Paperlogy OFL / MaruBuri Naver / Noto OFL).

사용:
  python3 shorts_render.py <source.mp4> <words.json> <clips.json> [--crop w:h:x:y] [--out DIR]
  clips.json: [{"name","start","end","hook","yellow"(1|2, 선택)}, ...]  (start/end = source 초)
  --crop: 얼굴 웹캠 영역(소스 픽셀). 기본은 슬라이드+PIP 셋업 값.
          풀프레임 토킹헤드 소스면 얼굴에 맞게 조정(예: 전체 프레임이면 w=1080:h=1080:x=420:y=0 식).
"""
import sys, os, json, subprocess, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "assets", "fonts")

W, H = 1080, 1920
# ── 템플릿 지오메트리(확정 레퍼런스 실측, 2026-07) ──
VID_H = 1030              # 영상(얼굴) 세로 크기
VID_Y = 532               # 영상 상단(위 여백 = 제목 존)
TITLE_Y = 250             # 제목 블록 상단(an8)
CAP_FRAC = 0.70           # 자막 세로 위치(영상 영역 비율 — 얼굴 아래)
WM_GAP = 55               # 워터마크: 영상 바로 아래 간격
WATERMARK = "비건먼지 Veganmonji"
YELLOW = r"&H0022CCFF&"    # 골드 옐로 (BGR: R255 G204 B34)
WHITE = r"&H00FFFFFF&"
GRAY = r"&H00CFCFCF&"
# 폰트: PostScript/가중치별 패밀리명으로 지정(안 그러면 macOS CoreText가 Regular로 폴백 → 얇아짐)
F_TITLE = "Paperlogy 9 Black"
F_CAP = "Noto Sans CJK KR Black"
F_WM = "MaruBuriot-SemiBold"
# 슬라이드+PIP 소스 기본 웹캠(얼굴) 영역.
# INSET: PIP의 흰 라운드 테두리가 화면에 걸리지 않게 안쪽으로 파고 들어가 크롭.
DEFAULT_CROP = dict(w=430, h=486, x=1486, y=474)
CROP_INSET = 14


def kchars(s):
    return len(s.replace(" ", ""))


# 어절 완결 신호(이 글자로 끝나면 독립 자막 가능 — 뒤 어절을 붙이지 않음)
JOSA_END = set("은는이가을를에도만와과로게며요죠다서든까")
# 연결어미 — 조사는 아니지만 여기서 끊어도 자연스러움(나와야/올리고/해서…)
CONN_END = set("야서면며자러고나때")
# 조사로 끝나도 실제로는 독립 완결인 어절(대명사+조사)
STANDALONE = {"나는", "저는", "내가", "제가", "우리는", "저희는", "이건", "그건", "저건"}
# 1자인데 앞이 아니라 '다음' 자막 머리로 가야 하는 말(관형/부정/접속/부사)
FWD_ONE = {"그", "이", "저", "안", "못", "왜", "또", "좀", "더", "꼭", "막", "딱", "다", "잘",
           "내", "제", "네", "한", "두", "세", "몇", "각", "첫"}
# 단독 자막 금지 부사 — 뒤 어절에 붙어야 맥락이 산다
ADV_FWD = {"정말", "진짜", "너무", "가장", "제일", "아주", "매우", "훨씬", "그냥", "계속",
           "바로", "일단", "특히", "결국", "아직", "이미", "거의", "금방", "방금", "절대",
           "전혀", "별로", "항상", "완전", "완전히", "무조건", "반드시", "굉장히", "충분히"}
# 관형사 — 반드시 뒤 명사와 한 자막
DET_FWD = {"이런", "그런", "저런", "어떤", "무슨", "모든", "여러", "몇", "새로운", "같은",
           "많은", "작은", "큰", "좋은", "다른", "진짜로"}
# 관형형/연결형 어미로 끝나는 어절 — 뒤 어절과 결합해야 완결
_BIND_SUFF = ("하는", "되는", "있는", "없는", "같은", "보는", "가는", "오는", "아닌",
              "라는", "다는", "려는", "위한", "대한", "관한", "않은", "않는", "드는")
# ㄹ-관형형(유지할/않을…) — 뒤 의존명사·명사와 결합
_L_ADNOM = ("할", "될", "낼", "볼", "갈", "올", "않을", "싶을", "있을", "없을")
# 의존명사 머리 — 앞 어절(관형형)에 붙고, 붙은 뒤엔 덩어리를 닫는다
_DEP_HEAD = ("수", "것", "게", "줄", "만큼", "정도", "때문", "뿐", "중", "등")
# 보조용언 머리 — 앞 어절에 붙고 덩어리를 닫는다(있게 되죠)
_AUX = {"있게", "있습니다", "있어요", "있죠", "없습니다", "없어요", "됩니다", "되죠", "돼요", "되고"}


def _hard_bind(core, nxt_core):
    """이 어절이 다음 어절과 '반드시' 한 자막이어야 하는가(강결합 — 길이보다 우선)."""
    if not core:
        return False
    if core in FWD_ONE or core in ADV_FWD or core in DET_FWD:
        return True
    if core.endswith(_BIND_SUFF):
        return True
    if core.endswith(_L_ADNOM) and len(core) >= 2:            # 유지할+수가, 않을+때
        return True
    if core.endswith(","):
        return True
    if core[-1].isdigit() or (len(core) >= 2 and core[-1] in "만억천백" and core[-2].isdigit()):
        return True                                            # 20만+회씩은
    if core.endswith("지") and nxt_core[:1] in "않못말":         # V-지 않다/못하다
        return True
    if core.endswith("게") and nxt_core[:1] in "되됐만":         # 있게+되죠
        return True
    if core == "정도":                                           # 이 정도+수익을
        return True
    return False


def _binds_back(core):
    """이 어절이 앞 어절에 붙어야 하는가(의존명사·보조용언). True면 붙인 뒤 덩어리 닫음."""
    base = core.rstrip(".?!,")
    for h in _DEP_HEAD:
        if base == h or (base.startswith(h) and len(base) <= len(h) + 2):
            return True
    return False


def chunk_captions(words, min_chars=2, max_chars=13, max_line=15):
    """의미 단위 자막 v3.2 (맥락 우선 — 문장이 잘게 끊기지 않게).
    목표: 한 덩어리가 그 자체로 읽히는 의미구가 되도록 8~15자로 묶는다. 강결합
    (수식어→피수식어, 수사→단위, 관형형→의존명사, V-지+않다, 보조용언)은 물론이고,
    글자수가 남으면 연결어미 앞까지 계속 이어 붙인다. 끊는 자리는 연결어미(-야/-고/-서)와
    관형격(-의) 뒤, 그리고 문장 끝이다.
    예: 다 20만 회씩은 나와야/이 정도 수익을 유지할 수가 있게 되죠"""
    merged = []
    for w in words:
        t = w[2]
        if merged:
            p = merged[-1][2]
            near = w[0] - merged[-1][1] < 0.35
            if near and (t.startswith(".") or (p and p[-1].isdigit() and t[0].isdigit())):
                merged[-1] = [merged[-1][0], w[1], p + t]; continue
        merged.append([w[0], w[1], t])
    caps, cur = [], []
    closed = False                                             # 의존명사/보조용언으로 완결된 덩어리

    def flush():
        nonlocal cur, closed
        if cur:
            caps.append([cur[0][0], cur[-1][1], " ".join(x[2] for x in cur)])
        cur, closed = [], False

    for k, w in enumerate(merged):
        t = w[2].strip()
        core = t.rstrip(".?!")
        nxt = merged[k + 1][2].strip().rstrip(".?!") if k + 1 < len(merged) else ""
        if cur:
            prev = cur[-1][2].strip()
            prev_core = prev.rstrip(".?!")
            prev_end = prev_core[-1] if prev_core else ""
            comb = kchars(" ".join(x[2] for x in cur)) + kchars(t)
            attach = False
            if not prev.endswith((".", "?", "!")):
                if _hard_bind(prev_core, core) and comb <= max_line + 3:   # 강결합
                    attach = True
                elif closed:                                               # 닫힌 덩어리엔 1자만
                    attach = kchars(core) == 1 and core not in FWD_ONE
                elif _binds_back(core) and comb <= max_line + 1:           # 의존명사·보조용언
                    attach = True; closed = True
                elif comb <= max_chars:
                    if kchars(core) == 1 and core not in FWD_ONE:          # 1자는 앞에
                        attach = True
                    elif prev_end in CONN_END:                             # 연결어미 뒤에서 끊는다
                        attach = False
                    elif prev_core.endswith("의"):                          # 관형격 뒤에서 끊는다
                        attach = False
                    else:
                        attach = True                                      # 그 외에는 이어 붙여 의미구를 키운다
            if attach:
                cur.append(w)
                if core.rstrip(".?!,") in _AUX:
                    closed = True
            else:
                flush(); cur = [w]
        else:
            cur = [w]
        if t.endswith((".", "?", "!")):
            flush()
    flush()
    # 초과 안전장치: 10자 초과 덩어리는 완결 어절 경계에서 재분할(수렴까지 반복)
    for _pass in range(3):
      out = []
      for c in caps:
        toks = c[2].split()
        if kchars(c[2]) <= max_line + 1 or len(toks) < 2:
            out.append(c); continue
        best, score = None, -1e9
        for i in range(1, len(toks)):
            a, b = kchars(" ".join(toks[:i])), kchars(" ".join(toks[i:]))
            if a < 2 or b < 2:
                continue
            sc = -abs(a - b) - 3 * max(0, max(a, b) - max_line)   # 초과 잔존에 벌점
            tail = toks[i - 1].rstrip(".?!,")
            if tail[-1:] in JOSA_END or tail[-1:] in CONN_END:
                sc += 6
            if sc > score:
                best, score = i, sc
        if not best:
            out.append(c); continue
        ratio = sum(len(x) + 1 for x in toks[:best]) / (len(c[2]) + 1)
        mid = c[0] + (c[1] - c[0]) * ratio
        out.append([c[0], mid, " ".join(toks[:best])])
        out.append([mid, c[1], " ".join(toks[best:])])
      if out == caps:
          break
      caps = out
    # 파편 흡수: 4자 이하로 남은 덩어리는 이웃 중 짧은 쪽에 붙인다(문장 경계는 넘지 않음)
    for _pass in range(3):
        merged2, i = [], 0
        while i < len(out):
            c = out[i]
            if kchars(c[2]) <= 4:
                prev = merged2[-1] if merged2 else None
                nxt = out[i + 1] if i + 1 < len(out) else None
                fit_prev = (prev is not None and not prev[2].rstrip().endswith((".", "?", "!"))
                            and kchars(prev[2]) + kchars(c[2]) <= max_line + 3)
                fit_next = (nxt is not None and not c[2].rstrip().endswith((".", "?", "!"))
                            and kchars(nxt[2]) + kchars(c[2]) <= max_line + 3)
                if fit_prev and (not fit_next or kchars(prev[2]) <= kchars(nxt[2])):
                    merged2[-1] = [prev[0], c[1], prev[2] + " " + c[2]]; i += 1; continue
                if fit_next:
                    out[i + 1] = [c[0], nxt[1], c[2] + " " + nxt[2]]; i += 1; continue
            merged2.append(c); i += 1
        if merged2 == out:
            break
        out = merged2
    # 문장부호 제거(2026-07-24: 마침표·따옴표·느낌표·물음표 등 자막에 금지)
    strip = str.maketrans("", "", ".?!,\"'\u201c\u201d\u2018\u2019\u2026~")
    cleaned = []
    for c in out:
        txt = " ".join(c[2].translate(strip).split())
        if txt:
            cleaned.append([c[0], c[1], txt])
    return cleaned


def ass_time(t):
    t = max(0, t)
    return f"{int(t//3600):d}:{int((t%3600)//60):02d}:{t%60:05.2f}"


def is_sent_end(words, i, gap_min=0.30):
    """words[i]가 문장 끝인가 — 구두점(.?!) 또는 종결어미(다/요/죠/까)+뒤 쉼."""
    t = words[i][2].rstrip()
    if t.endswith((".", "?", "!")):
        return True
    gap = (words[i + 1][0] - words[i][1]) if i + 1 < len(words) else 9.9
    return t.endswith(("다", "요", "죠", "까")) and gap >= gap_min


def snap_clip(words, start, end, min_dur=40.0, max_dur=60.0,
              start_exact=False, hard_end=None, end_exact=None):
    """구간을 문장 경계로 스냅. 시작=문장 첫 단어, 끝=min~max초 안의 마지막 문장 끝.
    '시간 맞추기'보다 '한 편이 말이 되는 것'이 우선 — 문장 끝이 없으면 최대 +8초까지 연장.
    start_exact: 후퇴 없이 start 직후 단어에서 그대로 시작(사용자 지정 시작).
    hard_end: 이 시각 이전의 마지막 문장 끝에서 무조건 종료(사용자 지정 끝)."""
    idx = [i for i, w in enumerate(words) if w[1] > start - 4 and w[0] < end + 12]
    if not idx:
        return start, end, "(단어 없음)"
    s_i = next((i for i in idx if words[i][0] >= start - 0.2), idx[0])
    if not start_exact:
        j = s_i
        while j - 1 >= 0 and words[s_i][0] - words[j - 1][0] <= 6.0 and not is_sent_end(words, j - 1):
            j -= 1
        s_i = j
    t0 = words[s_i][0]
    note = ""
    if end_exact is not None:                             # 사용자 지정 끝(문장 탐색 없이 그 지점 단어까지)
        e = [i for i in range(s_i, len(words)) if words[i][1] <= end_exact + 0.05]
        if e:
            return t0, words[e[-1]][1], "(정확 끝)"
    if hard_end is not None:                              # 사용자 지정 끝 — 그 안의 마지막 문장 끝
        cands = [i for i in range(s_i, len(words))
                 if words[i][1] <= hard_end + 0.05 and is_sent_end(words, i)]
        if cands:
            return t0, words[cands[-1]][1], "(지정 끝)"
    cands = [i for i in range(s_i, len(words))
             if min_dur <= words[i][1] - t0 <= max_dur and is_sent_end(words, i)]
    if cands:
        e_i = cands[-1]
    else:
        after = [i for i in range(s_i, len(words))
                 if max_dur < words[i][1] - t0 <= max_dur + 8 and is_sent_end(words, i)]
        if after:
            e_i = after[0]; note = f"(문장 완결 위해 {words[e_i][1]-t0:.0f}s로 연장)"
        else:
            e_i = max(i for i in range(s_i, len(words)) if words[i][1] - t0 <= max_dur)
            note = "(문장 끝 못 찾음 — 확인 필요)"
    return t0, words[e_i][1], note


def split2(hook):
    if "\n" in hook:                                      # 줄바꿈을 직접 지정한 제목은 그대로 따른다
        a, b = hook.split("\n", 1)
        return a.strip(), b.strip()
    if " " not in hook:
        return hook, ""
    ws = hook.split(" "); best = None
    for i in range(1, len(ws)):
        a, b = " ".join(ws[:i]), " ".join(ws[i:]); d = abs(kchars(a) - kchars(b))
        if best is None or d < best[0]:
            best = (d, a, b)
    return best[1], best[2]


def detect_pip(src, t):
    """t초 프레임에서 웹캠 PIP의 흰 라운드 테두리 박스를 감지(밝기>225의 긴 직선 런).
    성공 시 테두리 외곽 박스 dict(w,h,x,y), 실패 시 None."""
    try:
        import numpy as np
        r = subprocess.run(['ffmpeg', '-ss', str(t), '-i', src, '-frames:v', '1',
                            '-f', 'rawvideo', '-pix_fmt', 'gray', '-'],
                           capture_output=True)
        g = np.frombuffer(r.stdout, dtype=np.uint8)
        if g.size < 1920 * 1080:
            return None
        g = g[:1920 * 1080].reshape(1080, 1920)
        bright = g > 225

        def runs(mask_2d, axis_len, other_len, get_line):
            hits = []
            for i in range(axis_len):
                line = get_line(i)
                best = cur = 0
                for v in line:
                    cur = cur + 1 if v else 0
                    best = max(best, cur)
                if best >= 220:
                    hits.append(i)
            return hits

        rows = runs(bright, 1080, 1920, lambda y: bright[y])
        cols = runs(bright, 1920, 1080, lambda x: bright[:, x])
        if not rows or not cols:
            return None
        x0, x1 = min(cols), max(cols)
        y0, y1 = min(rows), max(rows)
        if x1 - x0 < 200 or y1 - y0 < 200:                # 너무 작으면 오탐
            return None
        # 너무 크면 오탐: 화면공유(브라우저 흰 요소) 구간에서 화면 전체를 박스로 오인하는 케이스
        if x1 - x0 > 900 or y1 - y0 > 750:
            return None
        return dict(w=x1 - x0, h=y1 - y0, x=x0, y=y0)
    except Exception:
        return None


def detect_pip_robust(src, times, duration=None):
    """여러 지점에서 PIP 감지 후 합의. 클립 지점들이 전부 실패(화면공유 등)하면
    소스 전역 지점을 추가 시도(웹캠 위치는 영상 내내 동일하다는 가정)."""
    results = []
    for t in times:
        r = detect_pip(src, t)
        if r:
            results.append(r)
    if not results and duration:
        for frac in (0.1, 0.3, 0.5, 0.7, 0.9):
            r = detect_pip(src, duration * frac)
            if r:
                results.append(r)
            if len(results) >= 2:
                break
    if not results:
        return None
    # 첫 결과와 30px 이내로 일치하는 것들의 평균
    base = results[0]
    close = [r for r in results
             if abs(r["x"] - base["x"]) < 30 and abs(r["y"] - base["y"]) < 30]
    n = len(close)
    return dict(w=sum(r["w"] for r in close) // n, h=sum(r["h"] for r in close) // n,
                x=sum(r["x"] for r in close) // n, y=sum(r["y"] for r in close) // n)


def zoom_crop(crop, inset=CROP_INSET):
    """얼굴 영역(crop)에서 테두리 인셋만큼 안으로 들어간 뒤, 풀와이드(W)×VID_H 비율로 잘라낸다.
    좌우는 꽉 채우고(비지 않게), 위아래를 잘라 얼굴 크게 + PIP 흰 라운드 테두리 제거."""
    cw, ch = crop["w"] - 2 * inset, crop["h"] - 2 * inset
    cx, cy = crop["x"] + inset, crop["y"] + inset
    aspect = W / VID_H                                    # 목표 가로세로비 (1080/1030)
    zw = min(cw, round(ch * aspect))
    zh = min(ch, round(zw / aspect))
    zx = cx + (cw - zw) // 2
    zy = cy + (ch - zh) // 2                              # 얼굴 중앙 기준 위아래 균등 크롭
    return dict(w=int(zw), h=int(zh), x=int(zx), y=int(zy))


def geometry():
    """템플릿 배치: 위 여백(제목 존) VID_Y, 영상 VID_H, 아래 여백 나머지."""
    return W, VID_H, VID_Y


def build_ass(hook, caps, dur, yellow_line=2):
    vid_w, vid_h, vid_y = geometry()
    cap_y = vid_y + int(vid_h * CAP_FRAC)
    wm_y = vid_y + vid_h + WM_GAP
    l1, l2 = split2(hook)
    maxlen = max(kchars(l1), kchars(l2))
    tsize = 120 if maxlen <= 8 else (114 if maxlen <= 10 else 108)   # 지정 110~120
    c1 = YELLOW if yellow_line == 1 else WHITE
    c2 = YELLOW if yellow_line == 2 else WHITE
    title = f"{{\\c{c1}}}{l1}" + (f"\\N{{\\c{c2}}}{l2}" if l2 else "")
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Title,{F_TITLE},{tsize},&H00FFFFFF,&H000000FF,&H00141414,&H64000000,0,0,0,0,100,100,0,0,1,3,3,8,40,40,0,1
Style: Cap,{F_CAP},118,&H00FFFFFF,&H000000FF,&H00101010,&H80000000,0,0,0,0,100,100,0.5,0,1,7,3,5,40,40,0,1
Style: WM,{F_WM},70,{GRAY},&H000000FF,&H00000000,&H00000000,0,-1,0,0,100,100,1,0,1,0,1,5,40,40,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = [f"Dialogue: 0,{ass_time(0)},{ass_time(dur)},Title,,0,0,0,,{{\\pos({W//2},{TITLE_Y})}}{title}",
          f"Dialogue: 0,{ass_time(0)},{ass_time(dur)},WM,,0,0,0,,{{\\pos({W//2},{wm_y})\\fax0.12}}{WATERMARK}"]
    for s, e, txt in caps:
        ev.append(f"Dialogue: 0,{ass_time(s)},{ass_time(e)},Cap,,0,0,0,,{{\\pos({W//2},{cap_y})}}{txt.strip()}")
    return head + "\n".join(ev) + "\n"


def _force_break(caps, marker):
    """자막 덩어리를 지정한 자리에서 둘로 나눈다(줄바꿈이 아니라 다음 화면으로 넘김).
    marker 는 "앞부분 | 뒷부분" 형태 — '|' 자리에서 끊는다."""
    if "|" not in marker:
        return caps
    head_ph, tail_ph = (s.strip() for s in marker.split("|", 1))
    whole = f"{head_ph} {tail_ph}".strip()
    out = []
    for s, e, t in caps:
        i = t.find(whole)
        if whole and i >= 0:
            head = t[:i + len(head_ph)].strip()
            tail = t[i + len(head_ph):].strip()
            if head and tail:
                mid = s + (e - s) * (len(head) + 1) / (len(t) + 1)
                out.append([s, mid, head]); out.append([mid, e, tail]); continue
        out.append([s, e, t])
    return out


def _apply_phrase_fix(rel, fixes):
    """여러 어절에 걸친 교정("그 기회를 조금만 더" → "그 길을 조금은 더").
    자막을 나누기 전에 단어 목록 자체를 고쳐야 어느 덩어리에 걸리든 반영된다."""
    for k, v in fixes.items():
        ks = k.split()
        if len(ks) < 2:
            continue
        vs = v.split() or [""]
        i = 0
        while i <= len(rel) - len(ks):
            got = [w[2].strip().rstrip(".?!,") for w in rel[i:i + len(ks)]]
            if got == ks:
                s, e = rel[i][0], rel[i + len(ks) - 1][1]
                new = [[s + (e - s) * j / len(vs), s + (e - s) * (j + 1) / len(vs), t]
                       for j, t in enumerate(vs)]
                rel[i:i + len(ks)] = new
                i += len(vs)
            else:
                i += 1
    return rel


def _apply_fix(t, fixes):
    for k, v in fixes.items():
        t = t.replace(k, v)
    return t


def prepare_clip(words, clip):
    """클립 준비(렌더/XML 공통): 문장 스냅 → 스마트 테일 → force_start → 구간 제거 → 자막 청킹.
    반환 dict: c_start/c_end(소스 절대초), removes(절대), segs(상대 keep 구간),
              dur(출력 길이), caps(출력 타임라인 자막), note, tail_txt. 단어 없으면 None."""
    start = float(clip["start"]); end = float(clip["end"])
    # 문장 경계 스냅: 시작=문장 첫 단어, 끝=40~60초 안 마지막 문장 끝(말이 되는 게 우선)
    t0, t1, note = snap_clip(words, start, end,
                             max_dur=float(clip.get("max_dur", 60)),
                             start_exact=bool(clip.get("start_exact")),
                             hard_end=clip.get("hard_end"),
                             end_exact=clip.get("end_exact"))
    ws = [w for w in words if t0 - 0.05 <= w[0] and w[1] <= t1 + 0.05]
    if not ws:
        return None
    tail_txt = " ".join(w[2] for w in ws[-6:])
    # 스마트 테일: 다음 발화 직전까지만(뒤 문장 첫음 '그래/특' 새어들기 방지) + 끝 페이드
    last_end = ws[-1][1]
    nxt = next((w for w in words if w[0] > last_end + 0.001), None)
    tail = 0.45 if nxt is None else max(0.05, min(0.45, nxt[0] - last_end - 0.08))
    c_start, c_end = ws[0][0], last_end + tail
    # force_start: 발화 온셋 직전으로 강제(첫 단어 앞의 '아~'/숨을 잘라냄 — STT 단어 시각이 앞으로 패딩된 경우)
    fs = clip.get("force_start")
    if fs is not None and fs > c_start:
        c_start = fs
        ws = [w for w in ws if w[1] > fs + 0.05]
    # 구간 제거(숨소리 등): clips.json "remove": [[소스초, 소스초], ...]
    removes = sorted([max(c_start, a), min(c_end, b)] for a, b in (clip.get("remove") or []))
    removes = [r for r in removes if r[1] - r[0] > 0.02]
    dur = (c_end - c_start) - sum(b - a for a, b in removes)
    rel = [[max(0.0, w[0] - c_start), max(0.06, w[1] - c_start), w[2]] for w in ws]
    for a, b in sorted(((a - c_start, b - c_start) for a, b in removes), reverse=True):
        cut = b - a
        # 제거 구간에 걸친 단어: 시작이 구간 안이면 구간 끝(=a)으로 클램프(안 하면 시작>끝 자막)
        rel = [[(s - cut if s >= b else (a if s > a else s)),
                (e - cut if e >= b else min(e, a)), t]
               for s, e, t in rel if not (a <= s and e <= b)]
    fixes = clip.get("fix") or {}
    if fixes:
        rel = _apply_phrase_fix(rel, fixes)                # 여러 어절짜리 교정 먼저
        rel = [[s, e, _apply_fix(t, fixes)] for s, e, t in rel]
        rel = [w for w in rel if w[2].strip()]
    cm = int(clip.get("cap_max", 8))                      # 한 자막의 목표 최대 글자수
    caps = chunk_captions(rel, max_chars=cm, max_line=cm + 1)
    if fixes:                                              # 어절 하나로 안 잡히는 구절 교정도 여기서
        caps = [[s, e, _apply_fix(t, fixes)] for s, e, t in caps]
    for ph in (clip.get("break_after") or []):             # "앞부분 | 뒷부분" — 그 자리에서 화면을 나눔
        caps = _force_break(caps, ph)
    # keep 세그먼트(상대 시간): 제거 구간을 뺀 나머지
    segs, pos = [], 0.0
    for a, b in ((a - c_start, b - c_start) for a, b in removes):
        if a > pos:
            segs.append((pos, a))
        pos = b
    if c_end - c_start > pos:
        segs.append((pos, c_end - c_start))
    return dict(c_start=c_start, c_end=c_end, removes=removes, segs=segs,
                dur=dur, caps=caps, note=note, tail_txt=tail_txt)


def render(src, words, clip, crop, outdir):
    name = clip["name"]
    p = prepare_clip(words, clip)
    if p is None:
        print(f"[{name}] 구간 내 단어 없음 — 건너뜀"); return None
    c_start, c_end, dur = p["c_start"], p["c_end"], p["dur"]
    removes, segs, caps = p["removes"], p["segs"], p["caps"]
    print(f"[{name}] 문장 스냅 {p['note']}  끝맺음: \"…{p['tail_txt']}\"")
    vid_w, vid_h, vid_y = geometry()
    zc = zoom_crop(crop)
    ass_path = os.path.join(outdir, name + ".ass")
    open(ass_path, "w", encoding="utf-8").write(
        build_ass(clip["hook"], caps, dur, clip.get("yellow", 2)))
    out_path = os.path.join(outdir, name + ".mp4")
    # 업로드 방탄: fps=30(CFR 강제·PTS 재생성)로 유튜브/인스타 '앞부분 빨리감기' 원천 차단
    vchain = (f"crop={zc['w']}:{zc['h']}:{zc['x']}:{zc['y']},"
              f"scale={vid_w}:{vid_h}:flags=lanczos,unsharp=5:5:0.9:5:5:0.0,"
              f"fps=30,pad={W}:{H}:0:{vid_y}:color=black,setsar=1,"
              f"ass={ass_path}:fontsdir={FONTS},setpts=PTS-STARTPTS")
    achain = (f"loudnorm=I=-14:TP=-1.5:LRA=11,"
              f"aresample=48000,"
              f"afade=t=out:st={max(0.0, dur - 0.22):.2f}:d=0.22,"
              f"asetpts=PTS-STARTPTS")
    # 제거 구간 반영: keep 세그먼트(segs)를 trim/concat (제거 없으면 단일 세그먼트)
    # ── 핵심: -copyts + 절대시간 trim ──
    # 입력 시킹(-ss)은 키프레임으로 점프하며 시크 지점 이전 '프리롤' 프레임을 흘려보낼 수 있고,
    # 그 프레임들이 첫 2~3초 빨리감기(내용이 앞당겨 압축 재생)로 나타난다.
    # -copyts로 원본 절대 타임스탬프를 유지하면 trim=start=<절대초>가 프리롤을 결정적으로 잘라낸다.
    parts, cc = [], ""
    for i, (a, b) in enumerate(segs):
        parts.append(f"[0:v]trim=start={c_start + a:.3f}:end={c_start + b:.3f},setpts=PTS-STARTPTS[v{i}];"
                     f"[0:a]atrim=start={c_start + a:.3f}:end={c_start + b:.3f},asetpts=PTS-STARTPTS[a{i}]")
        cc += f"[v{i}][a{i}]"
    fc = (";".join(parts) + f";{cc}concat=n={len(segs)}:v=1:a=1[vc][ac];"
          f"[vc]{vchain}[vout];[ac]{achain}[aout]")
    seek = max(0.0, c_start - 6.0)                       # 키프레임 여유(프리롤은 trim이 자름)
    cmd = ["ffmpeg", "-y", "-ss", f"{seek:.3f}", "-to", f"{c_end + 0.5:.3f}", "-i", src,
           "-copyts",
           "-filter_complex", fc, "-map", "[vout]", "-map", "[aout]",
           "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
           "-bf", "0",  # B프레임 off: dts=pts → 시작 0.000 보장(업로드 플랫폼 최무해)
           "-c:a", "aac", "-b:a", "192k",
           "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", out_path]
    rm = f" 제거{len(removes)}곳" if removes else ""
    print(f"[{name}] {ass_time(c_start)}~{ass_time(c_end)} ({dur:.0f}s) 자막 {len(caps)}개{rm} → 렌더...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("  에러:\n" + r.stderr[-1200:]); return None
    ok, msg = verify_timestamps(out_path)
    ok2, msg2 = verify_content(out_path, src, c_start, zc, vid_w, vid_h)
    ok3, msg3 = verify_audio_head(out_path)
    allok = ok and ok2 and ok3
    print(f"  {'완료' if allok else '[검증실패!]'} {msg} {msg2} {msg3} → {out_path}")
    return out_path if allok else None


def _grab_gray(path, t, vf, w, h):
    import numpy as np
    r = subprocess.run(["ffmpeg", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1",
                        "-vf", vf, "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                       capture_output=True)
    g = np.frombuffer(r.stdout, dtype=np.uint8)
    return g[:w * h].reshape(h, w).astype(int) if g.size >= w * h else None


def verify_audio_head(out_path):
    """오디오 헤드 검증: 첫 1.3초가 무음이 아닌지(클립은 발화로 시작 — 앞 무음 삽입 버그 감지)."""
    try:
        r = subprocess.run(["ffmpeg", "-i", out_path, "-t", "1.3",
                            "-af", "volumedetect", "-f", "null", "-"],
                           capture_output=True, text=True)
        import re as _re
        m = _re.search(r"mean_volume:\s*(-?[\d.]+)", r.stderr)
        if not m:
            return False, "(오디오헤드 측정 실패)"
        mv = float(m.group(1))
        return mv > -45.0, f"(음성헤드 {mv:.0f}dB{' 무음!' if mv <= -45 else ''})"
    except Exception as e:
        return False, f"(오디오헤드 오류: {e})"


def verify_content(out_path, src, c_start, zc, vid_w, vid_h, out_x=0, out_w=None, zc_at=None):
    """내용 검증: 출력 첫 부분 프레임이 소스의 '같은 시점' 프레임과 일치하는지(빨리감기/프리롤 오염 감지).
    출력 영상영역 상단(얼굴)과 소스 zoom_crop 동일 영역을 픽셀 대조(MAD).
    out_x/out_w: 출력에서 비교할 가로 구간(웹캠 와이드 모드의 전경 영역 지정용, 기본 풀폭).
    zc_at: 출력시간 → 크롭 dict. 얼굴 추적으로 크롭이 컷마다 움직일 때 그 시점 크롭으로 대조한다."""
    try:
        import numpy as np
        half_h = 480                                       # 영상영역 상단(자막·제목 안 겹침)
        ow = out_w or W
        checks = []
        for t in (0.5, 1.5, 2.5):
            zt = zc_at(t) if zc_at else zc
            o = _grab_gray(out_path, t,
                           f"crop={ow}:{half_h}:{out_x}:{VID_Y}, scale=96:64", 96, 64)
            s = _grab_gray(src, c_start + t,
                           f"crop={zt['w']}:{int(zt['h']*half_h/vid_h)}:{zt['x']}:{zt['y']},scale=96:64",
                           96, 64)
            if o is None or s is None:
                return False, "(내용검증 프레임 실패)"
            checks.append(float(np.abs(o - s).mean()))
        bad = [c for c in checks if c > 26]
        ok = len(bad) == 0
        return ok, f"(내용 MAD={','.join(f'{c:.0f}' for c in checks)}{' 불일치!' if not ok else ''})"
    except Exception as e:
        return False, f"(내용검증 오류: {e})"


def verify_timestamps(path):
    """업로드 안전성 검증: 영상/오디오 start=0, 음수 PTS 0개, CFR 균일."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v",
                            "-show_entries", "packet=pts_time", "-of", "csv=p=0", path],
                           capture_output=True, text=True)
        ts = sorted(float(x.strip().rstrip(",")) for x in r.stdout.splitlines()
                    if x.strip().rstrip(","))
        neg = sum(1 for t in ts if t < -0.001)
        gaps = [round(b - a, 4) for a, b in zip(ts, ts[1:])]
        irregular = sum(1 for g in gaps if abs(g - 1 / 30) > 0.003)
        ra = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a",
                             "-show_entries", "stream=start_time", "-of", "csv=p=0", path],
                            capture_output=True, text=True)
        a0 = float(ra.stdout.strip().rstrip(","))
        # 시작 오프셋 1프레임(33ms) 이내는 표준(AAC priming 상쇄) — 빨리감기 원인은 음수/불균일 PTS
        ok = abs(ts[0]) < 0.034 and neg == 0 and irregular == 0 and -0.001 <= a0 < 0.05
        return ok, (f"(검증: v0={ts[0]:.3f} a0={a0:.3f} 음수{neg} 불균일{irregular})")
    except Exception as e:
        return False, f"(검증 오류: {e})"


def src_size(path):
    """소스 영상의 (가로, 세로) 픽셀. 실패하면 1080p로 가정한다."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", path],
                           capture_output=True, text=True)
        w_, h_ = r.stdout.strip().split("x")
        return int(w_), int(h_)
    except Exception:
        return 1920, 1080


def src_duration(path):
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", path], capture_output=True, text=True)
        return float(r.stdout.strip())
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source"); ap.add_argument("words"); ap.add_argument("clips")
    ap.add_argument("--crop", default=None, help="w:h:x:y (얼굴 웹캠 영역, 소스 픽셀)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    cli_crop = None
    if a.crop:
        w, h, x, y = (int(v) for v in a.crop.split(":")); cli_crop = dict(w=w, h=h, x=x, y=y)
    outdir = a.out or os.path.join(os.path.dirname(a.source) or ".", "shorts")
    os.makedirs(outdir, exist_ok=True)
    words = [tuple(x) for x in json.load(open(a.words, encoding="utf-8"))]
    clips = json.load(open(a.clips, encoding="utf-8"))
    for c in clips:
        # 크롭 우선순위: --crop 명시 > 클립 중간 시점 PIP 자동 감지 > 기본값
        crop = cli_crop
        if crop is None:
            s0, e0 = float(c["start"]), float(c["end"])
            crop = detect_pip_robust(a.source, [s0 + 1, (s0 + e0) / 2, e0 - 2],
                                     duration=src_duration(a.source))
            if crop:
                print(f"[{c['name']}] PIP 자동 감지: x={crop['x']} y={crop['y']} "
                      f"w={crop['w']} h={crop['h']}")
            else:
                crop = DEFAULT_CROP
                print(f"[{c['name']}] PIP 감지 실패 → 기본 크롭 사용(확인 필요)")
        render(a.source, words, c, crop, outdir)


if __name__ == "__main__":
    main()
