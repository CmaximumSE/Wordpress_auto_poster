# publish_min.py
import os, json, textwrap
import httpx
from dotenv import load_dotenv

load_dotenv()
WP_SITE = os.getenv("WP_SITE")

API_BASE = "https://public-api.wordpress.com/rest/v1.1"

def load_token():
    with open("wp_token.json", "r", encoding="utf-8") as f:
        return json.load(f)["access_token"]

def simple_summarize(raw: str):
    title = raw.strip().split("\n")[0][:60] or "자동 생성 제목"
    excerpt = (raw.strip().replace("\n", " ")[:140] + "...") if len(raw) > 140 else raw.strip()

    body_text = raw.strip().replace("\n", "<br/>")  # ← f-string 밖에서 처리

    body = textwrap.dedent(f"""
    <h2>{title}</h2>
    <p>{excerpt}</p>
    <hr />
    <div>
      <p>{body_text}</p>
    </div>
    """).strip()
    return title, excerpt, body


def create_post(raw_text: str, status="draft", tags=None, categories=None, slug=None):
    access_token = load_token()
    headers = {"Authorization": f"Bearer {access_token}"}

    title, excerpt, content_html = simple_summarize(raw_text)

    payload = {
        "title": title,
        "content": content_html,
        "excerpt": excerpt,
        "status": status,       # "draft" | "publish" | "future"
        "slug": slug,
        "tags": tags or [],     # ["tag1","tag2"]
        "categories": categories or [],  # ["cat1","cat2"]
    }

    url = f"{API_BASE}/sites/{WP_SITE}/posts/new"
    with httpx.Client(timeout=30) as client:
        r = client.post(url, headers=headers, data=payload)
        r.raise_for_status()
        return r.json()

if __name__ == "__main__":
    # 여기에 올리고 싶은 원문 입력
    RAW = """나이아가라 당일치기 여행 메모.
- 가는 법/비용 정리
- 겨울 경치 포인트
- 브이로그 마무리 멘트 후보 등
"""
    res = create_post(RAW, status="publish", tags=["vlog","toronto"], categories=["일상"])
    print("Post created:")
    print(json.dumps({"ID": res.get("ID"), "URL": res.get("URL"), "status": res.get("status")}, ensure_ascii=False, indent=2))
