from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.db import models
from django.utils import timezone

class MemberManager(BaseUserManager):
    def create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Email은 필수입니다.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        return self.create_user(email, password, **extra_fields)
    
class Member(AbstractBaseUser, PermissionsMixin):
    MEMBER_TYPES = (
        ('user', '학생'),
        ('academy_admin', '학원운영자'),
        ('admin', '전체관리자'),
    )
    objects = MemberManager()
    email = models.EmailField(unique=True, null=True, blank=True)
    login_id = models.CharField(
        max_length=50, unique=True, null=True, blank=True,
        verbose_name='로그인 ID',
        help_text='학원이 등록한 재원생용 ID (영문/숫자). 일반 회원가입자는 이메일로 로그인.',
    )
    username = models.CharField(max_length=150, verbose_name='이름')
    is_active = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    is_approved = models.BooleanField(
        default=False, verbose_name='재원생 승인',
        help_text='학원이 재원생으로 인정한 경우 True. 재원생 메뉴 접근에 필요.',
    )
    member_type = models.CharField(max_length=20, choices=MEMBER_TYPES, default='user')
    phone = models.CharField(max_length=15, null=True, blank=True)
    is_academy = models.BooleanField(default=False)
    business_registration = models.FileField(upload_to='business_registrations/', null=True, blank=True)
    date_joined = models.DateTimeField(default=timezone.now)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    class Meta:
        db_table = 'member'
        verbose_name = '회원'
        verbose_name_plural = '회원들'

    def __str__(self):
        return self.login_id or self.email or f'user#{self.pk}'

class Profile(models.Model):
    user = models.OneToOneField(Member, on_delete=models.CASCADE)
    bio = models.TextField(blank=True)
    # 유저 정보에 있음. user에서 끌어오면 됨
    phone_number = models.CharField(max_length=15, blank=True)

    def __str__(self):
        return self.user.username