from django.shortcuts import render
from django.db.models import Count, Q, F
from django.contrib.auth.decorators import login_required
from .models import *

from django.http import HttpResponse
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os


# 선택한 카테고리를 이용해서 DB를 결정
DB_DICT = {"원문추가":AdditionalText_Data, "직보서술형":DescriptiveQuestion_Data,
            "상세해설":DetailedExplanation_Data, "객관식빈칸":FillinBlank_Data,
            "어법1단계":Grammarlv1_Data, "어법2단계":Grammarlv2_Data, "어법3단계":Grammarlv3_Data,
            "변형문제":ModifiedQuestions_Data, "문제출력":OriginalQuestion_Data,
            "원문":OriginalText_Data, "내신빨파":RedBlue_Data,
            "내신TEST":SchoolExamTest_Data, "요약문완성":Summary_Data,
            "중요영작":Translation_Data, "내신단어":WordTest_Data}

def academy_list(request):
    """
    이거를 이제 전체 문제에서 끌고 올 필요가 없음
    KEY_TABLE -> 연도 학년 월 제목
    이걸로 끌고오기    
    """

    # GET 요청에서 필터링 값 가져오기
    selected_grades = request.GET.get("grades", "").split(",") if request.GET.get("grades") else []
    selected_years = request.GET.get("years", "").split(",") if request.GET.get("years") else []

    # 모든 문제 가져오기 및 필터링
    questions = KeyTable.objects.all()
    if selected_years:
        questions = questions.filter(year__in=selected_years)
    if selected_grades:
        questions = questions.filter(grade__in=selected_grades)

    # 학년, 연도 및 유형 데이터베이스에서 가져오기
    grades = KeyTable.objects.values_list('grade', flat=True).distinct()
    years = sorted(KeyTable.objects.values_list('year', flat=True).distinct(), reverse=False)  # 내림차순 정렬

    # 필요한 필드만 가져오기
    exams = questions.values('pk_number', 'grade', 'year', 'month')

    # 결과를 원하는 형식으로 변환
    formatted_exams = []
    seen_titles = set()
    for exam in exams:
        title = f"{exam['grade']} {exam['year']}년 {exam['month']}월 모의고사"
        if title not in seen_titles:
            formatted_exam = {
                'grade': exam['grade'], 
                'year': exam['year'],
                'month': exam['month'],
                'title': title,
                'link': exam['pk_number'],
            }
            formatted_exams.append(formatted_exam)
            seen_titles.add(title)
    exams = formatted_exams

    context = {
        "exams": exams,
        "grades": [{"name": grade, "checked": grade in selected_grades} for grade in grades],
        "years": [{"name": year, "checked": str(year) in selected_years} for year in years],
        "selected_years": selected_years,
        "selected_grades": selected_grades,
    }

    return render(request, "academy_list.html", context)

