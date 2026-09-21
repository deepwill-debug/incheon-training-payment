from flask import Flask, render_template, request, send_from_directory, jsonify, session, redirect, url_for
import os
import uuid
import requests
import base64
import re
from datetime import datetime
from utils_google import record_payment, submit_application, get_application_status, get_service, check_is_member
from dotenv import load_dotenv

load_dotenv()

def parse_fee(fee_val, default_val=0):
    if fee_val is None:
        return default_val
    s = str(fee_val).replace(',', '').strip()
    digits = re.sub(r'[^\d]', '', s)
    if digits:
        return int(digits)
    return default_val

DEFAULT_CURRICULUM = {
    "산업안전": ["유해, 위험기계기구 방호 조치", "기계별 작업 시작 전 점검사항", "점검 이후 평가와 컨설팅", "산업안전보건 및 위험성 평가 관련 법률"],
    "퇴직급여": ["임원 퇴직소득 한도와 과세이연제도", "퇴직급여충당금의 세무상 한도", "세무상 퇴직급여충당금 설정 전 잔액", "확정급여형 및 확정기여형 퇴직연금"],
    "해외시장": ["글로벌 마케팅 전략과 프롬프트 활용", "해외바이어 맞춤형 홍보 콘텐츠 제작", "바이어 협상 전략 및 계약 실무", "VBA 활용 수출 프로세스 자동화"],
    "구매경쟁력": ["구매관리의 역할과 협력업체 관리", "신규업체 선정절차 및 평가 기준", "협력업체 납기관리 방안과 체크포인트", "정기평가의 중요성과 평가 방법"],
    "포괄임금제": ["포괄임금제 및 고정OT 약정과 노동법", "제도 도입 및 운영의 기초", "고정 OT 약정 적용 실무", "법률상 쟁점과 노무관리 쟁점"]
}

def get_curriculum_for_title(title, raw_content=None):
    if raw_content and str(raw_content).strip():
        lines = [line.strip('•\t- ') for line in str(raw_content).split('\n') if line.strip()]
        if lines:
            return lines
    for key, items in DEFAULT_CURRICULUM.items():
        if key in title:
            return items
    return ["기업 실무 맞춤형 전문 핵심 교육", "사례 분석 및 수강생 질의응답", "교육 수료 후 현장 적용 가이드 제공"]

def get_category_info(title, raw_cat=None):
    if raw_cat and str(raw_cat).strip():
        cat = str(raw_cat).strip()
        if "AI" in cat or "아카데미" in cat:
            return "인천AI아카데미", "AI 기술과 디지털 전환 시대에 대응하기 위해 기업 임직원 대상 실무 중심의 AI 활용 교육"
        return cat, "기업 현장에서 필요한 실무 중심 교육을 통해 임직원의 직무 전문성과 업무 역량 강화 지원"
    
    if "AI" in title or "아카데미" in title:
        return "인천AI아카데미", "AI 기술과 디지털 전환 시대에 대응하기 위해 기업 임직원 대상 실무 중심의 AI 활용 교육"
    return "사무관리분야 과정", "기업 현장에서 필요한 실무 중심 교육을 통해 임직원의 직무 전문성과 업무 역량 강화 지원"

def parse_course_date(date_str):
    if not date_str:
        return None
    s = str(date_str).strip()
    
    # 1. Full YYYY-MM-DD or YYYY.MM.DD
    m_full = re.search(r'(20\d{2})[.\/-]\s*(\d{1,2})[.\/-]\s*(\d{1,2})', s)
    if m_full:
        try:
            return datetime(int(m_full.group(1)), int(m_full.group(2)), int(m_full.group(3))).date()
        except:
            pass
            
    # 2. MM.DD or M.D (e.g. 9.17(목), 09.28, 9/17, 9월 17일)
    m_md = re.search(r'(\d{1,2})[.\/-월]\s*(\d{1,2})', s)
    if m_md:
        try:
            month = int(m_md.group(1))
            day = int(m_md.group(2))
            today = datetime.now().date()
            year = today.year
            return datetime(year, month, day).date()
        except:
            pass
            
    return None

