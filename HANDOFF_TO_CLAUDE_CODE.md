# 사내 제약 R&D 규제 통합 플랫폼 — Claude Code 인계 문서

이 프로젝트는 Claude(Cowork)와의 대화에서 처음부터 구현되어, 클라우드 작업공간에서 실제로
실행·테스트까지 마친 상태입니다. 이 폴더(`reg-platform/`)를 Claude Code로 여신 뒤, 이 문서를
먼저 읽고 이어서 작업해 주세요. 원래 요청서, 지금까지의 의사결정, 구현 세부사항, 알려진 한계와
다음 할 일을 정리했습니다.

## 0. 원래 요청 (요약)

RA(인허가)팀이 약전 개정/식약처 고시 변경을 놓치지 않도록, 식약처 고시·Q&A·사내 세미나 자료를
한 곳에서 검색하고 AI가 요약·해설·실무 가이드(RA/QC·QA 팀별 액션 아이템)까지 보여주는 사내 전용
웹 플랫폼. 코딩 경험이 없는 요청자가 실행·유지보수까지 할 수 있어야 함. 원래 초안은 Streamlit
기반이었음.

## 1. 이미 확정된 의사결정 (요청자 답변 기준)

| 항목 | 결정 |
|---|---|
| 접근 권한 | 로그인 없이 전 직원 접근 가능 (RA/QC·QA 한정 로그인은 보류) |
| 문서·데이터 저장 위치 | 프로토타입은 클라우드/로컬에서 진행, 실제 배포 방식(사내 서버 vs 외부 클라우드)은 **미정 — Claude Code에서 사용자와 논의 필요** |
| 원문 PDF 저장/공개 | 업로드 원문 파일을 서버에 저장 **+ ** 식약처 원문 링크(URL)도 함께 등록 — 둘 다 지원하도록 이미 구현됨. 저작권 정책은 최종 미확정 |
| 신규 업데이트 알림 | 1단계(사이드바 "신규" 배지)만 구현. Teams/이메일 발송, 식약처 사이트 자동 크롤링은 **의도적으로 보류** (2단계) |

## 2. 기술 스택과 그 이유 — 중요

**Streamlit → Flask로 전환했습니다.** 이유: Cowork 클라우드 작업공간에서 `pip install streamlit`이
네트워크 정책(pypi.org 미허용)으로 막혀 있었기 때문입니다. Flask, pypdf, python-pptx,
scikit-learn, requests, python-dotenv는 이미 설치되어 있어 이것으로 실제 동작하는 앱을 만들고
끝까지 테스트할 수 있었습니다.

**Claude Code 환경에서 다시 고려할 점**: Claude Code 실행 환경은 보통 pip/PyPI 접근이 자유로울
가능성이 높습니다. 즉, 원한다면 Streamlit으로 다시 마이그레이션하는 것도 선택지입니다. 다만:
- 지금 Flask 버전은 이미 안정적으로 동작하고, 요청자가 직접 실행까지 검증했습니다.
- Flask 유지보수 난이도도 낮게 유지되도록 코드를 단순하게 짰습니다 (`templates/`의 HTML을
  직접 고치는 정도).
- **권장: 특별한 이유가 없다면 Flask를 유지**하고, 요청자가 Streamlit의 특정 장점(예: 더 빠른
  프로토타이핑 UI)을 원한다고 명시하지 않는 한 다시 갈아엎지 않는 것을 추천합니다.

데이터베이스는 별도 서버가 필요 없는 SQLite 파일 하나로 구현되어 있습니다 (`data/app.db`).

## 3. 폴더/코드 구조

