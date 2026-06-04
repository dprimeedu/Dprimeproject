"""
Gemini API 통합 — 영어 문장의 단어별 한글뜻 자동 생성
"""
import os
import json
import re
from typing import List, Dict
from google import genai
from django.conf import settings
from dotenv import load_dotenv
load_dotenv()

_client = None
MODEL_NAME = 'gemini-2.5-flash-lite'  # thinking 없는 빠른 모델


def get_client():
    global _client
    if _client is None:
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise RuntimeError('GEMINI_API_KEY 환경변수 미설정')
        _client = genai.Client(api_key=api_key)
    return _client


def generate_word_hints(english: str, korean: str) -> List[Dict[str, str]]:
    """
    영어 문장과 한국어 번역을 받아 각 단어의 한글뜻 매핑 반환.

    Returns:
        [{"word": "In", "meaning": "(시간) ~에"}, {"word": "under", "meaning": "~아래에"}, ...]
        실패 시 빈 리스트.
    """
    english = (english or '').strip()
    korean = (korean or '').strip()
    if not english:
        return []

    words = english.split()

    prompt = f"""영어 문장과 한국어 번역이 주어졌을 때, 영어 문장의 각 단어에 대해 문맥에 맞는 한국어 뜻을 매핑해주세요.

영어: "{english}"
한국어 번역: "{korean}"

영어 단어 ({len(words)}개): {words}

규칙:
- 위 영어 단어 순서대로 정확히 {len(words)}개의 뜻을 출력
- 문맥에 맞는 뜻만 (사전상 일반 뜻 X)
- 짧고 명확하게 (각 뜻 5자 이내 권장)
- 관사(the, a, an)는 "(관사)" 또는 빈 문자열
- 전치사는 그 문장에서의 의미만
- JSON 배열만 출력, 다른 설명 X

출력 형식 (JSON):
[
  {{"word": "In", "meaning": "(시간) ~에"}},
  {{"word": "under", "meaning": "~아래에"}}
]
"""

    try:
        client = get_client()
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
        )
        text = response.text.strip()

        # JSON 추출 (마크다운 코드 블록 ```json ... ``` 제거)
        match = re.search(r'\[\s*\{.*?\}\s*\]', text, re.DOTALL)
        if match:
            text = match.group(0)

        data = json.loads(text)
        if not isinstance(data, list):
            return []

        # 단어 개수 검증 — AI가 다르게 답하면 단어 그대로 사용
        result = []
        for i, word in enumerate(words):
            if i < len(data) and isinstance(data[i], dict):
                meaning = data[i].get('meaning', '').strip()
                result.append({'word': word, 'meaning': meaning})
            else:
                result.append({'word': word, 'meaning': ''})
        return result

    except json.JSONDecodeError:
        return [{'word': w, 'meaning': ''} for w in words]
    except Exception as e:
        # 로그만 남기고 빈 결과 (서비스는 계속 동작)
        print(f'[AI] generate_word_hints 실패: {e}')
        return [{'word': w, 'meaning': ''} for w in words]


def translate_word_en_ko(word: str) -> str:
    """영어 단어 하나의 한국어 사전 뜻을 반환 (낱말카드 만들기 사전 기능용).

    예: "abandon" → "버리다, 포기하다". 실패 시 빈 문자열.
    """
    word = (word or '').strip()
    if not word:
        return ''

    prompt = f"""영어 단어 "{word}"의 한국어 뜻을 알려주세요.

규칙:
- 가장 일반적인 뜻 1~3개를 쉼표로 구분
- 짧고 명확하게 (학습용 사전식)
- 품사 표기·예문·영어 설명 없이 한국어 뜻만
- 한 줄로만 출력

예: "abandon" → 버리다, 포기하다
출력:"""

    try:
        client = get_client()
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
        )
        text = (response.text or '').strip()
        # 첫 줄만, 따옴표/화살표 등 군더더기 제거
        line = text.splitlines()[0].strip() if text else ''
        line = line.lstrip('→-:').strip().strip('"').strip()
        return line[:200]
    except Exception as e:
        print(f'[AI] translate_word_en_ko 실패: {e}')
        return ''


