# gemini_publish.py
import os, json, textwrap
from typing import Dict, Any
import httpx
from dotenv import load_dotenv

import google.generativeai as genai

import re

load_dotenv()

# --- 환경 변수 ---
WP_SITE = os.getenv("WP_SITE")                 # 예: maximum711.wordpress.com
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
API_BASE = "https://public-api.wordpress.com/rest/v1.1"

def _extract_json_block(text: str) -> str:
    """
    응답에서 가장 그럴듯한 JSON 블록만 추출.
    - 코드펜스 제거
    - 앞뒤 잡다한 설명 제거
    - 첫 '{'부터 마지막 '}'까지를 잘라서 반환
    """
    # 코드펜스 제거
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", t, count=1).rstrip("`").strip("`").strip()
    # 스마트 따옴표 -> 일반 따옴표
    t = (t.replace("\u201c", '"').replace("\u201d", '"')
           .replace("\u2018", "'").replace("\u2019", "'"))
    # 첫 '{'와 마지막 '}' 사이를 취함
    start = t.find("{")
    end = t.rfind("}")
    if start != -1 and end != -1 and end > start:
        return t[start:end+1]
    return t  # 차선

def _sanitize_json(text: str) -> str:
    """
    JSON 파싱 전에 자잘한 문법 오류를 정리.
    - trailing comma 제거
    - BOM/제어문자 제거
    """
    t = _extract_json_block(text)
    # 제어문자 제거
    t = "".join(ch for ch in t if ch == "\t" or 32 <= ord(ch))
    # 배열/객체 끝의 트레일링 콤마 제거: ,] 또는 ,} -> ] / }
    t = re.sub(r",\s*([\]\}])", r"\1", t)
    return t

