# -*- coding: utf-8 -*-
"""변형문제 텍스트 후처리 — HWPX/PDF/엑셀 출력 공통 정규화 로직.

웹(Django)의 변형문제 HWPX·PDF 다운로드, 그리고 로컬 'AI 자동화' 의 엑셀
후처리 단계에서 같은 양식을 보장하기 위한 순수 함수 모음. Django/모델
의존성 없음 — `import re` 만 사용. dict/str 입출력.

진입 함수: `_build_modified_question(row, total_number) -> dict | None`
"""
import re as _re


# 엑셀 인라인 그림(아이콘) placeholder.
#   - 좌표형 'icon_1_3' : 어디에 있든 제거
#   - 맨몸 'icon' : 보기 마커(①②③…)에 바로 붙은 경우만 제거('icon③' → '③').
#     실제 단어 'icon'/'iconic'(뒤가 글자) 은 건드리지 않는다.
_ICON_PLACEHOLDER_RE = _re.compile(r'icon_\d+_\d+|icon(?=[①②③④⑤⑥⑦⑧⑨⑩])')


# ---------------------------------------------------------------------------
# 1) 텍스트 토큰 정리 (Excel OOXML 토큰, 줄바꿈, 빈칸 라벨)
# ---------------------------------------------------------------------------
def _hwpx_clean(text):
    """DB/엑셀 저장 텍스트를 인쇄용으로 변환.

    - Excel OOXML 토큰 `_x000D_` (CR) / `_x000A_` (LF) → 진짜 줄바꿈
    - literal `\\r\\n` (4글자) / 실제 컨트롤 문자 → 줄바꿈
    - `\\t` 는 한/글 렌더링 오류 유발 → 공백으로
    - uFFF0 강조 마커는 그대로 둠 (HWPX 빌더가 별도 처리)
    """
    if not text:
        return ""
    text = str(text)
    text = text.replace('_x000D_', '\n').replace('_x000A_', '\n')
    text = text.replace('\\r\\n', '\n').replace('\\n', '\n').replace('\\r', '\n')
    text = _re.sub(r'\r\n?', '\n', text)
    text = text.replace('\t', ' ')
    # 엑셀 인라인 그림(아이콘) placeholder 제거 — 'icon_1_3' 및 마커에 붙은 'icon③'
    text = _ICON_PLACEHOLDER_RE.sub('', text)
    # 빈칸 라벨 표기 통일: '(A)____' 처럼 라벨 뒤에만 밑줄 있는 형태를
    # '____(A)____' (양쪽 밑줄, 라벨 가운데) 로 맞춘다. 밑줄이 하나도 없는
    # '(A)'(발문의 (A),(B) 참조 등)는 그대로 둔다. 라벨 양옆에 공백이 끼어 있는
    # '____ (A) ____'(사진 18) 도 정규형으로 흡수.
    text = _re.sub(
        r'_*[ \t]*\(([A-E])\)[ \t]*_*',
        lambda m: '____(%s)____' % m.group(1) if '_' in m.group(0) else m.group(0),
        text)
    # 연속 빈줄 3+ → 2개로
    text = _re.sub(r'\n{3,}', '\n\n', text)
    return text


def _normalize_passage_markers(text):
    """지문 내 동그라미 번호 마커 표기 통일.
      1) 괄호 마커 '(①)' → '( ① )'  (괄호 안 양쪽 공백; 문장넣기 삽입표시)
      2) 괄호 없이 본문에 붙은 마커 '①However' → '① However' (마커 뒤 한 칸)
    발문에는 적용하지 않는다(어법 발문의 ①~⑤ 참조 등 훼손 방지) — 지문에만 호출.
    """
    if not text:
        return text
    M = '①②③④⑤⑥⑦⑧⑨⑩'
    text = _re.sub(r'[(（]\s*([' + M + r'])\s*[)）]', r'( \g<1> )', text)
    text = _re.sub(r'([' + M + r'])(?=\S)', r'\g<1> ', text)
    return text


def _space_marker_after_word(text):
    """'단어붙은 마커' 다음에 공백 한 칸을 강제 (본문/보기 공통, 안전).
    예) '①classified and …' → '① classified and …', '①Muscle …' → '① Muscle …'
    이미 공백이 있으면 노옵. 발문 ①~⑤ 참조는 매칭 안 됨(뒤가 ','·')'·공백).
    """
    if not text:
        return text
    M = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮'
    return _re.sub(r'([' + M + r'])(?=[A-Za-z가-힣])', r'\g<1> ', text)


def _fix_irrelevant_marker_junk(text):
    """무관한문장: 마커 뒤에 '두 칸+ 공백으로 감싼 잡토큰'이 끼어든 것을 제거.

    예) '①  The  This is called …'  → '① This is called …'
        '①  However,  Note that …'  → '① Note that …'
        '⑤  make_up  In order …'    → '⑤ In order …'
    '마커 + 2칸+ 공백 + 한 토큰 + 2칸+ 공백' 패턴만 잡으므로, 정상 문장
    '① The viewer is not asked …'(마커+한 칸 공백)은 건드리지 않는다(번호 203 형태 유지).
    """
    if not text:
        return text
    return _re.sub(r'([①②③④⑤⑥⑦⑧⑨⑩])[ \t]{2,}\S+[ \t]{2,}', r'\1 ', text)


def _parenthesize_insertion_markers(text):
    """문장넣기 지문의 삽입 위치 마커를 '( ① )' 형태로 통일.

    맨 마커 '①' 와 괄호 마커 '(①)'/'( ① )' 가 섞여 있던 것을 모두 '( ① )' 로
    맞춘다. 마커 양옆의 기존 괄호·공백(개행 제외)만 흡수하므로 문단 줄바꿈은 보존.
    """
    if not text:
        return text
    M = '①②③④⑤⑥⑦⑧⑨⑩'
    text = _re.sub(
        r'[ \t]*[(（]?[ \t]*([' + M + r'])[ \t]*[)）]?[ \t]*',
        r' ( \g<1> ) ',
        text)
    text = _re.sub(r'[ \t]{2,}', ' ', text)      # 군더더기 공백 정리
    text = _re.sub(r'[ \t]+\n', '\n', text)      # 줄 끝 공백 제거
    text = _re.sub(r'\n[ \t]+', '\n', text)      # 줄 앞 공백 제거
    return text


def _normalize_order_passage(text):
    """순서 유형 지문의 단락 간격을 통일한다.

      - 제시문 ↔ (A) 사이 : 빈 줄 1개(= 줄바꿈 두 번)
      - (A) ↔ (B) ↔ (C) 사이 : 줄바꿈만(빈 줄 없음)

    엑셀 원본이 단락마다 0~2줄로 들쭉날쭉하던 것을 위 규칙으로 맞춘다.
    줄 맨앞에 오는 문단 라벨 '(A)'~'(E)' 만 단락 경계로 본다(본문 중간의
    '(A)' 참조는 \\n 이 앞에 없으므로 건드리지 않음).
    """
    if not text:
        return text
    parts = _re.split(r'\n\s*(?=\([A-E]\)[ \t])', text)
    if len(parts) < 2:
        return text                      # 단락 라벨이 없으면 손대지 않음
    intro = parts[0].rstrip()
    blocks = [p.strip() for p in parts[1:]]
    return intro + '\n\n' + '\n'.join(blocks)


