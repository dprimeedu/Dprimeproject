from django.urls import reverse_lazy, reverse
from django.views import generic
from member.forms import SignupForm  # 수정된 SignupForm 사용
from django.views.generic import TemplateView
from django.contrib.auth import login as auth_login
from django.contrib.auth.views import LoginView
from django.contrib import messages
from django.shortcuts import redirect, render
from member.views import profile_edit_view
from datetime import datetime

class HomeView(generic.TemplateView):
    template_name = 'home.html'


class MockExamView(generic.RedirectView):
    """모고 데이터 다운로드 — 검색·필터 가능한 모의고사 리스트(academy_list)로 통합."""
    pattern_name = 'academy:academy_list'
    permanent = False


class TrainingView(generic.TemplateView):
    template_name = 'training.html'

class UserCreateView(generic.CreateView):
    template_name = 'registration/register.html'
    form_class = SignupForm
    success_url = reverse_lazy('register_done')

    def form_valid(self, form):
        user = form.save(commit=False)
        user_type = self.request.POST.get('user_type')

        if user_type == 'academy':
            user.is_academy = True
            user.member_type = 'academy_admin'
            user.is_active = True            # 가입 즉시 로그인 가능(변형문제 열람용)
            user.is_approved = False
            # 가입=변형문제 열람만. 관리자가 access-admin에서 variant_down으로 올리면 다운로드 허용.
            user.academy_access = 'variant_view'
        else:
            user.is_academy = False
            user.member_type = 'user'
            user.is_active = True         # 학생: 즉시 활성, 사이트 로그인 가능
            user.is_approved = False      # 재원생 메뉴는 별도 학원 승인 필요

        user.save()

        if user.is_active:
            auth_login(
                self.request, user,
                backend='member.backends.LoginIdOrEmailBackend',
            )
        return super().form_valid(form)

class UserCreateDoneTV(generic.TemplateView):
    template_name = 'registration/register_done.html'

class CustomLoginView(LoginView):
    def form_valid(self, form):
        user = form.get_user()
        auth_login(self.request, user)

        # 'next' 값이 있으면 해당 페이지로 리디렉션
        next_url = self.request.GET.get('next') or self.request.POST.get('next')
        if next_url:
            return redirect(next_url)

        if user.is_academy:
            return redirect('acad:academy_dashboard')

        # 학원에서 승인한 재원생은 바로 재원생 메뉴(/training/)로
        is_admin = user.is_superuser or user.is_staff
        if not is_admin and getattr(user, 'is_approved', False):
            return redirect('training')

        return redirect('index')

    def form_invalid(self, form):
        messages.error(self.request, '아이디 또는 비밀번호가 잘못되었습니다.')
        return super().form_invalid(form)
    
def academy_dashboard(request):
    return render(request, 'academy_dashboard.html')

def custom_404(request, exception=None):
    return render(request, 'exception/404.html', status=404)

def custom_500(request, exception=None):
    return render(request, 'exception/500.html', status=500)

def custom_403(request, exception=None):
    return render(request, 'exception/403.html', status=403)

def custom_400(request, exception=None):
    return render(request, 'exception/400.html', status=400)