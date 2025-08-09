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

    # GET 요청에서 필터링 값 가져오기
    selected_categories = request.GET.get("categories", "").split(",") if request.GET.get("categories") else []
    selected_grades = request.GET.get("grades", "").split(",") if request.GET.get("grades") else []
    selected_years = request.GET.get("years", "").split(",") if request.GET.get("years") else []

    # 모든 문제 가져오기 및 필터링
    questions = QuestionData.objects.all()
    if selected_years:
        questions = questions.filter(연도__in=selected_years)
    if selected_grades:
        questions = questions.filter(학년__in=selected_grades)
    if selected_categories:
        questions = questions.filter(유형__in=selected_categories)

    # 학년, 연도 및 유형 데이터베이스에서 가져오기
    grades = QuestionData.objects.values_list('학년', flat=True).distinct()
    years = sorted(QuestionData.objects.values_list('연도', flat=True).distinct(), reverse=False)  # 내림차순 정렬
    categories = QuestionData.objects.values_list('유형', flat=True).distinct()

    # 필요한 필드만 가져오기
    exams = questions.values('색인', '유형', '학년', '연도', '강')

    # 결과를 원하는 형식으로 변환
    formatted_exams = []
    seen_titles = set()
    for exam in exams:
        title = f"{exam['학년']} {exam['연도']}년 {exam['강']}월 모의고사"
        category = "모의고사"
        if title not in seen_titles:
            formatted_exam = {
                'category': category,
                'grade': exam['학년'], 
                'year': exam['연도'],
                'month': exam['강'],
                'title': title,
                'link': exam['색인'],
            }
            formatted_exams.append(formatted_exam)
            seen_titles.add(title)
    exams = formatted_exams

    context = {
    
        "exams": exams,
        "grades": [{"name": grade, "checked": grade in selected_grades} for grade in grades],
        "years": [{"name": year, "checked": str(year) in selected_years} for year in years],
        # "categories": [{"name": category, "checked": category in selected_categories} for category in categories],
        "categories": [{"name": category, "checked": category}],
        "selected_years": selected_years,
        "selected_grades": selected_grades,
        "selected_categories": selected_categories,
    }

    return render(request, "academy_list.html", context)

def academy_list_result(request):
    # 선택된 값 가져오기
    selected_year = request.GET.getlist("year", [])
    selected_grade = request.GET.getlist("grade", [])
    selected_month = request.GET.getlist('month', [])
    selected_category = request.GET.getlist("category", [])
    

    # 필터링된 문제 가져오기
    if selected_year and selected_grade:
        questions = QuestionData.objects.filter(
            연도__in=selected_year, 학년__in=selected_grade
        )
                # 선택된 카테고리에 따라 추가 필터링
        if selected_month:
            questions = questions.filter(강__in=selected_month)
        if selected_category:
            questions = questions.filter(유형__in=selected_category)

    else:
        questions = QuestionData.objects.none()  # 조건이 없을 경우 빈 쿼리셋 반환

    # 번호별 문제 수 계산
    number_counts = questions.values('번호').annotate(count=Count('번호')).order_by('번호')

    # 📌 (번호(개수)) 문자열 리스트 생성
    # question_list = ', '.join(f"{num['번호']}({num['count']})" for num in number_counts)
    question_list = [
    {"번호": num["번호"], "count": num["count"]}
    for num in number_counts
]
    total_count = sum(num['count'] for num in number_counts) if number_counts else 0  # 총 문제 수 계산

    # 📌 학년별 문제 수 계산 및 리스트 변환
    grade_counts = QuestionData.objects.values('학년').annotate(count=Count('학년'))
    grades = [
        {
            "name": grade['학년'], 
            "count": grade['count'],
            #"checked": selected_grade == grade['학년']
            "checked": grade['학년'] in selected_grade
        }
        for grade in grade_counts
    ]

    # 📌 유형별 문제 수 계산 및 리스트 변환
    category_counts = QuestionData.objects.filter(연도__in=selected_year, 강__in=selected_month).values('유형').annotate(count=Count('유형'))
    categories = [
        {
            "name": category['유형'], 
            "count": category['count'],
            #"checked": selected_category == category['유형']
            "checked": category['유형'] in selected_category or not selected_category 
        }
        for category in category_counts
    ]

    # 📌 연도별 문제 수 계산 및 리스트 변환
    year_counts = QuestionData.objects.values('연도').annotate(count=Count('연도'))
    sorted_years = sorted(year_counts, key=lambda x: x['연도'], reverse=False)  # 연도를 내림차순 정렬
    years = [
        {
            "name": year['연도'], 
            "count": year['count'],
            'year': selected_year,
            'grade': selected_grade,
            'month': selected_month,
            #"checked": str(selected_year) == str(year['연도'])
            "checked": str(year['연도']) in selected_year
        }
        for year in sorted_years
    ]

    exams = [{
        'question_list': question_list,
        'question_counter': total_count,  # 총 문제 수
        #'link': ['색인']  # 필요에 따라 링크 설정
        'link': None,
        'year': selected_year, # ['2019'] -> 
        'grade': selected_grade,
        'month': selected_month,
    }]

    category = '모의고사'
    context = {
        "exams": exams,
        "selected_year": selected_year,
        "selected_grade": selected_grade,
        "selected_category": category,
        "grades": grades,
        "years": years,
        "categories": categories,
        "selected_month" : selected_month,
    }

    return render(request, "academy_list_result.html", context)



@login_required(login_url='/accounts/login/')
# 기존에 있는는 코딩한 내용
def exam_list_result(request):
    selected_year = request.GET.getlist('year', [])
    selected_grade = request.GET.getlist('grade', [])
    selected_month = [m for m in request.GET.getlist('month', []) if m]
    selected_category = request.GET.getlist("category", [])

    # 필터링된 문제 가져오기
    if selected_year and selected_grade:
        questions = QuestionData.objects.filter(
            연도__in=selected_year, 학년__in=selected_grade
        )
                # 선택된 카테고리에 따라 추가 필터링
        if selected_category:
            questions = questions.filter(유형__in=selected_category)
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