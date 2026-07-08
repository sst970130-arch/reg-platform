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

from . import db, extract

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
    "축산", "동물용의약품", "사료", "유전자변형",
    "위생용품",
    "건강기능식품",
    "의료기기", "체외진단", "혈압계",
    "식품", "복어", "야생동식물",
    # 공지 게시판에 섞이는, 실무(RA/QC)와 무관한 홍보성/행정성 공지
    "공모전", "공모 공고", "이벤트", "당첨자", "채용", "사칭",
    "청렴도", "국정과제", "콘텐츠", "퀴즈", "위탁계약",
]

# "민원인안내서" 게시판 글 중 실제 질의응답집/자주묻는질문 형태만 qna 카테고리로 분류하고,
# 나머지 가이드라인/사례집 등은 notice(고시/가이드라인) 카테고리로 둔다.
_QNA_TITLE_PATTERN = re.compile(r"질의응답|질문집|Q\s*&\s*A", re.IGNORECASE)


def resolve_category(board_name, title):
    if board_name == "민원인안내서" and _QNA_TITLE_PATTERN.search(title or ""):
        return "qna"
    return "notice"


_AGENCY_NAMES = ("식품의약품안전처", "식품의약품안전평가원")


def is_excluded(title):
    # 기관명(식품의약품안전처/평가원)에 포함된 "식품"까지 걸리지 않도록 먼저 제거하고 검사합니다.
    title = title or ""
    for name in _AGENCY_NAMES:
        title = title.replace(name, "")
    return any(kw in title for kw in EXCLUDE_TITLE_KEYWORDS)

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
            db.append_extracted_text(document_id, extracted)


def sync_all():
    """모든 RSS_FEEDS를 순회하며 신규 항목만 documents에 등록합니다."""
    new_count = 0
    error = None
    download_attachments = os.environ.get("MFDS_DOWNLOAD_ATTACHMENTS", "true").lower() in ("1", "true", "yes")
    for board_name, board_id in RSS_FEEDS.items():
        try:
            items = fetch_feed(board_name, board_id)
            for it in items:
                if is_excluded(it["title"]):
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
        except Exception as e:  # 방화벽 차단 등 어떤 이유로든 전체 동기화가 죽지 않게 함
            error = str(e)

    _last_sync_info["time"] = datetime.now().isoformat(timespec="seconds")
    _last_sync_info["new_count"] = new_count
    _last_sync_info["error"] = error
    return new_count
