# -*- coding: utf-8 -*-
"""
hwpx_builder.py
===============
프라임에듀 양식(.hwpx)을 기반으로 영어 문제지를 생성하는 빌더.

지원 기능
  1. 머리말 텍스트 치환            (set_header)
  2. 미주로 정답 삽입         (문제별 answer)
  3. 일반 텍스트(지문/발문/선택지) 입력
  4. 굵은 글씨 + 붉은 네모 박스(테두리)  (지문 박스)
  5. 단(컬럼) 넘침 방지 - 높이 추정 후 잘릴 것 같으면 columnBreak 자동 삽입

설계
  - .hwpx 는 ZIP + XML. 한/글 설치 불필요, 순수 표준 라이브러리(zipfile, re)만 사용.
  - header.xml 은 test1.hwpx 의 것을 베이스로 사용한다.
    (양식의 스타일 0~12 를 모두 포함하면서, 박스/굵게/미주용 스타일
     10~16, borderFill 3~4 까지 갖추고 있어 ID 충돌이 없다.)
  - section0.xml 은 양식의 '빈 본문'에 문제 단락을 채워 넣는다.

스타일 ID (header.xml 기준 - test1 베이스)
  charPr  8  : 본문 일반 (검정, 950)
  charPr 11  : 굵게 + 파랑 (#0000FF)  -> 날짜 [2025-11-18]
  charPr 12  : 굵게 + 검정             -> 발문
  charPr  9  : 미주 번호 (2000)
  charPr 13~16 : 선택지/지문용 변형
  paraPr  1  : 일반 문단
  paraPr 13  : 붉은박스 시작 문단 (borderFill 3, 사방 빨강 0.5mm)
  paraPr 14  : 붉은박스 연속 문단 (borderFill 4, 테두리 NONE - 박스 연결)
"""
import io
import re
import zipfile

