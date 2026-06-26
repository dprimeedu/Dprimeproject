from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter


class CustomAccountAdapter(DefaultAccountAdapter):
    """일반 allauth 계정 어댑터 (소셜 로그인이 공유 사용)."""

    def save_user(self, request, user, form, commit=True):
        user = super().save_user(request, user, form, commit=False)
        if not getattr(user, 'username', None):
            user.username = (user.email or '').split('@')[0] or '사용자'
        if commit:
            user.save()
        return user


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    """소셜 로그인(Google, Kakao) 전용 어댑터."""

    def pre_social_login(self, request, sociallogin):
        """
        소셜 로그인 시 동일 이메일 계정이 이미 존재하면 연결(connect)한다.
        이메일 중복 오류 방지 및 기존 계정과의 통합.
        """
        if sociallogin.is_existing:
            return

        email = self._extract_email(sociallogin)
        if not email:
            return

        from member.models import Member
        try:
            existing = Member.objects.get(email=email)
            sociallogin.connect(request, existing)
        except Member.DoesNotExist:
            pass

    def populate_user(self, request, sociallogin, data):
        """소셜 데이터로 user 채우기. 카카오 일반앱처럼 이메일을 안 주는 프로바이더는
        provider_uid 기반 가짜 이메일로 채워, 자동 가입(SIGNUP form 노출 없이)을 통과시킨다.
        나중에 비즈앱 전환·이메일 동의 시 실제 이메일로 교체할 수 있다.
        """
        user = super().populate_user(request, sociallogin, data)
        if not getattr(user, 'email', ''):
            provider = sociallogin.account.provider
            uid = sociallogin.account.uid
            user.email = f'{provider}_{uid}@social.dprimeedu.local'
        return user

    def save_user(self, request, sociallogin, form=None):
        """
        소셜 계정으로 새 Member 생성 시 기본값 설정.
        - is_active=True (소셜 로그인 사용자는 즉시 활성)
        - username: 소셜 프로필의 이름 사용
        - member_type: 'user'
        """
        user = sociallogin.user

        # 신규 사용자에게만 기본값 설정
        if not user.pk:
            user.is_active = True
            user.member_type = 'user'
            user.max_allowed_ips = 2          # 소셜(이메일) 신규 가입도 IP 2개 제한
            user.needs_type_selection = True  # 첫 접속 시 학생/학원 선택 화면으로
            if not getattr(user, 'username', None):
                user.username = self._extract_name(sociallogin) or \
                                self._extract_email(sociallogin).split('@')[0] or '사용자'

        user = super().save_user(request, sociallogin, form)
        return user

    # ── 내부 헬퍼 ───────────────────────────────────────────────

    def _extract_email(self, sociallogin):
        """프로바이더별 이메일 추출."""
        extra = sociallogin.account.extra_data

        # Google: extra_data['email']
        email = extra.get('email', '')
        if email:
            return email

        # Kakao: kakao_account.email
        kakao_account = extra.get('kakao_account', {})
        return kakao_account.get('email', '')

    def _extract_name(self, sociallogin):
        """프로바이더별 이름(표시명) 추출."""
        extra = sociallogin.account.extra_data

        # Google: name 또는 given_name
        name = extra.get('name') or extra.get('given_name', '')
        if name:
            return name

        # Kakao: kakao_account.profile.nickname
        kakao_account = extra.get('kakao_account', {})
        profile = kakao_account.get('profile', {})
        return profile.get('nickname', '')
