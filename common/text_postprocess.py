# -*- coding: utf-8 -*-
"""변형문제 텍스트 후처리 — HWPX/PDF/엑셀 출력 공통 정규화 로직.

웹(Django)의 변형문제 HWPX·PDF 다운로드, 그리고 로컬 'AI 자동화' 의 엑셀
후처리 단계에서 같은 양식을 보장하기 위한 순수 함수 모음. Django/모델
의존성 없음 — `import re` 만 사용. dict/str 입출력.

진입 함수: `_build_modified_question(row, total_number) -> dict | None`
"""
import re as _re


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
    # 엑셀 인라인 그림(아이콘) placeholder 제거 — 예: icon_1_3
    text = _re.sub(r'icon_\d+_\d+', '', text)
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


_TWO_BLANK_TYPES = {'[요약문완성]', '[연결어]', '[연결사]'}


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


def _normalize_two_blank(choice):
    """두-빈칸 유형 보기의 단어 사이 구분을 ' …… ' 로 통일.

    DB 에 어떤 항목은 '단어A \t…… \t단어B', 어떤 항목은 '단어A \t단어B' 처럼
    들쭉날쭉하게 들어와 인쇄물에서 가독성이 떨어지는 문제를 보정.
    탭(\\t) 단독, 2칸 이상 공백, ……/... 모두 분리자로 인식한다.
    """
    MARKERS = '①②③④⑤⑥⑦⑧⑨⑩'
    body = choice.strip()
    marker = ''
    if body and body[0] in MARKERS:
        marker = body[0]
        body = body[1:].lstrip()

    # 엑셀 셀참조(A1, B2 …) 같은 잡토큰이 보기 맨 앞에 끼어든 경우 제거.
    body = _re.sub(r'^[A-Z]{1,2}\d{1,3}\s+', '', body)

    # A/B 두 답 사이 분리자를 ' …… ' 하나로 통일. 점선(……/.../⋯)·공백+대시(-)·
    # 탭·2칸 이상 공백의 조합을 모두 분리자로 본다. 원문 'word  -  word' 때문에
    # "word …… - word" 처럼 대시가 남던 문제 교정(대시도 분리자로 보고 제거).
    # 단어 내부 하이픈(well-being)은 양옆 공백이 없어 매칭되지 않아 안전.
    sep = r'(?:\s*(?:……|\.{3,}|⋯)\s*|\s+[-/]+\s+|\s{2,}|	+)+'
    body = _re.sub(sep, ' …… ', body, count=1)

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


def _hwpx_choices(option_str, qtype=''):
    """선택지 문자열을 리스트로 분리 — 엑셀 원본의 줄바꿈만 따른다.

    마커(①②③) 자동 분리는 하지 않음: 출제자가 의도적으로 한 줄에
    여러 보기를 둔 경우(순서 유형 등) 그 의도를 보존하기 위함.
    qtype 이 요약문완성/연결어 같은 두-빈칸 유형이면 단어 사이 구분자를
    ' …… ' 로 통일한다.

    NOTE: _hwpx_clean 은 호출하지 않는다 — 탭(\\t)이 단어 구분자 신호로 쓰이므로
    공백 치환 전에 _normalize_two_blank 가 먼저 처리해야 한다.
    """
    if not option_str:
        return []
    text = str(option_str)
    text = text.replace('_x000D_', '\n').replace('_x000A_', '\n')
    text = text.replace('\\r\\n', '\n').replace('\\n', '\n').replace('\\r', '\n')
    text = _re.sub(r'\r\n?', '\n', text)
    text = _re.sub(r'icon_\d+_\d+', '', text)
    parts = [c.strip() for c in text.split('\n') if c.strip()]
    parts = [_strip_marker_garbage(p) for p in parts]
    parts = _split_inline_long_choices(parts)
    parts = [_space_inline_markers(p) for p in parts]
    if (qtype or '') in _TWO_BLANK_TYPES:
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
    매긴다. 기존 번호(앞/뒤)는 제거. 반환:(텍스트, 밑줄개수)."""
    MARK = '￰'
    CIRC = _CIRCLED_NUMS
    parts = _re.split('(' + MARK + '.*?' + MARK + ')', text)
    seq = ['①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '⑩']
    out, n, count = [], 0, 0
    for p in parts:
        if p.startswith(MARK) and p.endswith(MARK) and len(p) >= 2:
            if out:
                out[-1] = _re.sub(r'[' + CIRC + r']\s*$', '', out[-1])
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


def _build_modified_question(r, total_number):
    """변형문제 한 행 → 빌더 dict. 데이터 오류/번호 깨짐이면 None(제외).

    입력 dict 키: qtype, question, sentence, option, answer
    """
    qtype = (r.get('qtype', '') or '')
    prompt = _hwpx_clean(r.get('question', '') or '')
    sentence = _hwpx_clean(r.get('sentence', '') or '')
    choices = _hwpx_choices(r.get('option', '') or '', qtype)
    choices = [c for c in choices if c.strip().lower() not in ('answer', '정답')]
    answer = (r.get('answer', '') or '').replace('	', ' ')
    if ('어휘' in qtype or '어법' in qtype) and '￰' in sentence:
        sentence, n = _number_underline_segments(sentence)
        if n != 5:
            return None
        choices = []
    else:
        # 문장넣기 본문은 밑줄이 필요 없다 — 원문 밑줄 마커(U+FFF0)를 제거.
        if '문장넣기' in qtype:
            sentence = sentence.replace('￰', '')
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
    "_hwpx_clean", "_normalize_passage_markers", "_TWO_BLANK_TYPES",
    "_space_inline_markers", "_strip_marker_garbage", "_normalize_two_blank",
    "_split_inline_long_choices", "_hwpx_choices",
    "_CIRCLED_NUMS", "_shorten_long_blanks", "_number_underline_segments",
    "_has_cjk_error", "_build_modified_question",
]
