import requests
from bs4 import BeautifulSoup
import os
import json
from datetime import datetime
from utils_google import get_service
from dotenv import load_dotenv
import re
from io import BytesIO
try:
    from PIL import Image
    import pytesseract
except ImportError:
    pass # Handled later if missing

def extract_fees_from_image(img_url):
    try:
        if 'pytesseract' not in globals():
            return None, None
        resp = requests.get(img_url, timeout=10)
        img = Image.open(BytesIO(resp.content))
        text = pytesseract.image_to_string(img, lang='kor+eng')
        
        text_no_space = text.replace(' ', '')
        member_match = re.search(r'(?<!비)회원.*?(\d{1,3}(?:,\d{3})*|\d{4,})원', text_no_space)
        non_member_match = re.search(r'비회원.*?(\d{1,3}(?:,\d{3})*|\d{4,})원', text_no_space)
        
        member_fee = member_match.group(1).replace(',', '') if member_match else None
        non_member_fee = non_member_match.group(1).replace(',', '') if non_member_match else None
        
        return member_fee, non_member_fee
    except Exception as e:
        print(f"OCR failed for {img_url}: {e}")
        return None, None


load_dotenv()

def scrape_incheon_korcham():
    url = "https://incheon.korcham.net/front/event/eventListPage.do"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    # Request 100 items to get all current ones
    data = {
        "miv_pageSize": "100",
        "miv_pageNo": "1"
    }
    
    print(f"[{datetime.now()}] Fetching courses from Incheon Korcham...")
    try:
        response = requests.post(url, headers=headers, data=data, timeout=10)
        response.raise_for_status()
    except Exception as e:
        print(f"Error fetching data: {e}")
        return []

    soup = BeautifulSoup(response.text, 'html.parser')
    rows = soup.select('tbody tr')
    
    courses = []
    today = datetime.now()
    
    for row in rows:
        title_tag = row.select_one('td.title a')
        if not title_tag:
            continue
            
        title = title_tag.get_text(strip=True)
        # Extract ID from javascript: eventView('20140338090')
        onclick = title_tag.get('href', '')
        event_id = "".join(filter(str.isdigit, onclick))
        link = f"https://incheon.korcham.net/front/event/eventView.do?eventId={event_id}"
        
        date_td = row.select('td')[1]
        date_str = date_td.get_text(strip=True)
        
        status_tag = row.select_one('div.btn4')
        status = status_tag.get_text(strip=True) if status_tag else ""
        
        # Only keep '접수중'
        if '접수중' not in status:
            continue

        # Exclude specific keywords
        exclude_keywords = ['교육훈련과정 안내', 'FTA', '설명회']
        if any(keyword in title for keyword in exclude_keywords):
            continue
            
        # Date filtering
        # Dates look like YYYY.MM.DD or YYYY.MM.DD~YYYY.MM.DD
        try:
            end_date_str = date_str.split('~')[-1].strip()
            end_date = datetime.strptime(end_date_str, '%Y.%m.%d')
            
            if end_date < today.replace(hour=0, minute=0, second=0, microsecond=0):
                continue
        except Exception as e:
            print(f"Date parsing error for '{title}': {e}")
            pass
            
        # Fetch fees
        member_fee_val = 77000
        non_member_fee_val = 176000
        if '무료' in title:
            member_fee_val = 0
            non_member_fee_val = 0
        else:
            try:
                detail_resp = requests.get(link, headers=headers, timeout=10)
                detail_soup = BeautifulSoup(detail_resp.text, 'html.parser')
                content_div = detail_soup.select_one('.view_cont') or detail_soup.select_one('.board_view') or detail_soup
                imgs = content_div.select('img')
                img_url = None
                for img in imgs:
                    src = img.get('src')
                    if src and not src.endswith('.gif'):
                        img_url = src if src.startswith('http') else "https://incheon.korcham.net" + src
                        break
                
                if img_url:
                    mf, nmf = extract_fees_from_image(img_url)
                    if mf: member_fee_val = mf
                    if nmf: non_member_fee_val = nmf
            except Exception as e:
                print(f"Detail fetch failed: {e}")
        
        courses.append({
            'title': title,
            'date': date_str,
            'link': link,
            'member_fee': member_fee_val,
            'non_member_fee': non_member_fee_val
        })
        
    print(f"Found {len(courses)} active courses.")
    return courses

def sync_to_google_sheet(courses):
    service, sheet_id = get_service()
    if not service or not sheet_id:
        print("Google Sheets service not available.")
        return False
        
    tab_name = "교육목록"
    
    try:
        # 1. Check if tab exists, if not create it
        spreadsheet = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
        sheets = [s['properties']['title'] for s in spreadsheet['sheets']]
        
        if tab_name not in sheets:
            print(f"Creating tab '{tab_name}'...")
            body = {
                'requests': [{
                    'addSheet': {
                        'properties': {'title': tab_name}
                    }
                }]
            }
            service.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body=body).execute()
            
        # 2. Clear existing data
        service.spreadsheets().values().clear(
            spreadsheetId=sheet_id, range=f"'{tab_name}'!A:E"
        ).execute()
        
        # 3. Write new data
        header = ["제목", "교육일정", "상세링크", "회원사 교육비", "비회원사 교육비"]
        rows = [[c['title'], c['date'], c['link'], c['member_fee'], c['non_member_fee']] for c in courses]
        
        body = {'values': [header] + rows}
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range=f"'{tab_name}'!A1",
            valueInputOption='USER_ENTERED',
            body=body
        ).execute()
        
        print(f"Successfully synced {len(courses)} courses to Google Sheet.")
        return True
    except Exception as e:
        print(f"Error syncing to Google Sheet: {e}")
        return False

if __name__ == "__main__":
    active_courses = scrape_incheon_korcham()
    if active_courses:
        sync_to_google_sheet(active_courses)
    else:
        print("No active courses found to sync.")