```
app.py                        Flask 라우트 (/, /search, /admin, /admin/upload, /download/<id>)
modules/
  db.py                       SQLite 스키마 + CRUD. documents 테이블 하나로 고시/Q&A/세미나 통합 관리
  extract.py                  PDF(pypdf)/PPTX(python-pptx) 텍스트 추출
  search.py                   검색 + Q&A 파싱 + 세미나 자동 연결 (아래 4번 참고)
  ai_analysis.py              Claude API 직접 REST 호출 (SDK 미사용, requests로 구현)
templates/                    base.html(사이드바+레이아웃), index.html(검색+2단 결과), admin_upload.html
static/style.css              전체 스타일
sample_docs/                  데모용 가상 샘플 3건 생성 스크립트 (generate_samples.py) — 실제 식약처
                               문서 아님, 텍스트/레이아웃 검증용
run.sh / run.bat               Mac·Linux / Windows 실행 스크립트 (최초 실행 시 venv+패키지 자동 설치)
.env.example                   ANTHROPIC_API_KEY, ANTHROPIC_MODEL, FLASK_SECRET_KEY, PORT
```

`documents` 테이블 주요 컬럼: `category`(notice/qna/seminar), `title`, `team_tag`, `uploader`,
`presenter`, `event_date`, `source_url`, `original_filename`, `stored_path`, `extracted_text`,
`upload_date`. `modules/db.py`의 `NEW_BADGE_DAYS = 14`가 "신규" 배지 기준.

## 4. 구현하면서 발견하고 고친 버그 (재발 방지용 기록)

1. **한글 PDF 생성 시 폰트 문제**: reportlab 기본 Helvetica 폰트는 한글을 지원하지 않아 추출된
   텍스트가 `■■■`로 깨짐. `UnicodeCIDFont("HYSMyeongJo-Medium")`로 해결 (`sample_docs/generate_samples.py`).
2. **한국어 검색이 거의 안 되던 문제**: 조사가 단어에 붙는 한국어 특성상(예: "유예기간을")
   단어 단위 TF-IDF로는 "유예기간"으로 검색해도 매칭이 안 됨. → `TfidfVectorizer(analyzer="char_wb",
   ngram_range=(2,3))` 문자 n-gram 방식으로 전환해 해결 (`modules/search.py`의 `_make_vectorizer`).
   형태소 분석기(예: konlpy, mecab) 없이 쓸 수 있는 실용적 타협점입니다. 문서가 많아지면
   임베딩 기반 검색으로 고도화를 고려해볼 만합니다.
3. **Q&A 원문 파싱 실패**: 질문/답변 분리 정규식에서 질문 쪽은 `Q\d+` 패턴이 있었는데 답변 쪽에는
   `A\d+` 패턴이 빠져있어 "A1." 형태를 못 잡았음. `extract_qna_pairs`의 `ans_split` 정규식에 추가해 해결.

이 세 가지는 실제로 서버를 띄우고 검색을 실행해보며 발견한 것들이라, 비슷한 종류의 회귀가
생기지 않도록 수정 시 `python3 -m py_compile`뿐 아니라 실제 검색 결과를 눈으로 확인하는 걸
권장합니다.

## 5. 테스트 현황 (Cowork 클라우드 환경에서 검증됨)

- Flask 개발 서버(`python3 app.py`)를 백그라운드로 띄우고 `/`, `/search`, `/admin` 라우트를
  curl로 200 확인.
- 관리자 업로드: 텍스트 직접 입력 방식 + 실제 PDF 파일(multipart) 업로드 방식 둘 다 curl로
  end-to-end 테스트 완료 (텍스트 추출까지 정상 확인).
- 검색: "유예기간", "미생물한도", "총호기성생균수", "TSA 배지" 등 여러 키워드로 3개 샘플 문서
  (고시/QA/세미나) 모두가 상황에 맞게 매칭되는 것을 확인.
- AI 분석 폴백: API 키 미설정 시 정상적으로 원문 요약 대체 문구가 뜨는 것 확인. **가짜(무효) API
  키로 401 에러 경로도 테스트해 예외 처리가 깨지지 않고 안내 메시지로 대체되는 것 확인.**
