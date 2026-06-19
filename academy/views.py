from django.shortcuts import render, redirect
from django.db.models import Count, Q, F
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from functools import wraps
from .models import *

from django.http import HttpResponse, JsonResponse
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os
import json
import re


# ──────────────────────────────────────────────────────────────────────
# 접근 권한 게이트 (2026-06-16)
#   재원생(academy_access='none')   → 모고/변형 접근 차단
#   외부 승인 variant               → 변형문제만
#   관리자/학원운영자/full           → 모고 전체
# 인증 안 된 사용자는 로그인으로, 인증됐지만 권한 없으면 403.
# ──────────────────────────────────────────────────────────────────────
def _require_access(check):
    def deco(view):
        @wraps(view)
        @login_required(login_url='/accounts/login/')
        def wrapped(request, *args, **kwargs):
            if not check(request.user):
                raise PermissionDenied("이 자료에 접근할 권한이 없습니다.")
            return view(request, *args, **kwargs)
        return wrapped
    return deco

require_variant = _require_access(lambda u: getattr(u, 'can_view_variant', False))      # 열람(변형 이상)
require_download = _require_access(lambda u: getattr(u, 'can_download', False))          # 다운로드(승인됨)
require_mock_full = _require_access(lambda u: getattr(u, 'can_view_mock_full', False))   # 모고 전체


# 선택한 카테고리를 이용해서 DB를 결정
DB_DICT = {"원문추가":AdditionalText_Data, "직보서술형":DescriptiveQuestion_Data,
            "상세해설":DetailedExplanation_Data, "객관식빈칸":FillinBlank_Data,
            "어법1단계":Grammarlv1_Data, "어법2단계":Grammarlv2_Data, "어법3단계":Grammarlv3_Data,
            "변형문제":ModifiedQuestions_Data, "문제출력":OriginalQuestion_Data,
            "원문":OriginalText_Data, "내신빨파":RedBlue_Data,
            "내신TEST":SchoolExamTest_Data, "요약문완성":Summary_Data,
            "중요영작":Translation_Data, "내신단어":WordTest_Data}

@require_variant
def academy_list(request):
    """모의고사 선택 — 학년·년도·월 + 번호 + 변형유형 한 화면 통합 선택.

    번호는 KeyTable.total_number='YYYY-MM-NN' 끝 두자리(번호)를 회차별로 모아 그리드 표시,
    변형 유형은 QuestionData.유형 distinct 를 위쪽에 칩 멀티선택.
    """
    import json
    import re
    from collections import defaultdict
    NUM_RE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})$')

    def _int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    # 회차별 번호 모음 — '학년|년도|월' → 정렬된 번호 리스트
    round_numbers = defaultdict(set)
    for r in KeyTable.objects.values('grade', 'year', 'month', 'total_number'):
        m = NUM_RE.match(r['total_number'] or '')
        if not m:
            continue
        round_numbers[f"{r['grade']}|{r['year']}|{r['month']}"].add(int(m.group(3)))
    round_numbers_list = {k: sorted(v) for k, v in round_numbers.items()}

    # 회차 목록 (학년·년도·월 조합) — 필터 chip 활성화·search 용
    formatted_exams = []
    seen_titles = set()
    for exam in KeyTable.objects.values('grade', 'year', 'month'):
        title = f"{exam['grade']} {exam['year']}년 {exam['month']}월 모의고사"
        if title in seen_titles:
            continue
        seen_titles.add(title)
        formatted_exams.append({
            'grade': exam['grade'], 'year': exam['year'], 'month': exam['month'],
            'title': title,
        })
    formatted_exams.sort(key=lambda e: (-_int(e['year']), str(e['grade']), _int(e['month'])))

    grades = sorted(KeyTable.objects.values_list('grade', flat=True).distinct())
    years = sorted(KeyTable.objects.values_list('year', flat=True).distinct(), key=_int, reverse=True)
    months = sorted(KeyTable.objects.values_list('month', flat=True).distinct(), key=_int)

    # 변형 유형 — QuestionData.유형 distinct(대괄호 제거). 로컬 부교재 출력의 순서를 따른다.
    raw_types = set(
        (t or '').strip().strip('[]')
        for t in QuestionData.objects.values_list('유형', flat=True).distinct()
    )
    raw_types.discard('')
    # 로컬 프로그램 순서 우선 정렬, 나머지는 뒤로
    PREFERRED = ['순서', '도표', '그림', '문장넣기', '무관한문장', '연결어', '연결사',
                 '일치불일치', '심경분위기', '지칭대상', '지칭추론', '주제', '주장',
                 '제목', '요지', '목적', '밑줄의미', '어휘', '요약문완성', '빈칸', '어법',
                 '장문2', '장문3']
    variant_types = [t for t in PREFERRED if t in raw_types]
    for t in sorted(raw_types):
        if t not in variant_types:
            variant_types.append(t)

    return render(request, "academy_list.html", {
        "exams": formatted_exams,
        "grades": grades,
        "years": years,
        "months": months,
        # json_script 필터가 알아서 직렬화 — dict 그대로 넘기지 않으면 이중 인코딩됨.
        "round_numbers": round_numbers_list,
        "variant_types": variant_types,
    })

