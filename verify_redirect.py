import requests

def verify_redirect():
    url = "http://localhost:5000/"
    try:
        response = requests.get(url, allow_redirects=False)
        print(f"Status Code: {response.status_code}")
        print(f"Location Header: {response.headers.get('Location')}")
        
        if response.status_code == 302 and "/education-form" in response.headers.get('Location', ''):
            print("Redirect Verification: SUCCESS")
        else:
            print("Redirect Verification: FAILED")
    except Exception as e:
        print(f"Error connecting to server: {e}")

if __name__ == "__main__":
    verify_redirect()
