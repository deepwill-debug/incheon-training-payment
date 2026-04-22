import requests
from bs4 import BeautifulSoup
import os
import json
from datetime import datetime
from utils_google import get_service
from dotenv import load_dotenv

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
            
        # Date filtering
        # Dates look like YYYY.MM.DD or YYYY.MM.DD~YYYY.MM.DD
        try:
            end_date_str = date_str.split('~')[-1].strip()
            end_date = datetime.strptime(end_date_str, '%Y.%m.%d')
            
            if end_date < today.replace(hour=0, minute=0, second=0, microsecond=0):
                continue
        except Exception as e:
            print(f"Date parsing error for '{title}': {e}")
            # If date parse fails but it's '접수중', we might want to keep it? 
            # Usually keep it just in case.
            pass
            
        courses.append({
            'title': title,
            'date': date_str,
            'link': link
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
            spreadsheetId=sheet_id, range=f"'{tab_name}'!A:C"
        ).execute()
        
        # 3. Write new data
        header = ["제목", "교육일정", "상세링크"]
        rows = [[c['title'], c['date'], c['link']] for c in courses]
        
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
