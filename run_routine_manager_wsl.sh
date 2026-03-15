#!/usr/bin/env bash
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

if [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
  # shellcheck disable=SC1091
  source "$HOME/miniconda3/etc/profile.d/conda.sh"
elif [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
  # shellcheck disable=SC1091
  source "$HOME/anaconda3/etc/profile.d/conda.sh"
fi

if ! conda run -n routinmanager python -c "import streamlit, supabase, streamlit_sortables" >/dev/null 2>&1; then
  echo "[RoutineManager] 필수 패키지 설치를 진행합니다..."
  conda run -n routinmanager pip install -r requirements.txt
fi

echo "[RoutineManager] 서버를 시작합니다: http://localhost:8501"
conda run -n routinmanager streamlit run app.py --browser.gatherUsageStats false --server.headless true --server.port 8501