def sort_courses_by_date(courses):
    today = datetime.now().date()
    
    def sort_key(course):
        c_date = parse_course_date(course.get('date', ''))
        if c_date:
            if c_date >= today:
                # Upcoming date (closest first): Priority 0, then by date ascending
                return (0, c_date)
            else:
                # Past date (placed after upcoming): Priority 1, then by date ascending
                return (1, c_date)
        else:
            # Unparseable date: Priority 2
            return (2, datetime.max.date())
            
    return sorted(courses, key=sort_key)

def get_active_courses():
    try:
        service, sheet_id = get_service()
        if not service:
            return None
        
        # Read from '교육목록' tab from A1 to Z
        result = service.spreadsheets().values().get(
            spreadsheetId=sheet_id, range='교육목록!A1:Z'
        ).execute()
        
        values = result.get('values', [])
        if not values:
            return []

        # Locked Column Mapping based on Google Sheet '교육목록' specifications:
        # A(0): 교육명, B(1): 교육일정, C(2): 강사, D(3): 시간, E(4): 장소, F(5): 회원가, G(6): 비회원가, H(7): 상세URL, I(8): 상태
        idx_title = 0
        idx_date = 1
        idx_instructor = 2
        idx_time = 3
        idx_location = 4
        idx_member_fee = 5
        idx_non_member_fee = 6
        idx_link = 7
        idx_status = 8

        start_row = 0
        if len(values) > 0:
            header_row = [str(cell).strip() for cell in values[0]]
            if any('교육' in cell or '제목' in cell or '강사' in cell or '회원' in cell for cell in header_row):
                start_row = 1

        courses = []
        for i, row in enumerate(values[start_row:]):
            if len(row) > idx_title:
                title = str(row[idx_title]).strip()
                if not title or title == '제목' or title.startswith('교육명'):
                    continue

                date = str(row[idx_date]).strip() if len(row) > idx_date else ''
                instructor = str(row[idx_instructor]).strip() if len(row) > idx_instructor else ''
                time_str = str(row[idx_time]).strip() if len(row) > idx_time else ''
                location = str(row[idx_location]).strip() if len(row) > idx_location else ''
                
                member_fee = parse_fee(row[idx_member_fee], 0) if len(row) > idx_member_fee else 0
                non_member_fee = parse_fee(row[idx_non_member_fee], 0) if len(row) > idx_non_member_fee else 0
                link = str(row[idx_link]).strip() if len(row) > idx_link else '#'

                raw_status = str(row[idx_status]).strip() if len(row) > idx_status else ''
                if not raw_status:
                    row_text = " ".join(str(c) for c in row)
                    status = '마감' if ('마감' in row_text or '종료' in row_text) else '접수중'
                else:
                    status = '마감' if ('마감' in raw_status or '종료' in raw_status) else '접수중'

                clean_date = re.sub(r'^[\[\s]+|[\]\s]+$', '', date) if date else ''

                category, cat_subtitle = get_category_info(title, row[9] if len(row) > 9 else None)
                curriculum = get_curriculum_for_title(title, row[10] if len(row) > 10 else None)

                courses.append({
                    "id": i + 1,
                    "title": title,
                    "name": title,
                    "status": status,
                    "date": clean_date,
                    "time": time_str,
                    "location": location or '인천상공회의소 교육장',
                    "instructor": instructor or '담당 강사',
                    "memberFee": member_fee,
                    "nonMemberFee": non_member_fee,
                    "category": category,
                    "categorySubtitle": cat_subtitle,
                    "curriculum": curriculum,
                    "link": link,
                    "detailUrl": link
                })
        return sort_courses_by_date(courses)
    except Exception as e:
        print(f"Error fetching active courses from sheet: {e}")
        return None

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'incheon_chamber_secret_2026')

# Toss Payments keys
TOSS_CLIENT_KEY = os.environ.get('TOSS_CLIENT_KEY', 'test_ck_BX7zk2yd8yOPGqPq5QzpVx9POLqK')
TOSS_SECRET_KEY = os.environ.get('TOSS_SECRET_KEY', 'test_sk_d46qopOB89RJQwq1wNod3ZmM75y0')

