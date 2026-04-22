from google.oauth2 import service_account
from googleapiclient.discovery import build
import os
import json
from datetime import datetime

def record_payment(payment_data):
    try:
        sheet_id = os.environ.get('GOOGLE_SHEET_ID')
        if not sheet_id:
            print('No GOOGLE_SHEET_ID in environment. Skipping Google Sheet recording.')
            print('Data to be recorded:', payment_data)
            return

        # Prepare credentials
        # 1. Check for env var with JSON content
        # 2. Check for service-account.json file path
        creds = None
        service_account_info = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
        
        if service_account_info:
            info = json.loads(service_account_info)
            creds = service_account.Credentials.from_service_account_info(
                info, scopes=['https://www.googleapis.com/auth/spreadsheets']
            )
        else:
            key_file = os.environ.get('GOOGLE_SERVICE_ACCOUNT_KEY_PATH', 'service-account.json')
            if os.path.exists(key_file):
                creds = service_account.Credentials.from_service_account_file(
                    key_file, scopes=['https://www.googleapis.com/auth/spreadsheets']
                )
            else:
                 print('No credentials found. Skipping Google Sheet recording.')
                 return

        service = build('sheets', 'v4', credentials=creds)

        # Prepare values
        # Date, Course Name, Applicant, Company Name, Amount, Method, Order ID
        date_str = datetime.fromisoformat(payment_data['approvedAt'].replace('Z', '+00:00')).strftime('%Y-%m-%d %H:%M:%S')
        values = [[
            date_str,
            payment_data['orderName'],
            payment_data.get('applicant', 'N/A'),
            payment_data.get('companyName', 'N/A'),
            payment_data['amount'],
            payment_data['method'],
            payment_data['orderId']
        ]]

        body = {
            'values': values
        }

        result = service.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range='2026_교육신청현황!A:G',
            valueInputOption='USER_ENTERED',
            body=body
        ).execute()

        print(f"{result.get('updates').get('updatedCells')} cells appended to Google Sheet.")

    except Exception as e:
        print(f"Failed to record to Google Sheet: {e}")

# Local Fallback path
LOCAL_DB_PATH = 'applications_local_db.json'

def load_local_db():
    if os.path.exists(LOCAL_DB_PATH):
        try:
            with open(LOCAL_DB_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_local_db(data):
    try:
        with open(LOCAL_DB_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Failed to save local DB: {e}")

def get_service():
    sheet_id = os.environ.get('GOOGLE_SHEET_ID')
    # If no sheet ID, return None to trigger fallback
    if not sheet_id:
        return None, None

    creds = None
    service_account_info = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
    
    if service_account_info:
        try:
            info = json.loads(service_account_info)
            creds = service_account.Credentials.from_service_account_info(
                info, scopes=['https://www.googleapis.com/auth/spreadsheets']
            )
        except:
            pass
    else:
        key_file = os.environ.get('GOOGLE_SERVICE_ACCOUNT_KEY_PATH', 'service-account.json')
        if os.path.exists(key_file):
            try:
                creds = service_account.Credentials.from_service_account_file(
                    key_file, scopes=['https://www.googleapis.com/auth/spreadsheets']
                )
            except:
                pass
    
    if not creds:
        return None, None

    service = build('sheets', 'v4', credentials=creds)
    return service, sheet_id

def submit_application(data):
    unique_id = None
    try:
        # DB Structure: { 'YYYYMMDD-001': { data..., status: '대기' } }
        
        # 1. Try Google Sheets
        service, sheet_id = get_service()
        
        if service:
            # Generate ID: YYYYMMDD-HHMMSS (Simple unique ID)
            today_str = datetime.now().strftime('%Y%m%d')
            unique_id = f"{today_str}-{datetime.now().strftime('%H%M%S')}" 
            
            # Try to make it -001 style
            try:
                result = service.spreadsheets().values().get(
                    spreadsheetId=sheet_id, range='2026_교육신청현황!A:A'
                ).execute()
                rows = result.get('values', [])
                count = sum(1 for row in rows if row and row[0].startswith(today_str))
                unique_id = f"{today_str}-{count + 1:03d}"
            except:
                pass

            # Prepare Row
            row = [
                unique_id,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                data.get('companyName'),
                data.get('businessNo'),
                data.get('applicantName'),
                data.get('courseName'),
                '대기', # Status
                0,      # Amount
                '',     # Method
                data.get('orderId')
            ]

            service.spreadsheets().values().append(
                spreadsheetId=sheet_id,
                range='2026_교육신청현황!A:J',
                valueInputOption='USER_ENTERED',
                body={'values': [row]}
            ).execute()
            
            return unique_id, None

    except Exception as e:
        print(f"Google Sheet Submit Error: {e}")
        # Proceed to fallback

    # 2. Local Fallback
    print("Using Local JSON Fallback for Application Storage")
    db = load_local_db()
    
    today_str = datetime.now().strftime('%Y%m%d')
    if not unique_id:
        count = sum(1 for k in db.keys() if k.startswith(today_str))
        unique_id = f"{today_str}-{count + 1:03d}"
    
    db[unique_id] = {
        'id': unique_id,
        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'companyName': data.get('companyName'),
        'businessNo': data.get('businessNo'),
        'applicantName': data.get('applicantName'),
        'courseName': data.get('courseName'),
        'status': '대기',
        'amount': 0,
        'orderId': data.get('orderId')
    }
    save_local_db(db)
    
    return unique_id, None

def get_application_status(app_id):
    # 1. Try Google Sheets
    try:
        service, sheet_id = get_service()
        if service:
            result = service.spreadsheets().values().get(
                spreadsheetId=sheet_id, range='2026_교육신청현황!A:G'
            ).execute()
            rows = result.get('values', [])
            for row in rows:
                if row and row[0] == app_id:
                    # Status is Col G (index 6)
                    return row[6] if len(row) > 6 else '대기'
    except:
        pass
        
    # 2. Local Fallback
    db = load_local_db()
    if app_id in db:
        return db[app_id].get('status', '대기')
        
    return None
