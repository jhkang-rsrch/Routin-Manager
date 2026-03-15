import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from tkinter import Tk, messagebox

URL = "http://localhost:8501"


def _show_error(title: str, msg: str) -> None:
    root = Tk()
    root.withdraw()
    messagebox.showerror(title, msg)
    root.destroy()


def _show_info(title: str, msg: str) -> None:
    root = Tk()
    root.withdraw()
    messagebox.showinfo(title, msg)
    root.destroy()


def _is_port_open(host: str = "127.0.0.1", port: int = 8501, timeout: float = 0.5) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def _resolve_project_dir_wsl() -> str | None:
    if getattr(sys, "frozen", False):
        win_dir = Path(sys.executable).resolve().parent
    else:
        win_dir = Path(__file__).resolve().parent

    if not (win_dir / "run_routine_manager_wsl.sh").exists():
        return None

    try:
        out = subprocess.check_output(["wsl.exe", "wslpath", str(win_dir)], text=True)
        return out.strip() or None
    except Exception:
        return None


def main() -> int:
    project_dir_wsl = _resolve_project_dir_wsl()
    if not project_dir_wsl:
        _show_error(
            "Routine Manager",
            "프로젝트 폴더를 찾지 못했습니다.\nexe를 프로젝트 폴더 안에서 실행해 주세요.",
        )
        return 1

    run_script_wsl = f"{project_dir_wsl}/run_routine_manager_wsl.sh"
    cmd = [
        "wsl.exe",
        "bash",
        "-lc",
        f"cd '{project_dir_wsl}' && bash '{run_script_wsl}'",
    ]

    try:
        subprocess.Popen(cmd, creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
    except FileNotFoundError:
        _show_error("Routine Manager", "WSL(wsl.exe)을 찾을 수 없습니다.")
        return 1
    except Exception as exc:
        _show_error("Routine Manager", f"서버 시작 실패: {exc}")
        return 1

    for _ in range(60):
        if _is_port_open():
            webbrowser.open(URL)
            return 0
        time.sleep(1)

    webbrowser.open(URL)
    _show_info(
        "Routine Manager",
        "서버 시작이 지연되고 있습니다.\n잠시 후 브라우저 새로고침(F5) 해주세요.",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
