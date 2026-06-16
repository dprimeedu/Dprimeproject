from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import Member, Profile

class SignupForm(UserCreationForm):
    class Meta:
        model = Member
        fields = ['username', 'email', 'password1', 'password2']

# ProfileForm에서 수정할 필드들 정의
class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ['bio', 'phone_number']  # bio와 phone_number 필드를 수정 가능하게 설정

class MemberProfileEditForm(forms.ModelForm):
    class Meta:
        model = Member
        fields = ['nickname', 'phone']  # 기본 필드 설정

    nickname = forms.CharField(
        required=False,
        max_length=30,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '대전/리더보드에 표시될 별명 (한글/영문/숫자 1~30자, 비우면 ID로 표시)',
        }),
        label='별명',
    )
    phone = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '전화번호'}),
    )

    def clean_nickname(self):
        import re as _re
        v = (self.cleaned_data.get('nickname') or '').strip()
        if not v:
            return ''
        if len(v) > 30:
            raise forms.ValidationError('별명은 30자 이하여야 합니다.')
        if not _re.match(r'^[가-힣A-Za-z0-9 _\-.]+$', v):
            raise forms.ValidationError('한글/영문/숫자/공백만 사용 가능합니다.')
        # 중복 체크
        qs = Member.objects.exclude(pk=self.instance.pk).filter(nickname=v)
        if qs.exists():
            raise forms.ValidationError('이미 사용 중인 별명입니다.')
        return v

    # __init__ 메서드 오버라이드: is_academy에 따라 business_registration 필드를 동적으로 추가
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.is_academy:  # 만약 사용자가 학원일 경우
            self.fields['business_registration'] = forms.FileField(
                widget=forms.ClearableFileInput(attrs={'class': 'form-control'}),
                required=False
            )
        else:
            # 학원이 아닌 경우에는 해당 필드를 삭제
            self.fields.pop('business_registration', None)