_TWO_BLANK_TYPES = {'[요약문완성]', '[연결어]', '[연결사]'}

# 지문 밑줄을 유지해야 하는 유형(밑줄 친 부분 자체가 문제) — qtype 부분일치 키.
# 지칭대상/지칭추론, 밑줄의미, 함축의미. 그 외 유형은 잔여 밑줄로 보고 제거.
_UNDERLINE_KEEP_KEYS = ('지칭', '밑줄', '함축')


# ---------------------------------------------------------------------------
# 2) 보기(선택지) 정리
# ---------------------------------------------------------------------------
def _space_inline_markers(line):
    """한 줄 안에 ②~⑩ 마커가 앞 글자에 붙어있으면 공백을 넣어 시각적으로 분리.

    예) '① (A)-(C)-(B)② (B)-(A)-(C)③ (B)-(C)-(A)'
      → '① (A)-(C)-(B)   ② (B)-(A)-(C)   ③ (B)-(C)-(A)'
    줄 시작의 ① 는 건드리지 않는다.
    """
    return _re.sub(r'(\S)([②③④⑤⑥⑦⑧⑨⑩])', r'\1   \2', line)


def _strip_marker_garbage(line):
    """보기 줄 앞에 잘못 들어간 숫자/공백을 제거.

    예) '174 ③ Practically speaking ...' → '③ Practically speaking ...'
    엑셀 데이터에 회차/페이지번호가 셀에 잘못 섞여 들어간 경우 방어.
    마커가 따라오는 경우에만 제거(일반 텍스트는 손대지 않음).
    """
    return _re.sub(r'^\s*\d+\s+(?=[①②③④⑤⑥⑦⑧⑨⑩])', '', line)


# A/B 두 답 사이 표준 구분자.
_TWO_BLANK_SEP = ' ----- '


def _normalize_two_blank(choice):
    """두-빈칸 유형 보기의 A/B 두 답 사이 구분을 '-----' 로 통일.

    DB 에 항목마다 '단어A \t단어B', '단어A   ―   단어B', '단어A …… 단어B',
    '단어A    단어B'(여러 칸 공백) 처럼 구분 표기가 들쭉날쭉해 인쇄물에서
    제각각으로 보이던 문제를 보정. 점선(……/.../⋯)·각종 대시(- – — ― 등,
    양옆 공백 필요)·탭·2칸 이상 공백을 모두 분리자로 보고 하나로 통일한다.
    단어 내부 하이픈(well-being)·붙은 하이픈(mix-up)은 양옆 공백이 없어
    매칭되지 않아 안전.
    """
    MARKERS = '①②③④⑤⑥⑦⑧⑨⑩'
    body = choice.strip()
    marker = ''
    if body and body[0] in MARKERS:
        marker = body[0]
        body = body[1:].lstrip()

    # 엑셀 셀참조(A1, B2 …) 같은 잡토큰이 보기 맨 앞에 끼어든 경우 제거.
    body = _re.sub(r'^[A-Z]{1,2}\d{1,3}\s+', '', body)

    # 대시(공백 포함) 분리자를 공백·탭보다 먼저 매칭해 '   ―   ' 전체를 한 번에 흡수.
    sep = (r'(?:'
           r'\s*(?:……|\.{3,}|⋯)\s*'
           r'|\s+[\-‐-―−]+\s+'
           r'|\s{2,}'
           r'|\t+'
           r')+')
    # 보통은 두-빈칸이라 sep 1회지만, 데이터에 3-단어 보기가 있으면 모두 통일
    # (사진 13: '① In contrast ----- Therefore Meanwhile' → 두 번째 공백도 -----로).
    body = _re.sub(sep, _TWO_BLANK_SEP, body)

    return f"{marker} {body}" if marker else body


def _split_inline_long_choices(parts, threshold=30):
    """한 줄에 보기 마커(①②③…)가 둘 이상 몰려 있고 각 보기가 문장처럼 길면
    마커 단위로 줄을 나눈다. (요지/주제 등 긴 보기 5개가 줄바꿈 없이 한 줄에
    붙어 나오던 문제 교정.) 보기가 짧으면(순서·연결어처럼 의도적으로 묶은 짧은
    보기) 원래 한 줄을 유지해 기존 레이아웃을 보존한다.
    """
    MARKERS = '①②③④⑤⑥⑦⑧⑨⑩'
    out = []
    for p in parts:
        idxs = [i for i, ch in enumerate(p) if ch in MARKERS]
        if len(idxs) >= 2:
            segs = []
            for j, start in enumerate(idxs):
                end = idxs[j + 1] if j + 1 < len(idxs) else len(p)
                seg = p[start:end].strip()
                if seg:
                    segs.append(seg)
            if segs and max(len(s) for s in segs) > threshold:
                out.extend(segs)
                continue
        out.append(p)
    return out


def _drop_duplicate_choice_set(parts):
    """보기 마커 ① 가 2회 이상 등장하면 두 번째 세트 이후를 잘라낸다.

    AI 생성 데이터에서 보기 5개가 두 세트(=10개) 중복 출력되는 케이스 방어.
    예) ['① ignores -- harmony', ..., '⑤ encourages -- fairness',
         '① confirm -- arbitrary',   ..., '⑤ reinforce -- objective']  → 앞 5개만.
    """
    MARKERS = '①②③④⑤⑥⑦⑧⑨⑩'
    seen_first = False
    out = []
    for p in parts:
        body = p.lstrip()
        if body[:1] == '①':
            if seen_first:
                break        # 두 번째 ① 등장 → 중복 세트 시작, 잘라냄
            seen_first = True
        out.append(p)
    return out


def _grammar_choice_sep(choice):
    """어법 변형 보기 '① during adopting continues' →
       '① during ----- adopting ----- continues' 로 단어 사이 구분 통일.

    보기가 영문 단어(또는 짧은 구) 2~4개로만 구성된 경우만 처리.
    단어 사이 공백(1칸 이상)을 모두 '-----' 로 치환. 한국어/문장형 보기는
    건드리지 않는다.
    """
    MARKERS = '①②③④⑤⑥⑦⑧⑨⑩'
    body = choice.strip()
    marker = ''
    if body and body[0] in MARKERS:
        marker = body[0]
        body = body[1:].strip()
    if not body:
        return choice
    # 이미 -----로 구분돼 있으면 _normalize_two_blank 와 같은 정규식으로 통일.
    if _re.search(r'-{3,}|\t|\s{2,}|……|\.{3,}|⋯', body):
        return _normalize_two_blank(choice)
    # 단어 2~4개(영문) 만 있는 경우에만 단어 사이를 ----- 로.
    words = body.split()
    if not (2 <= len(words) <= 4):
        return choice
    if not all(_re.fullmatch(r"[A-Za-z][A-Za-z\-']*", w) for w in words):
        return choice
    body = _TWO_BLANK_SEP.strip().join(' ' + w + ' ' for w in words).strip()
    body = _re.sub(r'\s+', ' ', body)
    # join 결과를 표준화: 'word1 ----- word2 ----- word3'
    body = _TWO_BLANK_SEP.join(words).strip()
    return f"{marker} {body}" if marker else body


