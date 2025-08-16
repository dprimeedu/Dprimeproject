from django.shortcuts import render
from django.db.models import Count
from django.contrib.auth.decorators import login_required
from .models import *

from django.http import HttpResponse
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

def additional_text_list(request):
    data = AdditionalText_Data.objects.all()
    for row in data:
        row.additional_text = row.additional_text.replace('\\r\\n', '\r\n')
    return render(request, 'additional_text.html', {'data': data})

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
    TABLE_NAMES = ["Additional_text", "Descriptive_Question",
                   "DetailedExplanation", "FillinBlank",
                   "Grammarlv1", "Grammarlv2", "Grammarlv3",
                   "Modified_Questions", "Original_Question",
                   "Original_text", "RedBlue",
                   "SchoolExamtest", "Summary",
                   "Translation", "WordTest"]
    
    # 선택된 값 가져오기
    selected_year = request.GET.getlist("year", [])
    selected_grade = request.GET.getlist("grade", [])
    selected_month = request.GET.getlist('month', [])
    
    # KEY_TABLE에서 PK number 가져오기 및 필터링
    questions = KeyTable.objects.all()
    if selected_year or selected_grade or selected_month:
        if selected_year:
            questions = questions.filter(year__in=selected_year)
        if selected_grade:
            questions = questions.filter(grade__in=selected_grade)
        if selected_month:
            questions = questions.filter(month__in=selected_month)
    else:
        questions = KeyTable.objects.none()

    pk_key_numbers = questions.values_list('pk_number', flat=True)
    exams = []
    for table in TABLE_NAMES:
        counts = CountTable.objects.filter(pk_number__in=pk_key_numbers, table_name=table).values('pk_number', 'count')

        # 📌 (번호(개수)) 문자열 리스트 생성
        # question_list = ', '.join(f"{num['번호']}({num['count']})" for num in number_counts)
        question_list = [
        {"번호": c["pk_number"], "count": c["count"]}
        for c in counts] 


        total_count = sum(c['count'] for c in counts) if counts else 0  # 총 문제 수 계산
        exams.append( {
            'question_list': question_list,
            'question_counter': total_count,  # 총 문제 수
            #'link': ['색인']  # 필요에 따라 링크 설정
            'link': None,
            'category': table
        })

    context = {
        "exams": exams,
        "categories": TABLE_NAMES,
        "selected_year": selected_year,
        "selected_grade": selected_grade,
        "selected_month" : selected_month,
    }

    return render(request, "academy_list_result.html", context)



@login_required(login_url='/accounts/login/')
# 기존에 있는는 코딩한 내용
def exam_list_result(request):
    selected_year = request.GET.getlist('year', [])
    selected_grade = request.GET.getlist('grade', [])
    selected_month = [m for m in request.GET.getlist('month', []) if m]

    # 필터링된 문제 가져오기
    if selected_year and selected_grade:
        questions = QuestionData.objects.filter(
            연도__in=selected_year, 학년__in=selected_grade
        )
        # 선택된 카테고리에 따라 추가 필터링
        if selected_month and all(m.isdigit() for m in selected_month):  # 숫자값만 필터링
            questions = questions.filter(강__in=selected_month)

    else:
        questions = QuestionData.objects.none()  # 조건이 없을 경우 빈 쿼리셋 반환

    # # 문제 데이터 가져오기
    if selected_year and selected_grade and selected_month:
        questions = QuestionData.objects.filter(연도=selected_year, 학년=selected_grade, 강=selected_month)
    else:
        questions = QuestionData.objects.none()  # 조건이 없을 경우 빈 쿼리셋 반환

    for q in questions:
        q.지문 = q.지문.replace('\\r\\n', '\r\n')
        if q.보기:
            q.보기 = q.보기.replace('\\r\\n', '\r\n')

    # 문제 데이터를 리스트화
    question_data = questions.values('색인', '문제', '지문', '보기')
    question_answer = questions.values('색인','정답')

    context = {
        "selected_questions": question_data,
        "selected_questions_answer": question_answer,
        "selected_year": selected_year,
        "selected_grade": selected_grade,
        "selected_month": selected_month,
    }    

    return render(request, "exam_list_result.html", context)



@login_required(login_url='/accounts/login/')
def download_pdf(request):
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="exam_list.pdf"'

    # 한글 폰트 등록 (예: 나눔고딕)
    pdfmetrics.registerFont(TTFont('NanumGothic', os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'fonts', 'NanumSquareRoundR.ttf')))

    pdf = canvas.Canvas(response, pagesize=letter)
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