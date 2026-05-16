"""
Gemini API 통합 — 영어 문장의 단어별 한글뜻 자동 생성
"""
import os
import json
import re
from typing import List, Dict
from google import genai
from django.conf import settings


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

    prompt = f"""다음 {len(valid)}개 문제에 대해, 각 영어 문장의 단어별 문맥상 한국어 뜻을 매핑해주세요.

{items_block}

규칙:
- 각 문제마다 영어 단어 수와 정확히 일치하는 한국어 뜻 리스트
- 문맥에 맞는 짧고 명확한 뜻 (5자 이내 권장)
- 관사는 "(관사)" 또는 빈 문자열
- JSON 형식만 출력. 설명 X.

출력 형식 (JSON 객체):
{{
  "results": [
    {{"index": 1, "hints": [{{"word": "In", "meaning": "(시간) ~에"}}, ...]}},
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
                    clean.append({'word': w, 'meaning': hints[i].get('meaning', '').strip()})
                else:
                    clean.append({'word': w, 'meaning': ''})
            out[orig_i] = clean

        return out

    except Exception as e:
        print(f'[AI batch] 실패, 개별 처리로 fallback: {e}')
        # 실패 시 1개씩 처리
        return [generate_word_hints(p.get('english', ''), p.get('korean', '')) for p in problems]
