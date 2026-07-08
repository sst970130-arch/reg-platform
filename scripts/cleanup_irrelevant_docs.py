"""
자동 수집(RSS)된 문서 중 화장품/축산/식품/건강기능식품/위생용품/의료기기 등
의약품 업무와 무관한 항목을 정리하는 1회성 스크립트.

- modules/mfds_sync.py의 EXCLUDE_TITLE_KEYWORDS를 기준으로 판단합니다 (같은 기준을
  앞으로의 자동 수집에도 적용하도록 mfds_sync.sync_all()에 이미 반영되어 있습니다).
- 수동으로 등록한 문서(origin='manual')는 건드리지 않습니다.
- 실행: python scripts/cleanup_irrelevant_docs.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import db, mfds_sync


def cleanup():
    rows = [r for r in db.get_all_documents() if r["origin"] == "mfds_rss"]
    to_delete = [r for r in rows if mfds_sync.is_excluded(r["title"])]

    for r in to_delete:
        print(f"삭제: [{r['board_name']}] {r['title']}")
        db.delete_document(r["id"])

    print(f"\n총 {len(to_delete)}건 삭제 완료 (자동수집 {len(rows)}건 중).")


if __name__ == "__main__":
    db.init_db()
    cleanup()
