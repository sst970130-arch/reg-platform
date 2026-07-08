"""
이미 저장된 첨부파일 중 HWP/HWPX 파일을 정리하는 1회성 스크립트.

- HWP/HWPX는 텍스트 추출이 안 되면서 용량만 차지하므로 더 이상 저장하지 않기로 했습니다
  (modules/mfds_sync.py의 _SKIP_EXTENSIONS 참고).
- 이미 내려받아둔 것들을 디스크에서 지우고 DB 행도 함께 삭제합니다.
- 실행: python scripts/cleanup_hwp_attachments.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import db

TARGET_EXTENSIONS = (".hwp", ".hwpx")


def cleanup():
    attachments = [
        a for a in db.get_all_attachments()
        if a["filename"].lower().endswith(TARGET_EXTENSIONS)
    ]
    freed_bytes = 0
    for a in attachments:
        path = os.path.join(db.UPLOAD_DIR, a["stored_path"])
        if os.path.exists(path):
            freed_bytes += os.path.getsize(path)
            os.remove(path)
        db.delete_attachment(a["id"])

    print(f"{len(attachments)}건의 HWP/HWPX 첨부파일 삭제, {freed_bytes / 1024 / 1024:.1f}MB 확보.")


if __name__ == "__main__":
    db.init_db()
    cleanup()
