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

    # 변형 유형 — QuestionData.유형 distinct(대괄호 제거).
    # 연결사 → 연결어, 지칭추론 → 지칭대상 동의어 통일.
    TYPE_ALIAS = {'연결사': '연결어', '지칭추론': '지칭대상'}
    raw_types = set()
    for t in QuestionData.objects.values_list('유형', flat=True).distinct():
        n = (t or '').strip().strip('[]')
        if not n:
            continue
        raw_types.add(TYPE_ALIAS.get(n, n))
    # 'B. 부교재 출력.py' Question.TYPE_LIST_ALL 의 표준 순서를 따른다.
    PREFERRED = ['순서', '도표', '그림', '문장넣기', '무관한문장', '연결어',
                 '일치불일치', '기타', '심경분위기', '지칭대상',
                 '주제', '주장', '제목', '요지', '목적', '밑줄의미',
                 '어휘', '요약문완성', '빈칸', '어법', '서술형',
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
    """변형문제 PDF 다운로드 — HTML 렌더 후 WeasyPrint 로 변환.

    템플릿: academy/print_paper.html (2단 column-count CSS, Nanum Gothic 폰트, 지문 박스, 정답 단단 페이지)
    GET: year, grade, month, number, category, type? — type 필터(쉼표 구분 [순서],[빈칸]…)
    """
    from django.template.loader import render_to_string
    from weasyprint import HTML
    import re as _re
    import urllib.parse
    import html as _html

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
        qs = qs.filter(qtype__in=_expand_type_filter(selected_types))
    qrows = list(qs.values('index', 'question', 'sentence', 'option', 'answer',
                            'qtype', 'pk_number'))
    # 'B. 부교재 출력.py' 표준 순서로 정렬 — 유형 그룹 + 회차 라운드로빈.
    qrows = _round_robin_sort(qrows, total_map)

    # 텍스트 정리 — uFFF0 마커는 밑줄 span, literal '\r\n' / Excel _x000D_ 도 줄바꿈, HTML 이스케이프
    MARK_RE = _re.compile(r'￰(.*?)￰')
    CHOICE_MARKERS = '①②③④⑤⑥⑦⑧⑨⑩'
    CHOICE_SPLIT_RE = _re.compile(r'(?=[①②③④⑤⑥⑦⑧⑨⑩])')

    def _normalize_breaks(s):
        # Excel OOXML 의 _x000D_(CR) / _x000A_(LF) 토큰 + literal escape + 실제 컨트롤
        s = (s or '')
        s = s.replace('_x000D_', '\n').replace('_x000A_', '\n')
        s = s.replace('\\r\\n', '\n').replace('\\n', '\n').replace('\\r', '\n')
        s = _re.sub(r'\r\n?', '\n', s)
        # 엑셀 인라인 그림(아이콘) placeholder 제거 — 예: icon_1_3
        s = _re.sub(r'icon_\d+_\d+', '', s)
        # 연속 빈줄 3개 이상은 2개로 축약
        s = _re.sub(r'\n{3,}', '\n\n', s)
        return s

    def _clean(s):
        s = _normalize_breaks(s)
        # HTML escape (uFFF0 마커는 보존하기 위해 임시 토큰 사용)
        marks = []
        def _grab(m):
            marks.append(m.group(1))
            return f'\x00MK{len(marks)-1}\x00'
        s = MARK_RE.sub(_grab, s)
        s = _html.escape(s)
        for i, inner in enumerate(marks):
            s = s.replace(f'\x00MK{i}\x00', f'<span class="mark">{_html.escape(inner)}</span>')
        return s

    def _split_choices(option_str):
        cleaned = _normalize_breaks(option_str)
        parts = [c.strip() for c in cleaned.split('\n') if c.strip()]
        # 줄바꿈으로 안 갈리고 한 줄 안에 ①②③ 가 같이 있으면 마커 앞에서 분리
        if any(any(m in p for m in CHOICE_MARKERS) for p in parts):
            new_parts = []
            for p in parts:
                if any(m in p[1:] for m in CHOICE_MARKERS):   # 첫 글자 외에 마커 더 있으면 split
                    chunks = [c.strip() for c in CHOICE_SPLIT_RE.split(p) if c.strip()]
                    new_parts.extend(chunks)
                else:
                    new_parts.append(p)
            parts = new_parts
        return [_clean(p) for p in parts]

    rows_ctx = []
    answers_ctx = []
    for r in qrows:
        total_no = total_map.get(r['pk_number'], '')
        date_str = total_no or ''
        rows_ctx.append({
            'date':    date_str,
            'prompt':  _clean(r.get('question', '')).replace('\n', '<br/>'),
            'passage': _clean(r.get('sentence', '')).replace('\n', '<br/>'),
            'choices': _split_choices(r.get('option', '')),
        })
        ans = (r.get('answer') or '').replace('\t', ' ').strip()
        if ans:
            answers_ctx.append({'date': date_str, 'answer': _clean(ans).replace('\n', ' ')})

    year_str = ', '.join(selected_year)
    grade_str = ', '.join(selected_grade)
    month_str = ', '.join(selected_month)
    header_text = f'{year_str}년 {grade_str} {month_str}월 {selected_category}'

    html_str = render_to_string('academy/print_paper.html', {
        'header_text': header_text,
        'rows': rows_ctx,
        'answers': answers_ctx,
    })

    pdf_bytes = HTML(string=html_str, base_url=request.build_absolute_uri()).write_pdf()

    filename = f'[프라임에듀]_{year_str}년_{grade_str}_{month_str}월_{selected_category}.pdf'
    encoded = urllib.parse.quote(filename, safe='')
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = (
        f"attachment; filename=\"exam.pdf\"; filename*=UTF-8''{encoded}"
    )
    return response


def _download_pdf_OLD_reportlab(request):
    """[DEPRECATED] ReportLab 기반. WeasyPrint 로 대체됨. 기존 코드 보존만 위해 남김."""
    from io import BytesIO
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame,
                                     Paragraph, Spacer, PageBreak, NextPageTemplate,
                                     Table, TableStyle, KeepTogether)
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
        qs = qs.filter(qtype__in=_expand_type_filter(selected_types))
    rows = list(qs.values('index', 'question', 'sentence', 'option', 'answer',
                          'qtype', 'pk_number'))
    # 'B. 부교재 출력.py' 표준 순서로 정렬 — 유형 그룹 + 회차 라운드로빈.
    rows = _round_robin_sort(rows, total_map)

    # 폰트 등록 (한글)
    from reportlab.lib import colors
    font_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                             'static', 'fonts', 'NanumSquareRoundR.ttf')
    try:
        pdfmetrics.registerFont(TTFont('NanumSquareRound', font_path))
        FONT = 'NanumSquareRound'
    except Exception:
        FONT = 'Helvetica'   # 등록 실패 시 fallback (한글 깨질 수 있음)

    # HWPX(한/글 변형문제) 인쇄물 표준에 맞춘 크기/간격 — 9pt 본문, 좁은 행간, 지문 박스.
    style_header = ParagraphStyle('hdr', fontName=FONT, fontSize=9, leading=12,
                                   alignment=TA_LEFT, textColor=colors.HexColor('#6b7280'),
                                   spaceAfter=8)
    style_qno    = ParagraphStyle('qno', fontName=FONT, fontSize=9.5, leading=12,
                                   alignment=TA_LEFT, textColor=colors.HexColor('#0f172a'),
                                   spaceBefore=8, spaceAfter=2)
    style_prompt = ParagraphStyle('prompt', fontName=FONT, fontSize=9.5, leading=12,
                                   alignment=TA_LEFT, textColor=colors.HexColor('#0f172a'),
                                   spaceAfter=3)
    style_passage = ParagraphStyle('passage', fontName=FONT, fontSize=8.5, leading=12,
                                   alignment=TA_LEFT, textColor=colors.HexColor('#0f172a'),
                                   spaceAfter=0)
    style_choice = ParagraphStyle('choice', fontName=FONT, fontSize=8.5, leading=11,
                                   alignment=TA_LEFT, textColor=colors.HexColor('#0f172a'),
                                   leftIndent=4, spaceAfter=0)
    style_ans_head = ParagraphStyle('anshd', fontName=FONT, fontSize=12, leading=16,
                                     alignment=TA_LEFT, textColor=colors.HexColor('#0f172a'),
                                     spaceAfter=8)
    style_ans_row = ParagraphStyle('ansrow', fontName=FONT, fontSize=9, leading=13,
                                    alignment=TA_LEFT, textColor=colors.HexColor('#0f172a'),
                                    spaceAfter=1)

    # 지문을 둘러쌀 회색 박스(Table 1-cell, 1pt 회색 테두리)용 스타일
    box_style = TableStyle([
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#94a3b8')),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ])

    def _passage_box(text):
        p = Paragraph(_esc(text), style_passage)
        t = Table([[p]], colWidths=[col_w - 8])
        t.setStyle(box_style)
        return t

    def _esc(s):
        # Paragraph 가 마크업으로 해석하는 < > & 이스케이프, uFFF0 마커 제거.
        # 데이터에 컨트롤 \r\n 외에 literal '\r\n' 4글자(\\r\\n) 가 들어있는 경우가 많음 — 둘 다 처리.
        s = (s or '').replace('￰', '')
        s = s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        # literal escape 시퀀스 → 진짜 줄바꿈
        s = s.replace('\\r\\n', '\n').replace('\\n', '\n').replace('\\r', '\n')
        s = _re.sub(r'\r\n?', '\n', s)   # 실제 컨트롤 문자
        s = s.replace('\n', '<br/>')
        return s

    # 2단 레이아웃 — 본문 페이지는 좌/우 두 단, 정답 페이지는 단단(BaseDocTemplate + PageTemplate).
    buf = BytesIO()
    PAGE_W, PAGE_H = A4
    L_MARG = 18*mm; R_MARG = 18*mm; T_MARG = 16*mm; B_MARG = 16*mm
    GUTTER = 8*mm
    col_w = (PAGE_W - L_MARG - R_MARG - GUTTER) / 2
    col_h = PAGE_H - T_MARG - B_MARG
    frame_left = Frame(L_MARG, B_MARG, col_w, col_h, leftPadding=4, rightPadding=4,
                       topPadding=2, bottomPadding=2, id='col1')
    frame_right = Frame(L_MARG + col_w + GUTTER, B_MARG, col_w, col_h,
                        leftPadding=4, rightPadding=4, topPadding=2, bottomPadding=2, id='col2')
    frame_single = Frame(L_MARG, B_MARG, PAGE_W - L_MARG - R_MARG, col_h,
                          leftPadding=4, rightPadding=4, topPadding=2, bottomPadding=2, id='full')
    doc = BaseDocTemplate(buf, pagesize=A4)
    doc.addPageTemplates([
        PageTemplate(id='2col',  frames=[frame_left, frame_right]),
        PageTemplate(id='1col',  frames=[frame_single]),
    ])

    year_str = ', '.join(selected_year)
    grade_str = ', '.join(selected_grade)
    month_str = ', '.join(selected_month)
    header_text = f'{year_str}년 {grade_str} {month_str}월 {selected_category}'

    def _split_choices(option_str, qtype=''):
        cleaned = (option_str or '').replace('￰', '')
        # literal '\r\n' 4글자 + 실제 CR/LF 모두 줄바꿈으로
        cleaned = cleaned.replace('\\r\\n', '\n').replace('\\n', '\n').replace('\\r', '\n')
        cleaned = _re.sub(r'\r\n?', '\n', cleaned)
        parts = [c.strip() for c in cleaned.split('\n') if c.strip()]
        parts = [_strip_marker_garbage(p) for p in parts]
        parts = [_space_inline_markers(p) for p in parts]
        if (qtype or '') in _TWO_BLANK_TYPES:
            parts = [_normalize_two_blank(p) for p in parts]
        # 남은 탭은 마지막에 공백으로
        parts = [p.replace('\t', ' ') for p in parts]
        return parts

    story = [Paragraph(_esc(header_text), style_header)]
    if not rows:
        story.append(Paragraph('선택한 조건에 맞는 변형문제가 없습니다.', style_prompt))

    # ① 본문 — HWPX 와 동일한 블록 순서: [회차] 라벨 → 문제 → 지문 → 보기 한 줄씩 → (정답은 끝 페이지)
    answers_index = []   # 끝 페이지 정답 모음용 (회차, 정답) 쌍
    for i, r in enumerate(rows, 1):
        total_no = total_map.get(r['pk_number'], '')
        if total_no:
            story.append(Paragraph(_esc(f'[{total_no}]'), style_qno))
        if r.get('question'):
            story.append(Paragraph(_esc(r['question']), style_prompt))
        if r.get('sentence'):
            story.append(_passage_box(r['sentence']))
        for ch in _split_choices(r.get('option', ''), r.get('qtype', '')):
            story.append(Paragraph(_esc(ch), style_choice))
        ans = (r.get('answer') or '').replace('\t', ' ').strip()
        if ans:
            answers_index.append((total_no, ans))

    # ② 정답은 새 페이지에서 단단 레이아웃 (HWPX 의 endnote-on-new-page 와 동일 의도)
    if answers_index:
        story.append(NextPageTemplate('1col'))
        story.append(PageBreak())
        story.append(Paragraph('■ 정답', style_ans_head))
        for total_no, ans in answers_index:
            story.append(Paragraph(_esc(f'[{total_no}]  {ans}'), style_ans_row))

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
# 변형 유형 동의어 — 사용자 화면(연결어/지칭대상) 입력을 DB 의 두 가지 형태로 모두 매핑.
# DB 에 `[연결사]` `[지칭추론]` 같은 옛 표기가 남아있을 수 있어 둘 다 필터에 포함.
_TYPE_SYNONYMS = {
    '연결어': ['연결어', '연결사'],
    '지칭대상': ['지칭대상', '지칭추론'],
}


def _expand_type_filter(selected_types):
    """'순서,연결어' 같은 입력 → ['[순서]', '[연결어]', '[연결사]'] 처럼 대괄호 포함 동의어 확장."""
    out = set()
    for t in selected_types:
        n = (t or '').strip().strip('[]')
        if not n:
            continue
        for v in _TYPE_SYNONYMS.get(n, [n]):
            out.add(f'[{v}]')
    return list(out)


# ---------------------------------------------------------------------------
# HWPX 공통 전처리 유틸
# ---------------------------------------------------------------------------
def _hwpx_clean(text):
    """DB 저장 텍스트를 HWPX용으로 변환.

    - Excel OOXML 토큰 `_x000D_` (CR) / `_x000A_` (LF) → 진짜 줄바꿈
    - literal `\\r\\n` (4글자) / 실제 컨트롤 문자 → 줄바꿈
    - `\\t` 는 한/글 렌더링 오류 유발 → 공백으로
    - uFFF0 강조 마커는 그대로 둠 (HWPX 빌더가 별도 처리)
    """
    import re as _re
    if not text:
        return ""
    text = str(text)
    text = text.replace('_x000D_', '\n').replace('_x000A_', '\n')
    text = text.replace('\\r\\n', '\n').replace('\\n', '\n').replace('\\r', '\n')
    text = _re.sub(r'\r\n?', '\n', text)
    text = text.replace('\t', ' ')
    # 엑셀 인라인 그림(아이콘) placeholder 제거 — 예: icon_1_3
    text = _re.sub(r'icon_\d+_\d+', '', text)
    # 연속 빈줄 3+ → 2개로
    text = _re.sub(r'\n{3,}', '\n\n', text)
    return text


_TWO_BLANK_TYPES = {'[요약문완성]', '[연결어]', '[연결사]'}


# 'B. 부교재 출력.py' (CLASS\\고등부교재자동화.py) excel_question 의
# __typeCheck 그룹 순서를 따른다 — TYPE1 → ... → TYPE6 → 그 외.
_PRINT_TYPE_ORDER = [
    '[순서]', '[문장넣기]', '[무관한문장]', '[연결어]', '[연결사]',     # TYPE1
    '[일치불일치]', '[기타]',                                          # TYPE2
    '[지칭대상]', '[지칭추론]',                                        # TYPE3
    '[주제]', '[주장]', '[제목]', '[요지]', '[목적]', '[밑줄의미]', '[함축의미]',  # TYPE4
    '[어휘]',                                                          # TYPE5
    '[요약문완성]', '[빈칸]',                                          # TYPE6
    # 그 외 — 표시 순서 유지
    '[도표]', '[그림]', '[심경분위기]',
    '[어법]', '[서술형]',
    '[장문]', '[장문2]', '[장문3]',
]
_PRINT_TYPE_RANK = {qt: i for i, qt in enumerate(_PRINT_TYPE_ORDER)}


def _round_robin_sort(rows, keytable_map):
    """변형문제 행을 (유형 그룹) → (회차번호 라운드로빈) 순으로 재정렬.

    같은 회차번호의 모든 변형이 연속으로 나오지 않고, 회차 1번/2번/3번...의
    첫 변형 → 다시 1번/2번/3번...의 두 번째 변형 식으로 분산된다.
    'B. 부교재 출력.py' 의 1순환 출력 의도와 동일.
    """
    from collections import defaultdict

    def _tn_key(tn):
        try:
            return (0, int(tn))
        except (TypeError, ValueError):
            return (1, str(tn or ''))

    groups = defaultdict(lambda: defaultdict(list))
    for r in rows:
        tn = keytable_map.get(r['pk_number'], '')
        groups[r.get('qtype', '')][tn].append(r)
    for qt in groups:
        for tn in groups[qt]:
            groups[qt][tn].sort(key=lambda r: r.get('index', 0))

    qt_order = sorted(groups.keys(), key=lambda q: _PRINT_TYPE_RANK.get(q, 9999))
    out = []
    for qt in qt_order:
        tn_keys = sorted(groups[qt].keys(), key=_tn_key)
        while any(groups[qt][tn] for tn in tn_keys):
            for tn in tn_keys:
                if groups[qt][tn]:
                    out.append(groups[qt][tn].pop(0))
    return out


def _space_inline_markers(line):
    """한 줄 안에 ②~⑩ 마커가 앞 글자에 붙어있으면 공백을 넣어 시각적으로 분리.

    예) '① (A)-(C)-(B)② (B)-(A)-(C)③ (B)-(C)-(A)'
      → '① (A)-(C)-(B)   ② (B)-(A)-(C)   ③ (B)-(C)-(A)'
    줄 시작의 ① 는 건드리지 않는다.
    """
    import re as _re
    return _re.sub(r'(\S)([②③④⑤⑥⑦⑧⑨⑩])', r'\1   \2', line)


def _strip_marker_garbage(line):
    """보기 줄 앞에 잘못 들어간 숫자/공백을 제거.

    예) '174 ③ Practically speaking ...' → '③ Practically speaking ...'
    엑셀 데이터에 회차/페이지번호가 셀에 잘못 섞여 들어간 경우 방어.
    마커가 따라오는 경우에만 제거(일반 텍스트는 손대지 않음).
    """
    import re as _re
    return _re.sub(r'^\s*\d+\s+(?=[①②③④⑤⑥⑦⑧⑨⑩])', '', line)


def _normalize_two_blank(choice):
    """두-빈칸 유형 보기의 단어 사이 구분을 ' …… ' 로 통일.

    DB 에 어떤 항목은 '단어A \t…… \t단어B', 어떤 항목은 '단어A \t단어B' 처럼
    들쭉날쭉하게 들어와 인쇄물에서 가독성이 떨어지는 문제를 보정.
    탭(\\t) 단독, 2칸 이상 공백, ……/... 모두 분리자로 인식한다.
    """
    import re as _re
    MARKERS = '①②③④⑤⑥⑦⑧⑨⑩'
    body = choice.strip()
    marker = ''
    if body and body[0] in MARKERS:
        marker = body[0]
        body = body[1:].lstrip()

    if _re.search(r'……|\.{3,}|⋯', body):
        body = _re.sub(r'\s*(?:……|\.{3,}|⋯)\s*', ' …… ', body, count=1)
    else:
        # 탭 단독 또는 2칸 이상 공백/탭 혼합을 분리자로
        body = _re.sub(r'[ \t ]{2,}|\t', ' …… ', body, count=1)

    return f"{marker} {body}" if marker else body


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
    import re as _re
    text = str(option_str)
    text = text.replace('_x000D_', '\n').replace('_x000A_', '\n')
    text = text.replace('\\r\\n', '\n').replace('\\n', '\n').replace('\\r', '\n')
    text = _re.sub(r'\r\n?', '\n', text)
    text = _re.sub(r'icon_\d+_\d+', '', text)
    parts = [c.strip() for c in text.split('\n') if c.strip()]
    parts = [_strip_marker_garbage(p) for p in parts]
    parts = [_space_inline_markers(p) for p in parts]
    if (qtype or '') in _TWO_BLANK_TYPES:
        parts = [_normalize_two_blank(p) for p in parts]
    # 남은 탭은 마지막에 공백으로 (한/글 렌더링 오류 방지)
    parts = [p.replace('\t', ' ') for p in parts]
    return parts


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
        qs = qs.filter(qtype__in=_expand_type_filter(selected_types))
    rows = list(qs.values('index', 'question', 'sentence', 'option', 'answer', 'pk_number', 'qtype'))
    # 'B. 부교재 출력.py' 표준 순서로 정렬 — 유형 그룹 + 회차 라운드로빈.
    rows = _round_robin_sort(rows, keytable_map)

    questions = []
    for r in rows:
        total_number = keytable_map.get(r['pk_number'], '')
        questions.append({
            "date":    f"[{total_number}]" if total_number else "",
            "prompt":  _hwpx_clean(r.get('question', '')),
            "passage": _hwpx_clean(r.get('sentence', '')),
            "choices": _hwpx_choices(r.get('option', ''), r.get('qtype', '')),
            "answer":  r.get('answer', '').replace('\t', ' '),
        })

    year_str = ', '.join(selected_year)
    grade_str = ', '.join(selected_grade)
    month_str = ', '.join(selected_month)
    header_text = f"{year_str}년도 {grade_str} {month_str}월 {selected_category}"

    # 빈 결과면 안내 한 문항만 — HWPX 가 완전 비어 보이지 않게.
    if not questions:
        questions = [{
            "date": "",
            "prompt": "선택한 회차/번호에 변형문제 데이터가 없습니다.",
            "passage": "다른 회차를 선택하거나 관리자에게 문의해 주세요.",
            "choices": [],
            "answer": "",
        }]

    data = build_hwpx_bytes(TEMPLATE_PATH, header_text, questions)

    import urllib.parse
    import datetime
    # 파일명에 생성시각을 넣어 매 다운로드가 '다른 파일'이 되게 한다.
    #  → 브라우저/한글이 이전에 받은 동명 파일(옛 내용)을 그대로 보여주는 혼선 방지.
    #  USE_TZ=False 라 timezone.localtime() 은 못 씀(naive 에러) → datetime.now() 사용.
    stamp = datetime.datetime.now().strftime("%m%d_%H%M")
    filename = f"[프라임에듀]_{year_str}년_{grade_str}_{month_str}월_{selected_category}_{stamp}.hwpx"
    encoded_filename = urllib.parse.quote(filename, safe='')
    response = HttpResponse(data, content_type='application/hwp+zip')
    response['Content-Disposition'] = (
        f"attachment; filename=\"exam_{stamp}.hwpx\"; filename*=UTF-8''{encoded_filename}"
    )
    # 다운로드 응답 캐싱 금지 — 항상 최신 생성본을 받도록.
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'

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