def generate_post_with_gemini(raw_text: str) -> dict:
    """
    입력문(raw_text) -> {title, excerpt, content_html, tags[], categories[], slug?} JSON 생성
    (방어적 파싱 포함)
    """
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY가 설정되어 있지 않습니다 (.env 확인).")

    genai.configure(api_key=GEMINI_API_KEY)

    generation_config = {
        "temperature": 0.3,            # 안정성 ↑
        "top_p": 0.9,
        "max_output_tokens": 2048,
        "response_mime_type": "application/json",  # JSON만 받도록 강제
    }

    model = genai.GenerativeModel(model_name=GEMINI_MODEL, generation_config=generation_config)

    schema_hint = {
        "title": "string (<=80 chars, click-enticing, 존댓말 유지)",
        "excerpt": "string (<=160 chars, 메타디스크립션 용)",
        "content_html": "string (HTML only: h2/h3/p/ul/li/blockquote; no script/style)",
        "tags": ["string (3~6개, 공백 대신 하이픈 권장)"],
        "categories": ["string (1~2개, 예: 일상/여행/리뷰/팁/튜토리얼 등)"],
        "slug": "string (optional, 소문자와 하이픈만 권장)"
    }

    instructions = textwrap.dedent(f"""
    당신은 한국어 '개발자 블로그' 에디터입니다. 독자가 바로 따라 할 수 있도록
    정확하고 재현 가능한 튜토리얼/가이드 문서를 작성하십시오. 존댓말(정중체) 사용.
    
    [출력 형식: 반드시 JSON(아래 스키마)만 출력]
    - title: 80자 이내. 핵심 키워드 포함. (예: 프레임워크/라이브러리/오류명)
    - excerpt: 160자 이내. 무엇을 얻게 되는지 한 문단 요약(메타디스크립션).
    - content_html: 다음 섹션을 이 순서로 포함한 HTML만 생성:
      1) <h2>개요</h2>
         <p>무엇을 다루는지, 대상 독자, 사전 지식 1~2줄</p>
      2) <h2>빠른 요약</h2>
         <ul><li>핵심 포인트 3~6개(명령어/파일/옵션 이름은 코드로 표시)</li></ul>
      3) <h2>사전 준비물</h2>
         <ul><li>OS/버전, 의존 라이브러리, 권장 사양, 필요 권한</li></ul>
      4) <h2>설치 · 설정</h2>
         <h3>단계별 진행</h3>
         <p>각 단계는 목적/명령/결과/검증을 포함</p>
         <pre><code class="language-bash"># 예시 명령
    cmd1 --flag
    cmd2
    </code></pre>
      5) <h2>예제 코드</h2>
         <p>최소 재현 가능한 코드 + 실행/출력 예</p>
         <pre><code class="language-python"># 최소 예제
    def main():
        print("hello")
    </code></pre>
         <pre><code class="language-plaintext"># 예상 출력
    hello
    </code></pre>
      6) <h2>자주 발생하는 오류와 해결</h2>
         <ul>
           <li><b>오류 메시지</b>: 원인 → 해결 절차 1,2,3</li>
           <li><b>성능/비용 팁</b>: 캐시/배치/옵션</li>
           <li><b>보안 주의</b>: 키/토큰, 민감정보 처리</li>
         </ul>
      7) <h2>마이그레이션 · 대안</h2>
         <ul><li>버전 차이/대체 라이브러리/호환성 메모</li></ul>
      8) <h2>마무리</h2>
         <p>적용 시 얻는 이점과 다음 단계(테스트/배포/모니터링)</p>
      9) <h2>FAQ</h2>
         <ul><li>짧은 Q/A 3~5개</li></ul>
    
    [콘텐츠 규칙]
    - HTML만 사용: h2/h3/p/ul/li/blockquote/pre/code/table/a(img 제외). script/style 삽입 금지.
    - **코드 예제는 반드시 <pre><code class="language-언어명">…</code></pre> 형식으로 감싸고, 언어명을 지정** (예: language-javascript, language-python, language-bash, language-plaintext).
    - 명령/파일/옵션/키 이름은 인라인 <code>…</code> 로 강조.
    - 가능한 곳에 실제 버전/경로/옵션 값을 명시(예: Python 3.11, macOS 14).
    - 각 하위 섹션은 2~4문단 이상으로, 숫자/명령/출력 예를 포함.
    - 외부 링크는 http/https 절대경로만 사용하고, 과도한 링크는 지양.
    
    [분류 규칙]
    - tags: 4~7개. 소문자/하이픈 권장 (예: python, fastapi, github-actions, performance)
    - categories: 1~2개. 기본값은 ["개발","튜토리얼"]. 주제가 명확하면 적절히 교체.
    - slug: 소문자-하이픈 형식.
    
    [품질 기준]
    - 사실 검증(명령·옵션이 실제로 존재하도록 기술).
    - 재현 가능(설치→실행→검증 흐름이 끊기지 않게).
    - 중복·군더더기 문장 금지. 표와 리스트를 적극 사용.
    """)

    prompt = [
        {"role": "user", "parts": [instructions, "\n\n[입력문]\n", raw_text]}
    ]

    resp = model.generate_content(prompt)
    text = resp.text or ""

    # 1차 시도: 바로 파싱
    try:
        return json.loads(text)
    except Exception:
        pass

    # 2차 시도: 정리 후 파싱
    cleaned = _sanitize_json(text)
    try:
        data = json.loads(cleaned)
    except Exception as e:
        # 디버깅에 도움: 앞부분만 보여주기
        snippet = cleaned[:800]
        raise RuntimeError(f"Gemini 응답이 유효한 JSON이 아닙니다. 원문 일부:\n{snippet}\n\n오류: {e}")

    # 필수 필드 보정
    data.setdefault("tags", [])
    data.setdefault("categories", [])
    data.setdefault("slug", "")
    if not isinstance(data.get("tags"), list):        data["tags"] = []
    if not isinstance(data.get("categories"), list):  data["categories"] = []

    return data

# --- WordPress.com 토큰 로드 ---
def load_wp_token() -> str:
    with open("wp_token.json", "r", encoding="utf-8") as f:
        return json.load(f)["access_token"]