- Playwright(헤드리스 Chromium)로 메인/검색결과/관리자 페이지 스크린샷을 찍어 레이아웃 육안 확인.
- **테스트 못한 것**: 실제 유효한 ANTHROPIC_API_KEY로 AI 요약/해설/액션아이템 생성 품질 확인
  (요청자가 아직 키를 발급하지 않음). `run.bat`은 로직만 리뷰했고 실제 Windows 환경에서
  더블클릭 실행은 검증되지 않음 — **Claude Code에서 우선적으로 확인해줄 것을 권장**.

## 6. 파일 전달 현황

- 전체 소스코드 zip + 사용 설명서(docx)를 Cowork 채팅으로 전달함.
- 이후 요청자가 Windows 데스크톱 `C:\Users\User\OneDrive\Desktop\reg-platform` 폴더를 연결해,
  폴더 구조를 그대로 유지한 채(19개 파일 + run.bat) 그 경로에 직접 저장함.
- **Claude Code는 아마 이 Desktop 경로(또는 요청자가 다시 지정하는 경로)에서 작업하게 될
  것입니다.** 이 markdown 파일도 같은 폴더에 저장되어 있습니다.

## 7. 다음 단계 제안 (우선순위 순)

1. **`run.bat` 실제 Windows 실행 검증** — 더블클릭 시 Python 유무 확인, venv 생성, 패키지 설치,
   샘플 데이터 자동 등록, 서버 기동까지 문제없이 되는지 요청자와 함께(또는 화면 공유로) 확인.
2. **실제 Anthropic API 키 연동 테스트** — 요청자가 console.anthropic.com에서 키를 발급하면
   `.env`에 넣고, 실제 식약처 문서로 AI 요약/Q&A 해설/실무 가이드 품질을 확인. 프롬프트
   (`modules/ai_analysis.py`의 `SYSTEM_PROMPT`)는 필요시 튜닝.
3. **실사용 데이터 등록** — 가상 샘플 대신 실제 식약처 고시/Q&A PDF, 사내 세미나 PPT 몇 건을
   등록해 텍스트 추출 품질과 검색 정확도를 검증.
4. **운영 배포 방식 결정** — 현재 `app.py`는 Flask 개발 서버(`app.run()`)로, 실제 운영에는
   부적합하다는 경고가 뜹니다. 사내 서버에 배포한다면 waitress(Windows) 또는 gunicorn(Linux)
   같은 프로덕션 WSGI 서버로 교체 필요. 사내망 전용 접근을 위한 방화벽/네트워크 구성은 IT팀과 논의.
5. **(선택) 로그인/권한 관리** — 현재는 전원 접근 가능. 추후 RA/QC·QA 한정이 필요해지면
   Flask-Login 등으로 확장 가능한 구조입니다 (라우트에 `@login_required`만 추가하면 됨).
6. **(선택) Teams/이메일 알림, 식약처 크롤링** — 요청서에 있었지만 의도적으로 보류한 2단계 기능.
   Teams는 Webhook URL, 이메일은 SMTP 정보가 필요. 크롤링은 식약처 사이트 이용약관 확인이 선행되어야 함.
7. **(선택) 검색 고도화** — 문서량이 많아지면 char n-gram TF-IDF의 한계(비슷한 글자가 많은
   문서끼리 노이즈 매칭)가 드러날 수 있음. 임베딩 기반 검색(예: OpenAI/Anthropic 임베딩 API +
   벡터 유사도) 전환을 고려.

## 8. 요청자 특성 참고

코딩 경험이 없는 분입니다. 코드를 크게 바꿀 때는 `run.bat`/`run.sh`처럼 더블클릭이나 한 줄
명령으로 실행 가능한 형태를 유지해 주시고, 변경 후에는 항상 실제로 실행해서 화면까지 확인하는
것을 권장합니다 (이 프로젝트에서 이미 여러 버그가 "일단 만들고 안 돌려봄"이 아니라 "실제로
돌려보고 발견"되었습니다).
