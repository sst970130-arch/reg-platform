"""
이미 저장된 문서들의 본문(extracted_text)에서 "지침서・안내서 제・개정 점검표"
(등록대상 체크리스트, "공무원용/민원인용" 구분 문답 등)와 "이 안내서는 ~~" 소개・면책
문구를 잘라내는 1회성 스크립트.

- modules/search.py의 drop_admin_frontmatter()를 그대로 재사용합니다 (앞으로 새로 수집되는
  문서는 modules/mfds_sync.py에서 이미 자동으로 이 처리를 거칩니다).
- 실행: python scripts/cleanup_admin_frontmatter.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import db, search


def cleanup():
    rows = db.get_all_documents()
    cleaned = 0
    for r in rows:
        original = r["extracted_text"] or ""
        stripped = search.drop_admin_frontmatter(original)
        if stripped != original:
            db.update_extracted_text(r["id"], stripped)
            cleaned += 1
            print(f"정리: [{r['id']}] {r['title'][:50]} ({len(original)} -> {len(stripped)}자)")

    print(f"\n총 {len(rows)}건 중 {cleaned}건 정리 완료.")


if __name__ == "__main__":
    db.init_db()
    cleanup()
