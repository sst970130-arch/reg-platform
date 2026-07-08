"""
식약처(MFDS) 공식 RSS 피드 자동 동기화 모듈.

- 식약처가 공식 제공하는 무료 RSS 피드(로그인/API키/결재 불필요)를 주기적으로 폴링해
  새 고시/훈령/예규/행정예고/공지 항목을 documents 테이블에 자동 등록합니다.
- 신규 pip 패키지 없이 표준 라이브러리(xml.etree.ElementTree)만 사용합니다.
- 사내망 방화벽 등으로 요청이 실패해도 예외를 삼켜 앱이 죽지 않게 하고, 다음 주기에 재시도합니다.
"""
import html
import os
import re
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

import requests

from . import db, extract, search

RSS_BASE = "https://www.mfds.go.kr/www/rss/brd.do?brdId={board_id}"

# 게시판명 -> brdId (필요시 자유롭게 추가/삭제 가능)
RSS_FEEDS = {
    "고시전문": "data0005",
    "훈령전문": "data0006",
    "예규전문": "data0007",
    "행정예고": "data0009",
    "공지": "ntc0003",
    "민원인안내서": "data0011",  # 가이드라인/사례집/질의응답집이 올라오는 게시판
}

# 식약처 RSS는 의약품 외에 화장품/축산/식품/의료기기 등 소관 전체가 섞여 나옵니다.
# 이 회사는 제약(의약품) 업무만 필요하므로, 제목에 아래 키워드가 포함된 항목은 자동 수집에서
# 제외합니다. 제목 기준으로만 검사해 "식품의약품안전처"(기관명) 같은 오탐을 피합니다.
EXCLUDE_TITLE_KEYWORDS = [
    "화장품",
    "축산", "동물용의약품", "사료", "유전자변형", "가금육", "알가공품",
    "위생용품",
    "건강기능식품",
    "의료기기", "체외진단", "혈압계",
    "식품", "식생활", "복어", "야생동식물",
    # 공지 게시판에 섞이는, 실무(RA/QC)와 무관한 홍보성/행정성 공지
    "공모전", "공모 공고", "이벤트", "당첨자", "채용", "사칭",
    "청렴도", "국정과제", "콘텐츠", "퀴즈", "위탁계약",
]

# 훈령전문/예규전문 게시판은 식약처 내부 인사·행정 운영 규정(공무원 행동강령, 고충처리,
# 성과평가, 감사규정, 각종 내부위원회 운영 등)이 대부분이고 실제 제약 관련 내용은 소수라,
# "제외 키워드" 방식 대신 "이 키워드가 있어야만 포함"하는 화이트리스트로 뒤집어서 걸러낸다.
PHARMA_KEEP_KEYWORDS = [
    "의약품", "생물학적제제", "바이오의약품", "백신", "혈액", "혈장",
    "마약류", "향정신성", "원료의약품", "한약", "생약", "약사법",
    "임상시험", "시료채취", "국가출하승인", "의료제품", "첨단바이오",
]
WHITELIST_ONLY_BOARDS = ("훈령전문", "예규전문")


# "민원인안내서" 게시판 글 중 실제 질의응답집/자주묻는질문 형태만 qna 카테고리로 분류하고,
# 나머지 가이드라인/사례집 등은 notice(고시/가이드라인) 카테고리로 둔다.
_QNA_TITLE_PATTERN = re.compile(r"질의응답|질문집|Q\s*&\s*A", re.IGNORECASE)


def resolve_category(board_name, title):
    if board_name == "민원인안내서" and _QNA_TITLE_PATTERN.search(title or ""):
        return "qna"
    return "notice"


_AGENCY_NAMES = ("식품의약품안전처", "식품의약품안전평가원")


