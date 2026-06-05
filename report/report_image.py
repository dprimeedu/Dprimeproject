"""일일 학습 리포트 PNG 생성 — '학습보고서.py'(matplotlib) 이식.

Django와 분리된 순수 렌더러. render_report_png(row) 는 한글 키 dict 를 받아 PNG bytes 반환.
헬퍼/플로팅 로직은 원본(완성(코드)\\권용국 작업\\학습보고서.py)을 거의 그대로 옮겼고,
pandas 의존(pd.isna)만 _isna 로 치환, 저장은 파일 대신 BytesIO 로 변경.

서버(Docker)에 한글 폰트(Malgun Gothic / NanumGothic 등)가 설치돼 있어야 한다.
"""
import io
import re
import math
import textwrap

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt          # noqa: E402
import matplotlib.patches as patches     # noqa: E402
import matplotlib.font_manager as fm     # noqa: E402

# 한글 폰트 — 사용 가능한 첫 후보 적용
_FONT_CANDIDATES = ('Malgun Gothic', 'AppleGothic', 'NanumGothic', 'NanumBarunGothic', 'UnDotum')
_available = {f.name for f in fm.fontManager.ttflist}
for _c in _FONT_CANDIDATES:
    if _c in _available:
        plt.rcParams['font.family'] = _c
        break
plt.rcParams['axes.unicode_minus'] = False


# ─────────────────────────────────────────────
# 유틸 (학습보고서.py 와 동일 — pd.isna → _isna)
# ─────────────────────────────────────────────
def _isna(v):
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    if isinstance(v, str) and v.strip() in ('', 'nan', 'NaN'):
        return True
    return False


def clean_text(t):
    if _isna(t):
        return '-'
    t_str = str(t).strip()
    if t_str in ['0', 'nan', 'NaN', '', '0.0']:
        return '-'
    return t_str


def parse_progress_range(val):
    v = str(val).strip()
    if '-' in v:
        return v.split('-')[-1].strip()
    if '~' in v:
        return v.split('~')[-1].strip()
    return v


def get_eval_status(val, am_val=None, threshold=60, inclusive=True):
    if _isna(val):
        return '-', '#34495E'
    val_str = str(val).strip()
    if val_str in ['0', 'nan', 'NaN', '', '-']:
        return '-', '#34495E'

    color = '#E74C3C'
    display_str = val_str

    if "과제를 꼼꼼히 했습니다" in val_str:
        return display_str, '#27AE60'

    if '/' in val_str:
        match = re.search(r'(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)', val_str)
        if match:
            try:
                score = float(match.group(1))
                total = float(match.group(2))
                if total > 0:
                    percent = (score / total) * 100
                    if '점' in val_str:
                        display_str = val_str
                    else:
                        display_str = f"{val_str}\n({percent:.0f}점)"
                    is_red = (percent <= threshold) if inclusive else (percent < threshold)
                    color = '#E74C3C' if is_red else '#27AE60'
            except Exception:
                pass
    elif val_str == "합격":
        color = '#27AE60'

    if am_val and str(am_val).strip() not in ['0', 'nan', 'NaN', '', '-']:
        color = '#E74C3C'

    return display_str, color


def extract_textbook_label(result_val, today_val=None):
    if not _isna(result_val):
        s = str(result_val).strip()
        if ':' in s and '/' in s:
            prefix = s.split(':', 1)[0].strip()
            if prefix and prefix not in ['', '-', '0', 'nan']:
                return prefix
    if not _isna(today_val):
        s = str(today_val).strip()
        if s and s not in ['0', '0.0', '-', 'nan', 'NaN']:
            s = re.sub(r'\d{4}년\s*', '', s)
            s = re.sub(r'\d{1,2}월\s*모의고사', '모고', s)
            s = re.sub(r'\(\s*\d+\s*[-~]\s*\d+\s*\)', '', s)
            s = re.sub(r'\s+', ' ', s).strip()
            if s:
                return s
    return None


def is_first_class_value(val):
    if _isna(val):
        return False
    return '첫수업' in str(val)


