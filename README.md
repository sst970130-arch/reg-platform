# 사내 제약 R&D 규제 통합 플랫폼

식약처 고시/Q&A, 사내 세미나 자료를 한 곳에서 검색하고 AI가 요약·해설·실무 가이드를 제공하는 사내 전용 웹 플랫폼입니다.

자세한 사용법은 함께 전달된 "사용 설명서.docx"를 참고하세요. 이 파일은 개발/유지보수용 간단 참고 문서입니다.

## 빠른 시작

**Windows**: `run.bat` 파일을 더블클릭하세요. 터미널을 직접 열 필요가 없습니다.

**Mac/Linux**:
```bash
./run.sh
```

또는 수동으로:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows는 .venv\Scripts\activate.bat
pip install -r requirements.txt
cp .env.example .env   # 그 후 .env를 열어 ANTHROPIC_API_KEY 입력
python3 app.py
```

브라우저에서 http://localhost:8000 접속.

## 폴더 구조

```
app.py                  메인 서버 (라우트 정의)
modules/
  db.py                 SQLite 데이터베이스 (문서 저장/조회)
  extract.py             PDF/PPTX 텍스트 추출
  search.py               검색(TF-IDF 문자 n-gram) + Q&A 파싱 + 세미나 연결
  ai_analysis.py           Claude API 호출 (요약/해설/실무가이드)
templates/               화면 (Jinja2 HTML)
static/style.css         스타일
data/                    SQLite DB + 업로드 원본 파일 저장 위치 (git에는 포함 안 됨)
sample_docs/              데모용 샘플 문서 생성 스크립트
```

## 기술 스택 선택 이유

원래 검토했던 Streamlit 대신 Flask를 사용했습니다. 실행 환경에 따라 Streamlit 설치가 막혀 있는 경우가 있어,
어디서나 안정적으로 설치·실행되는 표준 Flask + SQLite 조합으로 구현했습니다. 필요한 패키지가 적고,
코드 구조가 단순해 유지보수 부담은 Streamlit과 큰 차이가 없습니다.

## 주요 설계 메모

- **검색**: 한국어는 조사가 붙는 특성상(예: "유예기간을") 단어 단위 검색이 잘 안 되어, 문자 n-gram 기반
  TF-IDF(scikit-learn)로 구현했습니다. 완벽한 의미 기반 검색은 아니며, 문서가 많아지면 임베딩 기반
  검색으로 고도화하는 것을 고려해볼 수 있습니다.
- **AI 분석**: `.env`의 `ANTHROPIC_API_KEY`가 없으면 기능이 자동으로 비활성화되고, 검색된 원문 일부를
  대신 보여줍니다 (에러 없이 동작).
- **Q&A 원문 파싱**: "Q1.", "A1." 등의 패턴을 정규식으로 인식합니다. 원문 포맷이 크게 다르면 파싱이
  안 될 수 있는데, 이 경우 원문 앞부분을 그대로 보여주는 방식으로 자동 대체됩니다.
- **신규 알림**: 업로드일 기준 14일 이내 문서에 "신규" 배지가 표시됩니다 (`modules/db.py`의
  `NEW_BADGE_DAYS` 상수로 조절 가능).