def is_excluded(title, board_name=None):
    # 기관명(식품의약품안전처/평가원)에 포함된 "식품"까지 걸리지 않도록 먼저 제거하고 검사합니다.
    title = title or ""
    clean_title = title
    for name in _AGENCY_NAMES:
        clean_title = clean_title.replace(name, "")
    if any(kw in clean_title for kw in EXCLUDE_TITLE_KEYWORDS):
        return True
    if board_name in WHITELIST_ONLY_BOARDS and not any(kw in clean_title for kw in PHARMA_KEEP_KEYWORDS):
        return True
    return False

_CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}encoded"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

_last_sync_info = {"time": None, "new_count": 0, "error": None}


def get_last_sync_info():
    return dict(_last_sync_info)


def _parse_pub_date(pub_date_text):
    # db.is_new()이 timezone-naive datetime.now()와 뺄셈을 하므로, 여기서도 naive로 통일합니다.
    try:
        dt = parsedate_to_datetime(pub_date_text)
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt.isoformat(timespec="seconds")
    except Exception:
        return datetime.now().isoformat(timespec="seconds")


def fetch_feed(board_name, board_id, timeout=15):
    """RSS XML을 받아 [{guid, title, link, summary, pub_date}, ...] 로 반환합니다.
    실패하면 빈 리스트를 반환합니다 (호출부에서 앱을 멈추지 않기 위함)."""
    url = RSS_BASE.format(board_id=board_id)
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception:
        return []

    items = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        guid = (item.findtext("guid") or link or title).strip()
        pub_date_text = (item.findtext("pubDate") or "").strip()
        summary = (item.findtext(_CONTENT_NS) or item.findtext("description") or "").strip()
        if not title or not link:
            continue
        items.append({
            "guid": guid,
            "title": title,
            "link": link,
            "summary": summary,
            "pub_date": _parse_pub_date(pub_date_text) if pub_date_text else datetime.now().isoformat(timespec="seconds"),
        })
    return items


_ATTACHMENT_PATTERN = re.compile(
    r"<strong>([^<]+\.(?:pdf|hwpx?|zip|docx?))</strong>.*?href=\"(\./down\.do\?[^\"]+)\"",
    re.DOTALL | re.IGNORECASE,
)


def fetch_attachment_list(detail_url, timeout=15):
    """문서 상세페이지에서 첨부파일 [(파일명, 절대다운로드URL), ...] 목록을 찾습니다.
    식약처 사이트 구조가 바뀌면 못 찾을 수 있는데, 그 경우 조용히 빈 리스트를 반환합니다."""
    try:
        resp = requests.get(detail_url, headers={**_HEADERS, "Referer": detail_url}, timeout=timeout)
        resp.raise_for_status()
    except Exception:
        return []

    page_html = resp.text
    results = []
    for filename, href in _ATTACHMENT_PATTERN.findall(page_html):
        href = html.unescape(href)
        results.append((html.unescape(filename.strip()), urljoin(detail_url, href)))
    return results


# HWP/HWPX는 텍스트 추출이 안 되면서 용량만 차지하므로 저장하지 않습니다 (PDF가 있으면 그걸로 충분).
_SKIP_EXTENSIONS = {".hwp", ".hwpx"}


def download_and_store_attachments(document_id, detail_url):
    """상세페이지의 첨부파일을 내려받아 저장하고, 텍스트 추출이 되는 파일(PDF 등)은
    문서의 extracted_text에 이어붙입니다. 개별 파일 실패는 다음 파일 처리에 영향 없이 넘어갑니다."""
    attachments = fetch_attachment_list(detail_url)
    for file_seq, (filename, url) in enumerate(attachments, start=1):
        if os.path.splitext(filename)[1].lower() in _SKIP_EXTENSIONS:
            continue
        try:
            resp = requests.get(url, headers={**_HEADERS, "Referer": detail_url}, timeout=30)
            resp.raise_for_status()
        except Exception:
            continue

        ext = os.path.splitext(filename)[1].lower()
        safe_name = f"{uuid.uuid4().hex}{ext}"
        stored_path_abs = os.path.join(db.UPLOAD_DIR, safe_name)
        try:
            with open(stored_path_abs, "wb") as f:
                f.write(resp.content)
        except OSError:
            continue

        db.insert_attachment(document_id, filename, safe_name, file_seq)

        try:
            extracted = extract.extract_text(stored_path_abs)
        except Exception:
            extracted = ""
        if extracted and not extracted.startswith("[텍스트 추출 실패"):
            extracted = search.drop_admin_frontmatter(extracted)
            db.append_extracted_text(document_id, extracted)