@require_variant
def academy_list_result(request):
    TABLE_NAMES_DICT = {"Additional_text":"원문추가", "Descriptive_Question":"직보서술형",
                       "DetailedExplanation":"상세해설", "FillinBlank":"객관식빈칸",
                       "Grammarlv1":"어법1단계", "Grammarlv2":"어법2단계", "Grammarlv3":"어법3단계",
                       "Modified_Questions":"변형문제", "Original_Question":"문제출력",
                       "Original_text":"원문", "RedBlue":"내신빨파",
                       "SchoolExamtest":"내신TEST", "Summary":"요약문완성",
                       "Translation":"중요영작", "WordTest":"내신단어"}

    selected_year = [y for val in request.GET.getlist('year', []) for y in val.split(',') if y]
    selected_grade = [g for val in request.GET.getlist('grade', []) for g in val.split(',') if g]
    selected_month = [m for val in request.GET.getlist('month', []) for m in val.split(',') if m]
    selected_numbers = [n for val in request.GET.getlist('number', []) for n in val.split(',') if n]

    keys = KeyTable.objects.all()
    if selected_year or selected_grade or selected_month:
        if selected_year:
            keys = keys.filter(year__in=selected_year)
        if selected_grade:
            keys = keys.filter(grade__in=selected_grade)
        # "전체"가 포함되어 있으면 특정 월 필터링을 생략하여 모든 월 조회
        if selected_month and "전체" not in selected_month:
            keys = keys.filter(month__in=selected_month)
    else:
        keys = KeyTable.objects.none()

    # 선택 가능한 전체 번호 목록 추출 및 숫자 길이 기반 정렬
    available_numbers = sorted(
        [x for x in keys.values_list('total_number', flat=True).distinct() if x], 
        key=lambda x: (len(str(x)), str(x))
    )

    # 사용자가 번호를 선택했다면 번호로 필터링 적용
    if selected_numbers:
        keys = keys.filter(total_number__in=selected_numbers)

    pk_key_numbers = list(keys.values_list('pk_number', flat=True))
    keytable_map = dict(keys.values_list('pk_number', 'total_number'))

    # 쿼리 1회로 전체 CountTable 조회 후 Python에서 table_name별 그룹핑
    from collections import defaultdict
    all_counts = CountTable.objects.filter(
        pk_number__in=pk_key_numbers
    ).values('table_name', 'pk_number', 'count')

    counts_by_table = defaultdict(list)
    for c in all_counts:
        counts_by_table[c['table_name']].append({
            'pk_number': c['pk_number'],
            'count': int(c['count']),
            'total_number': keytable_map.get(c['pk_number']),
        })

    # variant 전용(모고 전체 권한 없음) 계정은 변형문제 카테고리만 노출
    only_variant = not request.user.can_view_mock_full

    exams = []
    for table, korname in TABLE_NAMES_DICT.items():
        if only_variant and korname != '변형문제':
            continue
        counts = counts_by_table.get(table, [])
        question_list = [{"num": c["total_number"], "count": c["count"]} for c in counts]
        total_count = sum(c['count'] for c in counts)
        exams.append({
            'question_list': question_list,
            'question_counter': total_count,
            'link': None,
            'category': korname,
        })

    all_grades = list(KeyTable.objects.values_list('grade', flat=True).distinct().order_by('grade'))
    all_years  = sorted(KeyTable.objects.values_list('year',  flat=True).distinct())
    all_months = sorted(KeyTable.objects.values_list('month', flat=True).distinct(),
                        key=lambda m: int(m))

    context = {
        "exams": exams,
        "categories": TABLE_NAMES_DICT,
        "selected_year": selected_year,
        "selected_grade": selected_grade,
        "selected_month": selected_month,
        "all_grades": all_grades,
        "all_years": all_years,
        "all_months": all_months,
        "available_numbers": available_numbers,
        "selected_numbers": selected_numbers,
    }

    return render(request, "academy_list_result.html", context)