def _hwpx_choices(option_str, qtype='', two_blank=None):
    """선택지 문자열을 리스트로 분리 — 엑셀 원본의 줄바꿈만 따른다.

    마커(①②③) 자동 분리는 하지 않음: 출제자가 의도적으로 한 줄에
    여러 보기를 둔 경우(순서 유형 등) 그 의도를 보존하기 위함.
    두-빈칸 유형(요약문완성/연결어, 또는 지문에 (A)·(B) 빈칸이 있는 어휘변형
    등)이면 A/B 두 답 사이 구분자를 '-----' 로 통일한다. two_blank 가 None 이면
    qtype 으로 판정하고, True/False 면 그 값을 강제한다.

    NOTE: _hwpx_clean 은 호출하지 않는다 — 탭(\\t)이 단어 구분자 신호로 쓰이므로
    공백 치환 전에 _normalize_two_blank 가 먼저 처리해야 한다.
    """
    if not option_str:
        return []
    text = str(option_str)
    text = text.replace('_x000D_', '\n').replace('_x000A_', '\n')
    text = text.replace('\\r\\n', '\n').replace('\\n', '\n').replace('\\r', '\n')
    text = _re.sub(r'\r\n?', '\n', text)
    text = _ICON_PLACEHOLDER_RE.sub('', text)
    parts = [c.strip() for c in text.split('\n') if c.strip()]
    parts = [_strip_marker_garbage(p) for p in parts]
    # 이중 마커(ⓐ①/①①) 및 보기 내부 '점선에 둘러싸인 잡 마커'를 먼저 제거 (사진15)
    #  — 분리(_split_inline_long_choices) 전에 해야 잡 마커에서 잘못 쪼개지지 않음.
    parts = [_strip_interior_choice_markers(_dedupe_inline_markers(p)) for p in parts]
    parts = _split_inline_long_choices(parts)
    parts = [_space_inline_markers(p) for p in parts]
    # 보기가 두 세트(10개) 중복 출력된 데이터 방어 → 앞 5개만 사용.
    parts = _drop_duplicate_choice_set(parts)
    # 마커만 있고 내용 없는 잡 항목(외톨이 '③' 등) 제거 (사진14).
    parts = _drop_orphan_marker_choices(parts)
    # 보기 시작 마커가 단어에 붙은 경우 한 칸 공백('①talented' → '① talented').
    parts = [_space_marker_after_word(p) for p in parts]
    if two_blank is None:
        two_blank = (qtype or '') in _TWO_BLANK_TYPES
    if two_blank:
        parts = [_normalize_two_blank(p) for p in parts]
    elif '어법' in (qtype or ''):
        # 어법 변형 보기 '① word1 word2 word3' → '① word1 ----- word2 ----- word3'.
        parts = [_grammar_choice_sep(p) for p in parts]
    # 남은 탭은 마지막에 공백으로 (한/글 렌더링 오류 방지)
    parts = [p.replace('\t', ' ') for p in parts]
    return parts


# ---------------------------------------------------------------------------
# 3) 어법·어휘 밑줄형, 데이터 오류 필터, 통합 진입
# ---------------------------------------------------------------------------
_CIRCLED_NUMS = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮'


def _shorten_long_blanks(text, keep=10):
    """지문의 너무 긴 밑줄 빈칸(______…)을 일정 길이로 줄인다."""
    if not text:
        return text
    return _re.sub(r'_{11,}', '_' * keep, text)