@app.route('/')
def index():
    return redirect(url_for('education_form'))

@app.route('/api/courses')
def api_courses():
    courses = get_active_courses()
    if courses is None:
        return jsonify({'success': False, 'message': 'Failed to fetch courses'}), 500
    return jsonify({'success': True, 'courses': courses})

@app.route('/education-form')
def education_form():
    order_id = str(uuid.uuid4())
    courses = get_active_courses()
    if not courses:
        courses = [
            { "id": 1, "name": "연결된 교육 과정이 없습니다 (시트 확인 필요)", "memberFee": 0, "nonMemberFee": 0 }
        ]
    return render_template('education_form.html', clientKey=TOSS_CLIENT_KEY, orderId=order_id, initialCourses=courses)

@app.route('/api/save-application', methods=['POST'])
def save_application():
    data = request.json
    order_id = data.get('orderId')
    if not order_id:
        return jsonify({'error': 'Missing orderId'}), 400
    
    # Store application info in session tied to orderId
    session[f'app_{order_id}'] = {
        'courseName': data.get('courseName'),
        'companyInfo': data.get('companyInfo'),
        'participants': data.get('participants'),
        'totalPrice': data.get('totalPrice')
    }
    return jsonify({'success': True})

@app.route('/api/verify-member', methods=['POST'])
def verify_member():
    data = request.json or {}
    business_no = data.get('businessNo', '')
    is_member = check_is_member(business_no)
    return jsonify({
        'success': True,
        'isMember': is_member,
        'message': '회원사 판별 완료' if is_member else '비회원사 판별 완료'
    })

@app.route('/api/submit-application', methods=['POST'])
def api_submit_application():
    try:
        data = request.json or {}
        order_id = data.get('orderId')
        company_info = data.get('companyInfo') or {}
        business_no = company_info.get('businessNo') or data.get('businessNo') or ''
        course_name = data.get('courseName') or ''
        course_id = data.get('courseId')
        participants = data.get('participants') or []
        participant_count = len(participants) if participants else 1

        company_name = company_info.get('companyName') or data.get('companyName') or ''
        applicant_name = ''
        if participants and isinstance(participants, list) and len(participants) > 0:
            applicant_name = participants[0].get('name', '')
        if not applicant_name:
            applicant_name = data.get('applicantName', '신청자')

        # 1. Automatic Member Verification via Google Sheet '회원사목록'
        is_member = False
        try:
            is_member = check_is_member(business_no)
        except Exception as member_err:
            print(f"[MemberCheck] Warning: {member_err}")
            is_member = False

        # 2. Calculate Final Payment Amount
        courses = get_active_courses() or []
        selected_course = None
        if course_id is not None:
            selected_course = next((c for c in courses if c['id'] == course_id), None)
        if not selected_course and course_name:
            selected_course = next((c for c in courses if c['name'] == course_name), None)
        if not selected_course and courses:
            selected_course = courses[0]

        unit_fee = 77000 if is_member else 176000
        if selected_course:
            unit_fee = selected_course['memberFee'] if is_member else selected_course['nonMemberFee']
            if not course_name:
                course_name = selected_course['name']

        total_amount = unit_fee * participant_count if isinstance(unit_fee, int) else 0

        # 3. Store Application Record to Google Sheet (2026_교육신청현황)
        submit_data = {
            'companyName': company_name,
            'businessNo': business_no,
            'applicantName': applicant_name,
            'courseName': course_name,
            'orderId': order_id,
            'isMember': is_member,
            'amount': total_amount
        }
        app_id, error = submit_application(submit_data)

        if not app_id:
            return jsonify({'success': False, 'message': f'신청 저장 실패: {error}'}), 500

        # 4. Save Session Data for Toss Payment Confirmation Callback
        if order_id:
            session[f'app_{order_id}'] = {
                'courseName': course_name,
                'companyInfo': {
                    'companyName': company_name,
                    'businessNo': business_no,
                    'isMember': is_member
                },
                'participants': participants,
                'totalPrice': total_amount,
                'applicationId': app_id
            }

        order_name = f"[{course_name}] ({participant_count}명)"
        return jsonify({
            'success': True,
            'isMember': is_member,
            'is_member': is_member,
            'amount': total_amount,
            'orderId': order_id,
            'orderName': order_name,
            'applicationId': app_id,
            'message': '회원사 할인 적용 완료' if is_member else '비회원가 적용 완료'
        })
    except Exception as e:
        import traceback
        print(f"[SubmitError] {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'신청 접수 처리 중 오류가 발생했습니다: {str(e)}'
        }), 500

