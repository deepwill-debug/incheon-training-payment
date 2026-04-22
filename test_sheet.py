import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv

# Load env
load_dotenv()

def test_google_sheets():
    print("=== Google Sheets Connection Test ===")
    
    sheet_id = os.environ.get('GOOGLE_SHEET_ID')
    service_account_json = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
    
    print(f"Sheet ID: {sheet_id}")
    
    if not sheet_id or not service_account_json:
        print("Error: Missing environment variables.")
        return

    try:
        # Load credentials
        info = json.loads(service_account_json)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/spreadsheets']
        )
        service = build('sheets', 'v4', credentials=creds)
        
        # 1. Try to read the first row
        sheet_range = '2026_교육신청현황!A1:J1'
        print(f"\nChecking sheet range: {sheet_range}...")
        
        try:
            result = service.spreadsheets().values().get(
                spreadsheetId=sheet_id, range=sheet_range
            ).execute()
            values = result.get('values', [])
        except Exception as e:
            if 'not found' in str(e).lower() or 'parse' in str(e).lower():
                print(f"Sheet '2026_교육신청현황' not found. We will attempt to use the first sheet.")
                # Get spreadsheet details to find the first sheet name
                spreadsheet = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
                sheet_name = spreadsheet['sheets'][0]['properties']['title']
                print(f"Found sheet name: {sheet_name}")
                sheet_range = f"'{sheet_name}'!A1:J1"
                result = service.spreadsheets().values().get(
                    spreadsheetId=sheet_id, range=sheet_range
                ).execute()
                values = result.get('values', [])
            else:
                raise e

        # Define required header
        required_header = ["신청번호", "신청일시", "업체명", "사업자번호", "성명", "교육명", "상태", "금액", "결제수단", "주문번호"]
        
        if not values or not values[0]:
            print("Status: Sheet is empty. Creating headers...")
            body = {'values': [required_header]}
            service.spreadsheets().values().update(
                spreadsheetId=sheet_id, range=sheet_range,
                valueInputOption='USER_ENTERED', body=body
            ).execute()
            print("Success: Headers created.")
        else:
            print(f"Status: Found existing header: {values[0]}")
            if values[0][0] != "신청번호":
                print("Warning: First column header is not '신청번호'. Check your sheet structure.")
            else:
                print("Status: Header looks correct.")

        print("\n=== Test Final Result: SUCCESS ===")
        print("The system can connect and write to the Google Sheet.")

    except Exception as e:
        print(f"\n=== Test Final Result: FAILED ===")
        print(f"Error details: {str(e)}")
        if "403" in str(e):
            print("\nHint: Please make sure you shared the sheet with the service account email:")
            print(f"Email: {info.get('client_email')}")

if __name__ == "__main__":
    test_google_sheets()
