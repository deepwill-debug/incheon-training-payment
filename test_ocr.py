import requests
from bs4 import BeautifulSoup
import re

def test_ocr():
    # 1. Fetch event list to find "절세"
    url = "https://incheon.korcham.net/front/event/eventListPage.do"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    data = {"miv_pageSize": "100", "miv_pageNo": "1"}
    
    print("Fetching event list...")
    resp = requests.post(url, headers=headers, data=data, timeout=10)
    soup = BeautifulSoup(resp.text, 'html.parser')
    rows = soup.select('tbody tr')
    
    target_link = None
    target_title = None
    for row in rows:
        title_tag = row.select_one('td.title a')
        if title_tag:
            title = title_tag.get_text(strip=True)
            if '절세' in title:
                onclick = title_tag.get('href', '')
                event_id = "".join(filter(str.isdigit, onclick))
                target_link = f"https://incheon.korcham.net/front/event/eventView.do?eventId={event_id}"
                target_title = title
                break
                
    if not target_link:
        print("Could not find '절세' course. Testing the first available course instead.")
        title_tag = rows[0].select_one('td.title a')
        onclick = title_tag.get('href', '')
        event_id = "".join(filter(str.isdigit, onclick))
        target_link = f"https://incheon.korcham.net/front/event/eventView.do?eventId={event_id}"
        target_title = title_tag.get_text(strip=True)

    print(f"\nTarget Course: {target_title}")
    print(f"Link: {target_link}")
    
    # 2. Fetch detail page and find image
    detail_resp = requests.get(target_link, headers=headers, timeout=10)
    detail_soup = BeautifulSoup(detail_resp.text, 'html.parser')
    content_div = detail_soup.select_one('.boardveiw') or detail_soup.select_one('.contents_detail') or detail_soup
    imgs = content_div.select('img')
    img_url = None
    print("\nAll images found:")
    for img in imgs:
        src = img.get('src')
        if src:
            print(src)
            if not src.endswith('.gif') and 'home.png' not in src and 'btn' not in src:
                # clean up /../.. from src
                clean_src = re.sub(r'^(/(\.\./)+)', '/', src)
                img_url = clean_src if clean_src.startswith('http') else "https://incheon.korcham.net" + clean_src
                break
    
    # 3. Test OCR using OCR.space Free API
    print("Sending image to OCR.space API for testing...")
    ocr_api_url = "https://api.ocr.space/parse/image"
    ocr_payload = {
        'apikey': 'helloworld',
        'url': img_url,
        'language': 'kor',
        'scale': 'true',
        'isTable': 'true'
    }
    
    ocr_resp = requests.post(ocr_api_url, data=ocr_payload)
    ocr_data = ocr_resp.json()
    
    if ocr_data.get('IsErroredOnProcessing'):
        print(f"OCR API Error: {ocr_data.get('ErrorMessage')}")
        return
        
    parsed_results = ocr_data.get('ParsedResults', [])
    if not parsed_results:
        print("No text found in image.")
        return
        
    text = parsed_results[0].get('ParsedText', '')
    print("\n--- Extracted Text ---")
    with open('ocr_result.txt', 'w', encoding='utf-8') as f:
        f.write(text)
    print("Text saved to ocr_result.txt")
    print("----------------------\n")
    
    # 4. Run regex logic
    text_no_space = text.replace(' ', '')
    member_match = re.search(r'(?<!비)회원.*?(\d{1,3}(?:,\d{3})*|\d{4,})원', text_no_space)
    non_member_match = re.search(r'비회원.*?(\d{1,3}(?:,\d{3})*|\d{4,})원', text_no_space)
    
    member_fee = member_match.group(1).replace(',', '') if member_match else '확인 필요'
    non_member_fee = non_member_match.group(1).replace(',', '') if non_member_match else '확인 필요'
    
    print(f"Extracted Member Fee: {member_fee}")
    print(f"Extracted Non-Member Fee: {non_member_fee}")

if __name__ == '__main__':
    test_ocr()
