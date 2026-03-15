# 🌸 Routine Manager

매일 해야 할 루틴을 등록하고,
날짜별로 완료 여부를 체크할 수 있는 심플한 루틴 관리 앱입니다.

## 기능
- 루틴 등록
- 요일별 루틴 설정 (월~일)
- 날짜별 체크리스트 관리
- 하루 전체 완료/전체 해제
- 완료율(%) 확인
- 최근 7일 기록 확인
- 연속 달성일 확인
- 백업 파일(JSON) 다운로드/복원

## 실행 방법
1. conda 환경 활성화
2. 패키지 설치
3. 앱 실행

```bash
conda activate routinmanager
pip install -r requirements.txt
streamlit run app.py --browser.gatherUsageStats false
```

실행 후 브라우저에서 안내되는 로컬 주소를 열면 됩니다.

## 주소를 더 예쁘게 쓰는 방법

로컬 실행 주소(`http://localhost:8501`)는 기본적으로 고정입니다.
대신 **배포 주소**를 쓰면 더 예쁜 URL을 사용할 수 있습니다.

추천: Streamlit Community Cloud
- 예: `https://routin-manager.streamlit.app`
- 장점: 다른 사람도 바로 접속 가능

즉,
- 내 PC에서만 사용: `http://localhost:8501`
- 다른 사람과 공유 + 예쁜 주소: 배포 URL 사용

## 다른 사람 컴퓨터에서도 가능한가?

가능합니다.
아래 둘 중 하나로 사용하면 됩니다.

1) GitHub에서 코드 내려받아 로컬 실행
2) 배포 URL(예: Streamlit Cloud)로 접속

WSL/Conda를 강제하지 않으려면,
각자 Python 환경(venv/conda)에서 `pip install -r requirements.txt` 후 실행하면 됩니다.

## 여러 컴퓨터에서 동일 상태 유지 (가장 쉬운 방법)

앱 사이드바의 **데이터 동기화** 기능을 쓰면 됩니다.

1) 기존 PC에서 `백업 파일 다운로드`
2) 다른 PC에서 앱 실행 후 `백업 파일 업로드` + `백업 복원`

이 방식이 가장 단순하고, 환경 차이(WSL/Windows/macOS)에도 안정적입니다.

추가로 자동화하고 싶다면,
- `.data` 폴더를 Dropbox/Google Drive/iCloud 같은 동기화 폴더에 두거나
- DB(Supabase/Neon)로 전환하는 방법이 있습니다.

## Supabase 자동 동기화 설정 (무료 플랜 가능)

앱은 Supabase 키가 설정되면 자동 동기화를 활성화합니다.

1) Supabase 프로젝트 생성
2) SQL Editor에서 아래 쿼리 실행

```sql
create table if not exists public.routine_manager_state (
	id text primary key,
	state jsonb not null,
	updated_at timestamptz not null default now()
);

alter table public.routine_manager_state enable row level security;

drop policy if exists "allow_all_select" on public.routine_manager_state;
drop policy if exists "allow_all_insert" on public.routine_manager_state;
drop policy if exists "allow_all_update" on public.routine_manager_state;

create policy "allow_all_select"
on public.routine_manager_state
for select
to anon
using (true);

create policy "allow_all_insert"
on public.routine_manager_state
for insert
to anon
with check (true);

create policy "allow_all_update"
on public.routine_manager_state
for update
to anon
using (true)
with check (true);
```

3) 프로젝트 루트에 `.streamlit/secrets.toml` 생성

```toml
SUPABASE_URL = "https://YOUR_PROJECT_REF.supabase.co"
SUPABASE_KEY = "YOUR_SUPABASE_ANON_KEY"
```

예시 파일: [.streamlit/secrets.toml.example](.streamlit/secrets.toml.example)

4) 앱 실행

```bash
streamlit run app.py --browser.gatherUsageStats false
```

정상 설정되면 사이드바에 `클라우드 자동 동기화: 활성화`가 표시됩니다.

## GitHub 업로드 정리

프로젝트는 GitHub에 올리기 좋게 정리되어 있습니다.
- 불필요 산출물 제외: [.gitignore](.gitignore)
- 실행 가이드 포함: [README.md](README.md)
- 빌드 산출물(`build/`, `dist/`, `*.spec`)은 저장소에서 제외

업로드 예시:

```bash
git init
git add .
git commit -m "feat: initial routine manager app"
git branch -M main
git remote add origin <YOUR_GITHUB_REPO_URL>
git push -u origin main
```

## Windows + WSL 실행

### A) 프로젝트 폴더에서 바로 실행 (권장)

- [run_routine_manager_windows.bat](run_routine_manager_windows.bat)
- [run_routine_manager_wsl.sh](run_routine_manager_wsl.sh)

`run_routine_manager_windows.bat`를 더블클릭하면 WSL에서 서버를 실행합니다.

### B) exe로 실행 (선택)

아래 빌드 스크립트로 exe를 만들 수 있습니다.
- [build_windows_exe.ps1](build_windows_exe.ps1)
- [run_routine_manager_windows_launcher.py](run_routine_manager_windows_launcher.py)

```powershell
cd "\\wsl.localhost\Ubuntu\home\kangjuheon\workspace\simple_projects\260316_routin_manager"
powershell -ExecutionPolicy Bypass -File .\build_windows_exe.ps1
```

주의:
- exe는 **프로젝트 폴더 안에서 실행**해야 경로를 정확히 찾습니다.
- exe만 단독으로 바탕화면에 옮겨 실행하면 프로젝트 경로를 못 찾을 수 있습니다.

## Linux(네이티브) 바탕화면 바로가기 만들기

아래 명령어를 한 번 실행하면 바탕화면에 실행 아이콘이 만들어집니다.

```bash
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
if [ -z "$DESKTOP_DIR" ] || [ "$DESKTOP_DIR" = "$HOME" ]; then
	if [ -d "$HOME/바탕화면" ]; then
		DESKTOP_DIR="$HOME/바탕화면"
	else
		DESKTOP_DIR="$HOME/Desktop"
	fi
fi

mkdir -p "$DESKTOP_DIR"
PROJECT_DIR="$(pwd)"

cat > "$DESKTOP_DIR/RoutineManager.desktop" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Routine Manager
Comment=루틴 매니저 서버 실행
Exec=$PROJECT_DIR/run_routine_manager.sh
Icon=utilities-terminal
Terminal=true
Categories=Utility;
EOF

chmod +x "$DESKTOP_DIR/RoutineManager.desktop"
```

- 아이콘 더블클릭으로 서버를 바로 실행할 수 있습니다.
- 실행하면 브라우저가 자동으로 열립니다(크롬이 있으면 크롬 우선).

## 데이터 저장 위치
- `.data/routines.json`
- `.data/logs.json`

앱을 다시 실행해도 데이터가 유지됩니다.
