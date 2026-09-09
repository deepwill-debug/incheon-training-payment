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

def parse_fee(fee_val, default_val):
    if fee_val is None:
        return default_val
    s = str(fee_val).strip()
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

def get_active_courses():
    try:
        service, sheet_id = get_service()
        if not service:
            return None
        
        # Read from '교육목록' tab
        result = service.spreadsheets().values().get(
            spreadsheetId=sheet_id, range='교육목록!A2:Z'
        ).execute()
        
        values = result.get('values', [])
        courses = []
        for i, row in enumerate(values):
            if len(row) >= 1:
                title = str(row[0]).strip()
                if not title or title == '제목' or title.startswith('교육명'):
                    continue

                raw_status = str(row[1]).strip() if len(row) > 1 else '접수중'
                status = '마감' if ('마감' in raw_status or '종료' in raw_status) else '접수중'
                
                date = str(row[2]).strip() if len(row) > 2 else ''
                time_str = str(row[3]).strip() if len(row) > 3 else ''
                location = str(row[4]).strip() if len(row) > 4 else ''
                instructor = str(row[5]).strip() if len(row) > 5 else ''

                if len(row) >= 8:
                    member_fee = parse_fee(row[6], 0)
                    non_member_fee = parse_fee(row[7], 0)
                    link = str(row[8]).strip() if len(row) > 8 else '#'
                else:
                    member_fee = parse_fee(row[4], 0) if len(row) > 4 else 0
                    non_member_fee = parse_fee(row[5], 0) if len(row) > 5 else 0
                    link = str(row[7]).strip() if len(row) > 7 else '#'

                category, cat_subtitle = get_category_info(title, row[9] if len(row) > 9 else None)
                curriculum = get_curriculum_for_title(title, row[10] if len(row) > 10 else None)

                courses.append({
                    "id": i + 1,
                    "title": title,
                    "name": f"{title} ({date})" if date else title,
                    "status": status,
                    "date": date,
                    "time": time_str,
                    "location": location or '인천상공회의소 3층 교육장',
                    "instructor": instructor or '전문 강사',
                    "memberFee": member_fee,
                    "nonMemberFee": non_member_fee,
                    "category": category,
                    "categorySubtitle": cat_subtitle,
                    "curriculum": curriculum,
                    "link": link,
                    "detailUrl": link
                })
        return courses
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
    data = request.json
    business_no = data.get('businessNo')
    
    # Internal API URLs (accessible only via VPN)
    list_url = "https://kccicrm.korcham.net/member/memberList.do"
    view_url = "https://kccicrm.korcham.net/member/memberView.do"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    try:
        from bs4 import BeautifulSoup
        
        # 1. Search for member by business number
        params = {'pageIndex': '1', 'searchCnd': '2', 'searchWrd': business_no} # Assuming searchCnd 2 is for Business No
        
        # Bypass system proxies to ensure VPN interface is used if applicable
        # verify=False for internal certs
        # allow_redirects=False to detect auth redirection (gw.korcham.net)
        response = requests.post(
            list_url, 
            data=params, 
            headers=headers, 
            proxies={'http': None, 'https': None}, 
            verify=False, 
            timeout=10,
            allow_redirects=False
        )
        
        # Check if redirected (Login required)
        if response.status_code in [301, 302]:
            redirect_url = response.headers.get('Location', '')
            if 'gw.korcham.net' in redirect_url or 'login' in redirect_url:
                print(f"[InternalAPI] Redirected to login: {redirect_url}")
                return jsonify({
                    'success': False,
                    'code': 'AUTH_REQUIRED',
                    'message': '내부망 로그인 필요 (세션이 없거나 만료됨)'
                }), 401
            # If redirected elsewhere, follow manually or error? 
            # Ideally we stop here.
            
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find the specific member row/link
        # Assuming the first result is correct or checking exact match if possible
        # Look for a link like "fn_egov_view('ID')" or similar in href/onclick
        list_table = soup.find('table', {'class': 'board_list'}) # Hypothetical class
        target_link = None
        
        if list_table:
            rows = list_table.find_all('tr')
            for row in rows:
                cols = row.find_all('td')
                # Assuming business number is in one of the columns
                if any(business_no in col.get_text() for col in cols):
                    # Found row, extract ID or link
                    link = row.find('a')
                    if link:
                        href = link.get('href', '')
                        onclick = link.get('onclick', '')
                        # Extract ID from javascript:fn_egov_view('MEM_ID') logic
                        import re
                        match = re.search(r"['\"](\w+)['\"]", onclick) or re.search(r"id=(\w+)", href)
                        if match:
                            target_id = match.group(1)
                            target_link = f"{view_url}?memberId={target_id}" # Hypothetical param
                            break
        
        # If we can't find a direct link, fallback to text search only (original logic)
        if not target_link:
             # Fallback: Just return true if business number is found in the list text
             is_member_simple = business_no in response.text
             return jsonify({
                 'success': True,
                 'isMember': is_member_simple,
                 'message': '확인 완료 (단순 조회)' if is_member_simple else '회원 정보 없음'
             })

        # 2. Fetch Member Detail Page to check Dues
        detail_resp = requests.post(
            target_link, 
            headers=headers, 
            proxies={'http': None, 'https': None}, 
            verify=False, 
            timeout=10
        )
        detail_soup = BeautifulSoup(detail_resp.text, 'html.parser')
        
        # 3. Parse Dues History Table
        # Look for table with "회비내역" or similar keywords
        # Columns often: Year, Term, Amount, Date
        dues_table = None
        tables = detail_soup.find_all('table')
        for tbl in tables:
            if "회비" in tbl.get_text() or "납입" in tbl.get_text():
                dues_table = tbl
                break

        is_paid_member = False
        if dues_table:
            # Check recent year/term
            current_year = datetime.now().year
            
            rows = dues_table.find_all('tr')[1:] # Skip header
            history = []
            
            for r in rows:
                cols = r.find_all('td')
                if len(cols) >= 3:
                    try:
                        year_text = cols[0].get_text(strip=True) # e.g. 2025
                        term_text = cols[1].get_text(strip=True) # e.g. 1기
                        amount_text = cols[2].get_text(strip=True).replace(',', '').replace('원', '')
                        
                        year = int(re.search(r'\d{4}', year_text).group()) if re.search(r'\d{4}', year_text) else 0
                        amount = int(amount_text) if amount_text.isdigit() else 0
                        
                        if amount > 0:
                            history.append({'year': year, 'amount': amount})
                    except:
                        continue
            
            # Simple Logic: Paid in current or last year
            history.sort(key=lambda x: x['year'], reverse=True)
            if history and history[0]['year'] >= current_year - 1:
                is_paid_member = True

        return jsonify({
            'success': True,
            'isMember': is_paid_member, 
            'message': '회원사 (회비 납부 확인)' if is_paid_member else '회비 미납 또는 정보 없음'
        })
        
    except requests.exceptions.ConnectionError as e:
        print(f"[InternalAPI] Connection Failed: {e}")
        return jsonify({
            'success': False,
            'code': 'VPN_ERROR',
            'message': f'내부망 연결 확인 필요: {str(e)}'
        }), 503
    except requests.exceptions.Timeout as e:
        print(f"[InternalAPI] Timeout: {e}")
        return jsonify({
            'success': False, 
            'code': 'TIMEOUT', 
            'message': '내부망 연결 시간 초과'
        }), 504
    except Exception as e:
        print(f"[InternalAPI] Error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

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