@require_variant
# 기존에 있는 코딩한 내용
def exam_list_result(request):
    if request.method == "POST":
        return grading(request)
    selected_year = [y for val in request.GET.getlist('year', []) for y in val.split(',') if y]
    selected_grade = [g for val in request.GET.getlist('grade', []) for g in val.split(',') if g]
    selected_month = [m for val in request.GET.getlist('month', []) for m in val.split(',') if m]
    selected_category = request.GET.getlist('category', [])
    # variant 전용 계정은 변형문제 외 카테고리 요청을 무시(직접 URL 접근 차단)
    if not request.user.can_view_mock_full:
        selected_category = [c for c in selected_category if c == '변형문제']
    selected_numbers = [n for val in request.GET.getlist('number', []) for n in val.split(',') if n]

    # KEY_TABLE에서 PK number 가져오기 및 필터링
    # 여기서 번호도 따와야지 출력할 수 있음
    pknum = KeyTable.objects.all()
    if selected_year or selected_grade or selected_month:
        if selected_year:
            pknum = pknum.filter(year__in=selected_year)
        if selected_grade:
            pknum = pknum.filter(grade__in=selected_grade)
        if selected_month and "전체" not in selected_month:
            pknum = pknum.filter(month__in=selected_month)
        if selected_numbers:
            pknum = pknum.filter(total_number__in=selected_numbers)
    else:
        pknum = KeyTable.objects.none()

    selected_pk_number = pknum.values_list('pk_number', flat=True)
    keytable_map = dict(pknum.values_list('pk_number', 'total_number'))
    
    if selected_category:
        for category in selected_category:
            database = DB_DICT[category]
            questions = database.objects.filter(pk_number__in=selected_pk_number)
            # 나중에 수정하기
            # 이유 -> 외부자료 불러와야 하기 때문
            if category == '직보서술형' or category == '상세해설':
                question_data = questions.none()
                question_answer = questions.none()

            if category == '원문추가':
                question_data = questions.values('index', 'additional_text', 'pk_number')
                question_answer = questions.none()

            if category == '객관식빈칸':
                question_data = questions.values('index', 'question', 'sentence', 'options', 'pk_number')
                question_answer = questions.values('index', 'answer')   

            if category == '어법1단계' or category == "어법2단계" or category == '어법3단계':
                question_data = questions.values('index', 'question', 'pk_number')
                question_answer = questions.values('index', 'answer')

            if category == '변형문제':
                # 문제 데이터를 리스트화
                question_data = questions.values('index', 'question', 'sentence', 'option', 'pk_number')
                question_answer = questions.values('index', 'answer')

            if category == '문제출력':
                # 문제 데이터를 리스트화
                question_data = questions.values('index', 'question', 'sentence', 'option', 'pk_number')
                question_answer = questions.values('index', 'answer')

            if category == '원문':
                # 문제 데이터를 리스트화
                question_data = questions.values('index', 'origin_text', 'pk_number')
                question_answer = questions.none()

            if category == '내신빨파':
                question_data = questions.values('index', 'origin_text', 'red', 'blue', 'pk_number')
                question_answer = questions.none()

            if category == '내신TEST':
                question_data = questions.values('index', 'question', 'sentence', 'option', 'modified', 'pk_number')
                question_answer = questions.values('index', 'answer')

            if category == '요약문완성':
                question_data = questions.values('index', 'origin_text', 'red', 'blue', 'summary', 'pk_number')
                question_answer = questions.values('index', 'answer')

            if category == '중요영작':
                question_data = questions.values('index', 'sentence', 'translation', 'etc', 'key_sentence', 'pk_number')
                question_answer = questions.none()

            if category == '내신단어':
                question_data = questions.values('index', 'word', 'english_definition', 'korean_definition', 'pk_number')
                question_answer = questions.none()
            
            for val in question_data:
                val['total_number'] = keytable_map.get(val['pk_number'])
                
            # session에 저장하여 download_pdf에서 접근할 수 있도록 리스트로 변환
            request.session['selected_questions'] = list(question_data)
            request.session['selected_questions_answer'] = list(question_answer)
    else:
        question_data = []
        question_answer = []
        request.session['selected_questions'] = []
        request.session['selected_questions_answer'] = []

    context = {
        "selected_questions": question_data,
        "selected_questions_answer": question_answer,
        "selected_year": selected_year,
        "selected_grade": selected_grade,
        "selected_month": selected_month,
        "selected_category": selected_category
    }    
    return render(request, "exam_list_result.html", context)

