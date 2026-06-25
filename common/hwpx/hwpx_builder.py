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
# charPr 11/12/15 는 빌드 시 양식의 charPr 8 에서 동적 파생한다 (_derive_charpr_from_base).
# 양식의 fontRef·shadeColor 가 정확히 일치하여 글꼴 문제가 없다.
# paraPr, borderFill 은 정적 정의를 사용한다.
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

# 줄간격(%). 양식 기본은 발문/선택지 160%·지문박스 150%. 답답함 없는 가독성 우선
# 으로 160% 통일. 페이지 밀도(여백·빈 단락)는 양식 그대로 두기로 함.
# ★ 이 값만 바꾸면 빽빽/헐거움 조절. 150=양식 지문박스 기준, 160=양식 발문 기준.
LINE_SPACING_PCT = 160

# 줄 높이 및 줄당 글자수(보수적 추정)
LINE_VSIZE = 950
LINE_SPACING = LINE_SPACING_PCT / 100.0
LINE_HEIGHT = LINE_VSIZE * LINE_SPACING
LINES_PER_COL = BODY_HEIGHT / LINE_HEIGHT           # 135%면 ≈ 55

# 단 채움 허용오차(줄). '거의 들어가는' 문제를 한두 줄 차이로 다음 단으로 밀어내지 않게.
# 줄간격으로 용량을 확보했으니 작게 유지(크면 단 끝에서 잘릴 수 있음).
COL_FILL_TOLERANCE = 2
# 문제 전체(발문+박스+선택지)를 한 단에 통째로 유지하기 위한 안전여유(줄).
# 줄 수 추정이 약간 낮게 잡혀도 단 경계에서 발문/박스/선택지가 잘리지 않도록
# 잔여 공간을 이만큼 더 요구한다. 크게 잡으면 단이 헐거워지므로 작게 유지.
COL_KEEP_SAFETY = 1
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
# charPr → 밑줄 구간 charPr 매핑.  ★HWPX 의 charPrIDRef 는 charProperties 배열의
# 0-based '위치'로 해석된다(한/글). 양식 charPr 0~9 뒤에 주입한 3개는 반드시
# 위치=id 가 되도록 id 10/11/12 로 넣는다: 10=날짜(파랑굵게) 11=발문(굵게)
# 12=밑줄. 지문/선택지(base 8) 의 밑줄 구간만 12(밑줄)로 보낸다.
_UNDERLINE_MAP = {8: 12, 10: 10, 11: 11}


