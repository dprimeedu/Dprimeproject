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

        # 이메일로 새로 가입하는 계정(외부/학원/일반)은 IP 2개로 제한.
        # 재원생(primeedu*)은 관리자가 따로 생성하므로 이 흐름을 안 타 영향 없음(=무제한 유지).
        user.max_allowed_ips = 2
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
    def get_context_data(self, **kwargs):
        from django.conf import settings
        ctx = super().get_context_data(**kwargs)
        ctx['google_login_enabled'] = getattr(settings, 'GOOGLE_LOGIN_ENABLED', False)
        ctx['kakao_login_enabled'] = getattr(settings, 'KAKAO_LOGIN_ENABLED', False)
        return ctx

    def form_valid(self, form):
        from member.models import UserIP, IPAccessLog
        from member.ip_utils import get_client_ip

        user = form.get_user()
        ip = get_client_ip(self.request)

        # ── IP 한도 초과 시 로그인 차단 ─────────────────────────
        if ip and getattr(user, 'max_allowed_ips', 0) > 0:
            registered = UserIP.objects.filter(user=user)
            if not registered.filter(ip_address=ip).exists():
                if registered.count() >= user.max_allowed_ips:
                    IPAccessLog.objects.create(
                        user=user,
                        ip_address=ip,
                        status='ip_blocked',
                        path=self.request.path,
                        user_agent=self.request.META.get('HTTP_USER_AGENT', '')[:500],
                    )
                    messages.error(
                        self.request,
                        f'이 계정은 최대 {user.max_allowed_ips}개의 IP에서만 접속할 수 있습니다. '
                        '관리자에게 문의하세요.',
                    )
                    self.request._ip_block_logged = True
                    return self.form_invalid(form)

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
        from member.models import IPAccessLog
        from member.ip_utils import get_client_ip

        # IP 차단으로 호출된 경우는 이미 로그 기록 완료 — 일반 실패만 기록
        if not getattr(self.request, '_ip_block_logged', False):
            ip = get_client_ip(self.request)
            if ip:
                IPAccessLog.objects.create(
                    ip_address=ip,
                    status='login_fail',
                    path=self.request.path,
                    user_agent=self.request.META.get('HTTP_USER_AGENT', '')[:500],
                )
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