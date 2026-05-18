"""
로그인 ID 또는 이메일 둘 다 허용하는 인증 백엔드.
- 학원이 일괄 등록한 재원생: login_id로 로그인 (예: dprimeedu1)
- 직접 회원가입한 일반 사용자: email로 로그인
"""
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q

from .models import Member


class LoginIdOrEmailBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or password is None:
            return None
        try:
            user = Member.objects.get(Q(login_id=username) | Q(email=username))
        except Member.DoesNotExist:
            return None
        except Member.MultipleObjectsReturned:
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
