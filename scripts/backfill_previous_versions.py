"""
이미 수집된 고시전문/훈령전문/예규전문 문서마다 직전 버전(같은 규정의 예전 게시글)을
찾아 PDF까지 소급 수집하는 1회성 스크립트.

- 민원인안내서/행정예고는 대상이 아닙니다 (modules/mfds_sync.py의 VERSIONED_BOARDS 참고).
- 식약처 서버에 부담을 주지 않도록 문서 사이에 짧은 간격을 둡니다.
- 실행: python scripts/backfill_previous_versions.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import db, mfds_sync

DELAY_SECONDS = 0.5


def backfill():
    targets = [
        r for r in db.get_all_documents()
        if r["origin"] == "mfds_rss" and r["board_name"] in mfds_sync.VERSIONED_BOARDS
    ]
    print(f"대상 문서: {len(targets)}건")

    before_count = db.document_count()
    for r in targets:
        try:
            mfds_sync.fetch_previous_version_document(r)
        except Exception as e:
            print(f"실패: [{r['board_name']}] {r['title'][:50]} - {e}")
        time.sleep(DELAY_SECONDS)

    added = db.document_count() - before_count
    print(f"\n{len(targets)}건 확인, 새로 추가된 직전 버전 문서: {added}건.")


if __name__ == "__main__":
    db.init_db()
    backfill()
