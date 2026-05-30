# 프라임에듀 HWPX 시험지 빌더

`.hwpx` 양식의 디자인을 유지한 채 영어 문제지를 서버에서 생성한다.
**한/글 설치 불필요, win32 불필요, Ubuntu OK, 순수 표준 라이브러리만 사용.**

## 조판 관련 처리 (중요)

- **줄간격**: 생성하는 본문 단락에 `<hp:lineseg>`(조판 결과 캐시)를 넣지 않는다.
  lineseg 의 spacing 값이 문단 줄간격(paraPr 160%)을 덮어써 줄이 겹쳐 보이는
  문제가 있어, lineseg 를 생략하고 한/글이 열 때 재계산하도록 한다.
- **머리말 장평/자간**: 머리말이 좁아 보이던 원인은 글자모양(charPr)이 아니라
  머리말 단락의 **조판 캐시**였다. 머리말은 `[공백][탭(고정폭)][텍스트]` 구조인데,
  탭의 `width` 가 옛 텍스트("[프라임에듀 머리말]") 길이에 맞춰 고정돼 있어,
  더 긴 텍스트를 넣으면 그 고정 탭폭 때문에 글자가 눌려(장평 자동 축소) 좁아 보였다.
  → 머리말 치환 시 **탭의 고정 width 와 lineseg 를 제거**한다. 그러면 한/글이
  단락의 자동 오른쪽 탭(autoTabRight) 규칙으로 폭을 재계산해 정상 출력된다.
  **글자모양(charPr)은 양식 그대로 둔다.**
- **쪽 나누기**: `page_break_before_endnotes=True`(기본값)이면 본문 끝에
  쪽나누기 단락을 넣어, 미주(정답)가 새 페이지에서 시작하도록 한다.

## 구현 기능

1. **머리말 수정** — `[프라임에듀 머리말]` → `[원하는 머리말]`
2. **미주(정답) 삽입** — 각 문제에 `<hp:endNote>` 로 정답을 넣고 번호 자동 부여
3. **텍스트 입력** — 발문 / 지문 / 선택지
4. **굵은 글씨 + 붉은 박스**
   - 날짜: 굵게 + 파랑(charPr 11)
   - 발문: 굵게 + 검정(charPr 12)
   - 지문: 사방 빨강 0.5mm 테두리 박스(paraPr 13 → borderFill 3)
5. **단(컬럼) 넘침 방지** — 문제 높이를 추정해, 한 단에서 잘릴 것 같으면
   그 문제를 다음 단에서 시작(`columnBreak="1"`)시킨다. 2단 레이아웃 기준.

## 왜 .hwpx 인가
`.hwpx` 는 **ZIP + XML** 구조라, `.hwp`(OLE 바이너리)와 달리 압축/레코드
파싱 없이 XML 텍스트를 직접 다룰 수 있다. 표준 `zipfile` 만으로 충분하다.

## 스타일 처리
양식(`프라임에듀_기본양식.hwpx`)의 header.xml 에는 박스/굵게/미주용 스타일이
없다. 그래서 이 스타일을 가진 참조본(`test1.hwpx`)의 header.xml 을 베이스로
사용한다. test1 은 양식에서 파생됐으므로 양식의 스타일(0~12)을 모두 포함하면서
박스(borderFill 3,4)·굵게(charPr 11,12)·미주 스타일(15)까지 갖추고 있어
ID 충돌이 없다. (`reference_path` 인자로 지정)

## 사용법

```python
from hwpx_builder import build_hwpx_bytes

questions = [
    {
        "date":    "[2025-11-18]",
        "prompt":  "다음 글의 목적으로 가장 적절한 것은?",
        "answer":  2,                       # 미주 정답
        "passage": "Dear Mr. Kelly, ...",   # 붉은 박스
        "choices": ["① ...", "② ...", "③ ...", "④ ...", "⑤ ..."],
    },
    # ...
]

data = build_hwpx_bytes(
    "프라임에듀_기본양식.hwpx",
    header_text="프라임에듀 2025 수능특강",
    questions=questions,
    reference_path="test1.hwpx",   # 스타일 참조본
)
open("exam.hwpx", "wb").write(data)
```

### Django
입력은 **Django Model 인스턴스 / dict / JSON** 모두 가능
(`date, prompt, answer, passage, choices` 필드/키 기준).
`django_example.py` 참고.

```python
resp = HttpResponse(data, content_type="application/vnd.hancom.hwpx")
resp["Content-Disposition"] = 'attachment; filename="exam.hwpx"'
```

## 입력 데이터 스펙

| 키        | 타입            | 설명                         | 스타일                |
|-----------|-----------------|------------------------------|-----------------------|
| `date`    | str (선택)      | 날짜/회차 `"[2025-11-18]"`   | 굵게+파랑 (charPr 11) |
| `prompt`  | str             | 발문                         | 굵게+검정 (charPr 12) |
| `answer`  | int/str (선택)  | 정답 (미주로 삽입)           | 미주 (charPr 9)       |
| `passage` | str (선택)      | 지문                         | 붉은 박스 (paraPr 13) |
| `choices` | list[str]/JSON  | 선택지                       | 일반 (charPr 8)       |

## 단 넘침 추정 파라미터 (필요시 hwpx_builder.py 상단에서 조정)
- `LINES_PER_COL` ≈ 49 (한 단 줄 수)
- `CHARS_PER_LINE_EN` = 52, `CHARS_PER_LINE_KR` = 26 (줄당 글자 수)
- 폰트/줄간격에 따라 실제와 차이가 날 수 있어 **보수적으로** 잡았다.
  더 빡빡하게/느슨하게 하려면 이 값들을 조정.

## 한계 / 주의
- 단 넘침은 **추정**이다. 한/글의 실제 조판과 100% 일치하지 않을 수 있다.
  정밀 조판이 필요하면 한/글에서 한 번 열어 확인 후 미세조정 권장.
- 지문 내 이미지/도표, 표, 밑줄/네모 같은 인라인 서식은 미지원(텍스트 위주).
  필요하면 charPr/run 분할로 확장 가능.
- `reference_path` 의 header.xml 스타일 ID 에 의존한다. 양식이나 참조본의
  스타일 구성을 바꾸면 빌더 상단의 ID 상수도 함께 맞춰야 한다.
- 검증: 생성물은 표준 XML 로 well-formed 하며, 독립 라이브러리 python-hwpx 로
  열기/문단 추출이 정상 동작함을 확인했다.
