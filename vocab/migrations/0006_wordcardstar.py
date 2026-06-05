from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('vocab', '0005_vocabunit_category'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='WordCardStar',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('card', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='stars', to='vocab.wordcard', verbose_name='낱말카드')),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='wordcard_stars', to=settings.AUTH_USER_MODEL, verbose_name='학생')),
            ],
            options={
                'verbose_name': '낱말카드 별표',
                'verbose_name_plural': '낱말카드 별표',
                'db_table': 'vocab_wordcard_star',
            },
        ),
        migrations.AddIndex(
            model_name='wordcardstar',
            index=models.Index(fields=['student', 'card'], name='vocab_wordc_student_idx'),
        ),
        migrations.AlterUniqueTogether(
            name='wordcardstar',
            unique_together={('student', 'card')},
        ),
    ]
