from django.urls import reverse_lazy, reverse
from django.views import generic
from member.forms import SignupForm  # 수정된 SignupForm 사용
from django.views.generic import TemplateView
from django.contrib.auth import login as auth_login
from django.contrib.auth.views import LoginView
from django.contrib import messages
from django.shortcuts import redirect, render
from member.views import profile_edit_view

class HomeView(generic.TemplateView):
    template_name = 'home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # 'member:profile_view'를 사용하여 URL을 찾습니다.
        context['profile_url'] = reverse('member:profile_view')
        return context

class UserCreateView(generic.CreateView):
    template_name = 'registration/register.html'
    form_class = SignupForm  # SignupForm 사용
    success_url = reverse_lazy('register_done')

    def form_valid(self, form):
        user = form.save(commit=False)  # 사용자 객체를 저장하되, 아직 DB에 저장하지 않음
        user_type = self.request.POST.get('user_type')  # 선택된 사용자 유형 가져오기

        if user_type == 'academy':
            user.is_academy = True
            user.is_active = True  # 학원은 기본적으로 활성화
        else:
            user.is_academy = False
            user.is_active = True  # 학생은 활성화 상태로 설정

        user.save()  # 사용자 객체를 DB에 저장
        auth_login(self.request, user)  # 로그인 처리
        return super().form_valid(form)  # 성공적으로 폼을 처리한 후 리디렉션

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
        
        # 사용자 유형에 따라 리디렉션
        if user.is_academy:
            return redirect('acad:academy_dashboard')  # 학원 대시보드 URL
        else:
            return redirect('index')  # 학생 대시보드 URL

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