def _number_underline_segments(text):
    """어법·어휘 밑줄형: 밑줄(U+FFF0…) 구간마다 번호 ①②③④⑤를 밑줄 앞에 새로
    매긴다. 기존 번호(밑줄 앞/뒤, 그리고 밑줄 안)는 제거. 반환:(텍스트, 밑줄개수)."""
    MARK = '￰'
    CIRC = _CIRCLED_NUMS
    parts = _re.split('(' + MARK + '.*?' + MARK + ')', text)
    seq = ['①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '⑩']
    out, n, count = [], 0, 0
    for p in parts:
        if p.startswith(MARK) and p.endswith(MARK) and len(p) >= 2:
            if out:
                out[-1] = _re.sub(r'[' + CIRC + r']\s*$', '', out[-1])
            # 밑줄 안에 이미 번호가 들어있으면 제거(이중 번호 방지): ￰①word￰ → ￰word￰
            p = _re.sub(r'^' + MARK + r'\s*[' + CIRC + r']\s*', MARK, p)
            num = seq[n] if n < len(seq) else '?'
            n += 1
            count += 1
            out.append(num + ' ' + p)
        else:
            out.append(_re.sub(r'^\s*[' + CIRC + r']', '', p))
    return ''.join(out), count


def _has_cjk_error(choices):
    """보기에 한자(CJK)+영문이 섞이면 데이터 오류(예: 記錄)."""
    for c in (choices or []):
        if _re.search(r'[一-鿿]', c) and _re.search(r'[A-Za-z]', c):
            return True
    return False


def _normalize_truefalse_prompt(prompt, qtype):
    """일치불일치 유형의 영어 발문을 표준 한국어 발문으로 치환.

    'Which of the following is NOT true ...' 같은 순수 영어 발문만 바꾼다.
    한글이 하나라도 있는 발문('Rembrandt에 관한 내용과 일치하지 않는 것은?' 등)은
    이미 한국어 양식이므로 고유명사를 보존하기 위해 그대로 둔다.
    부정(NOT) 여부로 '일치하지 않는 것은?' / '일치하는 것은?' 을 고른다.
    """
    if '일치' not in qtype or not prompt:
        return prompt
    if _re.search(r'[가-힣]', prompt):          # 이미 한국어 발문 → 보존
        return prompt
    if not _re.search(r'[A-Za-z]', prompt):     # 영문도 한글도 아니면 손대지 않음
        return prompt
    negative = bool(_re.search(r"\bnot\b|n['’]t\b", prompt, _re.IGNORECASE))
    if negative:
        return '다음 글의 내용과 일치하지 않는 것은?'
    return '다음 글의 내용과 일치하는 것은?'


def _is_two_blank(qtype, sentence, prompt):
    """두-빈칸((A)/(B)) 유형인지 판정.

    요약문완성/연결어/연결사 유형이거나, 지문에 밑줄로 둘러싸인 (A)·(B) 빈칸
    (___(A)___ 등)이 모두 있는 경우(어휘변형 '빈칸(A)(B)' 등)를 두-빈칸으로 본다.
    순서 유형의 문단 라벨 '(A) …'(밑줄 없음, (C)까지 동반)은 빈칸이 아니므로
    제외 — 이 경우 보기에 구분자를 넣으면 안 된다.
    '(A),(B)에 공통으로 들어갈' 유형은 보기가 '한 낱말 = 양쪽 공통답'이라 두-빈칸이
    아니다(보기에 구분자 넣으면 안 됨) — 발문에 '공통' 있으면 제외 (사진11).
    """
    if '공통' in (prompt or ''):
        return False
    if (qtype or '') in _TWO_BLANK_TYPES:
        return True
    s = sentence or ''
    has_a = bool(_re.search(r'_\(A\)|\(A\)_', s))
    has_b = bool(_re.search(r'_\(B\)|\(B\)_', s))
    return has_a and has_b


# ---------------------------------------------------------------------------
# 4) 품질 불량 검출 · 마커/간격 정리 (2026-06-28 일괄 추가)
#    AI 생성 변형문제의 정형 불량을 인쇄 직전에 자동 교정/제외한다.
# ---------------------------------------------------------------------------
_STD_CIRCLED = '①②③④⑤⑥⑦⑧⑨⑩'

# 다른 양식의 번호 글리프(➀ ❶ ⑴ ⒈ 등) → 표준 동그라미 번호 매핑.
_ALT_NUM_TABLE = {}
for _variants in (
    '➀➁➂➃➄➅➆➇➈➉',   # dingbat circled
    '➊➋➌➍➎➏➐➑➒➓',   # dingbat negative circled
    '❶❷❸❹❺❻❼❽❾❿',   # negative circled
    '⓵⓶⓷⓸⓹⓺⓻⓼⓽⓾',  # double circled
    '⑴⑵⑶⑷⑸⑹⑺⑻⑼⑽',   # parenthesized number
    '⒈⒉⒊⒋⒌⒍⒎⒏⒐⒑',   # number + full stop
):
    for _i, _ch in enumerate(_variants):
        _ALT_NUM_TABLE[ord(_ch)] = _STD_CIRCLED[_i]


def _normalize_alt_number_glyphs(text):
    """번호가 다른 양식(➀ ❶ ⑴ ⒈ …)으로 된 마커를 표준 ①②③ 으로 통일."""
    if not text:
        return text
    return text.translate(_ALT_NUM_TABLE)


def _is_corrupted_AE_option(option_str):
    """문장넣기 보기가 '① (A) ② (B) ③ (C) ④ (D) ⑤ (E)' 형태인지 판정.

    이 보기 형태는 본문 삽입 마커가 ①~⑤ 가 아니라 (A)~(E)(또는 깨진 placeholder
    'vitamin_D','einsteinium' 등)로 들어간 불량 데이터의 표식이다.
    """
    if not option_str:
        return False
    return bool(_re.search(
        r'①\s*\(?\s*A\s*\)?.*②\s*\(?\s*B\s*\)?.*③\s*\(?\s*C\s*\)?'
        r'.*④\s*\(?\s*D\s*\)?.*⑤\s*\(?\s*E\s*\)?', str(option_str), _re.S))


def _marker_like_token(t):
    """문장넣기 (A)~(E) 삽입 마커(또는 깨진 placeholder) 후보 토큰인가."""
    if _re.fullmatch(r'[A-Za-z]', t):              # 단일 글자 A~E / e
        return True
    if '_' in t:                                    # vitamin_D, atomic_number_99
        return True
    if _re.fullmatch(r'[A-Z]{2,}', t):             # UCLA 등 약어 → 마커 아님
        return False
    return bool(_re.fullmatch(r'[A-Za-z][A-Za-z0-9]*', t))  # calciferol, Es …


def _renumber_insertion_markers(text):
    """문장넣기: 본문의 (A)~(E)·깨진 placeholder 삽입 마커를 ( ① )~( ⑤ ) 로 치환.

    괄호로 둘러싼 '단일 토큰'만 마커 후보(_marker_like_token)로 보고 등장 순서대로
    번호를 매긴다. (D)/(E) 가 'calciferol'·'einsteinium'·'vitamin_D' 같은 원소/
    비타민명으로 깨진 케이스까지 위치 기준으로 정상 번호로 복구된다.
    """
    if not text:
        return text
    pat = _re.compile(r'[ \t]*[(（]\s*([A-Za-z][A-Za-z0-9_]*)\s*[)）][ \t]*')
    out, last, n = [], 0, 0
    for m in pat.finditer(text):
        if not _marker_like_token(m.group(1)):
            continue
        out.append(text[last:m.start()])
        out.append(' ( %s ) ' % (_STD_CIRCLED[n] if n < len(_STD_CIRCLED) else '?'))
        n += 1
        last = m.end()
    if n == 0:
        return text
    out.append(text[last:])
    res = ''.join(out)
    res = _re.sub(r'[ \t]{2,}', ' ', res)
    res = _re.sub(r'[ \t]+\n', '\n', res)
    res = _re.sub(r'\n[ \t]+', '\n', res)
    return res


def _normalize_insertion_intro(text):
    """문장넣기 제시문(첫 줄)과 본문 사이를 '빈 줄 1개(=\\n\\n)' 로 통일.

    첫 줄을 명시적으로 잡아 (re.S + 비탐욕 조합의 잠재 버그 회피) 본문과 분리.
    """
    if not text:
        return text
    text = text.lstrip()
    m = _re.match(r'([^\n]+)\n+([\s\S]+)$', text)
    if m:
        return m.group(1).rstrip() + '\n\n' + m.group(2).lstrip().rstrip()
    return text.rstrip()


def _strip_bracket_garbage(text):
    """대괄호 잡줄/꼬리 제거(어법·어휘 제외 호출).

      - '[' 로 시작하는 줄(통째 [..] 인용 줄) 삭제
      - 마지막 '내용 줄' 이 ']' / '"]' / "']" 로 끝나면 그 줄 통째로 삭제
        (예: 'Robinson: Navigating Cougar-Cub Dating and Relationships"]' → 통째 삭제)
      - 마지막 종결부호(.!?…) 뒤 꼬리에 '[' 또는 ']' 가 있으면 그 꼬리만 제거

    NOTE: 어법·어휘는 본문에 '[A / B]' 선택지 대괄호를 정상적으로 쓰므로 이 함수를
    호출하면 안 된다(_build_modified_question 에서 유형으로 가드).
    """
    if not text:
        return text
    # 1) '[' 로 시작하는 줄(통째 인용)은 삭제
    lines = [ln for ln in text.split('\n') if not ln.lstrip().startswith('[')]
    # 2) 마지막 content 줄이 ']' / '"]' / "']" 로 끝나면 그 줄 통째로 삭제
    #    (각주·빈 줄을 건너뛴 '내용 줄' 기준)
    while lines:
        idx = None
        for i in range(len(lines) - 1, -1, -1):
            s = lines[i].strip()
            if not s or s.startswith('*') or s.startswith('※'):
                continue
            idx = i
            break
        if idx is None:
            break
        s = lines[idx].rstrip()
        if s.endswith(']') or s.endswith('"]') or s.endswith("']") or s.endswith('"]'):
            lines.pop(idx)
            continue
        break
    text = '\n'.join(lines)
    # 3) 마지막 종결부호 뒤 꼬리에 '[' 또는 ']' 가 남아 있으면 꼬리만 제거
    terms = list(_re.finditer(r'[.!?…][”’"\')]*', text))
    if terms:
        end = terms[-1].end()
        tail = text[end:]
        if '[' in tail or ']' in tail:
            text = text[:end]
    return text


def _strip_summary_arrows(text):
    """본문↔요약문 사이의 화살표 마커(↓ → ⇒ ⇓ ⇨ ▼ ▽ ⬇) 제거.

    요약문완성/연결어 일부 데이터에서 본문 끝 또는 요약문 시작 줄에 시각적 화살표가
    들어있는 케이스(사진 11/19/20). 화살표만 제거하고 양옆 공백·줄바꿈은 정리.
    """
    if not text:
        return text
    text = _re.sub(r'[←-⇿⟰-⟿⬅-⬇⮕▼▽⬇]+', '', text)
    text = _re.sub(r'[ \t]{2,}', ' ', text)
    text = _re.sub(r'^[ \t]+', '', text, flags=_re.M)   # 줄 앞 공백 정리
    text = _re.sub(r'[ \t]+$', '', text, flags=_re.M)   # 줄 끝 공백 정리
    text = _re.sub(r'\n{3,}', '\n\n', text)
    return text


def _compact_paragraphs(text):
    """단락 내부 줄바꿈(\\n)을 공백으로 합쳐 한 단락으로 만든다.

    빈 줄(\\n\\n+)은 단락 경계로 보존 — 요약문완성의 '본문↔요약문',
    문장넣기의 '제시문↔본문', 순서의 '제시문↔(A)~(C)' 단락 구분은 유지된다.
    """
    if not text:
        return text
    SENT = '\x01PARA\x01'
    text = _re.sub(r'\n[ \t]*\n+', SENT, text)
    text = text.replace('\n', ' ')
    text = _re.sub(r'[ \t]{2,}', ' ', text)
    text = text.replace(SENT, '\n\n')
    return text.strip()


def _is_nonstandard_labeled_passage(sentence, choices):
    """본문에 (A)~(F) 라벨 4개 이상 + 보기가 한국어인 비표준 변형 유형.

    사진 23: 본문에 '(A)excited','(B)it'... 6개 라벨이 끼고, 보기는 '① In part (A),
    we can see ...' 같은 한국어 해설형 → 수능 표준 양식이 아니므로 문제 통째 제외.
    """
    if not sentence or not choices:
        return False
    labels = set(_re.findall(r'\(([A-F])\)', sentence))
    if len(labels) < 4:
        return False
    korean_count = sum(1 for c in choices if _re.search(r'[가-힣]', c))
    return korean_count >= max(2, len(choices) // 2)


def _extend_to_underline(text):
    """어법 변형 밑줄에서 '￰to￰ 다음단어' → '￰to 다음단어￰' 로 확장.

    'to' 만 밑줄 친 데이터를 'to + 동사' 한 덩어리로 묶어 인쇄 (사진 16 요구).
    소문자 to / 대문자 To 모두 처리.
    """
    if not text:
        return text
    MARK = '￰'
    return _re.sub(
        MARK + r'([Tt]o)' + MARK + r'(\s+)([A-Za-z][A-Za-z\-\']*)',
        MARK + r'\1\2\3' + MARK, text)


def _strip_type_label_garbage(text):
    """지문에 잘못 삽입된 '유형 라벨' 대괄호 잡줄 제거(전 유형, 어휘·어법 포함).

    예) '[ 주제 / 제목 / 요지 ]', '[주장/요지]' 처럼 대괄호 안이 '한글+슬래시(+공백/콤마)'
    로만 이뤄지고 슬래시가 1개 이상인 것. 어휘·어법의 '[uncomplicated / intricate]'
    (영어 선택지)나 '[중략]'(슬래시 없음)은 매칭되지 않아 그대로 둔다.
    """
    if not text:
        return text
    return _re.sub(r'[ \t]*\[[\s가-힣,·]*(?:/[\s가-힣,·]*)+\][ \t]*', ' ', text)


def _strip_trailing_blank(text):
    """맨 끝의 쓸데없는 줄바꿈/빈 줄/공백 제거(박스 끝 빈 줄 방지)."""
    if not text:
        return text
    return text.rstrip()


def _is_incomplete_ending(text):
    """마지막 문장이 '맨 소문자 낱말'로 끊겨 있으면(잘림) True → 문제 제외.

    정상 종결('… .'/'…?'/'…!'/'… ."'), 빈칸 끝('… (B)'/'____(B)____'), 서명
    ('Best regards, John Austin'·대문자 이름), 각주('*ionosphere : 전리층'),
    한글 끝 등은 모두 '맨 소문자 알파벳 낱말'이 아니므로 건드리지 않는다.
    오직 'It doesn't' / 'expand beyond its' 처럼 소문자 낱말로 뚝 끊긴 진짜 잘림만 잡는다.
    """
    if not text:
        return False
    # 각주(* / ※)·빈 줄을 건너뛰고 마지막 '내용 줄'을 찾는다.
    last = None
    for ln in reversed(text.split('\n')):
        s = ln.strip()
        if not s or s.startswith('*') or s.startswith('※'):
            continue
        last = s
        break
    if not last:
        return False
    # 같은 줄 끝에 붙은 각주 정의(' … .   *ionosphere : 전리층') 제거.
    #   - 각주 정의는 탭/2칸+공백으로 본문과 떨어져 있다.
    #   - 본문 중 단일 공백 각주 표시('a little *congestion')는 건드리지 않는다.
    last = _re.sub(r'(?:\s{2,}|\t)\s*[*※].*$', '', last).rstrip()
    # 끝에 매달린 빈 삽입 마커 '( ⑤ )' 제거(삽입점이 문장 끝일 수 있음).
    last = _re.sub(r'[ \t]*[(（]?\s*[' + _STD_CIRCLED + r']\s*[)）]?\s*$', '', last).rstrip()
    if not last:
        return False
    m = _re.search(r'([A-Za-z][A-Za-z\'’]*)$', last)   # 문장이 '맨 알파벳 낱말'로 끝?
    return bool(m and m.group(1)[0].islower())


_EMAIL_URL_RE = _re.compile(r'@|www\.|https?://|\.com|\.org|\.edu|\.net|\.gov', _re.I)


def _has_placeholder_garbage(text):
    """본문에 'vitamin_D','atomic_number_99','make_up','Hoosier_State' 같은
    placeholder/잡토큰(밑줄결합 식별자)이 있으면 True → 품질 불량으로 제외.

    이메일/URL(s_christen@gwu.edu, www.k_culture.org 등) 안의 밑줄은 정상이므로 제외.
    """
    if not text:
        return False
    for m in _re.finditer(r'[A-Za-z]+(?:_[A-Za-z0-9]+)+', text):
        window = text[max(0, m.start() - 25): m.end() + 5]
        if _EMAIL_URL_RE.search(window):
            continue
        return True
    return False


def _has_parenthesized_sentence(text):
    """'( "Explore your hypothesis and assess its validity." )' 처럼 따옴표 인용문이나
    완결 문장이 통째로 괄호에 감싸진 잡조각이 있으면 True → 품질 불량으로 제외.

    삽입 마커 '( ① )'·문단 라벨 '(A)' 와는 구분된다(여러 낱말 + 따옴표/종결부호).
    """
    if not text:
        return False
    # 괄호 안이 '대문자로 시작해 종결부호로 끝나는 인용 완결 문장' 하나로만 채워진 경우만
    # 불량으로 본다. 예) ( "Explore your hypothesis and assess its validity." )
    # 정상 인용 곁다리 '(called "shadowing")', '(for example, "now only $20")',
    # '("larks")', 종결부호 없는 인용 속담 '(“Birds of a feather flock together”)' 은 제외.
    return bool(_re.search(
        r'[(（]\s*[“"][A-Z][^”"]*[.?!][”"]\s*[)）]', text))


_CIRCLED_LOWER = {'ⓐ': 'A', 'ⓑ': 'B', 'ⓒ': 'C', 'ⓓ': 'D', 'ⓔ': 'E'}


def _standardize_connector_blanks(text):
    """연결어/연결사 본문 빈칸을 '____(A)____ / ____(B)____' 로 표준화.

      - 'ⓐ ________' / 'ⓑ ________'  → '____(A)____' / '____(B)____'
      - '(A) ________' / '(A)____' / '___(A)___'  → '____(A)____'
      - 라벨 없는 '________' 빈칸이 2개뿐이면 등장 순서대로 (A),(B) 부여
    마지막에 지문~보기 사이에 남은 잔여 ⓐ ⓑ 마커를 제거한다.
    """
    if not text:
        return text
    # ⓐ/ⓑ + 밑줄 → (A)/(B) 라벨 빈칸
    text = _re.sub(r'([ⓐⓑⓒⓓⓔ])\s*_{2,}',
                   lambda m: '____(%s)____' % _CIRCLED_LOWER[m.group(1)], text)
    # (A) 라벨의 모든 변형(앞뒤·한쪽 밑줄, 괄호 안 공백)을 한 번에 정규형으로.
    #   양옆 밑줄을 통째로 흡수하므로 멱등(idempotent) — 두 번 돌려도 안 늘어난다.
    text = _re.sub(r'_*\s*[(（]\s*([ABCDE])\s*[)）]\s*_*', r'____(\1)____', text)
    # 라벨 없는 긴 밑줄 빈칸이 정확히 2개면 (A),(B) 로 라벨링
    if not _re.search(r'\([ABCDE]\)', text):
        blanks = list(_re.finditer(r'_{4,}', text))
        if len(blanks) == 2:
            for lab, m in zip(('B', 'A'), reversed(blanks)):  # 뒤에서부터 치환(인덱스 보존)
                text = text[:m.start()] + '____(%s)____' % lab + text[m.end():]
    # 본문 끝에 남은 '(A) (B)' 헤더(보기 열 제목이 지문에 딸려온 잔재) 제거.
    #   예: '… make the music instead.____(A)____ ____(B)____' → '… instead.'
    text = _re.sub(r'\s*(?:____\([ABCDE]\)____\s*){1,3}$', '', text).rstrip()
    # 잔여 ⓐ ⓑ 마커 제거(지문~보기 사이 군더더기) + 군더더기 공백 정리
    text = _re.sub(r'\s*[ⓐⓑⓒⓓⓔ]\s*', ' ', text)
    text = _re.sub(r'[ \t]{2,}', ' ', text)
    return text


def _normalize_order_choice_sep(choice):
    """순서 유형 보기의 (A)(B)(C) 사이 구분 기호를 짧은 하이픈 '-'(공백 없음)으로 통일.

    예) '① (A) — (C) — (B)' · '① (A)―(C)―(B)' · '① (A) - (C) - (B)'
      → '① (A)-(C)-(B)'
    각종 대시(- – — ― −)·물결(~)을 양옆 공백까지 흡수해 '-' 로 맞춘다.
    괄호 사이('…) <기호> (…')만 건드리므로 본문/다른 보기엔 영향 없다.
    """
    if not choice:
        return choice
    return _re.sub(r'([)）])\s*[-‐-―−~]\s*([(（])', r'\1-\2', choice)


def _is_broken_connector(text):
    """연결어/연결사인데 (A)/(B) 빈칸이 '문장 사이 삽입'처럼 쓰인 불량 구조면 True.

    정상: '… ____(A)____, you are likely …'(문장 안, 뒤가 소문자/쉼표)
    불량: '… areas. ____(A)____ Various viewpoints …'(앞이 마침표, 뒤가 대문자 → 독립
          문장을 가르는 삽입 마커처럼 사용). 이런 구조는 연결어로 복구 불가 → 제외.
    """
    if not text:
        return False
    return bool(_re.search(r'(?:^|[.!?][”’"\')]*\s+)_*\([AB]\)_*\s+[A-Z]', text))


def _extract_abc_options(sentence):
    """본문의 (A)[x / y] (B)[..] (C)[..] 브래킷에서 각 칸 후보 단어를 추출.

    세 칸이 모두 있으면 {'A':[...],'B':[...],'C':[...]} 반환, 아니면 None.
    """
    if not sentence:
        return None
    opts = {}
    for lab in ('A', 'B', 'C'):
        m = _re.search(r'\(' + lab + r'\)\s*\[([^\]]*)\]', sentence)
        if not m:
            return None
        parts = [p.strip() for p in _re.split(r'\s*/\s*', m.group(1)) if p.strip()]
        if not parts:
            return None
        opts[lab] = parts
    return opts


def _segment_three_blank(body, opts):
    """공백만으로 붙은 세 칸 보기('shifted noticeable displaced from')를 본문 후보로
    분절해 [A,B,C] 로 반환. 분절 실패 시 None. (두 낱말 답 'displaced from' 대응)"""
    text = _re.sub(r'\s+', ' ', body).strip()

    def match_at(s, candidates):
        for cand in sorted(candidates, key=len, reverse=True):
            if s == cand:
                return cand, ''
            if s.startswith(cand + ' '):
                return cand, s[len(cand):].strip()
        return None, None

    a, rest = match_at(text, opts['A'])
    if a is None:
        return None
    b, rest2 = match_at(rest, opts['B'])
    if b is None:
        return None
    c = rest2.strip()
    # C는 A·B 매칭 후 남는 부분으로 둔다(본문 후보와 살짝 다른 'fire'/'fired'식
    # 데이터 불일치도 허용해 ②⑤ 보기까지 구분자가 들어가게 함, 사진12).
    if not c:
        return None
    return [a, b, c]


def _normalize_three_blank(choice, opts):
    """세 칸((A)(B)(C)) 보기의 칸 사이 구분을 ' ----- ' 로 통일.

      - 이미 구분자(…… / 점 / 대시 / 2칸+공백)가 있으면 그걸로 3분할
      - 구분자가 없고 공백만이면 본문 후보(opts)로 분절
    3분할 실패 시 원본 유지.
    """
    MARKERS = '①②③④⑤⑥⑦⑧⑨⑩'
    body = choice.strip()
    marker = ''
    if body and body[0] in MARKERS:
        marker = body[0]
        body = body[1:].strip()

    sep = r'\s*(?:……|⋯|\.{2,}|…)\s*|\s+[\-‐-―−]+\s+|\s{2,}'
    parts = [p.strip() for p in _re.split(sep, body) if p.strip()]
    if len(parts) != 3:
        seg = _segment_three_blank(body, opts) if opts else None
        if not seg:
            return choice
        parts = seg
    res = _TWO_BLANK_SEP.join(parts)
    return f"{marker} {res}" if marker else res


# ---------------------------------------------------------------------------
# 5) 2026-06-28 추가 15개 수정 (새 폴더\이미지001-015)
# ---------------------------------------------------------------------------
_CIRC15 = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮'


def _strip_leading_stars(text):
    """지문 맨 앞 별표시 장식('[★★★]','★★★','***','[*]')을 제거 (사진13).

    각주 '* hatchling: 갓 부화한 동물'(별표 1개 + 공백 + 단어)는 건드리지 않는다.
    """
    if not text:
        return text
    return _re.sub(r'^\s*(?:\[[\s★☆✦✧❋*]*\]|[★☆✦✧❋]+|\*{2,})\s*', '', text)


def _dedupe_inline_markers(text):
    """이중·중복 번호 마커 정리(본문·보기 공통).
      - 동그라미 글자(ⓐ~ⓩ/Ⓐ~Ⓩ)가 동그라미 숫자 옆 → 글자 제거: 'ⓐ①'→'①' (사진8)
      - 같은 동그라미 숫자가 잡문자(0~4) 끼고 중복 → 하나: '①①'·'②†②'→'①'·'②' (사진4,9)
    """
    if not text:
        return text
    C = _CIRC15
    text = _re.sub(r'[Ⓐ-Ⓩⓐ-ⓩ]\s*(?=[' + C + r'])', '', text)
    text = _re.sub(r'(?<=[' + C + r'])\s*[Ⓐ-Ⓩⓐ-ⓩ]', '', text)
    text = _re.sub(r'([' + C + r'])[^0-9A-Za-z가-힣\n]{0,4}\1', r'\1', text)
    return text


def _collapse_space_before_marker(text):
    """본문에서 마커 앞 군더더기 공백(2칸+) → 1칸 (사진3 '… fully    ③ engaged')."""
    if not text:
        return text
    return _re.sub(r'[ \t]{2,}(?=[' + _CIRC15 + r'])', ' ', text)


def _strip_stray_dots(text):
    """본문 중 단어 사이에 낀 잡 점선('called.....a' / 'in……a') 제거 → 공백 (사진5)."""
    if not text:
        return text
    return _re.sub(r'(?<=[A-Za-z])\s*(?:\.{3,}|…+|⋯|‥)\s*(?=[A-Za-z])', ' ', text)


def _strip_trailing_marker_row(text):
    """문장넣기 끝에 중복으로 붙은 삽입마커 행 '( ① ) ( ② ) … ( ⑤ )' 제거 (사진6)."""
    if not text:
        return text
    return _re.sub(r'(?:\s*[(（]\s*[' + _CIRC15 + r']\s*[)）]\s*){2,}$', '', text).rstrip()


def _strip_trailing_dashes(text):
    """끝에 의미없이 붙은 하이픈/대시 꼬리 제거 (사진7). 밑줄(빈칸)은 보존."""
    if not text:
        return text
    return _re.sub(r'\s+[-–—―]{1,}\s*$', '', text.rstrip()).rstrip()


def _drop_orphan_marker_choices(parts):
    """보기 목록에서 '마커만 있고 내용 없는' 잡 항목 제거 (사진14 '⑤' 뒤 외톨이 '③')."""
    out = []
    for p in parts:
        body = _re.sub(r'^[' + _CIRC15 + r']\s*', '', p.strip())
        if body.strip():
            out.append(p)
    return out


def _strip_interior_choice_markers(choice):
    """보기 내부에 '점선으로 둘러싸인 잡 마커'를 제거 (사진15 'calculatio…②…that').

    점선(…/.../⋯)이 붙은 마커만 제거하므로, 점선 없이 공백으로 구분된 정상 마커
    (여러 보기를 한 줄에 둔 '① …  ② …  ③ …'·순서 보기)는 보존한다.
    """
    if not choice or ('.' not in choice and '…' not in choice and '⋯' not in choice):
        return choice
    C = _CIRC15
    pat = (r'\s*(?:\.{2,}|…+|⋯)\s*[' + C + r']\s*(?:\.{2,}|…+|⋯)?\s*'
           r'|\s*[' + C + r']\s*(?:\.{2,}|…+|⋯)\s*')
    return _re.sub(pat, ' ', choice)


def _build_modified_question(r, total_number):
    """변형문제 한 행 → 빌더 dict. 데이터 오류/번호 깨짐이면 None(제외).

    입력 dict 키: qtype, question, sentence, option, answer
    """
    qtype = (r.get('qtype', '') or '')
    prompt = _hwpx_clean(r.get('question', '') or '')
    prompt = _normalize_truefalse_prompt(prompt, qtype)
    sentence = _hwpx_clean(r.get('sentence', '') or '')
    choices = _hwpx_choices(r.get('option', '') or '', qtype,
                            two_blank=_is_two_blank(qtype, sentence, prompt))
    choices = [c for c in choices if c.strip().lower() not in ('answer', '정답')]
    answer = (r.get('answer', '') or '').replace('	', ' ')
    if ('어휘' in qtype or '어법' in qtype) and '￰' in sentence:
        # 어법 변형의 'to' 만 밑줄 친 경우 다음 단어까지 확장 ('to get' 한 덩어리).
        sentence = _extend_to_underline(sentence)
        sentence, n = _number_underline_segments(sentence)
        if n != 5:
            return None
        # 본문에 마커가 단어에 붙은 경우(①classified) 한 칸 띄움.
        sentence = _space_marker_after_word(sentence)
        choices = []
    else:
        # 지문 밑줄(U+FFF0)은 '밑줄 친 부분' 자체가 문제인 유형에서만 의미가 있다
        # — 지칭대상/지칭추론·밑줄의미·함축의미. 그 외(문장넣기·일치불일치·순서·
        # 주제 등)는 원문에서 딸려온 잔여 밑줄이므로 제거한다.
        # (어법·어휘는 위에서 번호 매김으로 따로 처리.)
        if not any(k in qtype for k in _UNDERLINE_KEEP_KEYS):
            sentence = sentence.replace('￰', '')
        # 다른 양식 번호 글리프(➀ ❶ ⑴ ⒈ …) → 표준 ①②③ 으로 통일.
        sentence = _normalize_alt_number_glyphs(sentence)
        if '문장넣기' in qtype:
            # 보기가 '① (A) … ⑤ (E)' 거나 본문에 (A) 마커가 있으면, 본문 삽입
            # 마커(깨진 placeholder 포함)를 ( ① )~( ⑤ ) 로 복구하고 보기는 버린다.
            if _is_corrupted_AE_option(r.get('option', '')) or '(A)' in sentence:
                sentence = _renumber_insertion_markers(sentence)
            else:
                sentence = _parenthesize_insertion_markers(sentence)
            sentence = _normalize_insertion_intro(sentence)   # 제시문↔본문 빈 줄 1개
            sentence = _strip_trailing_marker_row(sentence)   # 끝 '( ① )…( ⑤ )' 중복행 제거(사진6)
            choices = []                                      # 삽입 위치 = 보기 → 별도 보기 제거
        elif '순서' in qtype:
            # 제시문↔(A)=빈 줄 1개, (A)↔(B)↔(C)=줄바꿈만 으로 통일.
            sentence = _normalize_order_passage(sentence)
            # 보기 (A)(B)(C) 사이 구분 기호를 짧은 하이픈 '-' 로 통일.
            choices = [_normalize_order_choice_sep(c) for c in choices]
        elif '무관' in qtype:
            # 마커 뒤 '두 칸+ 공백으로 감싼 잡토큰'(번호 204 형태) 제거 → 번호 203 형태로.
            sentence = _fix_irrelevant_marker_junk(sentence)
            sentence = _normalize_passage_markers(sentence)
            sentence = _space_marker_after_word(sentence)
        elif '연결' in qtype:
            # 연결어/연결사 본문 빈칸을 ____(A)____ / ____(B)____ 로 표준화.
            sentence = _standardize_connector_blanks(sentence)
            # 본문↔요약·빈칸 줄 사이 화살표(↓→⇒…) 제거 (사진 11).
            sentence = _strip_summary_arrows(sentence)
        elif '요약' in qtype:
            # 본문↔요약문 사이 화살표(↓→⇒…) 제거 (사진 19/20).
            sentence = _strip_summary_arrows(sentence)
        else:
            sentence = _normalize_passage_markers(sentence)

    # ---- 전 유형 공통 품질 정리/검출 ----
    # 지문 맨 앞 별표시([★★★]) 제거(사진13) — 대괄호 정리보다 먼저 해야 줄 통째 삭제 방지.
    sentence = _strip_leading_stars(sentence)
    # 이중·중복 마커(ⓐ①/①①/②†②) 정리(사진4,8,9), 마커 앞 군더더기 공백(사진3),
    # 단어 사이 잡 점선(사진5) 정리.
    sentence = _dedupe_inline_markers(sentence)
    sentence = _collapse_space_before_marker(sentence)
    sentence = _strip_stray_dots(sentence)
    # 유형 라벨 잡줄('[ 주제 / 제목 / 요지 ]' 등)은 전 유형에서 제거(어휘/어법 포함).
    sentence = _strip_type_label_garbage(sentence)
    # 어법·어휘는 본문 '[A / B]' 선택지 대괄호가 정상이므로 일반 대괄호 정리에선 제외.
    if not ('어법' in qtype or '어휘' in qtype):
        sentence = _strip_bracket_garbage(sentence)           # 대괄호 잡줄/꼬리 제거
    sentence = _shorten_long_blanks(sentence)
    # 본문 단락화: 문장넣기/순서는 빈 줄로 단락 구분이 의미 있고 한 단락 내부엔
    # 줄바꿈이 거의 없어 안전, 요약문완성/연결어는 본문↔요약/빈칸을 빈 줄로
    # 보존하므로 안전. 단일 \n 은 공백으로 합쳐 한 단락이 한 덩어리로 인쇄되게 함.
    sentence = _compact_paragraphs(sentence)
    sentence = _strip_trailing_blank(sentence)                # 끝 빈 줄 제거
    sentence = _strip_trailing_dashes(sentence)               # 끝 의미없는 하이폰 제거(사진7)
    # 지문이 비었거나(각주만 남음 등) 영문/한글 내용이 전혀 없으면 제외 (사진10).
    # 단, 장문(2/3) 세트 문항은 본문을 메인 장문과 공유해 sentence가 비어 정상 →
    # 장문은 제외하지 않는다.
    if ('장문' not in qtype
            and not _re.search(r'[A-Za-z가-힣]',
                               _re.sub(r'(?m)^[ \t]*[*※].*$', '', sentence))):
        return None
    # 연결어/연결사 빈칸이 문장 삽입처럼 쓰인 불량 구조 → 제외.
    if '연결' in qtype and _is_broken_connector(sentence):
        return None
    # 마지막 문장이 종결부호 없이 잘렸으면(미완성/꼬리잡문) 제외.
    if _is_incomplete_ending(sentence):
        return None
    # 본문에 placeholder/잡토큰(vitamin_D, make_up …)이나 괄호 통문장 → 품질 불량 제외.
    if _has_placeholder_garbage(sentence) or _has_parenthesized_sentence(sentence):
        return None
    # 본문에 (A)~(F) 라벨 4개 이상 + 보기가 한국어 해설형 → 수능 비표준 유형 → 제외.
    if _is_nonstandard_labeled_passage(sentence, choices):
        return None
    # 세 칸((A)[x/y](B)[..](C)[..]) 선택형(어법/어휘)이면 보기 칸 사이를 ' ----- ' 로 구분.
    _abc = _extract_abc_options(sentence)
    if _abc and choices:
        choices = [_normalize_three_blank(c, _abc) for c in choices]
    if _has_cjk_error(choices):
        return None
    return {
        "date":    f"[{total_number}]" if total_number else "",
        "prompt":  prompt,
        "passage": sentence,
        "choices": choices,
        "answer":  answer,
        "qtype":   qtype,     # HWPX 빌더의 레이아웃 분기용(연결어/연결사 박스+보기 묶기 등)
    }


__all__ = [
    "_hwpx_clean", "_normalize_passage_markers", "_parenthesize_insertion_markers",
    "_normalize_order_passage",
    "_TWO_BLANK_TYPES",
    "_space_inline_markers", "_strip_marker_garbage", "_normalize_two_blank",
    "_split_inline_long_choices", "_hwpx_choices",
    "_CIRCLED_NUMS", "_shorten_long_blanks", "_number_underline_segments",
    "_has_cjk_error", "_normalize_truefalse_prompt", "_TWO_BLANK_SEP",
    "_is_two_blank", "_build_modified_question",
    # 2026-06-28 품질 정리/검출 일괄 추가
    "_normalize_alt_number_glyphs", "_is_corrupted_AE_option",
    "_renumber_insertion_markers", "_normalize_insertion_intro",
    "_strip_bracket_garbage", "_strip_trailing_blank", "_is_incomplete_ending",
    "_has_placeholder_garbage", "_has_parenthesized_sentence",
    "_standardize_connector_blanks", "_is_broken_connector",
    "_normalize_order_choice_sep", "_fix_irrelevant_marker_junk",
    "_strip_type_label_garbage", "_extract_abc_options",
    "_segment_three_blank", "_normalize_three_blank",
    # 2026-06-28 추가 12개 수정 — 사진 1-23 증상 대응
    "_space_marker_after_word", "_drop_duplicate_choice_set",
    "_grammar_choice_sep", "_strip_summary_arrows", "_compact_paragraphs",
    "_is_nonstandard_labeled_passage", "_extend_to_underline",
    # 2026-06-28 추가 15개 수정 — 새 폴더\이미지001-015
    "_strip_leading_stars", "_dedupe_inline_markers", "_collapse_space_before_marker",
    "_strip_stray_dots", "_strip_trailing_marker_row", "_strip_trailing_dashes",
    "_drop_orphan_marker_choices", "_strip_interior_choice_markers",
]