# --- Gemini로 블로그 포스트 JSON 생성 ---
def generate_post_with_gemini(raw_text: str) -> Dict[str, Any]:
    """
    입력문(raw_text)을 받아
    {title, excerpt, content_html, tags[], categories[], slug?} JSON을 생성
    """
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY가 설정되어 있지 않습니다 (.env 확인).")

    genai.configure(api_key=GEMINI_API_KEY)

    # JSON 출력 강제: MIME 타입을 JSON으로 지정
    generation_config = {
        "temperature": 0.7,
        "top_p": 0.95,
        "max_output_tokens": 2048,
        "response_mime_type": "application/json",
    }

    model = genai.GenerativeModel(model_name=GEMINI_MODEL, generation_config=generation_config)

    # 간단한 스키마를 프롬프트로 명시(파서 안정성 ↑)
    schema_hint = {
        "title": "string (<=80 chars, click-enticing, 존댓말 유지)",
        "excerpt": "string (<=160 chars, 메타디스크립션 용)",
        "content_html": "string (HTML only: h2/h3/p/ul/li/blockquote; no script/style)",
        "tags": ["string (3~6개, 공백 대신 하이픈 권장)"],
        "categories": ["string (1~2개, 예: 일상/여행/리뷰/팁/튜토리얼 등)"],
        "slug": "string (optional, 소문자와 하이픈만 권장)"
    }

    instructions = textwrap.dedent(f"""
    당신은 한국어 '개발자 블로그' 에디터입니다. 독자가 바로 따라 할 수 있도록
    정확하고 재현 가능한 튜토리얼/가이드 문서를 작성하십시오. 존댓말(정중체) 사용.
    
    [출력 형식: 반드시 JSON(아래 스키마)만 출력]
    - title: 80자 이내. 핵심 키워드 포함. (예: 프레임워크/라이브러리/오류명)
    - excerpt: 160자 이내. 무엇을 얻게 되는지 한 문단 요약(메타디스크립션).
    - content_html: 다음 섹션을 이 순서로 포함한 HTML만 생성:
      1) <h2>개요</h2>
         <p>무엇을 다루는지, 대상 독자, 사전 지식 1~2줄</p>
      2) <h2>빠른 요약</h2>
         <ul><li>핵심 포인트 3~6개(명령어/파일/옵션 이름은 코드로 표시)</li></ul>
      3) <h2>사전 준비물</h2>
         <ul><li>OS/버전, 의존 라이브러리, 권장 사양, 필요 권한</li></ul>
      4) <h2>설치 · 설정</h2>
         <h3>단계별 진행</h3>
         <p>각 단계는 목적/명령/결과/검증을 포함</p>
         <pre><code class="language-bash"># 예시 명령
    cmd1 --flag
    cmd2
    </code></pre>
      5) <h2>예제 코드</h2>
         <p>최소 재현 가능한 코드 + 실행/출력 예</p>
         <pre><code class="language-python"># 최소 예제
    def main():
        print("hello")
    </code></pre>
         <pre><code class="language-plaintext"># 예상 출력
    hello
    </code></pre>
      6) <h2>자주 발생하는 오류와 해결</h2>
         <ul>
           <li><b>오류 메시지</b>: 원인 → 해결 절차 1,2,3</li>
           <li><b>성능/비용 팁</b>: 캐시/배치/옵션</li>
           <li><b>보안 주의</b>: 키/토큰, 민감정보 처리</li>
         </ul>
      7) <h2>마이그레이션 · 대안</h2>
         <ul><li>버전 차이/대체 라이브러리/호환성 메모</li></ul>
      8) <h2>마무리</h2>
         <p>적용 시 얻는 이점과 다음 단계(테스트/배포/모니터링)</p>
      9) <h2>FAQ</h2>
         <ul><li>짧은 Q/A 3~5개</li></ul>
    
    [콘텐츠 규칙]
    - HTML만 사용: h2/h3/p/ul/li/blockquote/pre/code/table/a(img 제외). script/style 삽입 금지.
    - **코드 예제는 반드시 <pre><code class="language-언어명">…</code></pre> 형식으로 감싸고, 언어명을 지정** (예: language-javascript, language-python, language-bash, language-plaintext).
    - 명령/파일/옵션/키 이름은 인라인 <code>…</code> 로 강조.
    - 가능한 곳에 실제 버전/경로/옵션 값을 명시(예: Python 3.11, macOS 14).
    - 각 하위 섹션은 2~4문단 이상으로, 숫자/명령/출력 예를 포함.
    - 외부 링크는 http/https 절대경로만 사용하고, 과도한 링크는 지양.
    
    [분류 규칙]
    - tags: 4~7개. 소문자/하이픈 권장 (예: python, fastapi, github-actions, performance)
    - categories: 1~2개. 기본값은 ["개발","튜토리얼"]. 주제가 명확하면 적절히 교체.
    - slug: 소문자-하이픈 형식.
    
    [품질 기준]
    - 사실 검증(명령·옵션이 실제로 존재하도록 기술).
    - 재현 가능(설치→실행→검증 흐름이 끊기지 않게).
    - 중복·군더더기 문장 금지. 표와 리스트를 적극 사용.
    """)

    prompt = [
        {"role": "user", "parts": [
            instructions,
            "\n\n[입력문]\n",
            raw_text
        ]}
    ]

    resp = model.generate_content(prompt)
    # Gemini는 response가 JSON 텍스트로 옵니다.
    text = resp.text
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # 혹시 모델이 JSON 외 텍스트를 섞어 보냈다면 간단 정리 시도
        text = text.strip().strip("```").strip()
        if text.startswith("{") and text.endswith("}"):
            data = json.loads(text)
        else:
            raise RuntimeError("Gemini 응답이 JSON이 아닙니다. 프롬프트/모델을 확인하세요.\n" + text[:500])

    # 필수 필드 보정(누락 시 간단 보완)
    data.setdefault("tags", [])
    data.setdefault("categories", [])
    data.setdefault("slug", "")

    return data

