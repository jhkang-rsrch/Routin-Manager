#!/usr/bin/env bash
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

if ! command -v conda >/dev/null 2>&1; then
	if [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
		# shellcheck disable=SC1091
		source "$HOME/miniconda3/etc/profile.d/conda.sh"
	elif [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
		# shellcheck disable=SC1091
		source "$HOME/anaconda3/etc/profile.d/conda.sh"
	fi
fi

if command -v google-chrome >/dev/null 2>&1; then
	export BROWSER=google-chrome
elif command -v chromium-browser >/dev/null 2>&1; then
	export BROWSER=chromium-browser
elif command -v chromium >/dev/null 2>&1; then
	export BROWSER=chromium
fi

if ! conda run -n routinmanager python -c "import streamlit, supabase, streamlit_sortables" >/dev/null 2>&1; then
	echo "[RoutineManager] 필수 패키지 설치를 진행합니다..."
	conda run -n routinmanager pip install -r requirements.txt
fi

conda run -n routinmanager streamlit run app.py --browser.gatherUsageStats false --server.headless false
