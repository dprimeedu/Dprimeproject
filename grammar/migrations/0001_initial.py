import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

GRADE_CHOICES = [(g, g) for g in (
    '초1', '초2', '초3', '초4', '초5', '초6',
    '중1', '중2', '중3', '고1', '고2', '고3', '기타',
)]


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='GrammarUnit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('school', models.CharField(blank=True, default='', max_length=50, verbose_name='학교')),
                ('exam', models.CharField(blank=True, default='', max_length=100, verbose_name='시험/교재')),
                ('title', models.CharField(max_length=200, verbose_name='단원명')),
                ('grade', models.CharField(choices=GRADE_CHOICES, default='기타', max_length=10, verbose_name='학년')),
                ('description', models.CharField(blank=True, default='', max_length=300)),
                ('is_active', models.BooleanField(default=True, verbose_name='활성화')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='grammar_units_created', to=settings.AUTH_USER_MODEL)),
            ],
            options={'verbose_name': '어법 단원', 'verbose_name_plural': '어법 단원', 'db_table': 'grammar_unit', 'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='GrammarProblem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('index', models.IntegerField(verbose_name='번호')),
                ('sentence', models.TextField(verbose_name='문장')),
                ('answer', models.CharField(blank=True, default='', max_length=300, verbose_name='정답키')),
                ('sub_unit', models.CharField(blank=True, default='', max_length=50, verbose_name='소단원')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('unit', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='problems', to='grammar.grammarunit')),
            ],
            options={'verbose_name': '어법 문항', 'verbose_name_plural': '어법 문항', 'db_table': 'grammar_problem', 'ordering': ['unit', 'index'], 'unique_together': {('unit', 'index')}},
        ),
        migrations.CreateModel(
            name='GrammarAssignment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('assigned_at', models.DateTimeField(auto_now_add=True)),
                ('due_date', models.DateField(blank=True, null=True)),
                ('assigned_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='grammar_assignments_made', to=settings.AUTH_USER_MODEL)),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='grammar_assignments', to=settings.AUTH_USER_MODEL)),
                ('unit', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='assignments', to='grammar.grammarunit')),
            ],
            options={'verbose_name': '어법 배정', 'verbose_name_plural': '어법 배정', 'db_table': 'grammar_assignment', 'unique_together': {('student', 'unit')}},
        ),
        migrations.CreateModel(
            name='GrammarSession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('start_index', models.IntegerField(blank=True, null=True, verbose_name='시작 문항')),
                ('end_index', models.IntegerField(blank=True, null=True, verbose_name='끝 문항')),
                ('status', models.CharField(choices=[('in_progress', '진행 중'), ('submitted', '채점 대기'), ('graded', '채점 완료')], db_index=True, default='in_progress', max_length=12)),
                ('started_at', models.DateTimeField(auto_now_add=True)),
                ('submitted_at', models.DateTimeField(blank=True, null=True)),
                ('correct_count', models.IntegerField(default=0)),
                ('total_count', models.IntegerField(default=0)),
                ('graded_at', models.DateTimeField(blank=True, null=True)),
                ('graded_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='grammar_sessions_graded', to=settings.AUTH_USER_MODEL)),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='grammar_sessions', to=settings.AUTH_USER_MODEL)),
                ('unit', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sessions', to='grammar.grammarunit')),
            ],
            options={'verbose_name': '어법 세션', 'verbose_name_plural': '어법 세션', 'db_table': 'grammar_session', 'ordering': ['-started_at']},
        ),
        migrations.CreateModel(
            name='GrammarAnswer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('student_input', models.CharField(blank=True, default='', max_length=300, verbose_name='학생 입력')),
                ('auto_correct', models.BooleanField(default=False, verbose_name='자동채점 정답')),
                ('correct_answer', models.CharField(blank=True, default='', max_length=300, verbose_name='정답(스냅샷)')),
                ('admin_verdict', models.CharField(blank=True, choices=[('O', 'O'), ('X', 'X')], max_length=1, null=True, verbose_name='관리자 판정')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('problem', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='grammar.grammarproblem')),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='answers', to='grammar.grammarsession')),
            ],
            options={'verbose_name': '어법 응답', 'verbose_name_plural': '어법 응답', 'db_table': 'grammar_answer', 'ordering': ['session', 'problem__index'], 'unique_together': {('session', 'problem')}},
        ),
        migrations.CreateModel(
            name='GrammarRangeTest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('start_index', models.IntegerField(blank=True, null=True)),
                ('end_index', models.IntegerField(blank=True, null=True)),
                ('source_label', models.CharField(blank=True, default='어법TEST', max_length=100)),
                ('pass_threshold', models.IntegerField(default=90, verbose_name='합격 기준(%)')),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('assigned_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='grammar_range_tests_made', to=settings.AUTH_USER_MODEL)),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='grammar_range_tests', to=settings.AUTH_USER_MODEL)),
                ('unit', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='range_tests', to='grammar.grammarunit')),
            ],
            options={'verbose_name': '어법 오늘볼TEST', 'verbose_name_plural': '어법 오늘볼TEST', 'db_table': 'grammar_range_test', 'ordering': ['-created_at']},
        ),
    ]
