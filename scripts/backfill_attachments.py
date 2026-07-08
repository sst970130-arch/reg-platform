"""
이미 자동 수집된(RSS) 문서 중 첨부파일이 아직 없는 문서들에 대해, 식약처 원문 첨부파일을
소급해서 내려받고 텍스트를 추출하는 1회성 스크립트.

- 식약처 서버에 부담을 주지 않도록 문서 사이에 짧은 간격을 둡니다.
- 실행: python scripts/backfill_attachments.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import db, mfds_sync

DELAY_SECONDS = 0.4


def backfill():
    targets = [
        r for r in db.get_all_documents()
        if r["origin"] == "mfds_rss" and not db.has_attachments(r["id"])
    ]
    print(f"대상 문서: {len(targets)}건")

    done = 0
    failed = 0
    for r in targets:
        try:
            mfds_sync.download_and_store_attachments(r["id"], r["source_url"])
            if db.has_attachments(r["id"]):
                done += 1
                print(f"완료: [{r['board_name']}] {r['title'][:50]}")
            else:
                print(f"첨부파일 없음(또는 파싱 실패): [{r['board_name']}] {r['title'][:50]}")
        except Exception as e:
            failed += 1
            print(f"실패: [{r['board_name']}] {r['title'][:50]} - {e}")
        time.sleep(DELAY_SECONDS)

    print(f"\n총 {len(targets)}건 중 {done}건 첨부파일 저장 완료, {failed}건 실패.")


if __name__ == "__main__":
    db.init_db()
    backfill()