# --- WordPress.com에 글 생성 ---
def create_wp_post(post: Dict[str, Any], status: str = "draft") -> Dict[str, Any]:
    """
    post 딕셔너리(위 JSON 스키마)와 status('draft'|'publish'|'future')를 받아
    WordPress.com에 글을 생성.
    """
    access_token = load_wp_token()
    headers = {"Authorization": f"Bearer {access_token}"}

    tags_str = ",".join(post.get("tags", []))
    # cats_str = ",".join(post.get("categories", []))
    # 카테고리 수정
    fixed_categories = ["Study", "JavaScript"]  # 원하는 카테고리 이름
    cats_str = ",".join(fixed_categories)

    payload = {
        "title": post["title"],
        "content": post["content_html"],
        "excerpt": post["excerpt"],
        "status": status,             # 'publish' | 'draft' | 'future'
        "slug": post.get("slug") or "",
        "tags": tags_str,
        "categories": cats_str,
    }

    url = f"{API_BASE}/sites/{WP_SITE}/posts/new"
    with httpx.Client(timeout=30) as client:
        r = client.post(url, headers=headers, data=payload)
        r.raise_for_status()
        return r.json()

# --- 진입점 ---
if __name__ == "__main__":
    # 여기 입력만 바꿔도 됩니다.
    RAW = """
        [주제] JavaScript에서 let과 var의 차이와 사용 시 주의사항

        [대상/전제]
        - JavaScript 기본 문법을 아는 웹 개발자
        - Node.js v20 이상 또는 최신 브라우저 콘솔 환경
        - 실습 예시는 macOS, Linux, Windows 모두 가능
        
        [해야 할 일]
        - let과 var의 기본 문법 차이 설명
        - 변수 스코프(scope) 차이: 함수 스코프 vs 블록 스코프
        - 호이스팅(hoisting) 동작 차이 시연
        - 재선언 가능 여부 비교
        - var 사용 시 잠재적 버그 사례
        - let 권장 이유와 예외적으로 var를 쓸 수 있는 상황
        
        [세부 제약/결정]
        - 예제 코드와 출력 예를 반드시 포함
        - 코드블록은 <pre><code class="language-javascript">로 표기
        - 각 차이점은 표나 불릿리스트로 정리
        - ES6(2015) 표준 이후 let이 기본 권장임을 명시
        
        [검증]
        - Node.js 콘솔에서 실행한 결과 예시 포함
        - 브라우저 콘솔에서도 동일하게 재현 가능함을 명시
        
        [오류/해결]
        - ReferenceError: Cannot access 'x' before initialization 발생 시 설명
        - var로 인한 전역 오염(global namespace pollution) 예와 해결책

        """

    # 1) Gemini로 포스트 JSON 생성
    post = generate_post_with_gemini(RAW)

    # 2) 워드프레스에 초안으로 업로드 (즉시 발행은 status="publish")(임시 발행은 status="draft")
    res = create_wp_post(post, status="publish")

    # 3) 결과 출력
    print(json.dumps({
        "ID": res.get("ID"),
        "URL": res.get("URL"),
        "status": res.get("status"),
        "title": res.get("title"),
    }, ensure_ascii=False, indent=2))