def grading(request):
    from django.http import JsonResponse
    import json
    if request.method == "POST":
        selected_category = request.GET.getlist('category', [])
        data = json.loads(request.body)
        answers = data.get("answers", [])
        # 채점하는 카테고리가 아닌 경우
        if not len(answers):
            response = {
                "correct_list" : [],
                "wrong_list": [],
            }
            return JsonResponse(response)
        correct_list = []
        wrong_list = []
        for item in answers:
            index = item.get("index")
            pk_number = item.get("pk_number")
            user_answer = item.get("answer")
            try:
                for category in selected_category:
                    question = DB_DICT[category].objects.get(index=index, pk_number=pk_number)
                    if user_answer and str(question.answer) == str(user_answer):
                        correct_list.append(question.index)
                    else:
                        wrong_list.append(question.index)
            except:
                pass

        response = {
            "correct_list" : correct_list,
            "wrong_list": wrong_list,
        }
        return JsonResponse(response)


@require_mock_full
def translation_select(request):
    """영작 연습 시작 전 년도/학년/월 선택 페이지"""
    translation_pk_numbers = Translation_Data.objects.values_list('pk_number', flat=True)
    keytable_qs = KeyTable.objects.filter(pk_number__in=translation_pk_numbers)

    grades = sorted(keytable_qs.values_list('grade', flat=True).distinct())
    years = sorted(keytable_qs.values_list('year', flat=True).distinct())
    months = sorted(keytable_qs.values_list('month', flat=True).distinct(), key=lambda m: int(m))

    context = {
        'grades': grades,
        'years': years,
        'months': months,
    }
    return render(request, 'translation_select.html', context)


def _clean_sentence(text):
    """sentence/translation 필드의 특수마커(밑줄, 개행)를 제거해 순수 텍스트로 반환"""
    text = text.replace('￰', '')
    text = text.replace('\\r\\n', ' ').replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' ')
    return ' '.join(text.split())


@require_mock_full
def translation_practice(request):
    selected_year = [y for val in request.GET.getlist('year', []) for y in val.split(',') if y]
    selected_grade = [g for val in request.GET.getlist('grade', []) for g in val.split(',') if g]
    selected_month = [m for val in request.GET.getlist('month', []) for m in val.split(',') if m]
    selected_numbers = [n for val in request.GET.getlist('number', []) for n in val.split(',') if n]

    pknum = KeyTable.objects.all()
    if selected_year or selected_grade or selected_month:
        if selected_year:
            pknum = pknum.filter(year__in=selected_year)
        if selected_grade:
            pknum = pknum.filter(grade__in=selected_grade)
        if selected_month and "전체" not in selected_month:
            pknum = pknum.filter(month__in=selected_month)
        if selected_numbers:
            pknum = pknum.filter(total_number__in=selected_numbers)
    else:
        pknum = KeyTable.objects.none()

    selected_pk_numbers = list(pknum.values_list('pk_number', flat=True))
    keytable_map = dict(pknum.values_list('pk_number', 'total_number'))

    questions_qs = Translation_Data.objects.filter(pk_number__in=selected_pk_numbers)
    questions = []
    for idx, q in enumerate(questions_qs):
        if not q.sentence or not q.translation:
            continue
        clean_eng = _clean_sentence(q.sentence)
        words = clean_eng.split()
        if not words:
            continue
        questions.append({
            'num': idx + 1,
            'pk_number': q.pk_number_id,
            'total_number': keytable_map.get(q.pk_number_id, ''),
            'korean': _clean_sentence(q.translation),
            'englishWords': words,
        })

    context = {
        'questions_json': json.dumps(questions, ensure_ascii=False),
        'selected_year': selected_year,
        'selected_grade': selected_grade,
        'selected_month': selected_month,
        'question_count': len(questions),
    }
    return render(request, 'translation_practice.html', context)