# === 자동 주입용 스타일 정의 ===
# header.xml 에 해당 ID 가 없을 때 주입한다. 참조하는 하위 ID
# (fontRef=1, borderFillIDRef=2, tabPrIDRef=0 등)는 양식 header 에 이미 존재.
# charPr 11/12/15/16/17 은 빌드 시 양식 charPr 8 에서 동적 파생 (_derive_charpr_styles)
_STYLE_DEFS = {
    'paraPr13': ('<hh:paraPr id="13" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="1" suppressLineNumbers="0" checked="0"><hh:align horizontal="JUSTIFY" vertical="BASELINE"/><hh:heading type="NONE" idRef="0" level="0"/><hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="KEEP_WORD" widowOrphan="0" keepWithNext="0" keepLines="0" pageBreakBefore="0" lineWrap="BREAK"/><hh:autoSpacing eAsianEng="0" eAsianNum="0"/><hp:switch><hp:case hp:required-namespace="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar"><hh:margin><hc:intent value="0" unit="HWPUNIT"/><hc:left value="0" unit="HWPUNIT"/><hc:right value="0" unit="HWPUNIT"/><hc:prev value="0" unit="HWPUNIT"/><hc:next value="0" unit="HWPUNIT"/></hh:margin><hh:lineSpacing type="PERCENT" value="150" unit="HWPUNIT"/></hp:case><hp:default><hh:margin><hc:intent value="0" unit="HWPUNIT"/><hc:left value="0" unit="HWPUNIT"/><hc:right value="0" unit="HWPUNIT"/><hc:prev value="0" unit="HWPUNIT"/><hc:next value="0" unit="HWPUNIT"/></hh:margin><hh:lineSpacing type="PERCENT" value="150" unit="HWPUNIT"/></hp:default></hp:switch><hh:border borderFillIDRef="3" offsetLeft="283" offsetRight="283" offsetTop="283" offsetBottom="283" connect="0" ignoreMargin="0"/></hh:paraPr>'),
    'paraPr14': ('<hh:paraPr id="14" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="1" suppressLineNumbers="0" checked="0"><hh:align horizontal="JUSTIFY" vertical="BASELINE"/><hh:heading type="NONE" idRef="0" level="0"/><hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="KEEP_WORD" widowOrphan="0" keepWithNext="0" keepLines="0" pageBreakBefore="0" lineWrap="BREAK"/><hh:autoSpacing eAsianEng="0" eAsianNum="0"/><hp:switch><hp:case hp:required-namespace="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar"><hh:margin><hc:intent value="0" unit="HWPUNIT"/><hc:left value="0" unit="HWPUNIT"/><hc:right value="0" unit="HWPUNIT"/><hc:prev value="0" unit="HWPUNIT"/><hc:next value="0" unit="HWPUNIT"/></hh:margin><hh:lineSpacing type="PERCENT" value="150" unit="HWPUNIT"/></hp:case><hp:default><hh:margin><hc:intent value="0" unit="HWPUNIT"/><hc:left value="0" unit="HWPUNIT"/><hc:right value="0" unit="HWPUNIT"/><hc:prev value="0" unit="HWPUNIT"/><hc:next value="0" unit="HWPUNIT"/></hh:margin><hh:lineSpacing type="PERCENT" value="150" unit="HWPUNIT"/></hp:default></hp:switch><hh:border borderFillIDRef="4" offsetLeft="0" offsetRight="0" offsetTop="0" offsetBottom="0" connect="0" ignoreMargin="0"/></hh:paraPr>'),
    'borderFill3': ('<hh:borderFill id="3" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0"><hh:slash type="NONE" Crooked="0" isCounter="0"/><hh:backSlash type="NONE" Crooked="0" isCounter="0"/><hh:leftBorder type="SOLID" width="0.5 mm" color="#FF0000"/><hh:rightBorder type="SOLID" width="0.5 mm" color="#FF0000"/><hh:topBorder type="SOLID" width="0.5 mm" color="#FF0000"/><hh:bottomBorder type="SOLID" width="0.5 mm" color="#FF0000"/><hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/><hc:fillBrush><hc:winBrush faceColor="none" hatchColor="#FF000000" alpha="0"/></hc:fillBrush></hh:borderFill>'),
    'borderFill4': ('<hh:borderFill id="4" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0"><hh:slash type="NONE" Crooked="0" isCounter="0"/><hh:backSlash type="NONE" Crooked="0" isCounter="0"/><hh:leftBorder type="NONE" width="0.5 mm" color="#FF0000"/><hh:rightBorder type="NONE" width="0.5 mm" color="#FF0000"/><hh:topBorder type="NONE" width="0.5 mm" color="#FF0000"/><hh:bottomBorder type="NONE" width="0.5 mm" color="#FF0000"/><hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/><hc:fillBrush><hc:winBrush faceColor="none" hatchColor="#FF000000" alpha="0"/></hc:fillBrush></hh:borderFill>'),
}


# ---- 페이지 기하 (HWPUNIT, section0.xml 에서 확인) ----
PAGE_W, PAGE_H = 59528, 84188
MARGIN_LR, MARGIN_TB = 2834, 2834
MARGIN_HEADER, MARGIN_FOOTER = 4252, 4252
COL_COUNT = 2
COL_GAP = 2268
BODY_HEIGHT = PAGE_H - MARGIN_TB * 2 - MARGIN_HEADER - MARGIN_FOOTER  # ≈ 70016
COL_WIDTH = (PAGE_W - MARGIN_LR * 2 - COL_GAP * (COL_COUNT - 1)) // COL_COUNT  # ≈ 25796

# 줄 높이(150% 줄간격) 및 줄당 글자수(보수적 추정)
LINE_VSIZE = 950
LINE_SPACING = 1.5
LINE_HEIGHT = LINE_VSIZE * LINE_SPACING            # 1425
LINES_PER_COL = BODY_HEIGHT / LINE_HEIGHT           # ≈ 49
# 영문 기준 한 줄에 들어가는 대략 글자 수 (보수적으로 약간 작게)
CHARS_PER_LINE_EN = 52
CHARS_PER_LINE_KR = 26


def _esc(text):
    """XML 텍스트 이스케이프(특수문자만). 줄바꿈은 그대로 두지 않는다 →
       단일 토큰(미주 정답 등 줄바꿈 없는 곳)에서만 사용."""
    if text is None:
        text = ""
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))


