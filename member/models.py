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
    email = models.EmailField(unique=True)
    username = models.CharField(max_length=150)
    # 회원가입 시 관리자 승인
    is_active = models.BooleanField(default=False)
    # 사이트 관리자 권한
    is_staff = models.BooleanField(default=False)
    # 사이트 전체 관리자 권한
    is_superuser = models.BooleanField(default=False)
    member_type = models.CharField(max_length=20, choices=MEMBER_TYPES, default='user')
    phone = models.CharField(max_length=15, null=True, blank=True)  # 전화번호 필드
    is_academy = models.BooleanField(default=False)  # 학원 여부
    business_registration = models.FileField(upload_to='business_registrations/', null=True, blank=True)
    date_joined = models.DateTimeField(default=timezone.now)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    class Meta:
        db_table = 'member'
        verbose_name = '회원'
        verbose_name_plural = '회원들'

    def __str__(self):
        return self.email

class Profile(models.Model):
    user = models.OneToOneField(Member, on_delete=models.CASCADE)
    bio = models.TextField(blank=True)
    # 유저 정보에 있음. user에서 끌어오면 됨
    phone_number = models.CharField(max_length=15, blank=True)

    def __str__(self):
        return self.user.username