_BRACKET_NAME = re.compile(r"「([^」]+)」")
_BOARD_PATH = re.compile(r"/brd/(m_\d+)/")
_SEARCH_RESULT_HREF = re.compile(r'href="\./view\.do\?seq=(\d+)[&"]')
_SEARCH_RESULT_TITLE = re.compile(r'class="title"[^>]*>\s*([^<]+?)\s*</a>')
_SEARCH_RESULT_DATE = re.compile(r"(20\d\d)[.\-]\s*(\d{1,2})[.\-]\s*(\d{1,2})")

# 이 유형만 "예전 게시글이 그대로 남는" 게시판이라 직전 버전 검색이 통합니다.
# 민원인안내서는 개정 시 같은 게시글을 덮어써서 예전 파일이 서버에 없고, 행정예고는
# 아직 확정 안 된 개정안이라 "직전 버전" 개념이 다르게 적용되므로 둘 다 대상에서 뺍니다.
VERSIONED_BOARDS = ("고시전문", "훈령전문", "예규전문")


def _normalize_reg_name(title):
    m = _BRACKET_NAME.search(title or "")
    if m:
        return m.group(1).strip()
    return re.sub(r"\([^)]*\)", "", title or "").strip()


def _parse_search_results(page_html):
    """게시판 목록/검색 결과 페이지에서 [(seq, title), ...]을 뽑습니다. 페이지 구조가 바뀌면
    둘 중 하나가 안 잡혀 개수가 안 맞을 수 있는데, 그 경우 안전하게 빈 리스트를 반환합니다."""
    seqs = _SEARCH_RESULT_HREF.findall(page_html)
    titles = _SEARCH_RESULT_TITLE.findall(page_html)
    if not seqs or len(seqs) != len(titles):
        return []
    return [(int(seq), html.unescape(title.strip())) for seq, title in zip(seqs, titles)]


_DETAIL_DATE = re.compile(r"(?:고시일|제정일|승인일자?)\s*</span>\s*(\d{4})-(\d{2})-(\d{2})")