# ---------------------------------------------------------------------------
# 단락(문단) 생성기
# ---------------------------------------------------------------------------
# charPr → 밑줄 charPr 매핑
# 한/글은 bold+underline 을 한 charPr 에 합치면 글꼴 폴백이 발생한다.
# 따라서 밑줄 run 은 항상 charPr 15(밑줄만, bold 없음)를 사용한다.

_UNDERLINE_MAP = {8: 15, 12: 16, 11: 17}


def _run(text, char_pr):
    """텍스트를 run 으로 만든다.
    U+FFF0 으로 감싸진 구간이 있으면 밑줄 run 으로 분리한다.
    예: "normal \ufff0underlined\ufff0 text"
        → normal(charPr) + underlined(밑줄 charPr) + text(charPr)
    """
    MARKER = "\ufff0"
    if MARKER not in text:
        return (f'<hp:run charPrIDRef="{char_pr}">'
                f'<hp:t>{_esc(text)}</hp:t></hp:run>')

    ul_pr = _UNDERLINE_MAP.get(char_pr, 15)   # 매핑 없으면 기본 밑줄
    parts = text.split(MARKER)
    runs = []
    for i, seg in enumerate(parts):
        if not seg:
            continue
        cp = ul_pr if (i % 2 == 1) else char_pr   # 홀수 구간 = 밑줄
        runs.append(f'<hp:run charPrIDRef="{cp}">'
                    f'<hp:t>{_esc(seg)}</hp:t></hp:run>')
    return "".join(runs)


def _para(runs_xml, para_pr=1, char_pr_for_seg=8, column_break=False,
          page_break=False, vsize=LINE_VSIZE):
    """하나의 <hp:p> 단락을 만든다. runs_xml 은 이미 만들어진 run 들의 연결.
       lineseg 는 넣지 않는다(한/글이 줄간격을 재계산하도록)."""
    cb = "1" if column_break else "0"
    pb = "1" if page_break else "0"
    return (f'<hp:p id="0" paraPrIDRef="{para_pr}" styleIDRef="0" '
            f'pageBreak="{pb}" columnBreak="{cb}" merged="0">'
            f'{runs_xml}</hp:p>')


def _endnote_run(answer, number, char_pr=11):
    """
    미주(정답) run. test1.hwpx 구조를 그대로 따른다.
      <hp:run><hp:ctrl><hp:endNote number=.. instId=..>
        <hp:subList><hp:p><hp:run charPrIDRef="9">
          <hp:ctrl><hp:autoNum .../></hp:ctrl><hp:t> 정답</hp:t>
        ...</hp:endNote></hp:ctrl></hp:run>
    number : 미주 순번(1,2,3...). 한/글이 재계산하지만 명시해 둔다.
    """
    inst = 1100000000 + number          # 임의의 고유 instId
    note = (
        '<hp:ctrl>'
        f'<hp:endNote number="{number}" suffixChar="41" instId="{inst}">'
        '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" '
        'vertAlign="TOP" linkListIDRef="0" linkListNextIDRef="0" '
        'textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
        '<hp:p id="2147483648" paraPrIDRef="1" styleIDRef="15" pageBreak="0" '
        'columnBreak="0" merged="0"><hp:run charPrIDRef="9">'
        f'<hp:ctrl><hp:autoNum num="{number}" numType="ENDNOTE">'
        '<hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" '
        'suffixChar=")" supscript="0"/></hp:autoNum></hp:ctrl>'
        f'<hp:t> {_esc(str(answer))}</hp:t></hp:run>'
        '</hp:p>'
        '</hp:subList></hp:endNote></hp:ctrl>'
    )
    return f'<hp:run charPrIDRef="{char_pr}">{note}</hp:run>'