@require_mock_full
def save_translation_log(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error'}, status=400)
    data = json.loads(request.body)
    logs = data.get('logs', [])
    log_objects = [
        TranslationLog(
            student=request.user,
            question_num=log.get('questionNum', 0),
            word_index=log.get('wordIndex', 0),
            input_value=log.get('input', '')[:255],
            correct_answer=log.get('correctAnswer', '')[:255],
            is_correct=log.get('isCorrect', False),
            attempt_num=log.get('attemptNum', 0),
            time_taken=log.get('timeTaken', 0),
            pk_number=log.get('pk_number', 0),
        )
        for log in logs
    ]
    TranslationLog.objects.bulk_create(log_objects)
    return JsonResponse({'status': 'ok'})


@require_download
def download_pdf(request):
    """변형문제 PDF 다운로드 — URL 파라미터로 동기 동작 (HWPX 다운로드와 동일 패턴).

    GET: year, grade, month, number, category, type? — type 필터(쉼표 구분 [순서],[빈칸]…)
    ModifiedQuestions_Data 를 필터해 한글 폰트로 readable PDF 생성. Platypus 자동 줄바꿈.
    """
    from io import BytesIO
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
    from reportlab.lib.enums import TA_LEFT
    import re as _re
    import urllib.parse

    selected_year = [y for val in request.GET.getlist('year', []) for y in val.split(',') if y]
    selected_grade = [g for val in request.GET.getlist('grade', []) for g in val.split(',') if g]
    selected_month = [m for val in request.GET.getlist('month', []) for m in val.split(',') if m]
    selected_numbers = [n for val in request.GET.getlist('number', []) for n in val.split(',') if n]
    cat_list = [n for val in request.GET.getlist('category', []) for n in val.split(',') if n]
    selected_category = cat_list[0] if cat_list else '변형문제'
    selected_types = [t for val in request.GET.getlist('type', []) for t in val.split(',') if t.strip()]

    pknum = KeyTable.objects.all()
    if selected_year:
        pknum = pknum.filter(year__in=selected_year)
    if selected_grade:
        pknum = pknum.filter(grade__in=selected_grade)
    if selected_month and "전체" not in selected_month:
        pknum = pknum.filter(month__in=selected_month)
    if selected_numbers:
        pknum = pknum.filter(total_number__in=selected_numbers)

    pk_ids = list(pknum.values_list('pk_number', flat=True))
    total_map = dict(pknum.values_list('pk_number', 'total_number'))

    qs = ModifiedQuestions_Data.objects.filter(pk_number__in=pk_ids)
    if selected_types:
        qs = qs.filter(qtype__in=[f'[{t.strip().strip("[]")}]' for t in selected_types])
    rows = list(qs.values('index', 'question', 'sentence', 'option', 'answer',
                          'qtype', 'pk_number').order_by('pk_number', 'index'))

    # 폰트 등록 (한글)
    font_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'fonts', 'NanumSquareRoundR.ttf')
    try:
        pdfmetrics.registerFont(TTFont('NanumSquareRound', font_path))
    except Exception:
        pass

    base_style = {'fontName': 'NanumSquareRound', 'fontSize': 11, 'leading': 16, 'alignment': TA_LEFT}
    style_title = ParagraphStyle('title', **base_style, textColor='#1f2937', fontSize=15, leading=22, spaceAfter=10)
    style_head  = ParagraphStyle('head',  **base_style, textColor='#6d28d9', fontSize=12, leading=18, spaceBefore=6, spaceAfter=4)
    style_body  = ParagraphStyle('body',  **base_style, textColor='#1f2937', spaceAfter=4)
    style_ans   = ParagraphStyle('ans',   **base_style, textColor='#16a34a', fontSize=11, leading=14, spaceBefore=4)

    def _esc(s):
        # Paragraph 가 마크업으로 해석하는 < > & 이스케이프, uFFF0 마커 제거, 줄바꿈 → <br/>
        s = (s or '').replace('￰', '')
        s = s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        s = _re.sub(r'\r\n?', '\n', s)
        s = s.replace('\n', '<br/>')
        return s

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm,
                            topMargin=18*mm, bottomMargin=18*mm)

    year_str = ', '.join(selected_year)
    grade_str = ', '.join(selected_grade)
    month_str = ', '.join(selected_month)
    header_text = f'{year_str}년 {grade_str} {month_str}월 — {selected_category}'

    story = [Paragraph(_esc(header_text), style_title)]
    for i, r in enumerate(rows, 1):
        total_no = total_map.get(r['pk_number'], '')
        qtype = r.get('qtype', '') or ''
        story.append(Paragraph(_esc(f'[{i}] {total_no} {qtype}'), style_head))
        if r.get('question'):
            story.append(Paragraph(_esc(r['question']), style_body))
        if r.get('sentence'):
            story.append(Paragraph(_esc(r['sentence']), style_body))
        if r.get('option'):
            story.append(Paragraph(_esc(r['option']), style_body))
        if r.get('answer'):
            story.append(Paragraph(_esc(f'정답: {r["answer"]}'), style_ans))
        story.append(Spacer(1, 6))

    if not rows:
        story.append(Paragraph('선택한 조건에 맞는 변형문제가 없습니다.', style_body))

    doc.build(story)
    data = buf.getvalue()
    buf.close()

    filename = f'[프라임에듀]_{year_str}년_{grade_str}_{month_str}월_{selected_category}.pdf'
    encoded = urllib.parse.quote(filename, safe='')
    response = HttpResponse(data, content_type='application/pdf')
    response['Content-Disposition'] = (
        f"attachment; filename=\"exam.pdf\"; filename*=UTF-8''{encoded}"
    )
    return response


