from flask import Flask, render_template, request, send_from_directory, jsonify, session, redirect, url_for
import os
import uuid
import requests
import base64
from datetime import datetime
from utils_google import record_payment, submit_application, get_application_status, get_service
from dotenv import load_dotenv

load_dotenv()

def get_active_courses():
    try:
        service, sheet_id = get_service()
        if not service:
            return None
        
        # Read from '교육목록' tab
        result = service.spreadsheets().values().get(
            spreadsheetId=sheet_id, range='교육목록!A2:C'
        ).execute()
        
        values = result.get('values', [])
        courses = []
        for i, row in enumerate(values):
            if len(row) >= 2:
                title = row[0]
                date = row[1]
                
                # Exclude specific keywords from showing up in the form
                if '교육훈련과정 안내' in title or 'FTA' in title:
                    continue
                
                member_fee = 77000
                non_member_fee = 176000
                
                if "무료" in title:
                    member_fee = 0
                    non_member_fee = 0
                elif "연말정산" in title:
                    member_fee = 55000
                    non_member_fee = 132000
                
                courses.append({
                    "id": i + 1,
                    "name": f"{title} ({date})",
                    "memberFee": member_fee,
                    "nonMemberFee": non_member_fee,
                    "link": row[2] if len(row) > 2 else "#"
                })
        return courses
    except Exception as e:
        print(f"Error fetching active courses: {e}")
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
    data = request.json
    # data: companyName, businessNo, applicantName, courseName, orderId
    app_id, error = submit_application(data)
    if app_id:
        return jsonify({'success': True, 'applicationId': app_id})
    else:
        return jsonify({'success': False, 'message': f'Failed to save application: {error}'}), 500

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