# ---------------------------------------------------------------------------
# 높이 추정 (단 넘침 판단용)
# ---------------------------------------------------------------------------
def _estimate_lines(text, chars_per_line=None):
    """문자열이 차지할 줄 수를 보수적으로 추정."""
    if not text:
        return 1
    if chars_per_line is None:
        # 한글 비중이 높으면 줄당 글자수를 줄인다
        kr = sum(1 for c in text if "\uac00" <= c <= "\ud7a3")
        ratio = kr / max(1, len(text))
        chars_per_line = (CHARS_PER_LINE_KR if ratio > 0.4
                          else CHARS_PER_LINE_EN)
    # 줄바꿈 단위로 끊고 각 줄을 폭으로 나눔
    lines = 0
    for seg in text.split("\n"):
        lines += max(1, -(-len(seg) // chars_per_line))  # ceil
    return lines


class _ColumnTracker:
    """현재 단(컬럼)에 쌓인 줄 수를 추적해, 넘칠 것 같으면 단 넘김을 지시."""
    def __init__(self, lines_per_col=LINES_PER_COL):
        self.cap = lines_per_col
        self.used = 0.0

    def fits(self, lines):
        return self.used + lines <= self.cap

    def add(self, lines):
        self.used += lines

    def newcol(self, lines):
        self.used = lines


# ---------------------------------------------------------------------------
# 문제 블록 생성
# ---------------------------------------------------------------------------
def build_question_block(q, tracker, endnote_no, force_newcol_if_overflow=True):
    """
    하나의 문제(dict)를 단락 XML 문자열로 변환.
    q = {
       "date":     "[2025-11-18]",      # 선택, 파랑 굵게
       "prompt":   "다음 글의 ...?",     # 발문, 굵게
       "answer":   2,                    # 미주 정답
       "passage":  "Dear Mr. Kelly ...", # 지문 (붉은 박스)
       "choices":  ["① ...","② ...",...] # 선택지
    }
    tracker     : _ColumnTracker
    endnote_no  : 이 문제의 미주 순번(1,2,3...)
    """
    # --- 높이 추정 ---
    total_lines = 0
    total_lines += _estimate_lines((q.get("date", "") + " " +
                                    q.get("prompt", "")))
    if q.get("passage"):
        total_lines += _estimate_lines(q["passage"]) + 1  # 박스 여백
    for ch in q.get("choices", []):
        total_lines += _estimate_lines(ch)
    total_lines += 1  # 문제 간 간격

    # --- 단 넘김 판단: 잘릴 것 같으면 새 단에서 시작 ---
    column_break = False
    if force_newcol_if_overflow and not tracker.fits(total_lines):
        # 문제 전체가 한 단보다 작으면 새 단으로, 크면 그냥 흐르게 둠
        if total_lines <= tracker.cap:
            column_break = True
            tracker.newcol(total_lines)
        else:
            tracker.add(total_lines)
    else:
        tracker.add(total_lines)

    parts = []

    # 1) 발문 단락: 미주(정답) + 날짜(파랑굵게) + 발문(굵게)
    head_runs = ""
    if "answer" in q and q["answer"] not in (None, ""):
        head_runs += _endnote_run(q["answer"], endnote_no)
    if q.get("date"):
        head_runs += _run(" " + q["date"], 11)       # 파랑 굵게
    if q.get("prompt"):
        head_runs += _run(" " + q["prompt"], 12)      # 검정 굵게
    parts.append(_para(head_runs, para_pr=1,
                       column_break=column_break))

    # 2) 지문 단락(붉은 박스). paraPr 13(박스 시작)으로 감싼다.
    if q.get("passage"):
        passage_runs = _run(q["passage"], 8)
        parts.append(_para(passage_runs, para_pr=13))  # 사방 빨강 테두리

    parts.append(_para('<hp:run charPrIDRef="8"></hp:run>', para_pr=1))
    # 3) 선택지 단락들 (일반 문단)
    if q.get("choices"):
        joined = "".join(q["choices"]) if all(
            len(c) < 30 for c in q["choices"]) else None
        if joined:
            parts.append(_para(_run(joined, 8), para_pr=1))
        else:
            for ch in q["choices"]:
                parts.append(_para(_run(ch, 8), para_pr=1))

    # 4) 문제 사이 간격용 빈 단락(= Enter 한 번). 포맷을 깔끔하게.
    parts.append(_para('<hp:run charPrIDRef="8"></hp:run>', para_pr=1))

    return "".join(parts)


# ---------------------------------------------------------------------------
# 메인: HWPX 생성
# ---------------------------------------------------------------------------
def build_hwpx(template_path, output_path, header_text, questions,
               reference_path=None, page_break_before_endnotes=True):
    """
    template_path : 프라임에듀_기본양식.hwpx
    output_path   : 출력 .hwpx 경로(문자열) 또는 파일류 객체(BytesIO 등)
    header_text   : 머리말에 넣을 문자열 (예: "프라임에듀 2025 수능특강")
    questions     : list[dict / Django Model / 객체]
    reference_path: 박스/굵게/미주 스타일을 가진 .hwpx (스타일 참조본)
    page_break_before_endnotes : 본문 끝에 '쪽 나누기'를 넣어
                    미주(정답)가 새 페이지에서 시작하도록 한다.

    머리말은 글자모양(charPr)을 양식 그대로 두고, 단락의 조판 캐시
    (탭 고정폭·lineseg)만 제거하여 정상 글자폭으로 출력한다.
    """
    with zipfile.ZipFile(template_path) as z:
        names = z.namelist()
        files = {n: z.read(n) for n in names}

    # header.xml: 박스(borderFill 3)/굵게(charPr 11,12)/박스문단(paraPr 13)
    # 스타일이 있어야 한다. 없으면 (1) reference 의 header 사용,
    # 그래도 없으면 (2) 내장 정의를 자동 주입한다.
    # 이 스타일이 빠진 채 본문이 참조하면 한/글이 렌더링에 실패(검은 화면)한다.
    header_xml = files["Contents/header.xml"].decode("utf-8")

    def _has_required(h):
        return ('borderFill id="3"' in h and 'charPr id="11"' in h
                and 'charPr id="12"' in h and 'paraPr id="13"' in h
                and 'charPr id="15"' in h)

    if not _has_required(header_xml) and reference_path:
        with zipfile.ZipFile(reference_path) as z2:
            ref_header = z2.read("Contents/header.xml").decode("utf-8")
        if _has_required(ref_header):
            header_xml = ref_header

    # 항상 _inject_styles 실행: charPr 11/12/15/16/17 을 양식 charPr 8 에서
    # 동적 파생하므로, 부족한 스타일이 있으면 어떤 경우든 보충된다.
    header_xml = _inject_styles(header_xml)

    if not ('charPr id="12"' in header_xml and 'paraPr id="13"' in header_xml):
        raise RuntimeError(
            "필수 스타일(charPr 11/12, paraPr 13, borderFill 3)을 "
            "header.xml 에 확보하지 못했습니다. reference_path 를 지정하세요.")

    files["Contents/header.xml"] = header_xml.encode("utf-8")

    # ---- section0.xml 편집 ----
    sec = files["Contents/section0.xml"].decode("utf-8")

    # 1) 머리말 치환 + 캐시 정리
    #    머리말은 [공백][탭(고정폭)][텍스트] 구조이며, 탭의 width 가
    #    옛 텍스트("[프라임에듀 머리말]") 길이에 맞춰 고정되어 있다.
    #    텍스트를 더 길게 바꾸면 고정 탭폭 때문에 글자가 눌려(장평 축소)
    #    좁아 보인다. 따라서 머리말 단락의
    #      (a) 탭의 고정 width 속성을 제거(한/글이 tabStop 기준 재계산)
    #      (b) lineseg(조판 캐시) 제거
    #    하여, charPr(글자모양)은 양식 그대로 두고도 정상 폭으로 나오게 한다.
    sec = _replace_header(sec, "[프라임에듀 머리말]",
                          "[" + header_text + "]")

    # 입력 정규화 (dict / Django Model / 객체 혼용 허용)
    questions = [q if (isinstance(q, dict) and "choices" in q
                       and isinstance(q.get("choices"), list))
                 else _normalize_question(q) for q in questions]

    # 2) 본문 문제 삽입
    tracker = _ColumnTracker()
    blocks = []
    endnote_no = 1
    for q in questions:
        has_ans = "answer" in q and q["answer"] not in (None, "")
        blocks.append(build_question_block(q, tracker, endnote_no))
        if has_ans:
            endnote_no += 1
    blocks = "".join(blocks)

    # 3) 본문 끝에 '쪽 나누기' 단락 추가
    #    미주는 문서 끝(END_OF_DOCUMENT)에 모인다. 본문 마지막에 빈 쪽나누기
    #    단락을 두면 미주(정답)가 새 페이지에서 시작한다.
    if page_break_before_endnotes:
        blocks += ('<hp:p id="0" paraPrIDRef="1" styleIDRef="0" '
                   'pageBreak="1" columnBreak="0" merged="0">'
                   '<hp:run charPrIDRef="8"></hp:run></hp:p>')
    # 4) 본문 삽입 위치 결정
    #   양식 본문 구조:
    #   단락1(최상위): secPr + header(머리말, 내부에 중첩 <hp:p> 포함) + 그림
    #   단락2(최상위): newNum + 빈 텍스트  (마지막)
    # 주의: header 안에 머리말용 <hp:p>...</hp:p> 가 '중첩'되어 있으므로
    #       단순히 첫 </hp:p> 를 찾으면 중첩 단락을 잡는다.
    #       반드시 </hp:header> '이후'의 첫 </hp:p> (= 최상위 단락1 종료)에 삽입한다.
    after_header = sec.find("</hp:header>")
    if after_header == -1:
        after_header = 0
    first_p_end = sec.find("</hp:p>", after_header) + len("</hp:p>")
    sec = sec[:first_p_end] + blocks + sec[first_p_end:]

    files["Contents/section0.xml"] = sec.encode("utf-8")

    # ---- 재패킹 (mimetype 은 비압축 + 맨 앞) ----
    _write_hwpx(output_path, files)
    return output_path


def _replace_header(sec, old_text, new_text):
    """
    머리말 텍스트를 치환하면서, 머리말이 들어있는 단락의
    조판 캐시(탭 고정폭, lineseg)를 제거한다.
    글자모양(charPr)은 건드리지 않는다.
    """
    idx = sec.find(old_text)
    if idx == -1:
        # 못 찾으면 단순 치환만
        return sec.replace(old_text, new_text)

    # 머리말이 들어있는 <hp:p> ... </hp:p> 범위
    p_start = sec.rfind("<hp:p ", 0, idx)
    p_end = sec.find("</hp:p>", idx) + len("</hp:p>")
    para = sec[p_start:p_end]

    new_para = para
    # 1) 텍스트 치환
    new_para = new_para.replace(old_text, new_text)
    # 2) 탭의 고정 width 제거 -> 한/글이 tabStop 기준으로 재계산
    new_para = re.sub(r'(<hp:tab\b[^>]*?)\swidth="\d+"', r"\1", new_para)
    # 3) lineseg(조판 캐시) 제거 -> 줄/폭 재계산
    new_para = re.sub(r"<hp:linesegarray>.*?</hp:linesegarray>", "",
                      new_para, flags=re.S)

    return sec[:p_start] + new_para + sec[p_end:]


def _derive_charpr_from_base(header_xml):
    """
    양식 header 의 charPr 8(본문 기본) 을 읽어, 거기서 파생한
    charPr 11/12/15/16/17 정의를 dict 로 돌려준다.
    양식의 fontRef·shadeColor 등이 정확히 일치하여 글꼴 불일치가 없다.

    파생 규칙:
      11 = 8 + bold + textColor 파랑(#0000FF)           (날짜)
      12 = 8 + bold                                     (발문)
      15 = 8 + underline BOTTOM                         (밑줄)
      16 = 8 + bold + underline BOTTOM                  (굵게+밑줄)
      17 = 8 + bold + textColor 파랑 + underline BOTTOM (날짜+밑줄)
    """
    m = re.search(r'<hh:charPr id="8".*?</hh:charPr>', header_xml, re.S)
    if not m:
        return {}
    base = m.group(0)
    defs = {}

    def make(new_id, bold=False, blue=False, underline=False):
        s = base.replace('id="8"', f'id="{new_id}"')
        if blue:
            s = s.replace('textColor="#000000"', 'textColor="#0000FF"')
        if bold and '<hh:bold/>' not in s:
            s = s.replace('<hh:underline', '<hh:bold/><hh:underline')
        if underline:
            s = s.replace('underline type="NONE"', 'underline type="BOTTOM"')
        return s

    defs['charPr11'] = make(11, bold=True, blue=True)
    defs['charPr12'] = make(12, bold=True)
    defs['charPr15'] = make(15, underline=True)
    defs['charPr16'] = make(16, bold=True, underline=True)
    defs['charPr17'] = make(17, bold=True, blue=True, underline=True)
    return defs


def _inject_styles(header_xml):
    """
    header.xml 에 필요한 스타일이 없으면 주입하고 itemCnt 를 갱신한다.
    charPr 11/12/15/16/17 은 양식 charPr 8 에서 동적 파생한다(글꼴 일치 보장).
    paraPr, borderFill 은 _STYLE_DEFS 에서 가져온다.
    """
    # charPr 을 charPr 8 에서 파생
    derived = _derive_charpr_from_base(header_xml)
    # _STYLE_DEFS + derived 를 합친다
    all_defs = dict(_STYLE_DEFS)
    all_defs.update(derived)

    plans = [
        ("borderFills", "borderFill",
         [("borderFill3", "3"), ("borderFill4", "4")]),
        ("charProperties", "charPr",
         [("charPr11", "11"), ("charPr12", "12"),
          ("charPr15", "15"), ("charPr16", "16"), ("charPr17", "17")]),
        ("paraProperties", "paraPr",
         [("paraPr13", "13"), ("paraPr14", "14")]),
    ]
    for container, item_tag, items in plans:
        open_m = re.search(r'<hh:' + container + r'\b[^>]*>', header_xml)
        close = f"</hh:{container}>"
        ci = header_xml.find(close)
        if not open_m or ci == -1:
            continue
        inner = header_xml[open_m.end():ci]
        add_xml = ""
        added = 0
        for key, idv in items:
            exists = re.search(r'<hh:' + item_tag + r' id="' + idv + r'"',
                               inner) is not None
            if not exists and all_defs.get(key):
                add_xml += all_defs[key]
                added += 1
        if add_xml:
            header_xml = header_xml[:ci] + add_xml + header_xml[ci:]
            m = re.search(r'(<hh:' + container + r' itemCnt=")(\d+)(")',
                          header_xml)
            if m:
                new_cnt = int(m.group(2)) + added
                header_xml = (header_xml[:m.start()] +
                              m.group(1) + str(new_cnt) + m.group(3) +
                              header_xml[m.end():])
    return header_xml


def _write_hwpx(output_path, files):
    """HWPX(=OPC/ZIP) 규칙에 맞게 저장. mimetype 은 STORED 로 가장 먼저.
       output_path 는 경로 문자열 또는 파일류 객체(BytesIO 등)."""
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as z:
        if "mimetype" in files:
            zi = zipfile.ZipInfo("mimetype")
            zi.compress_type = zipfile.ZIP_STORED
            z.writestr(zi, files["mimetype"])
        for name, data in files.items():
            if name == "mimetype":
                continue
            z.writestr(name, data)


def _normalize_question(obj):
    """
    다양한 입력(dict / Django Model / 객체)을 표준 dict 로 변환.
    필요한 키: date, prompt, answer, passage, choices
    """
    if isinstance(obj, dict):
        get = obj.get
    else:
        # Django 모델 인스턴스나 일반 객체: getattr 로 접근
        def get(k, default=None):
            return getattr(obj, k, default)

    choices = get("choices", []) or []
    # choices 가 JSON 문자열일 수도 있음
    if isinstance(choices, str):
        import json
        try:
            choices = json.loads(choices)
        except Exception:
            choices = [choices]

    return {
        "date":    get("date", "") or "",
        "prompt":  get("prompt", "") or "",
        "answer":  get("answer", None),
        "passage": get("passage", "") or "",
        "choices": list(choices),
    }


def build_hwpx_bytes(template_path, header_text, questions,
                     reference_path=None):
    """
    파일 대신 bytes 를 돌려준다. Django FileResponse/HttpResponse 에 바로 사용.
    questions: dict / Django Model / 객체의 리스트 (혼용 가능)
    """
    norm = [_normalize_question(q) for q in questions]
    buf = io.BytesIO()
    build_hwpx(template_path, buf, header_text, norm,
               reference_path=reference_path)
    return buf.getvalue()