def split_sentence_clauses(english: str, korean: str, max_words: int = 20,
                           lo: int = 10, hi: int = 15) -> List[Dict[str, str]]:
    """긴 영어 문장을 절·쉼표·관계대명사 기준 10~15단어 조각으로 분할 (영작 훈련용).

    - 영어는 원문 단어를 그대로 보존(채점 정확성 보장). 각 조각에 대응 한국어를 함께 반환.
    - max_words 이하면 분할하지 않고 원문 1개 반환.
    - AI 분할 실패/단어수 불일치 시 안전하게 원문 1개 반환.
    반환: [{'english': ..., 'korean': ...}, ...]
    """
    english = (english or '').strip()
    korean = (korean or '').strip()
    words = english.split()
    if len(words) <= max_words:
        return [{'english': english, 'korean': korean}]

    prompt = (
        "다음 영어 문장을 '영작 훈련용'으로 의미 단위(절·구)로 끊어 주세요.\n"
        "끊는 기준: 주절/종속절 경계, 쉼표, 대시(— -), 관계대명사(who/which/that/where 등), "
        "등위접속사(and/but/or) 앞.\n"
        "각 조각에 대응하는 한국어 번역 조각을 함께 주세요.\n"
        "영어 단어는 원문 순서를 그대로 유지하고, 조각들을 이으면 원문 전체가 되어야 합니다.\n"
        'JSON 배열만 출력: [{"english":"...","korean":"..."}, ...]\n\n'
        f'영어: "{english}"\n한국어: "{korean}"\n'
    )
    try:
        resp = get_client().models.generate_content(model=MODEL_NAME, contents=prompt)
        text = (resp.text or '').strip()
        m = re.search(r'\[\s*\{.*\}\s*\]', text, re.DOTALL)
        if m:
            text = m.group(0)
        ai = json.loads(text)
        counts = [len((c.get('english') or '').split()) for c in ai]
    except Exception as e:
        print(f'[split] AI 분할 실패: {e}')
        return [{'english': english, 'korean': korean}]

    if not counts or sum(counts) != len(words):
        return [{'english': english, 'korean': korean}]   # 단어수 보존 실패 → 미분할

    # 원문 단어를 그대로 잘라 영어 보존 + 한국어는 AI 조각
    fine, pos = [], 0
    for c, n in zip(ai, counts):
        if n <= 0:
            continue
        fine.append({'english': ' '.join(words[pos:pos + n]),
                     'korean': (c.get('korean') or '').strip()})
        pos += n

    # 인접 조각 병합 → 10~15단어 목표
    merged, ce, ck, cn = [], [], [], 0
    for f in fine:
        n = len(f['english'].split())
        if cn > 0 and cn + n > hi:
            merged.append({'english': ' '.join(ce),
                           'korean': ' '.join(x for x in ck if x).strip()})
            ce, ck, cn = [], [], 0
        ce.append(f['english']); ck.append(f['korean']); cn += n
        if cn >= lo:
            merged.append({'english': ' '.join(ce),
                           'korean': ' '.join(x for x in ck if x).strip()})
            ce, ck, cn = [], [], 0
    if ce:
        tail_k = ' '.join(x for x in ck if x).strip()
        if merged and cn < lo:          # 짧은 꼬리는 직전 조각에 병합
            merged[-1]['english'] += ' ' + ' '.join(ce)
            if tail_k:
                merged[-1]['korean'] = (merged[-1]['korean'] + ' ' + tail_k).strip()
        else:
            merged.append({'english': ' '.join(ce), 'korean': tail_k})

    # 최종 영어 보존 검증 (조각 합 == 원문)
    if ' '.join(mm['english'] for mm in merged).split() != words:
        return [{'english': english, 'korean': korean}]
    return merged


def generate_word_hints_batch(problems: List[Dict]) -> List[List[Dict[str, str]]]:
    """
    여러 문제를 한 번의 API 호출로 처리.
    problems: [{"english": "...", "korean": "..."}, ...]
    반환: 각 문제별 word_hints 리스트 (입력 순서와 동일)
    """
    if not problems:
        return []

    # 빈 영어는 건너뛰기
    valid = [(i, p) for i, p in enumerate(problems) if (p.get('english') or '').strip()]
    if not valid:
        return [[] for _ in problems]

    # 프롬프트 구성
    items_text = []
    for idx, (orig_i, p) in enumerate(valid):
        eng = (p.get('english') or '').strip()
        kor = (p.get('korean') or '').strip()
        words = eng.split()
        items_text.append(
            f'[문제 {idx + 1}]\n영어: "{eng}"\n한국어: "{kor}"\n영어 단어 ({len(words)}개): {words}'
        )

    items_block = '\n\n'.join(items_text)

    prompt = f"""다음 {len(valid)}개 문제에 대해, 각 영어 문장의 단어별 문맥상 한국어 뜻 + 고유명사 여부를 매핑해주세요.

{items_block}

규칙:
- 각 문제마다 영어 단어 수와 정확히 일치하는 리스트
- 문맥에 맞는 짧고 명확한 뜻 (5자 이내 권장)
- 관사는 "(관사)" 또는 빈 문자열
- proper_noun: true (사람·지명·고유 브랜드 등 고유명사) / false (일반 명사·동사·형용사 등)
- "Mt.", "Mr.", "Dr." 같은 약자는 proper_noun false (그 자체로는 고유명사 아님)
- "Tambora", "Indonesia", "Korea", "Tom" 같이 특정 대상 지칭은 proper_noun true
- JSON 형식만 출력. 설명 X.

출력 형식 (JSON 객체):
{{
  "results": [
    {{"index": 1, "hints": [
      {{"word": "Mt.", "meaning": "산", "proper_noun": false}},
      {{"word": "Tambora", "meaning": "탐보라", "proper_noun": true}}
    ]}},
    {{"index": 2, "hints": [...]}}
  ]
}}
"""

    try:
        client = get_client()
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
        )
        text = response.text.strip()

        # 마크다운 ```json 제거
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            text = match.group(0)

        data = json.loads(text)
        results_list = data.get('results', [])

        # index → hints 매핑
        by_index = {}
        for r in results_list:
            if isinstance(r, dict) and 'index' in r:
                by_index[r['index']] = r.get('hints', [])

        # 원래 순서로 재구성
        out = [[] for _ in problems]
        for idx, (orig_i, p) in enumerate(valid):
            hints = by_index.get(idx + 1, [])
            words = (p.get('english') or '').strip().split()
            # 단어 개수 일치 확인 + 정리
            clean = []
            for i, w in enumerate(words):
                if i < len(hints) and isinstance(hints[i], dict):
                    clean.append({
                        'word': w,
                        'meaning': hints[i].get('meaning', '').strip(),
                        'proper_noun': bool(hints[i].get('proper_noun', False)),
                    })
                else:
                    clean.append({'word': w, 'meaning': '', 'proper_noun': False})
            out[orig_i] = clean

        return out

    except Exception as e:
        print(f'[AI batch] 실패, 개별 처리로 fallback: {e}')
        # 실패 시 1개씩 처리
        return [generate_word_hints(p.get('english', ''), p.get('korean', '')) for p in problems]