# ---------------------------------------------------------------------------
# HWPX 공통 전처리 유틸
# ---------------------------------------------------------------------------
def _hwpx_clean(text):
    """DB 저장 텍스트를 HWPX용으로 변환: \\r\\n → 줄바꿈, uFFF0 밑줄 마커 제거.
        \t -> 한/글에서 제어 문자로 사용되나 이게 직접적으로 들어가면 렌더링 오류. 제거
    """
    if not text:
        return ""
    text = str(text).replace('\\r\\n', '\n').replace('\t', ' ')
    #text = re.sub(r'￰(.*?)￰', r'\1', text)
    return text


def _hwpx_choices(option_str):
    """선택지 문자열(\\r\\n 구분)을 리스트로 분리."""
    if not option_str:
        return []
    return [c for c in _hwpx_clean(option_str).split('\n') if c.strip()]


# ---------------------------------------------------------------------------
# 변형문제 HWPX 다운로드
# ---------------------------------------------------------------------------
@require_download
def download_modified_hwpx(request):
    from common.hwpx import TEMPLATE_PATH
    from common.hwpx.hwpx_builder import build_hwpx_bytes

    selected_year = [y for val in request.GET.getlist('year', []) for y in val.split(',') if y]
    selected_grade = [g for val in request.GET.getlist('grade', []) for g in val.split(',') if g]
    selected_month = [m for val in request.GET.getlist('month', []) for m in val.split(',') if m]
    selected_numbers = [n for val in request.GET.getlist('number', []) for n in val.split(',') if n]
    selected_category = [n for val in request.GET.getlist('category', []) for n in val.split(',') if n][0]
    # 변형 유형 필터 — '순서,빈칸,어법' 같이 와도, '[순서]' 형태 DB 값에 맞춰 대괄호 추가.
    selected_types = [t for val in request.GET.getlist('type', []) for t in val.split(',') if t.strip()]

    pknum = KeyTable.objects.all()
    if selected_year or selected_grade or selected_month:
        if selected_year:
            pknum = pknum.filter(year__in=selected_year)
        if selected_grade:
            pknum = pknum.filter(grade__in=selected_grade)
        if selected_month and "전체" not in selected_month:
            pknum = pknum.filter(month__in=selected_month)
        if selected_numbers:
            pknum = pknum.filter(total_number__in=selected_numbers)
    else:
        pknum = KeyTable.objects.none()

    pk_numbers = list(pknum.values_list('pk_number', flat=True))
    keytable_map = dict(pknum.values_list('pk_number', 'total_number'))

    qs = (ModifiedQuestions_Data.objects
          .filter(pk_number__in=pk_numbers))
    if selected_types:
        qs = qs.filter(qtype__in=[f'[{t.strip().strip("[]")}]' for t in selected_types])
    rows = qs.values('index', 'question', 'sentence', 'option', 'answer', 'pk_number').order_by('pk_number', 'index')

    questions = []
    for r in rows:
        total_number = keytable_map.get(r['pk_number'], '')
        questions.append({
            "date":    f"[{total_number}]" if total_number else "",
            "prompt":  _hwpx_clean(r.get('question', '')),
            "passage": _hwpx_clean(r.get('sentence', '')),
            "choices": _hwpx_choices(r.get('option', '')),
            "answer":  r.get('answer', '').replace('\t', ' '),
        })

    year_str = ', '.join(selected_year)
    grade_str = ', '.join(selected_grade)
    month_str = ', '.join(selected_month)
    header_text = f"{year_str}년도 {grade_str} {month_str}월 {selected_category}"

    data = build_hwpx_bytes(TEMPLATE_PATH, header_text, questions)

    import urllib.parse
    filename = f"[프라임에듀]_{year_str}년_{grade_str}_{month_str}월_{selected_category}.hwpx"
    encoded_filename = urllib.parse.quote(filename, safe='')
    response = HttpResponse(data, content_type='application/hwp+zip')
    response['Content-Disposition'] = (
        f"attachment; filename=\"exam.hwpx\"; filename*=UTF-8''{encoded_filename}"
    )

    return response


