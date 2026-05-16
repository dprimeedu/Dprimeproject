from django import forms
from .models import WritingUnit


class WritingUnitUploadForm(forms.Form):
    title = forms.CharField(
        max_length=200, label='단원명',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '예) 고1 진단평가 3과 - Wrap Up',
        })
    )
    grade = forms.ChoiceField(
        choices=WritingUnit.GRADE_CHOICES,
        label='학년',
        initial='고1',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    publisher = forms.CharField(
        max_length=50, required=False, label='출판사 (선택)',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '예) 천재교육',
        })
    )
    description = forms.CharField(
        required=False, label='설명 (선택)',
        widget=forms.Textarea(attrs={
            'class': 'form-control', 'rows': 2,
        })
    )
    excel_file = forms.FileField(
        label='엑셀 파일 (.xlsx)',
        widget=forms.ClearableFileInput(attrs={
            'class': 'form-control',
            'accept': '.xlsx,.xls',
        })
    )

    def clean_excel_file(self):
        f = self.cleaned_data['excel_file']
        if not f.name.lower().endswith(('.xlsx', '.xls')):
            raise forms.ValidationError('xlsx 또는 xls 파일만 업로드 가능합니다.')
        if f.size > 10 * 1024 * 1024:
            raise forms.ValidationError('10MB 이하 파일만 업로드 가능합니다.')
        return f
