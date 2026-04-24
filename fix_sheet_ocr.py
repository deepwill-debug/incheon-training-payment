from utils_google import get_service
import requests
from bs4 import BeautifulSoup
import re
import time

def extract_fees_ocr_space(img_url):
    print(f"Running OCR.space for {img_url}")
    ocr_api_url = "https://api.ocr.space/parse/image"
    ocr_payload = {'apikey': 'helloworld', 'url': img_url, 'language': 'kor', 'scale': 'true', 'isTable': 'true'}
    try:
        ocr_resp = requests.post(ocr_api_url, data=ocr_payload, timeout=20)
        ocr_data = ocr_resp.json()
        if ocr_data.get('IsErroredOnProcessing'):
            print(f"OCR Error: {ocr_data.get('ErrorMessage')}")
            return None, None
        parsed = ocr_data.get('ParsedResults', [])
        if not parsed:
            return None, None
        text = parsed[0].get('ParsedText', '')
        text_no_space = text.replace(' ', '')
        member_match = re.search(r'(?<!비)회원.*?(\d{1,3}(?:,\d{3})*|\d{4,})원', text_no_space)
        non_member_match = re.search(r'비회원.*?(\d{1,3}(?:,\d{3})*|\d{4,})원', text_no_space)
        mf = member_match.group(1).replace(',', '') if member_match else None
        nmf = non_member_match.group(1).replace(',', '') if non_member_match else None
        return mf, nmf
    except Exception as e:
        print(e)
        return None, None

def fix_sheet():
    service, sheet_id = get_service()
    result = service.spreadsheets().values().get(spreadsheetId=sheet_id, range='교육목록!A2:E').execute()
    rows = result.get('values', [])
    
    headers = {"User-Agent": "Mozilla/5.0"}
    
    updated_rows = []
    for row in rows:
        title = row[0]
        date = row[1]
        link = row[2]
        mf = row[3] if len(row)>3 else '확인 필요'
        nmf = row[4] if len(row)>4 else '확인 필요'
        
        if mf == '확인 필요' and '무료' not in title:
            print(f"Fetching {title}")
            try:
                detail_resp = requests.get(link, headers=headers, timeout=10)
                detail_soup = BeautifulSoup(detail_resp.text, 'html.parser')
                content_div = detail_soup.select_one('.boardveiw') or detail_soup.select_one('.contents_detail') or detail_soup
                imgs = content_div.select('img')
                img_url = None
                for img in imgs:
                    src = img.get('src')
                    if src and not src.endswith('.gif') and 'home.png' not in src and 'btn' not in src:
                        clean_src = re.sub(r'^(/(\.\./)+)', '/', src)
                        img_url = clean_src if clean_src.startswith('http') else "https://incheon.korcham.net" + clean_src
                        break
                
                if img_url:
                    new_mf, new_nmf = extract_fees_ocr_space(img_url)
                    if new_mf: mf = new_mf
                    if new_nmf: nmf = new_nmf
                time.sleep(2) # rate limit
            except Exception as e:
                print(e)
                
        updated_rows.append([title, date, link, mf, nmf])
        
    # Write back
    body = {'values': updated_rows}
    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range='교육목록!A2:E',
        valueInputOption='USER_ENTERED',
        body=body
    ).execute()
    print("Done fixing sheet.")

if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv('.env')
    fix_sheet()