def _run(text, char_pr):
    """텍스트를 run 으로 만든다.
    U+FFF0 으로 감싸진 구간이 있으면 밑줄 run 으로 분리한다.
    예: "normal \ufff0underlined\ufff0 text"
        → normal(charPr) + underlined(밑줄charPr) + text(charPr)
    """
    MARKER = "\ufff0"
    if MARKER not in text:
        return (f'<hp:run charPrIDRef="{char_pr}">'
                f'<hp:t>{_esc(text)}</hp:t></hp:run>')

    ul_pr = _UNDERLINE_MAP.get(char_pr, 12)
    parts = text.split(MARKER)
    runs = []
    for i, seg in enumerate(parts):
        if not seg:
            continue
        cp = ul_pr if (i % 2 == 1) else char_pr
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
        # 허용오차를 더해, 추정상 한두 줄 넘치는 문제도 같은 단에 채운다.
        return self.used + lines <= self.cap + COL_FILL_TOLERANCE

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
    head_lines = _estimate_lines((q.get("date", "") + " " +
                                  q.get("prompt", "")))
    box_lines = (_estimate_lines(q["passage"]) + 1) if q.get("passage") else 0
    choices_lines = sum(_estimate_lines(ch) for ch in q.get("choices", []))
    # +사이 간격: 발문↔박스, 박스↔선택지, 문제↔문제 의 빈 줄(최대 3)
    gap_lines = (2 if q.get("passage") else 1) + 1
    total_lines = head_lines + box_lines + choices_lines + gap_lines

    # --- 단 넘김 판단 ---
    # 한 문제(발문+박스+선택지)는 통째로 같은 단에 들어가야 한다.
    #   - 발문만 단 끝에 남고 박스가 다음 단/쪽으로 가는 분리(고아 발문) 방지
    #   - 선택지가 박스와 떨어져 다음 쪽으로 넘어가는 분리 방지
    # 따라서 잔여 공간이 '문제 전체'를 못 담으면 발문에 column_break 를 넣어
    # 문제 전체를 다음 단으로 옮긴다. 단, 문제가 한 단보다 길면(=어차피 한 단에
    # 못 담음) 강제하지 않고 자연 흐름에 맡긴다(무한 빈 단 생성 방지).
    needed = total_lines + COL_KEEP_SAFETY
    remaining = tracker.cap - tracker.used
    column_break = False
    if (force_newcol_if_overflow and total_lines <= tracker.cap
            and remaining < needed):
        column_break = True
        tracker.newcol(total_lines)
    else:
        tracker.add(total_lines)

    parts = []

    # 1) 발문 단락: 미주(정답) + 날짜(파랑굵게) + 발문(굵게)
    head_runs = ""
    if "answer" in q and q["answer"] not in (None, ""):
        head_runs += _endnote_run(q["answer"], endnote_no)
    if q.get("date"):
        head_runs += _run(" " + q["date"], 10)       # 파랑 굵게
    if q.get("prompt"):
        # 발문은 굵게만(밑줄 X). 원문 밑줄 마커(U+FFF0)는 제거해 통째로 굵게.
        prompt_text = q["prompt"].replace("￰", "")
        head_runs += _run(" " + prompt_text, 11)     # 검정 굵게(발문 강조)
    parts.append(_para(head_runs, para_pr=1,
                       column_break=column_break))

    # 1-2) 발문과 박스 사이 간격(= Enter 한 번).
    #   박스(붉은 테두리)의 윗변이 발문 바로 아래 붙으면 발문에 '밑줄'이 그어진
    #   것처럼 보인다. 한 줄 띄워 발문(굵게)과 지문 박스를 분리한다.
    if q.get("passage"):
        parts.append(_para('<hp:run charPrIDRef="8"></hp:run>', para_pr=1))

    # 2) 지문 단락(붉은 박스). paraPr 13(박스 시작)으로 감싼다.
    if q.get("passage"):
        passage_runs = _run(q["passage"], 8)
        parts.append(_para(passage_runs, para_pr=13))  # 사방 빨강 테두리

    parts.append(_para('<hp:run charPrIDRef="8"></hp:run>', para_pr=1))
    # 3) 선택지 단락들 — 각 선택지는 별도 단락(엑셀의 \r\n 줄바꿈을 보존).
    if q.get("choices"):
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
        return ('borderFill id="3"' in h and 'charPr id="10"' in h
                and 'charPr id="11"' in h and 'charPr id="12"' in h
                and 'paraPr id="13"' in h)

    if not _has_required(header_xml) and reference_path:
        with zipfile.ZipFile(reference_path) as z2:
            ref_header = z2.read("Contents/header.xml").decode("utf-8")
        if _has_required(ref_header):
            header_xml = ref_header

    # 항상 실행: charPr 11/12/15 를 양식 charPr 8 에서 동적 파생하므로
    # 부족한 스타일이 있으면 어떤 경우든 보충된다.
    header_xml = _inject_styles(header_xml)

    if not ('charPr id="12"' in header_xml and 'paraPr id="13"' in header_xml):
        raise RuntimeError(
            "필수 스타일(charPr 11/12/15, paraPr 13, borderFill 3)을 "
            "header.xml 에 확보하지 못했습니다.")

    # 본문 문단(발문/선택지=paraPr1, 지문박스=paraPr13/14) 줄간격을 통일
    # → 한 단에 문제가 더 들어가 페이지가 덜 헐거워진다(추정 LINES_PER_COL 과 일치).
    header_xml = _set_para_spacing(header_xml, (0, 1, 13, 14), LINE_SPACING_PCT)

    # 박스(지문) 단락이 페이지/단 경계에서 잘리지 않게 keepLines=1.
    # 자동 column_break 를 끈 뒤에는 한/글이 박스 중간에서 끊는 일이 있어, 박스는
    # 통째로 다음 페이지로 가도록 강제한다.
    header_xml = _set_para_keep(header_xml, 13, keep_lines=True)

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
                          header_text)

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

    # 양식의 첫 본문 단락(secPr·머리말 그림을 담은 '캐리어')은 본문에서 빈 줄
    # 하나로 렌더링된다 → 1번 문제 앞 '엔터'처럼 보임. 이를 없애기 위해 첫 문제의
    # 발문 단락을 별도 단락으로 두지 않고 캐리어 단락 안에 합쳐 넣는다(머리말 그림은
    # 여백 영역에 그대로, 첫 본문 줄부터 1번 발문이 시작).
    sec = _insert_blocks_after_carrier(sec, first_p_end, blocks)

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