def is_homework_failed_value(val):
    if _isna(val):
        return False
    s = re.sub(r'\s+', '', str(val))
    return '교재미지참' in s or '과제를하지않았습니다' in s


def get_homework_failed_label(val):
    if _isna(val):
        return None
    s = re.sub(r'\s+', '', str(val))
    if '교재미지참' in s:
        return '교재미지참'
    if '과제를하지않았습니다' in s:
        return '과제미이행'
    return None


def get_first_class_label(row):
    for col in ['과제1달성률', '과제2달성률']:
        v = row.get(col)
        if is_first_class_value(v):
            s = str(v).strip()
            if '내신' in s:
                return '내신첫수업'
            return '첫수업'
    return None


def convert_single_achievement(val):
    if _isna(val):
        return None
    if isinstance(val, (int, float)):
        if val == 0:
            return None
        return val * 100 if val <= 1.0 else val
    val_str = str(val).strip()
    if is_first_class_value(val_str):
        return None
    if is_homework_failed_value(val_str):
        return 0.0
    if val_str in ['0', 'nan', 'NaN', '', '숙제달성률']:
        return None
    if val_str == '결석':
        return 1.0
    if val_str in ['완료', '합격']:
        return 100.0
    match = re.search(r'달성률\s*(\d+(?:\.\d+)?)\s*%', val_str)
    if match:
        return float(match.group(1))
    if '%' in val_str:
        try:
            return float(val_str.replace('%', ''))
        except Exception:
            return None
    try:
        f_val = float(val_str)
        return f_val * 100 if f_val <= 1.0 else f_val
    except Exception:
        return None


def convert_achievement_combined(row):
    if is_first_class_value(row.get('과제1달성률')) or is_first_class_value(row.get('과제2달성률')):
        return float('nan')
    val1 = convert_single_achievement(row.get('과제1달성률'))
    val2 = convert_single_achievement(row.get('과제2달성률'))
    val3 = 0.0 if is_homework_failed_value(row.get('문법과제결과')) else None
    valid = [v for v in (val1, val2, val3) if v is not None]
    if valid:
        return sum(valid) / len(valid)
    return 100.0


def get_att_status(val):
    v = str(val).strip()
    if '결석' in v:
        return '결석'
    if '지각' in v:
        return '지각'
    if v in ['0', 'nan', 'NaN', '', '-']:
        return '미입력'
    return '출석'


