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
    # '___(A)___' (양쪽 밑줄, 라벨 가운데) 로 맞춘다. 밑줄이 하나도 없는
    # '(A)'(발문의 (A),(B) 참조 등)는 그대로 둔다.
    text = _re.sub(
        r'_*\(([A-E])\)_*',
        lambda m: '___(%s)___' % m.group(1) if '_' in m.group(0) else m.group(0),
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
    body = _re.sub(sep, _TWO_BLANK_SEP, body, count=1)

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
    parts = _split_inline_long_choices(parts)
    parts = [_space_inline_markers(p) for p in parts]
    if two_blank is None:
        two_blank = (qtype or '') in _TWO_BLANK_TYPES
    if two_blank:
        parts = [_normalize_two_blank(p) for p in parts]
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
    """
    if (qtype or '') in _TWO_BLANK_TYPES:
        return True
    s = sentence or ''
    has_a = bool(_re.search(r'_\(A\)|\(A\)_', s))
    has_b = bool(_re.search(r'_\(B\)|\(B\)_', s))
    return has_a and has_b


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
        sentence, n = _number_underline_segments(sentence)
        if n != 5:
            return None
        choices = []
    else:
        # 지문 밑줄(U+FFF0)은 '밑줄 친 부분' 자체가 문제인 유형에서만 의미가 있다
        # — 지칭대상/지칭추론·밑줄의미·함축의미. 그 외(문장넣기·일치불일치·순서·
        # 주제 등)는 원문에서 딸려온 잔여 밑줄이므로 제거한다.
        # (어법·어휘는 위에서 번호 매김으로 따로 처리.)
        if not any(k in qtype for k in _UNDERLINE_KEEP_KEYS):
            sentence = sentence.replace('￰', '')
        if '문장넣기' in qtype:
            # 삽입 위치 마커를 '( ① )' 로 통일(맨 마커·괄호 마커 혼용 정리).
            sentence = _parenthesize_insertion_markers(sentence)
        else:
            sentence = _normalize_passage_markers(sentence)
    sentence = _shorten_long_blanks(sentence)
    if _has_cjk_error(choices):
        return None
    return {
        "date":    f"[{total_number}]" if total_number else "",
        "prompt":  prompt,
        "passage": sentence,
        "choices": choices,
        "answer":  answer,
    }


__all__ = [
    "_hwpx_clean", "_normalize_passage_markers", "_parenthesize_insertion_markers",
    "_TWO_BLANK_TYPES",
    "_space_inline_markers", "_strip_marker_garbage", "_normalize_two_blank",
    "_split_inline_long_choices", "_hwpx_choices",
    "_CIRCLED_NUMS", "_shorten_long_blanks", "_number_underline_segments",
    "_has_cjk_error", "_normalize_truefalse_prompt", "_TWO_BLANK_SEP",
    "_is_two_blank", "_build_modified_question",
]
