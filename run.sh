#!/bin/bash
# 실행 스크립트: ./run.sh 로 실행하면 됩니다.
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "[1/3] 최초 실행 - 가상환경(.venv)을 만듭니다..."
  python3 -m venv .venv
fi

source .venv/bin/activate

echo "[2/3] 필요한 패키지를 설치/확인합니다..."
pip install -q -r requirements.txt

if [ ! -f ".env" ]; then
  echo "안내: .env 파일이 없습니다. .env.example을 복사해 .env로 만들고 API 키를 입력해 주세요."
  cp .env.example .env
fi

if [ ! -f "data/app.db" ]; then
  echo "안내: 처음 실행이라 데모용 샘플 문서와 밸리데이션 실무 해설 노트(초안)를 등록합니다..."
  python3 sample_docs/generate_samples.py
  python3 scripts/seed_guide_notes.py
fi

echo "[3/3] 서버를 시작합니다. 브라우저에서 http://localhost:8000 으로 접속하세요."
python3 app.py