# ─────────────────────────────────────────────
# 리포트 렌더 (학습보고서.py create_and_save_report_1 이식)
# row: 한글 키 dict — report.services.build_row 가 생성. 반환: PNG bytes
# ─────────────────────────────────────────────
def render_report_png(row):
    name = row['이름']
    achievement = row.get('숙제달성률_num', 100.0)
    if achievement is None or (isinstance(achievement, float) and math.isnan(achievement)):
        achievement = 100.0

    miss_count = int(row.get('연속미이행', 0) or 0)
    success_count = int(row.get('연속달성', 0) or 0)
    att_streak = int(row.get('연속출석', 0) or 0)
    late_streak = int(row.get('연속지각', 0) or 0)
    absent_streak = int(row.get('연속결석', 0) or 0)

    school_grade = str(row.get('학교학년', ''))
    attendance_raw = clean_text(row.get('출석', '출석'))
    att_status = row.get('출석_상태', '출석')

    school = school_grade[:-1] if len(school_grade) > 1 and school_grade[-1].isdigit() else school_grade
    date_obj = row.get('날짜_parsed')
    date_str = date_obj.strftime('%Y-%m-%d') if hasattr(date_obj, 'strftime') else str(date_obj)

    fig, ax = plt.subplots(figsize=(8.5, 20.5))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 20.5)
    ax.axis('off')
    fig.patch.set_facecolor('#F5EEF8')

    # (1) 헤더
    ax.add_patch(patches.Rectangle((0, 19.2), 10, 1.3, color='#4A235A'))
    ax.text(5, 20.0, "DAILY LEARNING REPORT", color='white', fontsize=24, fontweight='bold', ha='center')
    ax.text(5, 19.45, f"{date_str} | {name} ({school_grade})", color='#D2B4DE', fontsize=15, ha='center')

    # (2) 출결
    att_box_y = 18.4
    is_normal_att = (att_status == "출석")
    att_color = '#4A235A' if is_normal_att else '#C0392B'
    att_bg = '#EBDEF0' if is_normal_att else '#FADBD8'
    ax.add_patch(patches.Rectangle((0, att_box_y), 10, 0.7, color=att_bg))
    att_text = f"출결 상황 : {attendance_raw}"
    if att_status == "출석" and att_streak > 1:
        att_text += f" (연속 {att_streak}회 출석)"
    elif att_status == "지각" and late_streak > 1:
        att_text += f" (연속 {late_streak}회 지각)"
    elif att_status == "결석" and absent_streak > 1:
        att_text += f" (연속 {absent_streak}회 결석)"
    ax.text(5, att_box_y + 0.35, att_text, color=att_color, fontsize=15, fontweight='bold', ha='center', va='center')

    # (3) 과제 달성 알림
    hw_box_y = 17.65
    first_class_label = get_first_class_label(row)
    if att_status == "결석":
        ax.add_patch(patches.Rectangle((0, hw_box_y), 10, 0.55, color='#FCF3CF'))
        hw_msg = "오늘 결석 - 과제 및 보강 확인 요망"
        if miss_count > 0:
            hw_msg += f" (미이행 연속 {miss_count}회)"
        ax.text(5, hw_box_y + 0.275, hw_msg, color='#9A7D0A', fontsize=13, fontweight='bold', ha='center', va='center')
    elif first_class_label:
        ax.add_patch(patches.Rectangle((0, hw_box_y), 10, 0.55, color='#EBDEF0'))
        ax.text(5, hw_box_y + 0.275, first_class_label, color='#4A235A', fontsize=14, fontweight='bold', ha='center', va='center')
    elif achievement < 100:
        ax.add_patch(patches.Rectangle((0, hw_box_y), 10, 0.55, color='#FADBD8'))
        ax.text(5, hw_box_y + 0.275, f"주의: 과제 미이행 연속 {miss_count}회 발생", color='#922B21', fontsize=14, fontweight='bold', ha='center', va='center')
    else:
        ax.add_patch(patches.Rectangle((0, hw_box_y), 10, 0.55, color='#D4EFDF'))
        if success_count > 1:
            ax.text(5, hw_box_y + 0.275, f"훌륭합니다! 연속 {success_count}회 과제 100% 달성!", color='#145A32', fontsize=14, fontweight='bold', ha='center', va='center')
        else:
            ax.text(5, hw_box_y + 0.275, "오늘도 과제 100% 달성 완료!", color='#145A32', fontsize=14, fontweight='bold', ha='center', va='center')

    # (4) 시험 결과
    test_y = 16.0
    tests = [("어법 TEST", '어법/요약문결과', 80, False), ("단어 TEST", '단어시험결과', 80, False), ("영작 (Writing)", '영작시험결과', 60, True)]
    for i, (label, col, thres, inc) in enumerate(tests):
        x = 0.5 + i * 3.1
        res_t, res_c = get_eval_status(row.get(col, '-'), threshold=thres, inclusive=inc)
        ax.add_patch(patches.Rectangle((x, test_y), 2.8, 1.4, facecolor='white', edgecolor='#C39BD3', linewidth=1.5))
        ax.text(x + 1.4, test_y + 0.9, label, ha='center', fontsize=13, color='#6C3483')
        if res_t and res_t != '-':
            max_line = max((len(l) for l in res_t.split('\n')), default=0)
            if '\n' in res_t:
                test_fs = 13 if max_line > 8 else 15
            else:
                test_fs = 14 if max_line > 9 else (16 if max_line > 7 else 17)
            ax.text(x + 1.4, test_y + 0.35, res_t, ha='center', va='center', fontsize=test_fs, fontweight='bold', color=res_c)

    # (5) 오늘의 과제 평가
    ax.text(0.5, 15.35, "오늘의 과제 평가", fontsize=19, fontweight='bold', color='#4A235A')
    eval_cols = [
        ("독해 1 결과", '독해과제1결과', '오늘독해과제1', None, 75, True, '과제1달성률'),
        ("독해 2 결과", '독해과제2결과', '오늘독해과제2', None, 75, True, '과제2달성률'),
        ("문법 과제 결과", '문법과제결과', None, '문법번호', 60, True, None),
    ]
    eval_y = 13.15
    for i, (default_label, hcol, today_col, am_col, thres, inc, ach_col) in enumerate(eval_cols):
        x = 0.5 + i * 3.1
        res_t, res_c = get_eval_status(row.get(hcol, '-'), row.get(am_col), threshold=thres, inclusive=inc)
        label = default_label
        if today_col is not None:
            tb = extract_textbook_label(row.get(hcol), row.get(today_col))
            if tb:
                label = tb
                if res_t.startswith(tb + ':'):
                    res_t = res_t[len(tb) + 1:].strip()
        ach_failed_label = get_homework_failed_label(row.get(ach_col)) if ach_col else None
        if ach_failed_label:
            res_t = ach_failed_label
            res_c = '#E74C3C'
        if hcol == '문법과제결과':
            grammar_failed_label = get_homework_failed_label(row.get(hcol))
            if grammar_failed_label:
                res_t = grammar_failed_label
                res_c = '#E74C3C'
        if len(label) >= 11:
            label_fs = 10
        elif len(label) >= 9:
            label_fs = 11
        else:
            label_fs = 12
        ax.add_patch(patches.Rectangle((x, eval_y), 2.8, 1.8, facecolor='white', edgecolor='#C39BD3', linewidth=1.5))
        ax.text(x + 1.4, eval_y + 1.45, label, ha='center', fontsize=label_fs, color='#6C3483', fontweight='bold')
        if res_t and res_t != '-':
            wrapped = res_t if '\n' in res_t else "\n".join(textwrap.wrap(res_t, width=10))
            max_line = max((len(l) for l in wrapped.split('\n')), default=0)
            if max_line >= 11:
                eval_fs = 10
            elif max_line >= 9:
                eval_fs = 12
            else:
                eval_fs = 14
            ax.text(x + 1.4, eval_y + 0.65, wrapped, ha='center', va='center', fontsize=eval_fs, color=res_c, fontweight='bold', linespacing=1.1)

    # (5-2) 과제 달성률
    ach_y = 12.35
    val1 = convert_single_achievement(row.get('과제1달성률'))
    val2 = convert_single_achievement(row.get('과제2달성률'))
    miss1 = get_homework_failed_label(row.get('과제1달성률'))
    miss2 = get_homework_failed_label(row.get('과제2달성률'))
    if val1 is not None or val2 is not None:
        if val1 is not None:
            ax.add_patch(patches.Rectangle((0.5, ach_y), 4.2, 0.65, facecolor='white', edgecolor='#C39BD3', linewidth=1.5))
            if miss1:
                ax.text(2.6, ach_y + 0.45, "과제1 달성률", ha='center', fontsize=11, color='#E74C3C')
                ax.text(2.6, ach_y + 0.15, miss1, ha='center', fontsize=14, fontweight='bold', color='#E74C3C')
            else:
                c1 = '#27AE60' if val1 >= 100 else '#E74C3C'
                ax.text(2.6, ach_y + 0.45, "과제1 달성률", ha='center', fontsize=11, color='#6C3483')
                ax.text(2.6, ach_y + 0.15, f"{val1:.0f}%", ha='center', fontsize=15, fontweight='bold', color=c1)
        if val2 is not None:
            ax.add_patch(patches.Rectangle((5.3, ach_y), 4.2, 0.65, facecolor='white', edgecolor='#C39BD3', linewidth=1.5))
            if miss2:
                ax.text(7.4, ach_y + 0.45, "과제2 달성률", ha='center', fontsize=11, color='#E74C3C')
                ax.text(7.4, ach_y + 0.15, miss2, ha='center', fontsize=14, fontweight='bold', color='#E74C3C')
            else:
                c2 = '#27AE60' if val2 >= 100 else '#E74C3C'
                ax.text(7.4, ach_y + 0.45, "과제2 달성률", ha='center', fontsize=11, color='#6C3483')
                ax.text(7.4, ach_y + 0.15, f"{val2:.0f}%", ha='center', fontsize=15, fontweight='bold', color=c2)

    # (6) 다음 수업 상세 과제
    ax.text(0.5, 11.55, "다음 수업 상세 과제", fontsize=19, fontweight='bold', color='#4A235A')
    v_book = clean_text(row.get('단어장'))
    v_start = parse_progress_range(clean_text(row.get('숙제\n시작.1')))
    v_end = parse_progress_range(clean_text(row.get('숙제\n끝.1')))
    v_info = f"교재: {v_book}   범위: {v_start} - {v_end}"
    is_new_vocab = bool(row.get('is_new_vocab'))

    hw_data = [
        ("독해 과제 1", clean_text(row.get('다음독해과제1')), '#512E5F'),
        ("독해 과제 2", clean_text(row.get('다음독해과제2')), '#512E5F'),
        ("문법 과제", clean_text(row.get('다음문법과제')), '#512E5F'),
        ("단어 암기", v_info, '#512E5F'),
    ]
    for i, (htype, hval, t_color) in enumerate(hw_data):
        y_pos = 9.15 - i * 2.2
        ax.add_patch(patches.Rectangle((0.5, y_pos), 9, 1.9, facecolor='white', edgecolor='#D2B4DE', linewidth=1.5))
        if htype == "단어 암기" and is_new_vocab:
            ax.text(0.8, y_pos + 1.5, htype, fontsize=15, fontweight='bold', color='#4A235A')
            ax.add_patch(patches.FancyBboxPatch((0.8, y_pos + 0.9), 2.5, 0.35, boxstyle="round,pad=0.08", facecolor='#FADBD8', edgecolor='#E74C3C', linewidth=1.5))
            ax.text(2.05, y_pos + 1.075, "새 단어장!!!!", ha='center', va='center', color='#922B21', fontweight='bold', fontsize=14)
            if hval and hval != '-':
                ax.text(0.8, y_pos + 0.4, hval, fontsize=14, fontweight='bold', color='#922B21', va='center', linespacing=1.2)
        else:
            ax.text(0.8, y_pos + 1.3, htype, fontsize=15, fontweight='bold', color='#4A235A')
            if hval and hval != '-':
                ax.text(0.8, y_pos + 0.6, "\n".join(textwrap.wrap(hval, width=50)), fontsize=13.5, color=t_color, va='center', linespacing=1.2)

    # (7) 하단 한마디
    note_val = clean_text(row.get('선생님의 한마디', '-'))
    is_custom = (note_val != '-')
    if not is_custom:
        msg = "결석으로 아쉬움이 큽니다. 보강 일정을 확인하고 개별 지도 시간에 뵙겠습니다." if att_status == "결석" else "오늘도 수고많았습니다! 다음 개별 지도 때 봐요."
        msg_color = '#4A235A'
    else:
        msg = note_val
        msg_color = '#E74C3C'
    if att_status == "결석":
        bottom_bg = '#FCF3CF'
    elif first_class_label:
        bottom_bg = '#EBDEF0'
    elif achievement >= 100:
        bottom_bg = '#D4EFDF'
    else:
        bottom_bg = '#FADBD8'
    ax.add_patch(patches.FancyBboxPatch((0.5, 0.5), 9, 1.6, boxstyle="round,pad=0.1", facecolor=bottom_bg, edgecolor='#C39BD3'))
    wrapped_msg = "\n".join(textwrap.wrap(msg, width=42))
    ax.text(5, 1.3, wrapped_msg, ha='center', va='center', fontsize=14, fontweight='bold', color=msg_color, linespacing=1.3)

    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=200, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()
