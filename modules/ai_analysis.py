"""
AI 요약 / Q&A 해설 / 실무 적용 가이드 생성 모듈.

- Anthropic Claude API를 REST 방식(requests)으로 직접 호출합니다.
- .env 파일에 ANTHROPIC_API_KEY를 설정하면 실제 AI 분석이 동작합니다.
- 키가 없으면, 화면이 깨지지 않도록 "AI 분석 비활성화" 안내와 함께
  검색된 원문 기반의 간단한 요약(플레이스홀더)을 대신 보여줍니다.
"""
import os
import json
import re
import requests

from . import search

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")

SYSTEM_PROMPT = """\
당신은 국내 제약회사 RA(인허가)/QC·QA 실무자를 돕는 규제 분석 보조 AI입니다.
아래에 제공되는 '검색어'와 '관련 문서 발췌'만을 근거로 답변하십시오. 문서에 없는 내용은 추측하지 말고,
확실하지 않으면 "원문 확인 필요"라고 명시하십시오.

반드시 다음 JSON 형식으로만 답변하십시오 (다른 텍스트, 코드블록 없이 순수 JSON):
{
  "summary": "핵심 내용을 실무자가 30초 안에 이해할 수 있도록 3~5문장으로 직관적으로 요약",
  "qna_explanations": [
    {"question": "문서에 있는 질의 또는 실무자가 흔히 궁금해할 질문",
     "explanation": "유예기간, 적용 시점, 예외 사항 등을 포함해 실무자 언어로 명확하게 재해설"}
  ],
  "action_items": {
    "RA": ["RA팀이 무엇을, 언제까지, 어떻게 해야 하는지 구체적 액션 아이템"],
    "QC_QA": ["QC/QA팀이 무엇을, 언제까지, 어떻게 해야 하는지 구체적 액션 아이템"]
  }
}
"""


def is_configured():
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def analyze(query, matched_docs):
    """matched_docs: search.search_documents() 결과 리스트"""
    if not matched_docs:
        return {
            "summary": "관련 문서를 찾지 못했습니다. 다른 검색어로 시도하시거나, 관리자 업로드 메뉴에서 관련 고시/Q&A 문서를 먼저 등록해 주세요.",
            "qna_explanations": [],
            "action_items": {"RA": [], "QC_QA": []},
            "ai_enabled": is_configured(),
        }

    if not is_configured():
        return _fallback_analysis(query, matched_docs)

    context_blocks = []
    for item in matched_docs[:5]:
        d = item["doc"]
        excerpt = (d["extracted_text"] or "")[:1800]
        context_blocks.append(
            f"[{d['category']}] {d['title']}\n{excerpt}"
        )
    context_text = "\n\n---\n\n".join(context_blocks)

    user_prompt = f"검색어: {query}\n\n관련 문서 발췌:\n\n{context_text}"

    try:
        resp = requests.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": DEFAULT_MODEL,
                "max_tokens": 1500,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_prompt}],
            },
            timeout=45,
        )
        resp.raise_for_status()
        data = resp.json()
        text = "".join(block.get("text", "") for block in data.get("content", []))
        parsed = _parse_json_response(text)
        parsed["ai_enabled"] = True
        return parsed
    except Exception as e:
        fallback = _fallback_analysis(query, matched_docs)
        fallback["error"] = f"AI 호출 중 오류가 발생해 임시 요약으로 대체했습니다: {e}"
        return fallback


def _parse_json_response(text):
    # 모델이 코드블록으로 감싸는 경우 대비
    match = re.search(r"\{.*\}", text, re.DOTALL)
    raw = match.group(0) if match else text
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {
            "summary": text.strip()[:800] or "AI 응답을 해석하지 못했습니다.",
            "qna_explanations": [],
            "action_items": {"RA": [], "QC_QA": []},
        }
    data.setdefault("summary", "")
    data.setdefault("qna_explanations", [])
    data.setdefault("action_items", {"RA": [], "QC_QA": []})
    return data


def _fallback_analysis(query, matched_docs):
    top = matched_docs[0]["doc"]
    snippet = (top["extracted_text"] or "")[:300].strip()
    if is_configured():
        intro = "⚠ AI 호출에 실패해 임시로 원문 일부를 보여드립니다 (아래 오류 메시지를 확인해 주세요). "
    else:
        intro = "⚠ AI 분석 기능이 아직 설정되지 않아, 문서 유형 기반의 일반 체크리스트로 대신합니다. "
    return {
        "summary": (
            f"{intro}우선 가장 관련도가 높은 문서인 '{top['title']}'의 앞부분을 보여드립니다:\n\n{snippet}..."
        ),
        "qna_explanations": [],
        "action_items": search.suggest_action_items(top["board_name"], top["category"]),
        "ai_enabled": False,
    }