# ──────────────────────────────────────────────────────────────────────
# 관리자 전용 — 아이디별 모고 데이터 접근범위 설정 화면 (2026-06-16)
# ──────────────────────────────────────────────────────────────────────
require_admin = _require_access(lambda u: getattr(u, 'is_admin_level', False))

ACCESS_CHOICES = [
    ('none', '접근 없음'),
    ('variant_view', '변형문제 열람만'),
    ('variant_down', '변형문제 열람+다운로드'),
    ('full', '모고 전체'),
]


@require_admin
def access_admin(request):
    """아이디별로 모고 데이터 접근범위(none/variant/full)를 설정하는 관리자 페이지."""
    User = get_user_model()

    if request.method == 'POST':
        member_id = request.POST.get('member_id')
        new_level = request.POST.get('academy_access')
        valid = {c[0] for c in ACCESS_CHOICES}
        target = User.objects.filter(pk=member_id).first()
        if not target or new_level not in valid:
            messages.error(request, '잘못된 요청입니다.')
        elif target.is_admin_level:
            messages.error(request, f'{target.display_name}은(는) 관리자/학원운영자라 항상 전체 접근입니다.')
        else:
            target.academy_access = new_level
            target.save(update_fields=['academy_access'])
            label = dict(ACCESS_CHOICES)[new_level]
            messages.success(request, f'{target.display_name} → 접근범위 "{label}" 저장 완료.')
        return redirect('academy:access_admin')

    q = (request.GET.get('q') or '').strip()
    # 관리자(is_staff/superuser)는 항상 전체라 설정 대상에서 제외. 학원 계정은 관리 대상에 포함.
    members = (User.objects
               .filter(is_staff=False, is_superuser=False)
               .order_by('-date_joined'))
    if q:
        members = members.filter(
            Q(login_id__icontains=q) | Q(username__icontains=q) | Q(email__icontains=q)
        )

    rows = []
    for m in members[:500]:
        # 재원생(primeedu*) 여부 표시 — 기본 차단 대상 안내용
        is_resident = bool(m.is_approved) or bool(re.match(r'^primeedu\d+$', m.login_id or ''))
        rows.append({'m': m, 'is_resident': is_resident, 'is_academy': bool(m.is_academy)})

    return render(request, 'access_admin.html', {
        'rows': rows,
        'choices': ACCESS_CHOICES,
        'q': q,
        'total': members.count(),
    })