def academy_list_result(request):
    """
    여기서 이제 DB에 있는 해당하는 모든 값들을
    가져와야 함
    -> 데이터를 전부 긁어서 보내면 너무 무거우니까
    실제 데이터 가져오는건 "보기" 눌렀을 때만이고
    여기서는 쿼리를 가져오지 않음
    문제수를 가져오고 싶으면 미리 계산을 따로 해서
    저장을 해놔야 할 듯함
    로드할때마다 연산하는건 너무 비효율적임

    DB에 따로 테이블을 만들기
    색인 / 카테고리 / PK / 개수
    얘는 주기적으로 업데이트 해주면 될듯
    """
    TABLE_NAMES_DICT = {"Additional_text":"원문추가", "Descriptive_Question":"직보서술형",
                       "DetailedExplanation":"상세해설", "FillinBlank":"객관식빈칸",
                       "Grammarlv1":"어법1단계", "Grammarlv2":"어법2단계", "Grammarlv3":"어법3단계",
                       "Modified_Questions":"변형문제", "Original_Question":"문제출력",
                       "Original_text":"원문", "RedBlue":"내신빨파",
                       "SchoolExamtest":"내신TEST", "Summary":"요약문완성",
                       "Translation":"중요영작", "WordTest":"내신단어"}
    
    # 선택된 값 가져오기
    selected_year = request.GET.getlist("year", [])
    selected_grade = request.GET.getlist("grade", [])
    selected_month = request.GET.getlist('month', [])
    
    # KEY_TABLE에서 PK number 가져오기 및 필터링
    keys = KeyTable.objects.all()
    if selected_year or selected_grade or selected_month:
        if selected_year:
            keys = keys.filter(year__in=selected_year)
        if selected_grade:
            keys = keys.filter(grade__in=selected_grade)
        if selected_month:
            keys = keys.filter(month__in=selected_month)
    else:
        keys = KeyTable.objects.none()

    pk_key_numbers = keys.values_list('pk_number', flat=True)
    keytable_map = dict(keys.values_list('pk_number', 'total_number'))

    exams = []
    for table, korname in TABLE_NAMES_DICT.items():
        counts = CountTable.objects.filter(pk_number__in=pk_key_numbers, table_name=table).values('pk_number', 'count')
        for val in counts:
            val['total_number'] = keytable_map.get(val['pk_number'])
        # 📌 (번호(개수)) 문자열 리스트 생성
        # question_list = ', '.join(f"{num['번호']}({num['count']})" for num in number_counts)
        question_list = [
        {"num": c["total_number"], "count": c["count"]}
        for c in counts] 


        total_count = sum(c['count'] for c in counts) if counts else 0  # 총 문제 수 계산
        exams.append( {
            'question_list': question_list,
            'question_counter': total_count,  # 총 문제 수
            #'link': ['색인']  # 필요에 따라 링크 설정
            'link': None,
            'category': korname
        })

    context = {
        "exams": exams,
        "categories": TABLE_NAMES_DICT,
        "selected_year": selected_year,
        "selected_grade": selected_grade,
        "selected_month" : selected_month,
    }

    return render(request, "academy_list_result.html", context)



@login_required(login_url='/accounts/login/')
# 기존에 있는 코딩한 내용
def exam_list_result(request):
    if request.method == "POST":
        return grading(request)
    selected_year = request.GET.getlist('year', [])
    selected_grade = request.GET.getlist('grade', [])
    selected_month = [m for m in request.GET.getlist('month', []) if m]
    selected_category = request.GET.getlist('category', [])

    # KEY_TABLE에서 PK number 가져오기 및 필터링
    # 여기서 번호도 따와야지 출력할 수 있음
    pknum = KeyTable.objects.all()
    if selected_year and selected_grade and selected_month:
        pknum = pknum.filter(Q(year__in=selected_year) & Q(grade__in=selected_grade) & Q(month__in=selected_month))
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
    else:
        questions = QuestionData.objects.none()  # 조건이 없을 경우 빈 쿼리셋 반환

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


@login_required(login_url='/accounts/login/')
def download_pdf(request):
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="exam_list.pdf"'

    # 한글 폰트 등록 (예: 나눔고딕)
    pdfmetrics.registerFont(TTFont('NanumGothic', os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'fonts', 'NanumSquareRoundR.ttf')))

    pdf = canvas.Canvas(response, pagesize=A4)
    pdf.setTitle("시험 문제 리스트")
    
    y_position = 750

    pdf.setFont("NanumGothic", 14)
    pdf.drawString(100, y_position, "시험 문제 리스트")
    y_position -= 30

    pdf.setFont("NanumGothic", 12)

    selected_questions = request.session.get('selected_questions', [])
    selected_questions_answer = request.session.get('selected_questions_answer', [])

    for idx, question in enumerate(selected_questions, 1):
        pdf.drawString(100, y_position, f"문제 {idx}: {question['문제']}")
        y_position -= 20

        pdf.drawString(120, y_position, f"지문: {question['지문']}")
        y_position -= 20

        pdf.drawString(120, y_position, f"보기: {question['보기']}")
        y_position -= 20

        for answer in selected_questions_answer:
            if answer['색인'] == question['색인']:
                pdf.drawString(120, y_position, f"정답: {answer['정답']}")
                break
        y_position -= 30

        if y_position < 100:  # 페이지 넘김
            pdf.showPage()
            y_position = 750

    pdf.showPage()
    pdf.save()
    
    return response