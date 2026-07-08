"""
통합 검색 모듈.
- TF-IDF 기반 키워드 유사도로 전체 문서(고시/Q&A/세미나)를 교차 검색합니다.
- 별도의 외부 검색엔진/서버 없이 동작하도록 가볍게 구현했습니다.
"""
import re
import textwrap
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from . import db


def _clean_text(text):
    # 검색에 방해되는 불필요한 공백만 정리 (한글 자체는 그대로 유지)
    return re.sub(r"\s+", " ", text or "").strip()


def _make_vectorizer():
    # 한국어는 조사가 붙어(예: "유예기간을") 단어 단위 토큰화로는 검색이 잘 안 됩니다.
    # 그래서 문자 n-gram(char_wb) 방식을 사용해 형태소 분석기 없이도 안정적으로 매칭되게 합니다.
    return TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3), min_df=1)


def search_documents(query, top_k=8):
    """query와 관련도가 높은 문서를 카테고리 무관하게 랭킹하여 반환합니다."""
    rows = db.get_all_documents()
    if not rows or not query.strip():
        return []

    corpus = [_clean_text((r["title"] or "") + " " + (r["extracted_text"] or "")) for r in rows]
    corpus.append(_clean_text(query))

    try:
        vectorizer = _make_vectorizer()
        matrix = vectorizer.fit_transform(corpus)
    except ValueError:
        # 어휘가 전혀 없을 때 (빈 문서들만 있을 때) 등
        return []

    query_vec = matrix[-1]
    doc_vecs = matrix[:-1]
    sims = cosine_similarity(query_vec, doc_vecs).flatten()

    scored = list(zip(rows, sims))
    scored.sort(key=lambda x: x[1], reverse=True)

    results = []
    for row, score in scored:
        # 아주 관련 없는 문서(유사도 0)는 제외하되, 문서가 적을 때는 최소 결과는 보여줌
        if score <= 0:
            continue
        results.append({"doc": row, "score": float(score)})
        if len(results) >= top_k:
            break

    # 키워드 매칭이 전혀 없으면(TF-IDF 유사도 0) 제목에 단순 포함 여부로 한 번 더 시도
    if not results:
        q_lower = query.lower()
        for row in rows:
            if q_lower in (row["title"] or "").lower() or q_lower in (row["extracted_text"] or "").lower():
                results.append({"doc": row, "score": 0.01})
        results = results[:top_k]

    return results


def search_guide_notes(query, top_k=3):
    """실무 해설 지식베이스(guide_notes)에서 query와 관련도 높은 항목을 찾습니다."""
    notes = db.get_all_guide_notes()
    if not notes or not query.strip():
        return []

    corpus = [_clean_text((n["title"] or "") + " " + (n["body"] or "")) for n in notes]
    corpus.append(_clean_text(query))

    try:
        vectorizer = _make_vectorizer()
        matrix = vectorizer.fit_transform(corpus)
    except ValueError:
        return []

    query_vec = matrix[-1]
    note_vecs = matrix[:-1]
    sims = cosine_similarity(query_vec, note_vecs).flatten()

    scored = [(n, sc) for n, sc in zip(notes, sims) if sc > 0]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [n for n, _ in scored[:top_k]]


