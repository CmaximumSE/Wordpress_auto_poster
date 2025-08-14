# auth_wpcom.py
import json, urllib.parse, http.server, socketserver, threading
import httpx, os
from dotenv import load_dotenv

load_dotenv()
CLIENT_ID = os.getenv("WP_CLIENT_ID")
CLIENT_SECRET = os.getenv("WP_CLIENT_SECRET")
REDIRECT_URI = os.getenv("WP_REDIRECT_URI")

AUTH_URL = "https://public-api.wordpress.com/oauth2/authorize"
TOKEN_URL = "https://public-api.wordpress.com/oauth2/token"

PORT = 8765
received_code = {"code": None}

class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/callback"):
            qs = urllib.parse.urlparse(self.path).query
            code = dict(urllib.parse.parse_qsl(qs)).get("code")
            received_code["code"] = code
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Authorization code received. You can close this window.")
        else:
            self.send_response(404)
            self.end_headers()

def start_server():
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        httpd.timeout = 300
        while received_code["code"] is None:
            httpd.handle_request()

def main():
    # 1) 권한 요청 URL 출력
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "global",
    }
    url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    print("Open this URL in your browser and authorize:\n", url)

    # 2) 임시 콜백 서버 가동
    th = threading.Thread(target=start_server, daemon=True)
    th.start()

    # 3) code 수신 대기
    th.join()

    code = received_code["code"]
    if not code:
        raise SystemExit("No code received.")

    # 4) code -> access_token 교환
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
        "code": code,
    }
    with httpx.Client(timeout=30) as client:
        r = client.post(TOKEN_URL, data=data)
        r.raise_for_status()
        token = r.json()
        print("Token:", token)

    with open("wp_token.json", "w", encoding="utf-8") as f:
        json.dump(token, f, ensure_ascii=False, indent=2)
    print("Saved to wp_token.json")

if __name__ == "__main__":
    main()
