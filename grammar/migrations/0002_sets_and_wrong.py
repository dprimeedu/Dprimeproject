import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('grammar', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='grammarsession',
            name='problem_indices',
            field=models.TextField(blank=True, default='', verbose_name='출제 문항(JSON)'),
        ),
        migrations.AddField(
            model_name='grammarsession',
            name='set_no',
            field=models.IntegerField(blank=True, null=True, verbose_name='세트 번호'),
        ),
        migrations.CreateModel(
            name='GrammarWrongAnswer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('wrong_count', models.IntegerField(default=1, verbose_name='틀린 횟수')),
                ('resolved', models.BooleanField(default=False, verbose_name='해결됨(맞춤)')),
                ('last_wrong_at', models.DateTimeField(auto_now=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('problem', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='wrong_answers', to='grammar.grammarproblem')),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='grammar_wrong_answers', to=settings.AUTH_USER_MODEL)),
            ],
            options={'verbose_name': '어법 개인오답', 'verbose_name_plural': '어법 개인오답', 'db_table': 'grammar_wrong_answer', 'ordering': ['-wrong_count', '-last_wrong_at'], 'unique_together': {('student', 'problem')}},
        ),
    ]