def extract_snippet(text, query, context_chars=220):
    """원문에서 검색어 주변 발췌문을 만듭니다."""
    if not text:
        return ""
    idx = text.lower().find(query.lower())
    if idx == -1:
        return text[:context_chars].strip() + ("..." if len(text) > context_chars else "")
    start = max(0, idx - context_chars // 2)
    end = min(len(text), idx + len(query) + context_chars // 2)
    snippet = text[start:end].strip()
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{snippet}{suffix}"


_QNA_SPLIT_PATTERN = re.compile(
    r"(?:^|\n)\s*(?:Q\s*[\.\):]|질의\s*[\.\):]|Q\d+\s*[\.\):])",
    re.IGNORECASE,
)


def extract_qna_pairs(text, max_pairs=5):
    """Q&A 문서 본문에서 질문/답변 쌍을 아주 단순한 규칙으로 추출합니다.
    (완벽하지 않을 수 있어 원문 전체 링크도 함께 제공합니다.)"""
    if not text:
        return []
    chunks = _QNA_SPLIT_PATTERN.split(text)
    pairs = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        # 답변 구분자로 재분리
        ans_split = re.split(
            r"(?:^|\n)\s*(?:A\s*[\.\):]|답변\s*[\.\):]|A\d+\s*[\.\):])",
            chunk, maxsplit=1, flags=re.IGNORECASE,
        )
        if len(ans_split) == 2:
            question, answer = ans_split[0].strip(), ans_split[1].strip()
            if question:
                pairs.append({"question": question[:300], "answer": answer[:600]})
        if len(pairs) >= max_pairs:
            break
    return pairs


_REASON_LABEL = re.compile(r"1\s*[\.\)]\s*개정\s*이유")
_SUMMARY_LABEL = re.compile(r"2\s*[\.\)]\s*주요\s*내용")
_COMBINED_TAIL = re.compile(r"^\s*및\s*주요\s*내용")
_NEXT_SECTION = re.compile(r"(?:\n|^)\s*\d\s*[\.\)]\s*\S|의견\s*제출|부칙\s*[<〈]")


def extract_revision_info(text, max_len=900):
    """식약처 행정예고(입법예고) 공고문에 흔한 '1. 개정이유 2. 주요내용' 구조를 찾아
    {reason, summary} 로 구조화합니다. 이 형식이 아닌 문서(공지, 확정 고시전문 등)는
    None을 반환합니다 - 없는 내용을 억지로 만들어내지 않습니다."""
    if not text:
        return None

    reason_m = _REASON_LABEL.search(text)
    if not reason_m:
        return None

    tail = text[reason_m.end():reason_m.end() + 20]
    combined = bool(_COMBINED_TAIL.match(tail))

    if combined:
        content_start = reason_m.end() + _COMBINED_TAIL.match(tail).end()
        reason_text = None
    else:
        summary_m = _SUMMARY_LABEL.search(text, reason_m.end())
        if summary_m:
            reason_text = text[reason_m.end():summary_m.start()].strip(" \n:.　")[:400]
            content_start = summary_m.end()
        else:
            # "주요내용" 라벨을 못 찾으면 개정이유 뒤 전체를 요약으로 취급
            reason_text = None
            content_start = reason_m.end()

    boundary_m = _NEXT_SECTION.search(text, content_start + 10)
    content_end = boundary_m.start() if boundary_m else len(text)
    summary_text = text[content_start:content_end].strip(" \n:.　")[:max_len]

    if not reason_text and not summary_text:
        return None

    return {"reason": reason_text, "summary": summary_text, "combined": combined}


def to_diff_lines(text, max_chars=120):
    """difflib으로 비교하기 좋게 문장 단위(마침표/느낌표/물음표 뒤)로 잘게 나눕니다.
    너무 긴 문장은 고정 길이로 한 번 더 감쌉니다."""
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    lines = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) <= max_chars:
            lines.append(p)
        else:
            lines.extend(textwrap.wrap(p, max_chars))
    return lines


def suggest_action_items(board_name, category):
    """AI 없이, 문서 유형(게시판/카테고리)에 따른 일반적인 실무 체크리스트를 규칙 기반으로
    제안합니다. 문서 개별 내용까지 반영한 것은 아니므로 실제 적용 전 RA/QC 판단이 필요합니다."""
    if category == "qna":
        return {
            "RA": ["유사 품목·허가사항에 이 Q&A 내용이 적용되는지 검토"],
            "QC_QA": ["Q&A 내용을 사내 시험법/절차서·교육자료에 반영할지 검토"],
        }
    if board_name == "행정예고":
        return {
            "RA": [
                "의견제출 마감일 확인 및 필요 시 사내 의견 제출 여부 검토",
                "확정 고시로 전환될 경우 관련 인허가 문서(허가증, CTD 등) 개정 필요 여부 사전 검토",
            ],
            "QC_QA": ["시험법·규격 변경 가능성에 대비해 관련 SOP 영향도 사전 검토"],
        }
    if board_name in ("고시전문", "훈령전문", "예규전문"):
        return {
            "RA": ["시행일 확인 및 해당 품목의 인허가 사항 개정 필요 여부 검토"],
            "QC_QA": ["변경된 기준·시험법이 현재 SOP·규격과 일치하는지 확인, 불일치 시 개정 진행"],
        }
    if board_name == "공지":
        return {
            "RA": ["공지 내용이 현재 진행 중인 인허가 업무에 영향을 주는지 확인"],
            "QC_QA": [],
        }
    return {"RA": [], "QC_QA": []}


def find_related_seminars(matched_docs, top_k=3):
    """검색 결과 문서들과 키워드가 겹치는 세미나 자료를 찾아 연결합니다."""
    seminars = db.get_all_documents(category="seminar")
    if not seminars or not matched_docs:
        return []

    base_text = " ".join(
        _clean_text((d["doc"]["title"] or "") + " " + (d["doc"]["extracted_text"] or ""))
        for d in matched_docs
        if d["doc"]["category"] != "seminar"
    )
    if not base_text.strip():
        return []

    corpus = [_clean_text((s["title"] or "") + " " + (s["extracted_text"] or "")) for s in seminars]
    corpus.append(base_text)

    try:
        vectorizer = _make_vectorizer()
        matrix = vectorizer.fit_transform(corpus)
    except ValueError:
        return []

    base_vec = matrix[-1]
    sem_vecs = matrix[:-1]
    sims = cosine_similarity(base_vec, sem_vecs).flatten()

    scored = [(s, sc) for s, sc in zip(seminars, sims) if sc > 0]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [s for s, _ in scored[:top_k]]