@app.route('/api/check-status/<app_id>')
def api_check_status(app_id):
    status = get_application_status(app_id)
    if status is None:
        return jsonify({'success': False, 'status': 'NOT_FOUND'}), 404
    return jsonify({'success': True, 'status': status})

@app.route('/success')
def success():
    payment_key = request.args.get('paymentKey')
    order_id = request.args.get('orderId')
    amount = request.args.get('amount')

    if not payment_key or not order_id or not amount:
        return render_template('fail.html', message='Invalid Request', code='MISSING_PARAMS')

    # Retrieve stored application info
    app_data = session.get(f'app_{order_id}')
    
    print(f"Confirming payment: orderId={order_id}, amount={amount}")

    try:
        # Confirm payment with Toss API
        response = requests.post(
            'https://api.tosspayments.com/v1/payments/confirm',
            json={
                'paymentKey': payment_key,
                'orderId': order_id,
                'amount': int(amount)
            },
            auth=(TOSS_SECRET_KEY, ''),
            headers={'Content-Type': 'application/json'}
        )
        response.raise_for_status()
        payment_data = response.json()

        print(f"Payment confirmed: {payment_data['orderName']}")

        # Prepare record data
        record_info = {
            'orderId': payment_data['orderId'],
            'amount': payment_data['totalAmount'],
            'orderName': payment_data['orderName'],
            'approvedAt': payment_data['approvedAt'],
            'method': payment_data['method']
        }

        # Add detailed info if available
        if app_data:
            record_info['companyName'] = app_data['companyInfo'].get('companyName')
            participant_names = [p.get('name') for p in app_data['participants']]
            record_info['applicant'] = ", ".join(participant_names)
            record_info['participants_count'] = len(app_data['participants'])

        # Record to Google Sheets
        record_payment(record_info)

        return render_template('success.html', 
                             orderId=order_id, 
                             orderName=payment_data['orderName'],
                             amount=amount)

    except requests.exceptions.RequestException as e:
        error_msg = "Payment Confirmation Failed"
        error_code = "UNKNOWN_ERROR"
        if e.response is not None:
            try:
                error_response = e.response.json()
                error_msg = error_response.get('message', error_msg)
                error_code = error_response.get('code', error_code)
            except:
                pass
        print(f"Payment Confirm Error: {error_msg}")
        return render_template('fail.html', message=error_msg, code=error_code)

@app.route('/fail')
def fail():
    message = request.args.get('message', 'Unknown Error')
    code = request.args.get('code', 'UNKNOWN')
    return render_template('fail.html', message=message, code=code)

@app.route('/receipt')
def receipt():
    order_id = request.args.get('orderId')
    app_data = session.get(f'app_{order_id}')
    if not app_data:
        return "Receipt not found", 404
    
    return render_template('receipt.html', 
                          orderId=order_id,
                          courseName=app_data.get('courseName', 'N/A'),
                          companyName=app_data['companyInfo'].get('companyName'),
                          participants=app_data['participants'],
                          totalPrice=app_data['totalPrice'],
                          date=datetime.now().strftime('%Y-%m-%d'))

@app.route('/public/<path:filename>')
def serve_public(filename):
    return send_from_directory('public', filename)

if __name__ == '__main__':
    print("Starting Flask server on http://localhost:5000")
    app.run(debug=True, use_reloader=False, port=5000)