def _fetch_detail_date(detail_url, timeout=15):
    """상세페이지의 '고시일/제정일' 필드에서 실제 날짜를 가져옵니다 (백필 시점이 아니라
    그 규정이 실제로 고시된 날짜를 upload_date로 써야 "신규" 배지/정렬이 정확해집니다)."""
    try:
        resp = requests.get(detail_url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
    except Exception:
        return None
    m = _DETAIL_DATE.search(resp.text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}T00:00:00"
    return None


def find_previous_version(doc, timeout=15):
    """같은 규정명의 예전 게시글(직전 버전) (seq, title, url)을 찾습니다. 없으면 None."""
    source_url = doc["source_url"] or ""
    board_path_m = _BOARD_PATH.search(source_url)
    current_seq_m = re.search(r"seq=(\d+)", source_url)
    if not board_path_m or not current_seq_m:
        return None
    board_path = board_path_m.group(1)
    current_seq = int(current_seq_m.group(1))
    reg_name = _normalize_reg_name(doc["title"])
    if not reg_name:
        return None

    search_url = f"https://www.mfds.go.kr/brd/{board_path}/list.do?srchWord={requests.utils.quote(reg_name)}&srchTp=0"
    try:
        resp = requests.get(search_url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
    except Exception:
        return None

    results = _parse_search_results(resp.text)
    # 규정명이 정확히 같은 것만 남긴다 (예: "대한민국약전"과 "대한민국약전외한약(생약)규격집"은 다른 규정)
    same_name = [(seq, title) for seq, title in results if _normalize_reg_name(title) == reg_name]
    older = [(seq, title) for seq, title in same_name if seq < current_seq]
    if not older:
        return None
    prev_seq, prev_title = max(older, key=lambda x: x[0])
    prev_url = f"https://www.mfds.go.kr/brd/{board_path}/view.do?seq={prev_seq}"
    return {"seq": prev_seq, "title": prev_title, "url": prev_url}


def fetch_previous_version_document(doc):
    """doc의 직전 버전을 찾아 아직 없으면 새 문서로 등록하고 첨부파일까지 받아옵니다."""
    board_path_m = _BOARD_PATH.search(doc["source_url"] or "")
    if not board_path_m:
        return
    prev = find_previous_version(doc)
    if not prev:
        return

    board_id = next((bid for name, bid in RSS_FEEDS.items() if name == doc["board_name"]), board_path_m.group(1))
    guid = f"{board_id}_{prev['seq']}"
    if db.get_document_by_external_guid(guid):
        return  # 이미 백필된 경우 (백필 스크립트와 정기 동기화가 겹쳐도 중복 등록되지 않음)

    upload_date = _fetch_detail_date(prev["url"])
    if not upload_date:
        date_m = _SEARCH_RESULT_DATE.search(prev["title"])
        if date_m:
            upload_date = f"{date_m.group(1)}-{int(date_m.group(2)):02d}-{int(date_m.group(3)):02d}T00:00:00"
        else:
            upload_date = datetime.now().isoformat(timespec="seconds")

    prev_doc_id = db.insert_document(
        category="notice",
        title=prev["title"],
        extracted_text="",
        source_url=prev["url"],
        origin="mfds_rss",
        external_guid=guid,
        board_name=doc["board_name"],
        upload_date=upload_date,
    )
    download_and_store_attachments(prev_doc_id, prev["url"])


def sync_all():
    """모든 RSS_FEEDS를 순회하며 신규 항목만 documents에 등록합니다."""
    new_count = 0
    error = None
    download_attachments = os.environ.get("MFDS_DOWNLOAD_ATTACHMENTS", "true").lower() in ("1", "true", "yes")
    fetch_previous = os.environ.get("MFDS_FETCH_PREVIOUS_VERSION", "true").lower() in ("1", "true", "yes")
    for board_name, board_id in RSS_FEEDS.items():
        try:
            items = fetch_feed(board_name, board_id)
            for it in items:
                if is_excluded(it["title"], board_name):
                    continue
                if db.get_document_by_external_guid(it["guid"]):
                    continue
                doc_id = db.insert_document(
                    category=resolve_category(board_name, it["title"]),
                    title=it["title"],
                    extracted_text=it["summary"],
                    source_url=it["link"],
                    origin="mfds_rss",
                    external_guid=it["guid"],
                    board_name=board_name,
                    upload_date=it["pub_date"],
                )
                new_count += 1
                if download_attachments:
                    try:
                        download_and_store_attachments(doc_id, it["link"])
                    except Exception:
                        pass  # 첨부파일 처리 실패는 문서 등록 자체를 막지 않음
                if fetch_previous and board_name in VERSIONED_BOARDS:
                    try:
                        fetch_previous_version_document(db.get_document(doc_id))
                    except Exception:
                        pass  # 직전 버전 탐색 실패는 신규 문서 등록 자체를 막지 않음
        except Exception as e:  # 방화벽 차단 등 어떤 이유로든 전체 동기화가 죽지 않게 함
            error = str(e)

    _last_sync_info["time"] = datetime.now().isoformat(timespec="seconds")
    _last_sync_info["new_count"] = new_count
    _last_sync_info["error"] = error
    return new_count
