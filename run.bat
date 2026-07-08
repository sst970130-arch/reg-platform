@echo off
REM 이 파일을 더블클릭하면 자동으로 서버가 실행됩니다.
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo [안내] Python이 설치되어 있지 않은 것 같습니다.
  echo https://www.python.org/downloads/ 에서 Python을 먼저 설치해 주세요.
  echo 설치 화면 하단의 "Add Python to PATH" 체크박스를 꼭 체크해야 합니다.
  echo.
  pause
  exit /b 1
)

if not exist ".venv" (
  echo [1/3] 최초 실행입니다 - 필요한 프로그램 환경을 준비합니다. 1~2분 정도 걸릴 수 있어요...
  python -m venv .venv
)

call .venv\Scripts\activate.bat

echo [2/3] 필요한 패키지를 설치/확인합니다...
pip install -q -r requirements.txt

if not exist ".env" (
  echo [안내] .env 파일이 없어 .env.example을 복사해 새로 만듭니다.
  echo         AI 요약 기능을 쓰려면 .env 파일을 열어 ANTHROPIC_API_KEY 값을 넣어주세요.
  copy .env.example .env >nul
)

if not exist "data\app.db" (
  echo [안내] 처음 실행이라 데모용 샘플 문서 3건을 등록합니다 (검색 기능을 바로 확인해보실 수 있어요)...
  python sample_docs\generate_samples.py
  echo [안내] 밸리데이션 실무 해설 노트(초안) 5건도 함께 등록합니다...
  python scripts\seed_guide_notes.py
)

echo [3/3] 서버를 시작합니다.
echo.
echo   브라우저를 열고 아래 주소로 접속하세요:
echo   http://localhost:8000
echo.
echo   (이 검은 창을 닫으면 서버도 함께 꺼집니다. 계속 켜두세요.)
echo.
python app.py

pause