def _insert_blocks_after_carrier(sec, first_p_end, blocks):
    """본문 문제 블록을 캐리어 단락 뒤에 삽입하되, 첫 문제의 발문 단락은
    캐리어 단락 안으로 합쳐 1번 문제 앞의 빈 줄('엔터')을 없앤다.

    sec         : section0.xml 문자열
    first_p_end : 캐리어 단락(</hp:header> 이후 첫 최상위 단락)의 </hp:p> 끝 위치
    blocks      : 모든 문제 블록 + (선택) 끝 쪽나누기 단락이 이어붙은 문자열
                  맨 앞은 항상 첫 문제의 발문 단락(<hp:p ...>...</hp:p>).
    """
    CLOSE = "</hp:p>"
    carrier_start = sec.rfind("<hp:p ", 0, first_p_end)
    carrier = sec[carrier_start:first_p_end]

    # 첫 블록(발문 단락)을 떼어내 그 안의 run 들만 추출.
    head_end = blocks.find(CLOSE)
    if head_end == -1:
        # 예상치 못한 형태면 원래 방식대로 단순 삽입(안전 폴백).
        return sec[:first_p_end] + blocks + sec[first_p_end:]
    head_end += len(CLOSE)
    first_head = blocks[:head_end]
    rest_blocks = blocks[head_end:]
    m = re.match(r"<hp:p\b[^>]*>(.*)</hp:p>\s*$", first_head, re.S)
    head_runs = m.group(1) if m else ""

    # 캐리어의 조판 캐시(lineseg) 제거 → 합친 발문 기준으로 줄 재계산.
    carrier = re.sub(r"<hp:linesegarray>.*?</hp:linesegarray>", "",
                     carrier, flags=re.S)
    # 캐리어의 닫는 </hp:p> 직전에 발문 run 들을 끼워 넣는다.
    cut = carrier.rfind(CLOSE)
    merged_carrier = carrier[:cut] + head_runs + carrier[cut:]

    return sec[:carrier_start] + merged_carrier + rest_blocks + sec[first_p_end:]


def _derive_charpr_from_base(header_xml):
    """
    양식 header 의 charPr 8 을 읽어 파생 charPr 정의를 만든다.
    양식의 fontRef·shadeColor 등이 정확히 일치하여 글꼴 불일치가 없다.

    파생 규칙(★id = charProperties 배열 위치. 양식이 0~9 이므로 10/11/12):
      10 = 8 + bold + textColor 파랑(#0000FF)   (날짜)
      11 = 8 + bold                             (발문)
      12 = 8 + underline BOTTOM (bold 제거)     (지문 밑줄)
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
        elif not bold and '<hh:bold/>' in s:
            s = s.replace('<hh:bold/>', '')
        if underline:
            s = s.replace('underline type="NONE"', 'underline type="BOTTOM"')
        return s

    defs['charPr10'] = make(10, bold=True, blue=True)   # 날짜(파랑 굵게)
    defs['charPr11'] = make(11, bold=True)              # 발문(검정 굵게)
    defs['charPr12'] = make(12, underline=True)         # 지문 밑줄(굵게 X)
    return defs


def _inject_styles(header_xml):
    """
    header.xml 에 필요한 스타일이 없으면 주입하고 itemCnt 를 갱신한다.
    charPr 11/12/15 는 양식 charPr 8 에서 동적 파생한다(글꼴 일치 보장).
    paraPr, borderFill 은 _STYLE_DEFS 에서 가져온다.
    """
    derived = _derive_charpr_from_base(header_xml)
    all_defs = dict(_STYLE_DEFS)
    all_defs.update(derived)

    plans = [
        ("borderFills", "borderFill",
         [("borderFill3", "3"), ("borderFill4", "4")]),
        ("charProperties", "charPr",
         [("charPr10", "10"), ("charPr11", "11"), ("charPr12", "12")]),
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


def _set_para_keep(header_xml, para_id, keep_lines=False, keep_with_next=False):
    """paraPr 의 breakSetting 속성(keepLines/keepWithNext)을 설정.
       keep_lines=True → 단락이 페이지/단 경계에서 안 잘림.
       keep_with_next=True → 다음 단락과 같은 페이지에 묶임.
    """
    m = re.search(r'<hh:paraPr id="%d".*?</hh:paraPr>' % para_id, header_xml, re.S)
    if not m:
        return header_xml
    block = m.group(0)
    block = re.sub(r'keepWithNext="\d"',
                   'keepWithNext="%d"' % (1 if keep_with_next else 0),
                   block, count=1)
    block = re.sub(r'keepLines="\d"',
                   'keepLines="%d"' % (1 if keep_lines else 0),
                   block, count=1)
    return header_xml[:m.start()] + block + header_xml[m.end():]


def _set_para_spacing(header_xml, para_ids, percent):
    """지정한 paraPr id 들의 줄간격(lineSpacing PERCENT value)을 percent 로 바꾼다.
       글자모양은 건드리지 않고 문단 줄간격만 통일 → 페이지 밀도 조절.
    """
    for pid in para_ids:
        # id="1" 이 id="13" 을 잡지 않도록 닫는 따옴표까지 포함해 정확히 매칭.
        m = re.search(r'<hh:paraPr id="%d".*?</hh:paraPr>' % pid, header_xml, re.S)
        if not m:
            continue
        block = m.group(0)
        new_block = re.sub(
            r'(<hh:lineSpacing type="PERCENT" value=")\d+(")',
            r'\g<1>%d\g<2>' % percent, block)
        header_xml = header_xml[:m.start()] + new_block + header_xml[m.end():]
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
