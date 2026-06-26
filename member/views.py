from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Profile, Member
from .forms import SignupForm, MemberProfileEditForm

def signup(request):
    if request.method == 'POST':
        form = SignupForm(request.POST, request.FILES)  # 파일 업로드 처리
        user_type = request.POST.get('user_type')  # 수강생 또는 학원 구분
        
        if form.is_valid():
            # Member 모델로 저장
            user = form.save(commit=False)
            user.member_type = 'academy_admin' if user_type == 'academy' else 'user'
            user.is_academy = (user_type == 'academy')  # 학원인 경우 is_academy=True로 설정
            if user.is_academy:
                # 선생님(학원) 가입 — 즉시 로그인 가능, 관리자 승인 전까지는 변형문제 열람만 허용
                user.is_active = True
                user.academy_access = 'variant_view'
            user.save()

            # 사업자등록증 처리
            if user.is_academy and request.FILES.get('business_registration'):
                business_registration = request.FILES['business_registration']
                user.business_registration.save(business_registration.name, business_registration)

            if user.is_academy:
                messages.info(request,
                              "회원가입이 완료되었습니다. 관리자 승인 전까지는 변형문제 열람만 가능합니다.")
            else:
                messages.info(request, "회원가입이 완료되었습니다. 관리자 승인 후 로그인해주세요.")
            return redirect("login")
            
            """
            login(request, user)  # 자동 로그인 처리
            if user.is_academy:
                return redirect('academy_dashboard')  # 학원 대시보드로 리디렉션
            else:
                return redirect('student_academy_selection')  # 수강생 학원 선택 페이지로 리디렉션
            """
    else:
        form = SignupForm()

    return render(request, 'registration/register.html', {'form': form})

@login_required
def profile_view(request):
    member = request.user

    if request.method == 'POST':
        form = MemberProfileEditForm(request.POST, instance=member)
        if form.is_valid():
            form.save()
            return redirect('member:profile_view')  # 수정 후 프로필 페이지로 리디렉트
    else:
        form = MemberProfileEditForm(instance=member)

    return render(request, 'member/profile_view.html', {'form': form, 'member': member})

@login_required
def profile_edit_view(request):
    # 현재 로그인한 사용자에 해당하는 Member 객체를 가져옵니다.
    member = get_object_or_404(Member, id=request.user.id)

    if request.method == 'POST':
        # POST 요청 시 폼을 바인딩하고 제출된 데이터를 처리합니다.
        form = MemberProfileEditForm(request.POST, request.FILES, instance=member)
        if form.is_valid():
            form.save()  # 유효한 데이터일 경우 저장
            return redirect('member:profile_view')  # 프로필 뷰로 리디렉션
    else:
        # GET 요청 시 기존 데이터를 가지고 폼을 초기화합니다.
        form = MemberProfileEditForm(instance=member)

    return render(request, 'member/profile_edit.html', {'form': form})

@login_required
def change_password_view(request):
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            form.save()
            update_session_auth_hash(request, form.user)  # 세션에 새로운 비밀번호 업데이트
            return redirect('member:profile_view')
    else:
        form = PasswordChangeForm(request.user)
    return render(request, 'member/change_password.html', {'form': form})

@login_required
def mypage(request):
    profile, created = Profile.objects.get_or_create(user=request.user)
    return render(request, 'member/mypage.html', {'profile': profile})


@login_required
def select_type(request):
    """소셜 가입 등 학생/학원 미선택 계정의 1회성 유형 선택.

    학원 선택 시 변형문제 열람(variant_view) 권한 부여. 학생은 일반 회원.
    """
    user = request.user
    if not getattr(user, 'needs_type_selection', False):
        return redirect('index')

    if request.method == 'POST':
        if request.POST.get('user_type') == 'academy':
            user.is_academy = True
            user.member_type = 'academy_admin'
            user.academy_access = 'variant_view'   # 가입=변형문제 열람만(다운로드는 관리자 승인)
            msg = '학원 계정으로 설정되었습니다. 변형문제 자료를 열람하실 수 있습니다.'
        else:
            user.is_academy = False
            user.member_type = 'user'
            msg = '학생 계정으로 설정되었습니다.'
        user.needs_type_selection = False
        user.save(update_fields=['is_academy', 'member_type', 'academy_access', 'needs_type_selection'])
        messages.success(request, msg)
        return redirect('index')

    return render(request, 'registration/select_type.html')