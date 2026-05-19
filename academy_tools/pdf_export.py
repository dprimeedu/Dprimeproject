"""
부교재 매칭 결과 → PDF.

WeasyPrint 를 사용해 HTML → PDF 변환. Windows 에서는 GTK 런타임이 별도 필요해
실제 PDF 생성은 NAS Docker 환경 위주로 동작. HTML 빌드 부분은 테스트 가능하게 분리.
"""
from __future__ import annotations

import html as html_lib
from datetime import datetime


# CSS 안에서 한글 폰트 후보를 OS 별로 묶어 fallback.
# Linux/Docker: fonts-noto-cjk → Noto Sans CJK KR
# Windows: Malgun Gothic
# macOS: Apple SD Gothic Neo
FONT_STACK = ('"Noto Sans CJK KR", "Noto Sans KR", "Malgun Gothic", '
              '"Apple SD Gothic Neo", "맑은 고딕", sans-serif')


_CSS_BASE = """
@page {
    size: A4;
    margin: 14mm 12mm 14mm 12mm;
    @bottom-right {
        content: counter(page) " / " counter(pages);
        font-size: 9pt;
        color: #888;
    }
}
* { box-sizing: border-box; }
body {
    font-family: %(font_stack)s;
    font-size: 10pt;
    color: #222;
    line-height: 1.45;
}
h1 { font-size: 16pt; margin: 0 0 4mm; }
.meta {
    font-size: 9.5pt;
    color: #555;
    margin-bottom: 6mm;
}
.meta b { color: #1e5894; }
.summary {
    background: #f4f9ff;
    border: 1px solid #b9d0ec;
    border-radius: 4px;
    padding: 3mm 4mm;
    margin-bottom: 5mm;
    font-size: 9.5pt;
}
.summary .row { margin: 0.5mm 0; }
table { width: 100%%; border-collapse: collapse; font-size: 9pt; }
th, td {
    border: 1px solid #d0d0d0;
    padding: 1.2mm 2mm;
    vertical-align: top;
    text-align: left;
}
th { background: #eaf2fb; font-weight: 600; }
tr:nth-child(2n) td { background: #fafafa; }
.section-title {
    font-size: 11pt; font-weight: 700;
    margin: 6mm 0 2mm; color: #1e5894;
    border-bottom: 1px solid #b9d0ec;
    padding-bottom: 1mm;
}
.empty { color: #888; padding: 4mm; text-align: center; }
""" % {'font_stack': FONT_STACK}


def _esc(v) -> str:
    return html_lib.escape('' if v is None else str(v))


def build_html(
    *,
    name: str,
    test_type: str,
    dataset_label: str,
    options_labels: list[str],
    key_table_rows: list[dict],
    grade_selection: dict,
) -> str:
    """매칭 결과를 PDF 용 단일 HTML 문서로 직렬화."""
    now = datetime.now().strftime('%Y-%m-%d %H:%M')

    # 학년별 선택 요약
    selection_rows = []
    for grade, sel in grade_selection.items():
        if not (sel.get('units') or sel.get('numbers')):
            continue
        selection_rows.append(
            f'<div class="row"><b>{_esc(grade)}</b> · '
            f'단원 {len(sel.get("units") or [])}개 · '
            f'번호 {len(sel.get("numbers") or [])}개</div>'
        )
    selection_html = '\n'.join(selection_rows) or '<div class="row">(선택 없음)</div>'

    # KEY_TABLE 표
    if key_table_rows:
        body_rows = []
        for r in key_table_rows:
            body_rows.append(
                '<tr>'
                f'<td>{_esc(r.get("book") or "-")}</td>'
                f'<td>{_esc(r.get("grade"))}</td>'
                f'<td>{_esc(r.get("year") or "-")}</td>'
                f'<td>{_esc(r.get("month"))}</td>'
                f'<td>{_esc(r.get("number"))}</td>'
                f'<td>{_esc(r.get("total_number"))}</td>'
                '</tr>'
            )
        table_html = (
            '<table>'
            '<thead><tr>'
            '<th>교재</th><th>학년</th><th>연도</th><th>강(단원)</th>'
            '<th>번호</th><th>색인</th>'
            '</tr></thead>'
            f'<tbody>{"".join(body_rows)}</tbody>'
            '</table>'
        )
    else:
        table_html = '<div class="empty">매칭된 데이터가 없습니다.</div>'

    options_html = ', '.join(_esc(o) for o in options_labels) or '(없음)'

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>부교재 출력 — {_esc(name)}</title>
<style>{_CSS_BASE}</style>
</head>
<body>
  <h1>부교재 출력 결과</h1>
  <div class="meta">
    이름 <b>{_esc(name or '-')}</b>
    · 시험구분 <b>{_esc(test_type or '-')}</b>
    · 데이터셋 <b>{_esc(dataset_label)}</b>
    · 생성 {now}
  </div>

  <div class="summary">
    <div class="row"><b>선택 옵션:</b> {options_html}</div>
    {selection_html}
    <div class="row"><b>매칭 KEY_TABLE 행 수:</b> {len(key_table_rows)}건</div>
  </div>

  <div class="section-title">매칭 결과</div>
  {table_html}
</body>
</html>"""


def render_pdf(html: str) -> bytes:
    """HTML → PDF bytes. WeasyPrint 미설치/GTK 미설치 시 ImportError 그대로 전파."""
    # lazy import — 로컬 Windows 등 GTK 미설치 환경에서 모듈 import 자체는 막지 않음
    from weasyprint import HTML
    return HTML(string=html).write_pdf()
