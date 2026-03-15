import hashlib
import html
import importlib
import json
import os
import re
from calendar import monthrange
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import streamlit as st

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / ".data"
ROUTINES_FILE = DATA_DIR / "routines.json"
LOGS_FILE = DATA_DIR / "logs.json"
DEVICE_SESSION_FILE = DATA_DIR / "device_session.json"
UI_SETTINGS_FILE = DATA_DIR / "ui_settings.json"
SUPABASE_CONFIG_FILE = BASE_DIR / "supabase_config.json"
WEEKDAY_OPTIONS = ["월", "화", "수", "목", "금", "토", "일"]
CALENDAR_START_OPTIONS = ["월요일 시작", "일요일 시작"]
STATUS_OPTIONS = ["시작전", "진행중", "완료"]
MAIN_VIEW_OPTIONS = ["일간 보기", "주간 보기", "월간 보기"]
LANGUAGE_OPTIONS = ["한국어", "English"]
STATE_TABLE = "routine_manager_state"
USERS_TABLE = "routine_manager_users"


def default_profile(username: str) -> dict:
    return {
        "nickname": username,
        "bio": "",
        "share_progress": True,
    }


def normalize_nickname(value: str) -> str:
    compact = " ".join(value.strip().split())
    return compact[:30]


def validate_nickname(nickname: str) -> tuple[bool, str]:
    name = normalize_nickname(nickname)
    if len(name) < 2:
        return False, "닉네임은 2자 이상이어야 합니다."
    if len(name) > 30:
        return False, "닉네임은 30자 이하여야 합니다."
    if not re.fullmatch(r"[0-9A-Za-z가-힣ㄱ-ㅎㅏ-ㅣ _\-.]+", name):
        return False, "닉네임은 한글/영문/숫자/공백/-/_/. 만 사용할 수 있습니다."
    return True, ""


def normalize_profile(username: str, profile: Any) -> dict:
    base = default_profile(username)
    if not isinstance(profile, dict):
        return base
    nickname = normalize_nickname(str(profile.get("nickname", username)).strip())
    if not nickname:
        nickname = username
    bio = str(profile.get("bio", "")).strip()
    return {
        "nickname": nickname[:30],
        "bio": bio[:200],
        "share_progress": bool(profile.get("share_progress", True)),
    }


def default_social_state() -> dict:
    return {
        "friends": [],
        "incoming": [],
        "outgoing": [],
        "blocked": [],
    }


def normalize_social_state(social: Any) -> dict:
    base = default_social_state()
    if not isinstance(social, dict):
        return base

    normalized = {}
    for key in ("friends", "incoming", "outgoing", "blocked"):
        raw = social.get(key, [])
        if not isinstance(raw, list):
            normalized[key] = []
            continue
        cleaned: list[str] = []
        seen = set()
        for item in raw:
            if not isinstance(item, str):
                continue
            u = item.strip()
            if not u:
                continue
            lower_u = u.lower()
            if lower_u in seen:
                continue
            seen.add(lower_u)
            cleaned.append(u)
        normalized[key] = cleaned
    return normalized


def remove_username(values: list[str], target: str) -> list[str]:
    target_lower = target.strip().lower()
    return [v for v in values if v.strip().lower() != target_lower]


def add_username(values: list[str], target: str) -> list[str]:
    cleaned = remove_username(values, target)
    cleaned.append(target.strip())
    return cleaned


def is_nickname_available(client: Any, nickname: str, except_username: str = "") -> tuple[bool, str]:
    target = normalize_nickname(nickname).lower()
    if not target:
        return False, "닉네임을 입력해 주세요."
    try:
        result = client.table(STATE_TABLE).select("id,state").execute()
        rows = result.data or []
        for row in rows:
            state_id = str(row.get("id", ""))
            if not state_id.startswith("user_"):
                continue
            owner = state_id[5:]
            if except_username and owner.lower() == except_username.lower():
                continue
            profile = normalize_profile(owner, (row.get("state") or {}).get("profile"))
            if profile.get("nickname", "").strip().lower() == target:
                return False, "이미 사용 중인 닉네임입니다."
        return True, ""
    except Exception as exc:
        return False, f"닉네임 확인 실패: {exc}"


def find_username_by_nickname(client: Any, nickname: str) -> tuple[str, str]:
    target = normalize_nickname(nickname).lower()
    if not target:
        return "", "닉네임을 입력해 주세요."
    try:
        result = client.table(STATE_TABLE).select("id,state").execute()
        rows = result.data or []
        for row in rows:
            state_id = str(row.get("id", ""))
            if not state_id.startswith("user_"):
                continue
            owner = state_id[5:]
            profile = normalize_profile(owner, (row.get("state") or {}).get("profile"))
            if profile.get("nickname", "").strip().lower() == target:
                return owner, ""
        return "", "해당 닉네임의 사용자를 찾을 수 없습니다."
    except Exception as exc:
        return "", f"닉네임 조회 실패: {exc}"


def get_user_nickname(client: Any, username: str) -> str:
    bundle, err = get_user_state_bundle(client, username)
    if err:
        return username
    profile = normalize_profile(username, bundle.get("profile"))
    return profile.get("nickname", username)


def ensure_data_files() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not ROUTINES_FILE.exists():
        ROUTINES_FILE.write_text("[]", encoding="utf-8")
    if not LOGS_FILE.exists():
        LOGS_FILE.write_text("{}", encoding="utf-8")
    if not DEVICE_SESSION_FILE.exists():
        DEVICE_SESSION_FILE.write_text("{}", encoding="utf-8")
    if not UI_SETTINGS_FILE.exists():
        UI_SETTINGS_FILE.write_text("{}", encoding="utf-8")


def load_routines() -> list[dict]:
    ensure_data_files()
    return json.loads(ROUTINES_FILE.read_text(encoding="utf-8"))


def save_routines(routines: list[dict]) -> None:
    ROUTINES_FILE.write_text(json.dumps(routines, ensure_ascii=False, indent=2), encoding="utf-8")


def load_logs() -> dict:
    ensure_data_files()
    return json.loads(LOGS_FILE.read_text(encoding="utf-8"))


def save_logs(logs: dict) -> None:
    LOGS_FILE.write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8")


def load_ui_settings() -> dict:
    ensure_data_files()
    defaults = {
        "auto_rollover_todos": False,
        "week_start_option": CALENDAR_START_OPTIONS[0],
        "default_main_view_mode": MAIN_VIEW_OPTIONS[0],
        "language": LANGUAGE_OPTIONS[0],
    }
    try:
        data = json.loads(UI_SETTINGS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return defaults
        merged = defaults | data
        if merged.get("week_start_option") not in CALENDAR_START_OPTIONS:
            merged["week_start_option"] = CALENDAR_START_OPTIONS[0]
        if merged.get("default_main_view_mode") not in MAIN_VIEW_OPTIONS:
            merged["default_main_view_mode"] = MAIN_VIEW_OPTIONS[0]
        if merged.get("language") not in LANGUAGE_OPTIONS:
            merged["language"] = LANGUAGE_OPTIONS[0]
        merged["auto_rollover_todos"] = bool(merged.get("auto_rollover_todos", False))
        return merged
    except Exception:
        return defaults


def save_ui_settings(settings: dict) -> None:
    normalized = {
        "auto_rollover_todos": bool(settings.get("auto_rollover_todos", False)),
        "week_start_option": settings.get("week_start_option", CALENDAR_START_OPTIONS[0]),
        "default_main_view_mode": settings.get("default_main_view_mode", MAIN_VIEW_OPTIONS[0]),
        "language": settings.get("language", LANGUAGE_OPTIONS[0]),
    }
    if normalized["week_start_option"] not in CALENDAR_START_OPTIONS:
        normalized["week_start_option"] = CALENDAR_START_OPTIONS[0]
    if normalized["default_main_view_mode"] not in MAIN_VIEW_OPTIONS:
        normalized["default_main_view_mode"] = MAIN_VIEW_OPTIONS[0]
    if normalized["language"] not in LANGUAGE_OPTIONS:
        normalized["language"] = LANGUAGE_OPTIONS[0]
    UI_SETTINGS_FILE.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")


def get_active_routines(routines: list[dict]) -> list[dict]:
    return [r for r in routines if r.get("active", True) and r.get("mode", "routine") == "routine"]


def get_active_todos(routines: list[dict]) -> list[dict]:
    return [r for r in routines if r.get("active", True) and r.get("mode", "routine") == "todo"]


def get_active_items(routines: list[dict]) -> list[dict]:
    return [r for r in routines if r.get("active", True)]


def get_inactive_routines(routines: list[dict]) -> list[dict]:
    return [r for r in routines if not r.get("active", True) and r.get("mode", "routine") == "routine"]


def get_inactive_todos(routines: list[dict]) -> list[dict]:
    return [r for r in routines if not r.get("active", True) and r.get("mode", "routine") == "todo"]


def normalize_routines(routines: list[dict]) -> tuple[list[dict], bool]:
    changed = False
    normalized: list[dict] = []
    for routine in routines:
        item = dict(routine)
        mode = item.get("mode")
        if mode not in {"routine", "todo"}:
            item["mode"] = "routine"
            changed = True

        weekdays = item.get("weekdays")
        if not isinstance(weekdays, list):
            item["weekdays"] = list(range(7))
            changed = True
        else:
            valid_days = sorted({int(d) for d in weekdays if isinstance(d, int) and 0 <= d <= 6})
            if len(valid_days) != len(weekdays):
                changed = True
            item["weekdays"] = valid_days

        tags = item.get("tags")
        if not isinstance(tags, list):
            item["tags"] = []
            changed = True
        else:
            cleaned_tags = []
            seen = set()
            for tag in tags:
                if not isinstance(tag, str):
                    changed = True
                    continue
                normalized_tag = tag.strip()
                if not normalized_tag:
                    changed = True
                    continue
                lowered = normalized_tag.lower()
                if lowered in seen:
                    changed = True
                    continue
                seen.add(lowered)
                cleaned_tags.append(normalized_tag)
            if cleaned_tags != tags:
                changed = True
            item["tags"] = cleaned_tags

        todo_date = item.get("todo_date")
        if item.get("mode") == "todo":
            if not isinstance(todo_date, str):
                item["todo_date"] = date.today().isoformat()
                changed = True
            else:
                try:
                    date.fromisoformat(todo_date)
                except Exception:
                    item["todo_date"] = date.today().isoformat()
                    changed = True
        else:
            if "todo_date" in item:
                item.pop("todo_date", None)
                changed = True

        normalized.append(item)
    return normalized, changed


def get_routines_for_date(routines: list[dict], target: date) -> list[dict]:
    weekday = target.weekday()
    target_key = target.isoformat()
    filtered: list[dict] = []
    for routine in routines:
        mode = routine.get("mode", "routine")
        if mode == "todo":
            if routine.get("todo_date") == target_key:
                filtered.append(routine)
        else:
            if weekday in routine.get("weekdays", list(range(7))):
                filtered.append(routine)
    return filtered


def weekday_label(days: list[int]) -> str:
    if len(days) == 7:
        return "매일"
    if not days:
        return "설정 없음"
    return ", ".join(WEEKDAY_OPTIONS[d] for d in sorted(days))


def weekday_checkbox_selector(key_prefix: str, default_days: list[int]) -> list[int]:
    selected: list[int] = []
    row_sizes = [4, 4]
    start = 0
    for row_size in row_sizes:
        cols = st.columns(row_size)
        for col_idx in range(row_size):
            idx = start + col_idx
            if idx >= len(WEEKDAY_OPTIONS):
                break
            day_name = WEEKDAY_OPTIONS[idx]
            checked = cols[col_idx].checkbox(day_name, value=idx in default_days, key=f"{key_prefix}_{idx}")
            if checked:
                selected.append(idx)
        start += row_size
    return selected


def calendar_weekday_order(start_option: str) -> tuple[list[int], int]:
    if start_option == "일요일 시작":
        return [6, 0, 1, 2, 3, 4, 5], 6
    return [0, 1, 2, 3, 4, 5, 6], 0


def add_months(base: date, months: int) -> date:
    month_index = (base.month - 1) + months
    year = base.year + month_index // 12
    month = (month_index % 12) + 1
    day = min(base.day, monthrange(year, month)[1])
    return date(year, month, day)


def week_of_month(target: date, week_start_idx: int) -> int:
    first_day = target.replace(day=1)
    first_offset = (first_day.weekday() - week_start_idx) % 7
    return ((target.day + first_offset - 1) // 7) + 1


def parse_tag_input(raw_text: str) -> list[str]:
    seen = set()
    tags: list[str] = []
    for part in raw_text.replace("\n", ",").split(","):
        tag = part.strip()
        if not tag:
            continue
        lowered = tag.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        tags.append(tag)
    return tags


def tags_label(tags: list[str]) -> str:
    if not tags:
        return "태그 없음"
    return ", ".join(tags)


def collect_all_tags(routines: list[dict]) -> list[str]:
    tags: set[str] = set()
    for routine in routines:
        for tag in routine.get("tags", []):
            if isinstance(tag, str) and tag.strip():
                tags.add(tag.strip())
    return sorted(tags)


def filter_routines_by_tags(routines: list[dict], selected_tags: list[str]) -> list[dict]:
    if not selected_tags:
        return routines
    selected_set = {t.lower() for t in selected_tags}
    filtered = []
    for routine in routines:
        routine_tags = {t.lower() for t in routine.get("tags", []) if isinstance(t, str)}
        if routine_tags & selected_set:
            filtered.append(routine)
    return filtered


def day_progress(routines: list[dict], logs: dict, target: date) -> tuple[int, int, int]:
    target_routines = get_routines_for_date(routines, target)
    target_ids = {r["id"] for r in target_routines}
    day_log = logs.get(target.isoformat(), {})
    done = sum(1 for rid in target_ids if status_from_log_value(day_log.get(rid, "시작전")) == "완료")
    total = len(target_ids)
    ratio = int((done / total) * 100) if total else 0
    return done, total, ratio


def _truncate_line(text: str, max_len: int = 18) -> str:
    t = str(text).strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 3] + "..."


def progress_color_token(total: int, ratio: int) -> str:
    if total == 0:
        return "⚪"
    if ratio >= 100:
        return "🟢"
    if ratio >= 70:
        return "🟡"
    return "🔴"


def mini_progress_bar(total: int, ratio: int, width: int = 8) -> str:
    if total == 0:
        return "□" * width
    filled = max(0, min(width, round((ratio / 100) * width)))
    return "■" * filled + "□" * (width - filled)


def calendar_preview_html(routines: list[dict], target: date) -> str:
    day_items = get_routines_for_date(routines, target)
    if not day_items:
        return "<div class='cal-items empty'>일정 없음</div>"
    names = [str(item.get("name", "")).strip() for item in day_items if str(item.get("name", "")).strip()]
    if not names:
        return "<div class='cal-items empty'>일정 없음</div>"
    lines = "<br>".join(html.escape(f"• {_truncate_line(name)}") for name in names)
    return f"<div class='cal-items'>{lines}</div>"


def list_box_height_for_count(max_items: int) -> int:
    return max(62, min(220, 20 + max(1, max_items) * 17))


def day_items_list_html(routines: list[dict], target: date, max_len: int = 20, min_height: int = 78) -> str:
    day_items = get_routines_for_date(routines, target)
    if not day_items:
        return f"<div class='cal-list-box' style='min-height:{min_height}px'><div class='cal-list-empty'>일정 없음</div></div>"
    names = [str(item.get("name", "")).strip() for item in day_items if str(item.get("name", "")).strip()]
    if not names:
        return f"<div class='cal-list-box' style='min-height:{min_height}px'><div class='cal-list-empty'>일정 없음</div></div>"
    lines = "".join(f"<div class='cal-list-line'>• {html.escape(_truncate_line(name, max_len))}</div>" for name in names)
    return f"<div class='cal-list-box' style='min-height:{min_height}px'>{lines}</div>"


def build_calendar_card_html(title: str, color_token: str, bar_text: str, preview_html: str, href: str) -> str:
    return (
        f"<a class='cal-card-link' href='{href}'>"
        f"<div class='cal-title'>{html.escape(title)}</div>"
        f"<div class='cal-meta'>{html.escape(color_token)} {html.escape(bar_text)}</div>"
        "<div class='cal-sep'></div>"
        f"{preview_html}"
        "</a>"
    )


def status_from_log_value(value: Any) -> str:
    if value is True:
        return "완료"
    if value is False or value is None:
        return "시작전"
    if isinstance(value, str) and value in STATUS_OPTIONS:
        return value
    return "시작전"


def save_device_session(username: str) -> None:
    ensure_data_files()
    DEVICE_SESSION_FILE.write_text(json.dumps({"last_username": username, "auto_login": True}, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_device_session() -> None:
    ensure_data_files()
    DEVICE_SESSION_FILE.write_text("{}", encoding="utf-8")


def load_device_session_username() -> str:
    ensure_data_files()
    try:
        session = json.loads(DEVICE_SESSION_FILE.read_text(encoding="utf-8"))
        if session.get("auto_login") and isinstance(session.get("last_username"), str):
            return session["last_username"].strip()
        return ""
    except Exception:
        return ""


def user_exists(client: Any, username: str) -> bool:
    try:
        result = client.table(USERS_TABLE).select("username").eq("username", username).limit(1).execute()
        return bool(result.data)
    except Exception:
        return False


def rollover_incomplete_todos(routines: list[dict], logs: dict, reference_date: date) -> bool:
    changed = False
    target_key = reference_date.isoformat()
    for item in routines:
        if not item.get("active", True) or item.get("mode", "routine") != "todo":
            continue
        todo_date = item.get("todo_date")
        if not isinstance(todo_date, str) or todo_date >= target_key:
            continue
        item_status = status_from_log_value(logs.get(todo_date, {}).get(item["id"], "시작전"))
        if item_status != "완료":
            item["todo_date"] = target_key
            changed = True
    return changed


def render_status_board(routines_for_day: list[dict], logs_for_day: dict, date_key: str) -> tuple[dict, bool]:
    changed = False
    if not routines_for_day:
        return logs_for_day, changed

    token_to_rid: dict[str, str] = {}
    rid_to_token: dict[str, str] = {}
    used_tokens: set[str] = set()
    for routine in routines_for_day:
        rid = routine["id"]
        tag_text = " ".join(f"#{tag}" for tag in routine.get("tags", []))
        if tag_text:
            base = f"{routine['name']}\n{tag_text}"
        else:
            base = routine["name"]
        token = base if base else routine["name"]
        if token in used_tokens:
            token = f"{token} ({rid[:4]})"
        used_tokens.add(token)
        token_to_rid[token] = rid
        rid_to_token[rid] = token

    containers = []
    for status in STATUS_OPTIONS:
        items = []
        for routine in routines_for_day:
            rid = routine["id"]
            current_status = status_from_log_value(logs_for_day.get(rid, "시작전"))
            if current_status == status:
                items.append(rid_to_token[rid])
        containers.append({"header": f"{status} ({len(items)})", "items": items})
    sortables_module = None
    try:
        sortables_module = importlib.import_module("streamlit_sortables")
    except Exception:
        sortables_module = None

    if sortables_module:
        sort_items = getattr(sortables_module, "sort_items")
        # 최소 높이는 낮게 두고, 실제 높이는 아이템이 있는 컬럼에 맞춰 자연스럽게 늘어나게 둔다.
        body_min_height_px = 56
        custom_style = """
        .sortable-component * { box-sizing: border-box; }
        .sortable-component { border-radius: 14px; background: #f7f3ff; padding: 8px; width: 100%; }
        .sortable-component.horizontal { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; align-items: stretch; width: 100%; }
        .sortable-component.horizontal > .sortable-container { border-radius: 16px; overflow: hidden; min-width: 0 !important; width: 100% !important; height: 100% !important; display: flex; flex-direction: column; }
        .sortable-component.horizontal > .sortable-container:nth-of-type(1) { background: #fff4f4 !important; border: 1px solid #f3c4c4 !important; }
        .sortable-component.horizontal > .sortable-container:nth-of-type(2) { background: #eef6ff !important; border: 1px solid #bfdcff !important; }
        .sortable-component.horizontal > .sortable-container:nth-of-type(3) { background: #eefcf3 !important; border: 1px solid #b7e7c7 !important; }
        .sortable-container-header { color: #5a4a86; font-weight: 700; margin: 6px; padding: 8px 10px; text-align: center; border-radius: 12px; }
        .sortable-component.horizontal > .sortable-container:nth-of-type(1) .sortable-container-header { background: #ffdede !important; color: #a03f3f !important; }
        .sortable-component.horizontal > .sortable-container:nth-of-type(2) .sortable-container-header { background: #dcecff !important; color: #2d5f9a !important; }
        .sortable-component.horizontal > .sortable-container:nth-of-type(3) .sortable-container-header { background: #daf5e4 !important; color: #2d7a49 !important; }
        .sortable-container-body { border-radius: 10px; min-height: __BODY_MIN_HEIGHT__px; margin: 0 6px 6px; padding: 6px; overflow: hidden; width: calc(100% - 12px); flex: 1; }
        .sortable-component.horizontal > .sortable-container:nth-of-type(1) .sortable-container-body { background: #fff9f9 !important; }
        .sortable-component.horizontal > .sortable-container:nth-of-type(2) .sortable-container-body { background: #f8fbff !important; }
        .sortable-component.horizontal > .sortable-container:nth-of-type(3) .sortable-container-body { background: #f7fff9 !important; }
        .sortable-container-body:empty::before { content: '비어 있음'; display: flex; align-items: center; justify-content: center; min-height: __BODY_MIN_HEIGHT__px; color: #9a93b3; font-size: 0.85rem; border: 1px dashed #d9d3ef; border-radius: 10px; }
        .sortable-item, .sortable-item:hover { color: #4d3f73 !important; border-radius: 10px; width: 100% !important; max-width: 100% !important; height: auto !important; min-height: 0 !important; margin: 4px 0 !important; padding: 4px 10px !important; white-space: pre-line !important; word-break: break-word; display: block !important; font-family: "Comic Sans MS", "Trebuchet MS", sans-serif !important; font-size: 0.78rem !important; }
        .sortable-item::first-line { font-family: "Segoe UI", "Noto Sans KR", sans-serif !important; font-size: 1rem !important; font-weight: 700; }
        .sortable-component.horizontal > .sortable-container:nth-of-type(1) .sortable-item, .sortable-component.horizontal > .sortable-container:nth-of-type(1) .sortable-item:hover { background: #ffe3e3 !important; border: 1px solid #f1bebe !important; }
        .sortable-component.horizontal > .sortable-container:nth-of-type(2) .sortable-item, .sortable-component.horizontal > .sortable-container:nth-of-type(2) .sortable-item:hover { background: #dcecff !important; border: 1px solid #b3d3ff !important; }
        .sortable-component.horizontal > .sortable-container:nth-of-type(3) .sortable-item, .sortable-component.horizontal > .sortable-container:nth-of-type(3) .sortable-item:hover { background: #dcf7e6 !important; border: 1px solid #a8dfbb !important; }
        """
        custom_style = custom_style.replace("__BODY_MIN_HEIGHT__", str(body_min_height_px))
        header_signature = "_".join(str(len(c["items"])) for c in containers)
        sorted_containers = sort_items(containers, multi_containers=True, direction="horizontal", custom_style=custom_style, key=f"status_board_v8_{date_key}_{header_signature}")
        for container in sorted_containers:
            status_header = container["header"]
            status = next((s for s in STATUS_OPTIONS if str(status_header).startswith(s)), "")
            if not status:
                continue
            for token in container["items"]:
                rid = token_to_rid.get(token)
                if not rid:
                    continue
                if status_from_log_value(logs_for_day.get(rid, "시작전")) != status:
                    logs_for_day[rid] = status
                    changed = True
    else:
        st.warning("드래그 보드 라이브러리를 찾지 못했습니다. 아래 선택 박스로 상태를 바꿀 수 있습니다.")
        for routine in routines_for_day:
            rid = routine["id"]
            current_status = status_from_log_value(logs_for_day.get(rid, "시작전"))
            status = st.selectbox(
                f"{routine['name']} 상태",
                STATUS_OPTIONS,
                index=STATUS_OPTIONS.index(current_status),
                key=f"status_picker_{date_key}_{rid}",
            )
            if status != current_status:
                logs_for_day[rid] = status
                changed = True

    return logs_for_day, changed


def render_readonly_status_board(routines_for_day: list[dict], logs_for_day: dict) -> None:
    grouped: dict[str, list[dict]] = {status: [] for status in STATUS_OPTIONS}
    for item in routines_for_day:
        current_status = status_from_log_value(logs_for_day.get(item["id"], "시작전"))
        grouped.setdefault(current_status, []).append(item)

    cols = st.columns(3)
    for idx, status in enumerate(STATUS_OPTIONS):
        items = grouped.get(status, [])
        cols[idx].markdown(f"**{status} ({len(items)})**")
        if not items:
            cols[idx].caption("비어 있음")
            continue
        for item in items:
            item_tags = " ".join(f"#{t}" for t in item.get("tags", []))
            item_mode = "할일" if item.get("mode", "routine") == "todo" else "루틴"
            cols[idx].markdown(
                f"""
                <div class='routine-card'>
                    <div class='routine-name'>{item['name']}</div>
                    <div class='routine-meta'>{item_mode}{' · ' + item_tags if item_tags else ''}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def pastel_tone_for_ratio(total: int, ratio: int) -> tuple[str, str, str]:
    if total == 0:
        return "#f5f3ff", "#ddd6fe", "#6b5f8f"
    if ratio >= 100:
        return "#dcfce7", "#86efac", "#166534"
    if ratio >= 70:
        return "#fef9c3", "#fde68a", "#854d0e"
    return "#ffe4e6", "#fecdd3", "#9f1239"


def build_backup_payload(routines: list[dict], logs: dict, settings: dict | None = None) -> dict:
    return {
        "version": 1,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "routines": routines,
        "logs": logs,
        "settings": settings if isinstance(settings, dict) else load_ui_settings(),
    }


def apply_backup_payload(payload: dict, cloud_client=None, username: str = "local") -> tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "백업 파일 형식이 올바르지 않습니다."
    routines = payload.get("routines")
    logs = payload.get("logs")
    settings = payload.get("settings")
    if not isinstance(routines, list) or not isinstance(logs, dict):
        return False, "백업 파일에 routines/logs 데이터가 없습니다."
    normalized, _ = normalize_routines(routines)
    if isinstance(settings, dict):
        save_ui_settings(settings)
    ok, message = persist_state(normalized, logs, cloud_client, username, settings if isinstance(settings, dict) else None)
    if not ok:
        return False, message
    return True, "백업 데이터 복원이 완료되었습니다."


def get_supabase_client() -> tuple[Any, str]:
    try:
        supabase_module = importlib.import_module("supabase")
        create_client = getattr(supabase_module, "create_client")
    except Exception:
        return None, "supabase 패키지가 설치되지 않았습니다."

    url, key = "", ""

    if SUPABASE_CONFIG_FILE.exists():
        try:
            cfg = json.loads(SUPABASE_CONFIG_FILE.read_text(encoding="utf-8"))
            url = cfg.get("url", "")
            key = cfg.get("key", "")
        except Exception:
            pass

    if not url or not key:
        try:
            url = st.secrets.get("SUPABASE_URL", "")
            key = st.secrets.get("SUPABASE_KEY", "")
        except Exception:
            pass

    if not url:
        url = os.getenv("SUPABASE_URL", "")
    if not key:
        key = os.getenv("SUPABASE_KEY", "")

    if not url or not key:
        return None, "Supabase 연결 정보가 없습니다."

    try:
        return create_client(url, key), ""
    except Exception as exc:
        return None, f"Supabase 클라이언트 생성 실패: {exc}"


def load_cloud_state(client: Any, username: str) -> tuple[Any, str]:
    try:
        state_id = f"user_{username}"
        result = client.table(STATE_TABLE).select("state").eq("id", state_id).limit(1).execute()
        rows = result.data or []
        if not rows:
            return None, ""
        state = rows[0].get("state")
        if not isinstance(state, dict):
            return None, "클라우드 데이터 형식이 올바르지 않습니다."
        return state, ""
    except Exception as exc:
        return None, f"클라우드 데이터 조회 실패: {exc}"


def save_cloud_state(
    client: Any,
    routines: list[dict],
    logs: dict,
    username: str,
    settings: dict | None = None,
    profile: dict | None = None,
    social: dict | None = None,
) -> tuple[bool, str]:
    existing_state, _ = load_cloud_state(client, username)
    merged_state = existing_state if isinstance(existing_state, dict) else {}
    merged_state["version"] = 1
    merged_state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    merged_state["routines"] = routines
    merged_state["logs"] = logs
    merged_state["settings"] = settings if isinstance(settings, dict) else load_ui_settings()
    if isinstance(profile, dict):
        merged_state["profile"] = profile
    elif not isinstance(merged_state.get("profile"), dict):
        merged_state["profile"] = default_profile(username)
    if isinstance(social, dict):
        merged_state["social"] = social
    elif not isinstance(merged_state.get("social"), dict):
        merged_state["social"] = default_social_state()

    payload = {
        "id": f"user_{username}",
        "state": merged_state,
    }
    try:
        client.table(STATE_TABLE).upsert(payload, on_conflict="id").execute()
        return True, ""
    except Exception as exc:
        return False, f"클라우드 저장 실패: {exc}"


def get_user_state_bundle(client: Any, username: str) -> tuple[dict, str]:
    state, error = load_cloud_state(client, username)
    if error:
        return {}, error
    if not isinstance(state, dict):
        return {
            "routines": [],
            "logs": {},
            "settings": load_ui_settings(),
            "profile": default_profile(username),
            "social": default_social_state(),
        }, ""
    return {
        "routines": state.get("routines", []),
        "logs": state.get("logs", {}),
        "settings": state.get("settings", load_ui_settings()),
        "profile": normalize_profile(username, state.get("profile")),
        "social": normalize_social_state(state.get("social")),
    }, ""


def send_friend_request(client: Any, sender: str, receiver: str) -> tuple[bool, str]:
    receiver = receiver.strip()
    if not receiver:
        return False, "친구 아이디를 입력해 주세요."
    if sender.lower() == receiver.lower():
        return False, "자기 자신에게는 친구 요청을 보낼 수 없습니다."
    if not user_exists(client, receiver):
        return False, "해당 아이디를 찾을 수 없습니다."

    sender_bundle, err1 = get_user_state_bundle(client, sender)
    if err1:
        return False, err1
    receiver_bundle, err2 = get_user_state_bundle(client, receiver)
    if err2:
        return False, err2

    sender_social = normalize_social_state(sender_bundle.get("social"))
    receiver_social = normalize_social_state(receiver_bundle.get("social"))

    if any(u.lower() == receiver.lower() for u in sender_social["friends"]):
        return False, "이미 친구입니다."
    if any(u.lower() == receiver.lower() for u in sender_social["outgoing"]):
        return False, "이미 요청을 보냈습니다."
    if any(u.lower() == sender.lower() for u in receiver_social["blocked"]):
        return False, "상대방이 요청을 받을 수 없는 상태입니다."

    sender_social["outgoing"] = add_username(sender_social["outgoing"], receiver)
    receiver_social["incoming"] = add_username(receiver_social["incoming"], sender)

    ok1, msg1 = save_cloud_state(
        client,
        sender_bundle.get("routines", []),
        sender_bundle.get("logs", {}),
        sender,
        sender_bundle.get("settings", load_ui_settings()),
        profile=normalize_profile(sender, sender_bundle.get("profile")),
        social=sender_social,
    )
    if not ok1:
        return False, msg1

    ok2, msg2 = save_cloud_state(
        client,
        receiver_bundle.get("routines", []),
        receiver_bundle.get("logs", {}),
        receiver,
        receiver_bundle.get("settings", load_ui_settings()),
        profile=normalize_profile(receiver, receiver_bundle.get("profile")),
        social=receiver_social,
    )
    if not ok2:
        return False, msg2
    return True, "친구 요청을 보냈습니다."


def send_friend_request_by_nickname(client: Any, sender: str, receiver_nickname: str) -> tuple[bool, str]:
    receiver, err = find_username_by_nickname(client, receiver_nickname)
    if err:
        return False, err
    return send_friend_request(client, sender, receiver)


def accept_friend_request(client: Any, username: str, requester: str) -> tuple[bool, str]:
    requester = requester.strip()
    user_bundle, err1 = get_user_state_bundle(client, username)
    if err1:
        return False, err1
    req_bundle, err2 = get_user_state_bundle(client, requester)
    if err2:
        return False, err2

    user_social = normalize_social_state(user_bundle.get("social"))
    req_social = normalize_social_state(req_bundle.get("social"))

    if not any(u.lower() == requester.lower() for u in user_social["incoming"]):
        return False, "유효한 친구 요청이 아닙니다."

    user_social["incoming"] = remove_username(user_social["incoming"], requester)
    user_social["friends"] = add_username(user_social["friends"], requester)
    req_social["outgoing"] = remove_username(req_social["outgoing"], username)
    req_social["friends"] = add_username(req_social["friends"], username)

    ok1, msg1 = save_cloud_state(
        client,
        user_bundle.get("routines", []),
        user_bundle.get("logs", {}),
        username,
        user_bundle.get("settings", load_ui_settings()),
        profile=normalize_profile(username, user_bundle.get("profile")),
        social=user_social,
    )
    if not ok1:
        return False, msg1

    ok2, msg2 = save_cloud_state(
        client,
        req_bundle.get("routines", []),
        req_bundle.get("logs", {}),
        requester,
        req_bundle.get("settings", load_ui_settings()),
        profile=normalize_profile(requester, req_bundle.get("profile")),
        social=req_social,
    )
    if not ok2:
        return False, msg2
    return True, "친구 요청을 수락했습니다."


def reject_friend_request(client: Any, username: str, requester: str) -> tuple[bool, str]:
    requester = requester.strip()
    user_bundle, err1 = get_user_state_bundle(client, username)
    if err1:
        return False, err1
    req_bundle, err2 = get_user_state_bundle(client, requester)
    if err2:
        return False, err2

    user_social = normalize_social_state(user_bundle.get("social"))
    req_social = normalize_social_state(req_bundle.get("social"))
    user_social["incoming"] = remove_username(user_social["incoming"], requester)
    req_social["outgoing"] = remove_username(req_social["outgoing"], username)

    ok1, msg1 = save_cloud_state(
        client,
        user_bundle.get("routines", []),
        user_bundle.get("logs", {}),
        username,
        user_bundle.get("settings", load_ui_settings()),
        profile=normalize_profile(username, user_bundle.get("profile")),
        social=user_social,
    )
    if not ok1:
        return False, msg1

    ok2, msg2 = save_cloud_state(
        client,
        req_bundle.get("routines", []),
        req_bundle.get("logs", {}),
        requester,
        req_bundle.get("settings", load_ui_settings()),
        profile=normalize_profile(requester, req_bundle.get("profile")),
        social=req_social,
    )
    if not ok2:
        return False, msg2
    return True, "친구 요청을 거절했습니다."


def persist_state(routines: list[dict], logs: dict, cloud_client=None, username: str = "local", settings: dict | None = None) -> tuple[bool, str]:
    save_routines(routines)
    save_logs(logs)
    if isinstance(settings, dict):
        save_ui_settings(settings)
    if cloud_client is None:
        return True, ""
    return save_cloud_state(cloud_client, routines, logs, username, settings)


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000).hex()


def register_user(client: Any, username: str, password: str) -> tuple[bool, str]:
    try:
        result = client.table(USERS_TABLE).select("username").eq("username", username).execute()
        if result.data:
            return False, "이미 존재하는 아이디입니다."
        salt = str(uuid4())
        pw_hash = _hash_password(password, salt)
        client.table(USERS_TABLE).insert({"username": username, "password_hash": f"{salt}:{pw_hash}"}).execute()
        return True, "회원가입이 완료되었습니다."
    except Exception as exc:
        return False, f"회원가입 실패: {exc}"


def verify_user(client: Any, username: str, password: str) -> tuple[bool, str]:
    try:
        result = client.table(USERS_TABLE).select("password_hash").eq("username", username).execute()
        if not result.data:
            return False, "아이디 또는 비밀번호가 올바르지 않습니다."
        stored = result.data[0]["password_hash"]
        salt, pw_hash = stored.split(":", 1)
        if _hash_password(password, salt) == pw_hash:
            return True, ""
        return False, "아이디 또는 비밀번호가 올바르지 않습니다."
    except Exception as exc:
        return False, f"로그인 실패: {exc}"


def apply_pastel_theme() -> None:
    st.markdown(
        """
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Black+Han+Sans&family=Noto+Sans+KR:wght@700;900&display=swap');
            .stApp { background: linear-gradient(145deg, #fdfbff 0%, #f7fbff 40%, #fffaf1 100%); color: #3f3a4f; }
            .block-container { padding-top: 2rem; padding-bottom: 2rem; max-width: 920px; }
            h1, h2, h3 { color: #574b7a; letter-spacing: 0.2px; }
            div[data-testid="stMetricValue"] { color: #4f6f8f; }
            div[data-testid="stSidebar"] { background: #f9f6ff; border-right: 1px solid #ece5ff; }
            .stButton > button { border-radius: 12px; border: 1px solid #d9cfff; background: #efe8ff; color: #4e3f73; transition: 0.2s; }
            .stButton > button:hover { border-color: #c9b9ff; background: #e5dbff; }
            [data-testid="stCheckbox"] { background: transparent; border: none; border-radius: 0; padding: 0; margin-bottom: 2px; }
            .soft-card { background: transparent; border: none; border-radius: 0; padding: 0; margin-bottom: 0; box-shadow: none; }
            .calendar-caption { color: #6b5f8f; font-weight: 600; margin-top: 0.2rem; margin-bottom: 0.5rem; }
            .calendar-cell { border-radius: 12px; padding: 8px 10px; margin-bottom: 6px; }
            .calendar-title { font-weight: 700; font-size: 0.95rem; }
            .calendar-sub { font-size: 0.82rem; opacity: 0.92; }
            .routine-card { background: #fff9ff; border: 1px solid #eadfff; border-radius: 14px; padding: 10px 12px; margin: 8px 0 6px; }
            .routine-name { color: #51407b; font-weight: 700; font-size: 1rem; }
            .routine-meta { color: #6f6297; font-size: 0.85rem; margin-top: 2px; }
            .board-title-card { background: linear-gradient(135deg, #fdf2ff 0%, #eef6ff 55%, #f5fff8 100%); border: 1px solid #e7dbff; border-radius: 18px; padding: 14px 18px; margin-bottom: 10px; box-shadow: 0 8px 22px rgba(122, 103, 181, 0.08); }
            .board-title-main { color: #574b7a; font-weight: 800; font-size: 1.35rem; }
            .board-title-sub { color: #7a6f9f; font-size: 0.9rem; margin-top: 4px; }
            .board-stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin: 12px 0 4px; }
            .board-stat { border-radius: 14px; padding: 12px 14px; border: 1px solid transparent; }
            .board-stat-label { font-size: 0.82rem; font-weight: 700; opacity: 0.9; }
            .board-stat-value { font-size: 1.15rem; font-weight: 800; margin-top: 3px; }
            .board-stat.before { background: #fff0f0; border-color: #f3c3c3; color: #9a4040; }
            .board-stat.progress { background: #eaf3ff; border-color: #bfd9ff; color: #2f649f; }
            .board-stat.done { background: #eaf9ef; border-color: #bfe8cc; color: #2f8450; }
            .board-empty { border: 1px dashed #d8d1ee; border-radius: 14px; background: #fbf9ff; color: #8077a3; padding: 20px 16px; text-align: center; margin-bottom: 10px; }
            .calendar-grid [data-testid="stButton"] > button {
                white-space: nowrap;
                text-align: center;
                line-height: 1.15;
                min-height: 38px;
                padding: 6px 6px 7px 6px;
                border-radius: 0 !important;
                font-size: 0.78rem;
                background: #f9f7ff;
                border: 1px solid #ddd6f7;
                color: #000000 !important;
                font-family: "Noto Sans KR", "Malgun Gothic", sans-serif !important;
                font-weight: 500 !important;
                letter-spacing: 0.1px;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
            }
            div[class*="st-key-weekly_pick_"] button,
            div[class*="st-key-month_pick_"] button,
            div[class*="st-key-friend_week_pick_"] button,
            div[class*="st-key-friend_month_pick_"] button {
                color: #000000 !important;
                font-family: "Noto Sans KR", "Malgun Gothic", sans-serif !important;
                font-weight: 500 !important;
                border-radius: 0 !important;
                min-height: 34px !important;
                padding: 4px 6px !important;
                line-height: 1.2 !important;
                letter-spacing: 0.1px !important;
            }
            .calendar-grid [data-testid="stButton"] > button * {
                color: #000000 !important;
                font-weight: 500 !important;
                font-family: "Noto Sans KR", "Malgun Gothic", sans-serif !important;
                letter-spacing: 0.1px !important;
            }
            div[class*="st-key-weekly_pick_"] button > div,
            div[class*="st-key-month_pick_"] button > div,
            div[class*="st-key-friend_week_pick_"] button > div,
            div[class*="st-key-friend_month_pick_"] button > div,
            div[class*="st-key-weekly_pick_"] button p,
            div[class*="st-key-month_pick_"] button p,
            div[class*="st-key-friend_week_pick_"] button p,
            div[class*="st-key-friend_month_pick_"] button p,
            div[class*="st-key-weekly_pick_"] button span,
            div[class*="st-key-month_pick_"] button span,
            div[class*="st-key-friend_week_pick_"] button span,
            div[class*="st-key-friend_month_pick_"] button span {
                font-family: "Noto Sans KR", "Malgun Gothic", sans-serif !important;
                font-weight: 500 !important;
                color: #000000 !important;
            }
            div[class*="st-key-weekly_pick_"],
            div[class*="st-key-month_pick_"],
            div[class*="st-key-friend_week_pick_"],
            div[class*="st-key-friend_month_pick_"] {
                margin-bottom: 0 !important;
                padding-bottom: 0 !important;
            }
            .calendar-grid [data-testid="stButton"] > button::first-line {
                font-size: 0.8rem;
                font-weight: 900;
                text-align: center;
                display: block;
            }
            .calendar-grid [data-testid="stButton"] > button:hover {
                background: #f3eeff;
                border-color: #cbbcf2;
            }
            .cal-card-link {
                display: block;
                text-decoration: none;
                background: #f9f7ff;
                border: 1px solid #ddd6f7;
                border-radius: 12px;
                padding: 10px 11px;
                min-height: 132px;
                margin-bottom: 6px;
            }
            .cal-card-link:hover {
                background: #f3eeff;
                border-color: #cbbcf2;
            }
            .cal-title {
                text-align: center;
                font-size: 0.98rem;
                font-weight: 800;
                color: #4a3f70;
                line-height: 1.2;
                margin-bottom: 6px;
            }
            .cal-meta {
                text-align: center;
                font-size: 0.78rem;
                color: #5f5388;
                line-height: 1.2;
            }
            .cal-sep {
                height: 1px;
                background: #ddd6f7;
                margin: 6px 0;
            }
            .cal-items {
                text-align: left;
                font-size: 0.74rem;
                color: #4d436f;
                line-height: 1.28;
                white-space: pre-line;
            }
            .cal-items.empty {
                color: #8e86ad;
            }
            .calendar-grid [data-testid="stButton"] {
                margin-bottom: 0 !important;
            }
            .calendar-grid [data-testid="stMarkdown"] {
                margin-top: 0 !important;
                margin-bottom: 0 !important;
            }
            .calendar-grid [data-testid="stMarkdownContainer"] p {
                margin: 0 !important;
            }
            .week-date-btn [data-testid="stButton"] > button {
                min-height: 34px;
                padding: 4px 6px;
                font-size: 0.78rem;
                font-weight: 800 !important;
                border-radius: 0 !important;
                margin-bottom: 0 !important;
                color: #000000 !important;
            }
            .week-date-btn [data-testid="stButton"] {
                margin-bottom: 0 !important;
            }
            .week-date-btn {
                margin-bottom: 0 !important;
            }
            .cal-list-wrap {
                margin-top: -10px !important;
                padding-top: 0 !important;
            }
            .cal-list-box {
                border: 1px solid #ddd6f7;
                border-top: 0;
                border-radius: 0;
                background: #ffffff;
                padding: 8px 8px 6px 8px;
                margin-top: 0 !important;
            }
            .cal-list-line {
                font-size: 0.74rem;
                color: #111111;
                line-height: 1.25;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
                margin: 1px 0;
            }
            .cal-list-empty {
                font-size: 0.74rem;
                color: #111111;
            }
            .month-weekday {
                font-weight: 900;
                color: #111111;
                text-align: center;
                margin: 0 !important;
                padding: 0 !important;
                line-height: 1.1;
            }
            .month-weekday.sun {
                color: #b23a48;
            }
            .month-weekday.sat {
                color: #2f5fa9;
            }
            .month-weekday.normal {
                color: #222222;
            }
            .month-row-gap {
                height: 8px;
            }
            .month-grid {
                margin-top: -60px !important;
            }
            .month-grid [data-testid="column"] > div {
                gap: 0 !important;
            }
            .month-grid [data-testid="stButton"] {
                margin-top: 0 !important;
                margin-bottom: 0 !important;
            }
            .month-grid .cal-list-wrap {
                margin-top: -8px !important;
            }
            .month-header-row [data-testid="stMarkdown"] {
                margin-top: 0 !important;
                margin-bottom: 0 !important;
            }
            .month-header-row [data-testid="stMarkdownContainer"] p {
                margin: 0 !important;
            }
            .week-day-label {
                text-align: center;
                font-size: 0.82rem;
                font-weight: 900;
                margin: 0 !important;
                line-height: 1.1;
            }
            .week-day-label.sun {
                color: #b23a48;
            }
            .week-day-label.sat {
                color: #2f5fa9;
            }
            .week-day-label.normal {
                color: #222222;
            }
            div[class*="st-key-sidebar_top_settings_icon"] button {
                background: transparent !important;
                background-image: none !important;
                border: none !important;
                box-shadow: none !important;
                color: #4a4a4a !important;
                font-family: "Noto Sans KR", "Segoe UI", "Segoe UI Symbol", sans-serif !important;
                border-radius: 0 !important;
                padding: 0.1rem 0 !important;
                min-height: 0 !important;
                line-height: 1.15 !important;
                font-size: 1rem !important;
                font-weight: 600 !important;
                letter-spacing: -0.01em !important;
                justify-content: flex-start !important;
                display: inline-flex !important;
                white-space: nowrap !important;
                width: auto !important;
            }
            div[class*="st-key-sidebar_top_settings_icon"] button p,
            div[class*="st-key-sidebar_top_settings_icon"] button span {
                white-space: nowrap !important;
                margin: 0 !important;
            }
            div[class*="st-key-sidebar_top_settings_icon"] button:hover,
            div[class*="st-key-sidebar_top_settings_icon"] button:focus,
            div[class*="st-key-sidebar_top_settings_icon"] button:focus-visible,
            div[class*="st-key-sidebar_top_settings_icon"] button:active {
                background: transparent !important;
                background-image: none !important;
                border: none !important;
                box-shadow: none !important;
                color: #2f2f2f !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.dialog("설정")
def render_settings_dialog() -> None:
    is_en = st.session_state.get("language", LANGUAGE_OPTIONS[0]) == "English"
    def td(ko: str, en: str) -> str:
        return en if is_en else ko

    if "settings_week_start_tmp" not in st.session_state:
        st.session_state["settings_week_start_tmp"] = st.session_state.get("week_start_option", CALENDAR_START_OPTIONS[0])
    if "settings_default_view_tmp" not in st.session_state:
        st.session_state["settings_default_view_tmp"] = st.session_state.get("default_main_view_mode", MAIN_VIEW_OPTIONS[0])
    if "settings_language_tmp" not in st.session_state:
        st.session_state["settings_language_tmp"] = st.session_state.get("language", LANGUAGE_OPTIONS[0])

    st.radio(td("주 시작 요일", "Week starts on"), CALENDAR_START_OPTIONS, horizontal=True, key="settings_week_start_tmp")
    st.radio(td("기본 보기", "Default view"), MAIN_VIEW_OPTIONS, horizontal=True, key="settings_default_view_tmp")
    st.radio("Language", LANGUAGE_OPTIONS, horizontal=True, key="settings_language_tmp")

    cols = st.columns(2)
    if cols[0].button(td("저장", "Save"), use_container_width=True):
        st.session_state["week_start_option"] = st.session_state.get("settings_week_start_tmp", CALENDAR_START_OPTIONS[0])
        st.session_state["default_main_view_mode"] = st.session_state.get("settings_default_view_tmp", MAIN_VIEW_OPTIONS[0])
        st.session_state["language"] = st.session_state.get("settings_language_tmp", LANGUAGE_OPTIONS[0])
        st.session_state["open_settings_dialog"] = False
        st.rerun()
    if cols[1].button(td("닫기", "Close"), use_container_width=True):
        st.session_state["open_settings_dialog"] = False
        st.rerun()


def render_login_page(cloud_client: Any) -> None:
    st.title("🌸 Routine Manager")
    st.caption("로그인하여 루틴을 관리하세요.")
    tab_login, tab_register = st.tabs(["로그인", "회원가입"])

    with tab_login:
        with st.form("login_form"):
            username = st.text_input("아이디")
            password = st.text_input("비밀번호", type="password")
            remember = st.checkbox("이 디바이스에서 자동 로그인", value=True)
            submitted = st.form_submit_button("로그인", use_container_width=True)
            if submitted:
                if not username or not password:
                    st.warning("아이디와 비밀번호를 입력해 주세요.")
                else:
                    ok, msg = verify_user(cloud_client, username.strip(), password)
                    if ok:
                        st.session_state["logged_in_user"] = username.strip()
                        if remember:
                            save_device_session(username.strip())
                        else:
                            clear_device_session()
                        st.rerun()
                    else:
                        st.error(msg)

    with tab_register:
        with st.form("register_form"):
            new_username = st.text_input("아이디")
            new_nickname = st.text_input("닉네임", placeholder="예: 홍길동")
            new_password = st.text_input("비밀번호", type="password")
            new_password2 = st.text_input("비밀번호 확인", type="password")
            submitted = st.form_submit_button("회원가입", use_container_width=True)
            if submitted:
                if not new_username or not new_password:
                    st.warning("아이디와 비밀번호를 입력해 주세요.")
                elif not new_nickname.strip():
                    st.warning("닉네임을 입력해 주세요.")
                elif new_password != new_password2:
                    st.warning("비밀번호가 일치하지 않습니다.")
                elif len(new_password) < 4:
                    st.warning("비밀번호는 4자 이상이어야 합니다.")
                else:
                    nickname = normalize_nickname(new_nickname)
                    valid, valid_msg = validate_nickname(nickname)
                    if not valid:
                        st.warning(valid_msg)
                    else:
                        available, available_msg = is_nickname_available(cloud_client, nickname)
                        if not available:
                            st.warning(available_msg)
                        else:
                            ok, msg = register_user(cloud_client, new_username.strip(), new_password)
                            if ok:
                                init_profile = normalize_profile(
                                    new_username.strip(),
                                    {
                                        "nickname": nickname,
                                        "bio": "",
                                        "share_progress": True,
                                    },
                                )
                                save_cloud_state(
                                    cloud_client,
                                    [],
                                    {},
                                    new_username.strip(),
                                    load_ui_settings(),
                                    profile=init_profile,
                                    social=default_social_state(),
                                )
                                st.success(msg + " 로그인 탭에서 로그인해 주세요.")
                            else:
                                st.error(msg)


def main() -> None:
    st.set_page_config(page_title="Routine Manager", page_icon="🌸", layout="centered")
    apply_pastel_theme()

    cloud_client, cloud_error = get_supabase_client()

    username = st.session_state.get("logged_in_user", "")
    if cloud_client and not username:
        remembered_username = load_device_session_username()
        if remembered_username and user_exists(cloud_client, remembered_username):
            st.session_state["logged_in_user"] = remembered_username
            st.rerun()

    username = st.session_state.get("logged_in_user", "")
    if cloud_client and not username:
        render_login_page(cloud_client)
        return

    if not username:
        username = "local"

    routines = load_routines()
    logs = load_logs()
    ui_settings = load_ui_settings()
    if "auto_rollover_todos" not in st.session_state:
        st.session_state["auto_rollover_todos"] = bool(ui_settings.get("auto_rollover_todos", False))
    if "week_start_option" not in st.session_state:
        st.session_state["week_start_option"] = ui_settings.get("week_start_option", CALENDAR_START_OPTIONS[0])
    if "default_main_view_mode" not in st.session_state:
        st.session_state["default_main_view_mode"] = ui_settings.get("default_main_view_mode", MAIN_VIEW_OPTIONS[0])
    if "language" not in st.session_state:
        st.session_state["language"] = ui_settings.get("language", LANGUAGE_OPTIONS[0])

    is_en = st.session_state.get("language", LANGUAGE_OPTIONS[0]) == "English"
    def t(ko: str, en: str) -> str:
        return en if is_en else ko

    bootstrap_key = f"cloud_bootstrap_{username}"
    if cloud_client and not st.session_state.get(bootstrap_key, False):
        cloud_state, load_error = load_cloud_state(cloud_client, username)
        if load_error:
            st.warning(load_error)
        elif cloud_state:
            loaded_routines = cloud_state.get("routines", [])
            loaded_logs = cloud_state.get("logs", {})
            if isinstance(loaded_routines, list) and isinstance(loaded_logs, dict):
                routines = loaded_routines
                logs = loaded_logs
                save_routines(routines)
                save_logs(logs)
            loaded_settings = cloud_state.get("settings", {})
            if isinstance(loaded_settings, dict):
                save_ui_settings(loaded_settings)
                ui_settings = load_ui_settings()
                st.session_state["auto_rollover_todos"] = bool(ui_settings.get("auto_rollover_todos", False))
                st.session_state["week_start_option"] = ui_settings.get("week_start_option", CALENDAR_START_OPTIONS[0])
                st.session_state["default_main_view_mode"] = ui_settings.get("default_main_view_mode", MAIN_VIEW_OPTIONS[0])
                st.session_state["language"] = ui_settings.get("language", LANGUAGE_OPTIONS[0])
            st.session_state["user_profile"] = normalize_profile(username, cloud_state.get("profile"))
            st.session_state["social_state"] = normalize_social_state(cloud_state.get("social"))
        else:
            _, save_error = save_cloud_state(
                cloud_client,
                routines,
                logs,
                username,
                ui_settings,
                profile=default_profile(username),
                social=default_social_state(),
            )
            if save_error:
                st.warning(save_error)
            st.session_state["user_profile"] = default_profile(username)
            st.session_state["social_state"] = default_social_state()
        st.session_state[bootstrap_key] = True

    if "user_profile" not in st.session_state:
        st.session_state["user_profile"] = default_profile(username)
    if "social_state" not in st.session_state:
        st.session_state["social_state"] = default_social_state()

    routines, normalized_changed = normalize_routines(routines)
    if st.session_state.get("auto_rollover_todos", False):
        if rollover_incomplete_todos(routines, logs, date.today()):
            normalized_changed = True
    if normalized_changed:
        ok, msg = persist_state(routines, logs, cloud_client, username, ui_settings)
        if not ok:
            st.warning(msg)

    st.title("🌸 Routine Manager")
    if username != "local":
        profile_preview = normalize_profile(username, st.session_state.get("user_profile"))
        if is_en:
            st.caption(f"Hello, **{profile_preview.get('nickname', username)}** 👋")
        else:
            st.caption(f"안녕하세요, **{profile_preview.get('nickname', username)}** 님 👋")
    else:
        st.caption(t("매일 해야 할 일을 가볍게 체크하세요.", "Track your daily routines with ease."))

    with st.sidebar:
        side_top_cols = st.columns([3, 4])
        if side_top_cols[0].button(t("⚙️ 설정", "⚙️ Setting"), key="sidebar_top_settings_icon", help=t("설정", "Setting"), use_container_width=False):
            st.session_state["open_settings_dialog"] = True
        st.header(t("등록", "Create"))
        tab_todo_add, tab_routine_add, tab_data, tab_social = st.tabs([
            t("할일 등록", "Add To-do"),
            t("루틴 등록", "Add Routine"),
            t("데이터", "Data"),
            t("프로필/친구", "Profile/Friends"),
        ])
        active_routines = get_active_routines(routines)
        inactive_routines = get_inactive_routines(routines)

        with tab_routine_add:
            with st.form("add_routine_form", clear_on_submit=True):
                routine_name = st.text_input("루틴 이름", placeholder="예: 물 2L 마시기")
                st.caption("반복 요일")
                selected_days = weekday_checkbox_selector("add_days", list(range(7)))
                tag_input = st.text_input("태그 (쉼표로 구분)", placeholder="예: 오전, 학교, 운동")
                submitted = st.form_submit_button("루틴 추가")
                if submitted:
                    name = routine_name.strip()
                    tags = parse_tag_input(tag_input)
                    if not name:
                        st.warning("루틴 이름을 입력해 주세요.")
                    elif not selected_days:
                        st.warning("최소 1개 이상의 요일을 선택해 주세요.")
                    elif any(r["name"].lower() == name.lower() and r.get("active", True) and r.get("mode", "routine") == "routine" for r in routines):
                        st.warning("이미 존재하는 루틴입니다.")
                    else:
                        routines.append({
                            "id": str(uuid4()),
                            "name": name,
                            "mode": "routine",
                            "weekdays": sorted(selected_days),
                            "tags": tags,
                            "active": True,
                            "created_at": datetime.now().isoformat(timespec="seconds"),
                        })
                        ok, msg = persist_state(routines, logs, cloud_client, username)
                        if not ok:
                            st.warning(msg)
                        st.success(f"'{name}' 루틴이 추가되었습니다.")
                        st.rerun()

            st.divider()
            st.subheader("루틴 관리")

            if not active_routines:
                st.info("등록된 루틴이 없습니다.")
            else:
                st.caption("루틴 설정 변경")
                routine_options = ["선택하세요"] + [r["name"] for r in active_routines]
                selected_name = st.selectbox("수정할 루틴", routine_options, key="edit_routine")
                if selected_name != "선택하세요":
                    selected_routine = next(r for r in active_routines if r["name"] == selected_name)
                    st.caption("요일")
                    edited_days = weekday_checkbox_selector(f"edit_days_{selected_routine['id']}", selected_routine.get("weekdays", list(range(7))))
                    edited_tags_raw = st.text_input(
                        "태그(쉼표 구분)",
                        value=", ".join(selected_routine.get("tags", [])),
                        key=f"edit_tags_{selected_routine['id']}",
                    )
                    if st.button("설정 저장", use_container_width=True):
                        if not edited_days:
                            st.warning("최소 1개 이상의 요일을 선택해 주세요.")
                        else:
                            new_tags = parse_tag_input(edited_tags_raw)
                            for r in routines:
                                if r["id"] == selected_routine["id"]:
                                    r["weekdays"] = sorted(edited_days)
                                    r["tags"] = new_tags
                            ok, msg = persist_state(routines, logs, cloud_client, username)
                            if not ok:
                                st.warning(msg)
                            st.success("요일/태그 설정이 저장되었습니다.")
                        st.rerun()

                st.divider()
                to_archive = st.selectbox("관리할 루틴", ["선택하세요"] + [r["name"] for r in active_routines])
                archive_action = st.radio("동작", ["비활성화", "삭제"], horizontal=True, key="routine_archive_action")
                if st.button("적용", use_container_width=True):
                    if to_archive != "선택하세요":
                        target_ids = [r["id"] for r in routines if r["name"] == to_archive and r.get("active", True) and r.get("mode", "routine") == "routine"]
                        if archive_action == "삭제":
                            routines[:] = [r for r in routines if r.get("id") not in set(target_ids)]
                            if target_ids:
                                target_id_set = set(target_ids)
                                for day_key in list(logs.keys()):
                                    day_log = logs.get(day_key, {})
                                    if not isinstance(day_log, dict):
                                        continue
                                    for rid in target_id_set:
                                        day_log.pop(rid, None)
                                    if not day_log:
                                        logs.pop(day_key, None)
                        else:
                            for r in routines:
                                if r["name"] == to_archive and r.get("active", True) and r.get("mode", "routine") == "routine":
                                    r["active"] = False
                        ok, msg = persist_state(routines, logs, cloud_client, username)
                        if not ok:
                            st.warning(msg)
                        else:
                            if archive_action == "삭제":
                                st.success(f"'{to_archive}' 루틴을 삭제했습니다.")
                            else:
                                st.success(f"'{to_archive}' 루틴을 비활성화했습니다.")
                        st.rerun()

                st.divider()
                st.caption("비활성 루틴")
                if not inactive_routines:
                    st.info("비활성 루틴이 없습니다.")
                else:
                    for r in inactive_routines:
                        st.write(f"- {r['name']}: {weekday_label(r.get('weekdays', list(range(7))))} | {tags_label(r.get('tags', []))}")
                    to_reactivate = st.selectbox("재활성화할 루틴", [r["name"] for r in inactive_routines], key="reactivate_routine")
                    if st.button("재활성화", use_container_width=True):
                        for r in routines:
                            if r["name"] == to_reactivate and not r.get("active", True):
                                r["active"] = True
                        ok, msg = persist_state(routines, logs, cloud_client, username)
                        if not ok:
                            st.warning(msg)
                        st.success(f"'{to_reactivate}' 루틴을 재활성화했습니다.")
                        st.rerun()

        with tab_todo_add:
            with st.form("add_todo_form", clear_on_submit=True):
                todo_name = st.text_input("할일 이름", placeholder="예: 과제 제출")
                todo_date = st.date_input("할일 날짜", value=date.today(), key="todo_add_date")
                todo_tag_input = st.text_input("태그 (쉼표로 구분)", placeholder="예: 학교, 중요")
                submitted_todo = st.form_submit_button("할일 추가")
                if submitted_todo:
                    name = todo_name.strip()
                    tags = parse_tag_input(todo_tag_input)
                    if not name:
                        st.warning("할일 이름을 입력해 주세요.")
                    elif any(
                        r.get("mode", "routine") == "todo"
                        and r.get("active", True)
                        and r["name"].lower() == name.lower()
                        and r.get("todo_date") == todo_date.isoformat()
                        for r in routines
                    ):
                        st.warning("같은 날짜에 동일한 할일이 이미 있습니다.")
                    else:
                        routines.append(
                            {
                                "id": str(uuid4()),
                                "name": name,
                                "mode": "todo",
                                "todo_date": todo_date.isoformat(),
                                "weekdays": [],
                                "tags": tags,
                                "active": True,
                                "created_at": datetime.now().isoformat(timespec="seconds"),
                            }
                        )
                        ok, msg = persist_state(routines, logs, cloud_client, username)
                        if not ok:
                            st.warning(msg)
                        st.session_state["pending_target_date"] = todo_date.isoformat()
                        st.success(f"'{name}' 할일이 추가되었습니다.")
                        st.rerun()

        with tab_data:
            st.subheader("데이터 동기화")
            if cloud_client:
                st.success("클라우드 자동 동기화: 활성화")
                if st.button("클라우드에서 지금 가져오기", use_container_width=True):
                    cloud_state, load_error = load_cloud_state(cloud_client, username)
                    if load_error:
                        st.error(load_error)
                    elif cloud_state:
                        loaded_routines = cloud_state.get("routines", [])
                        loaded_logs = cloud_state.get("logs", {})
                        if isinstance(loaded_routines, list) and isinstance(loaded_logs, dict):
                            save_routines(loaded_routines)
                            save_logs(loaded_logs)
                            loaded_settings = cloud_state.get("settings", {})
                            if isinstance(loaded_settings, dict):
                                save_ui_settings(loaded_settings)
                                synced_settings = load_ui_settings()
                                st.session_state["auto_rollover_todos"] = bool(synced_settings.get("auto_rollover_todos", False))
                                st.session_state["week_start_option"] = synced_settings.get("week_start_option", CALENDAR_START_OPTIONS[0])
                            st.success("클라우드 데이터 가져오기가 완료되었습니다.")
                            st.rerun()
                    else:
                        st.info("클라우드에 저장된 데이터가 없습니다.")
                if st.button("클라우드로 지금 저장", use_container_width=True):
                    ok, msg = save_cloud_state(cloud_client, routines, logs, username, load_ui_settings())
                    if ok:
                        st.success("클라우드 저장이 완료되었습니다.")
                    else:
                        st.error(msg)
            else:
                st.info("클라우드 동기화 비활성화 상태입니다.")
                if cloud_error:
                    st.caption(cloud_error)

            st.divider()
            st.subheader("백업")
            backup_payload = build_backup_payload(routines, logs, load_ui_settings())
            st.download_button("백업 파일 다운로드", data=json.dumps(backup_payload, ensure_ascii=False, indent=2), file_name=f"routine-manager-backup-{date.today().isoformat()}.json", mime="application/json", use_container_width=True)
            backup_file = st.file_uploader("백업 파일 업로드", type=["json"], accept_multiple_files=False)
            if backup_file is not None and st.button("백업 복원", use_container_width=True):
                try:
                    payload = json.loads(backup_file.read().decode("utf-8"))
                    ok, message = apply_backup_payload(payload, cloud_client, username)
                    if ok:
                        st.success(message)
                        st.rerun()
                    else:
                        st.error(message)
                except Exception:
                    st.error("백업 파일을 읽지 못했습니다.")

            st.divider()
            st.subheader("데이터 초기화")
            reset_confirm = st.checkbox("정말로 모든 루틴/기록을 초기화합니다.", key="confirm_reset_all")
            if st.button("⚠️ 전체 루틴 초기화", use_container_width=True):
                if not reset_confirm:
                    st.warning("체크박스를 먼저 선택해 주세요.")
                else:
                    ok, msg = persist_state([], {}, cloud_client, username)
                    if not ok:
                        st.error(msg)
                    else:
                        st.success("전체 루틴과 기록이 초기화되었습니다.")
                        st.rerun()

        with tab_social:
            st.subheader("내 프로필")
            current_profile = normalize_profile(username, st.session_state.get("user_profile"))
            with st.form("profile_form"):
                nickname = st.text_input("닉네임", value=current_profile.get("nickname", username), max_chars=30)
                bio = st.text_area("소개", value=current_profile.get("bio", ""), max_chars=200, height=80)
                share_progress = st.checkbox("친구에게 달성률 공유", value=bool(current_profile.get("share_progress", True)))
                profile_submit = st.form_submit_button("프로필 저장", use_container_width=True)
                if profile_submit:
                    new_profile = normalize_profile(
                        username,
                        {
                            "nickname": nickname,
                            "bio": bio,
                            "share_progress": share_progress,
                        },
                    )
                    if cloud_client and username != "local":
                        valid, valid_msg = validate_nickname(new_profile.get("nickname", ""))
                        if not valid:
                            st.warning(valid_msg)
                        else:
                            available, available_msg = is_nickname_available(
                                cloud_client,
                                new_profile.get("nickname", ""),
                                except_username=username,
                            )
                            if not available:
                                st.warning(available_msg)
                            else:
                                st.session_state["user_profile"] = new_profile
                                social_snapshot = normalize_social_state(st.session_state.get("social_state"))
                                ok, msg = save_cloud_state(
                                    cloud_client,
                                    routines,
                                    logs,
                                    username,
                                    load_ui_settings(),
                                    profile=new_profile,
                                    social=social_snapshot,
                                )
                                if ok:
                                    st.success("프로필이 저장되었습니다.")
                                else:
                                    st.error(msg)
                    else:
                        st.session_state["user_profile"] = new_profile
                        st.info("로컬 모드에서는 프로필이 세션에만 저장됩니다.")

            st.divider()
            st.subheader("친구")
            if not cloud_client or username == "local":
                st.info("친구 기능은 로그인(클라우드) 모드에서 사용할 수 있습니다.")
            else:
                if st.button("친구 목록 새로고침", use_container_width=True):
                    bundle, err = get_user_state_bundle(cloud_client, username)
                    if err:
                        st.error(err)
                    else:
                        st.session_state["user_profile"] = normalize_profile(username, bundle.get("profile"))
                        st.session_state["social_state"] = normalize_social_state(bundle.get("social"))
                        st.success("새로고침 완료")
                        st.rerun()

                social = normalize_social_state(st.session_state.get("social_state"))
                with st.form("send_friend_request_form"):
                    target_nickname = st.text_input("닉네임으로 친구 추가", placeholder="예: 홍길동")
                    request_submit = st.form_submit_button("친구 요청 보내기", use_container_width=True)
                    if request_submit:
                        ok, msg = send_friend_request_by_nickname(cloud_client, username, target_nickname)
                        if ok:
                            bundle, _ = get_user_state_bundle(cloud_client, username)
                            st.session_state["social_state"] = normalize_social_state(bundle.get("social"))
                            st.success(msg)
                            st.rerun()
                        else:
                            st.warning(msg)

                friends = social.get("friends", [])
                incoming = social.get("incoming", [])
                outgoing = social.get("outgoing", [])

                st.caption(f"친구 {len(friends)}명")
                if friends:
                    for f in friends:
                        nick = get_user_nickname(cloud_client, f)
                        st.write(f"- {nick} (@{f})")
                else:
                    st.write("- 아직 친구가 없습니다.")

                st.caption(f"받은 요청 {len(incoming)}건")
                if incoming:
                    for req in incoming:
                        req_nick = get_user_nickname(cloud_client, req)
                        cols = st.columns([3, 1, 1])
                        cols[0].write(f"{req_nick} (@{req})")
                        if cols[1].button("수락", key=f"accept_{req}"):
                            ok, msg = accept_friend_request(cloud_client, username, req)
                            if ok:
                                bundle, _ = get_user_state_bundle(cloud_client, username)
                                st.session_state["social_state"] = normalize_social_state(bundle.get("social"))
                                st.success(msg)
                                st.rerun()
                            else:
                                st.warning(msg)
                        if cols[2].button("거절", key=f"reject_{req}"):
                            ok, msg = reject_friend_request(cloud_client, username, req)
                            if ok:
                                bundle, _ = get_user_state_bundle(cloud_client, username)
                                st.session_state["social_state"] = normalize_social_state(bundle.get("social"))
                                st.success(msg)
                                st.rerun()
                            else:
                                st.warning(msg)
                else:
                    st.write("- 받은 친구 요청이 없습니다.")

                st.caption(f"보낸 요청 {len(outgoing)}건")
                if outgoing:
                    for req in outgoing:
                        req_nick = get_user_nickname(cloud_client, req)
                        st.write(f"- {req_nick} (@{req})")
                else:
                    st.write("- 보낸 친구 요청이 없습니다.")

        st.divider()
        if st.button("로그아웃", use_container_width=True):
            st.session_state.pop("logged_in_user", None)
            st.session_state.pop(bootstrap_key, None)
            st.session_state.pop("user_profile", None)
            st.session_state.pop("social_state", None)
            clear_device_session()
            st.rerun()

    if st.session_state.get("open_settings_dialog", False):
        render_settings_dialog()

    query_params = st.query_params
    open_date = query_params.get("open_date")
    open_friend_date = query_params.get("open_friend_date")
    open_tab = query_params.get("open_tab")
    open_friend_view = query_params.get("open_friend_view")
    if open_date:
        st.session_state["pending_target_date"] = str(open_date)
    if open_friend_date:
        try:
            st.session_state["friend_target_date_input"] = date.fromisoformat(str(open_friend_date))
        except Exception:
            pass
    if open_tab == "day":
        st.session_state["pending_main_tab"] = "일간 보기"
    elif open_tab == "week":
        st.session_state["pending_main_tab"] = "주간 보기"
    elif open_tab == "month":
        st.session_state["pending_main_tab"] = "월간 보기"
    elif open_tab == "friend":
        st.session_state["pending_main_tab"] = "친구 일정"
    if open_friend_view == "day":
        st.session_state["pending_friend_view_mode"] = "일간"
    if open_date or open_friend_date or open_tab or open_friend_view:
        st.query_params.clear()

    pending_target_date = st.session_state.pop("pending_target_date", None)
    if pending_target_date:
        try:
            st.session_state["target_date_input"] = date.fromisoformat(pending_target_date)
        except Exception:
            pass
    if "target_date_input" not in st.session_state:
        st.session_state["target_date_input"] = date.today()

    st.markdown("<div class='soft-card'>", unsafe_allow_html=True)
    target_date = st.session_state.get("target_date_input", date.today())
    if not isinstance(target_date, date):
        target_date = date.today()
        st.session_state["target_date_input"] = target_date
    date_key = target_date.isoformat()
    active_items = get_active_items(routines)
    available_tags = collect_all_tags(active_items)

    if not active_items:
        st.info("왼쪽에서 루틴 또는 할일을 먼저 등록해 주세요.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    logs_for_day = logs.get(date_key, {})
    changed = False

    with st.expander("📅 빠른 날짜 이동", expanded=False):
        jump_cols = st.columns([5, 1, 1])
        jump_date = jump_cols[0].date_input("날짜 선택", value=target_date, key="quick_jump_date")
        if jump_cols[1].button("오늘", use_container_width=True):
            st.session_state["pending_target_date"] = date.today().isoformat()
            st.rerun()
        if jump_cols[2].button("이동", use_container_width=True):
            st.session_state["pending_target_date"] = jump_date.isoformat()
            st.rerun()

    pending_main_tab = st.session_state.pop("pending_main_tab", None)
    all_tab_labels = MAIN_VIEW_OPTIONS + ["친구 일정"]
    preferred_tab = pending_main_tab if pending_main_tab in all_tab_labels else st.session_state.get("default_main_view_mode", MAIN_VIEW_OPTIONS[0])
    if preferred_tab not in all_tab_labels:
        preferred_tab = MAIN_VIEW_OPTIONS[0]
    if pending_main_tab in all_tab_labels:
        st.session_state["main_tabs_nonce"] = int(st.session_state.get("main_tabs_nonce", 0)) + 1
    ordered_tab_labels = [preferred_tab] + [label for label in all_tab_labels if label != preferred_tab]
    tabs_nonce = int(st.session_state.get("main_tabs_nonce", 0))
    tab_name_map = {
        "일간 보기": t("일간 보기", "Day"),
        "주간 보기": t("주간 보기", "Week"),
        "월간 보기": t("월간 보기", "Month"),
        "친구 일정": t("친구 일정", "Friends"),
    }
    tab_display_labels = [f"{tab_name_map.get(label, label)}{'\u200b' * tabs_nonce}" for label in ordered_tab_labels]
    tabs = st.tabs(tab_display_labels)
    tab_map = {label: tab for label, tab in zip(ordered_tab_labels, tabs)}
    selected_filter_tags = st.multiselect("태그 필터", options=available_tags, help="선택한 태그 중 하나라도 포함한 항목만 표시됩니다.")
    filtered_active_items = filter_routines_by_tags(active_items, selected_filter_tags)
    routines_for_target_date = get_routines_for_date(filtered_active_items, target_date)

    if selected_filter_tags and not filtered_active_items:
        st.info("선택한 태그에 해당하는 항목이 없습니다.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    day_board_changed = False
    with tab_map["일간 보기"]:
        nav_cols = st.columns([1, 6, 1])
        if nav_cols[0].button("◀", use_container_width=True, key="day_prev"):
            st.session_state["pending_target_date"] = (target_date - timedelta(days=1)).isoformat()
            st.rerun()
        nav_cols[1].markdown(f"<div class='calendar-caption' style='text-align:center'>{target_date.isoformat()}</div>", unsafe_allow_html=True)
        if nav_cols[2].button("▶", use_container_width=True, key="day_next"):
            st.session_state["pending_target_date"] = (target_date + timedelta(days=1)).isoformat()
            st.rerun()

        st.markdown(
            f"""
            <div class='board-title-card'>
                <div class='board-title-main'>{date_key} To Do Board</div>
                <div class='board-title-sub'>오늘 할 일과 루틴을 파스텔 보드에서 가볍게 정리해보세요.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if not routines_for_target_date:
            st.markdown("<div class='board-empty'>이 날짜에는 항목이 없습니다. 화살표 또는 빠른 날짜 이동으로 다른 날짜를 확인해보세요.</div>", unsafe_allow_html=True)
        else:
            st.caption("드래그로 상태 열을 옮기면 바로 반영됩니다.")
            logs_for_day, board_changed = render_status_board(routines_for_target_date, logs_for_day, date_key)
            day_board_changed = board_changed
            changed = changed or board_changed

            st.checkbox("완료하지 않은 할일은 다음 날 자동 이월", key="auto_rollover_todos")

    if changed:
        logs[date_key] = logs_for_day
        ok, msg = persist_state(routines, logs, cloud_client, username, load_ui_settings())
        if not ok:
            st.warning(msg)
        elif day_board_changed:
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)
    week_start_option = st.session_state.get("week_start_option", CALENDAR_START_OPTIONS[0])
    if week_start_option not in CALENDAR_START_OPTIONS:
        week_start_option = CALENDAR_START_OPTIONS[0]
        st.session_state["week_start_option"] = week_start_option
    weekday_order, week_start_idx = calendar_weekday_order(week_start_option)

    current_ui_settings = {
        "auto_rollover_todos": bool(st.session_state.get("auto_rollover_todos", False)),
        "week_start_option": st.session_state.get("week_start_option", CALENDAR_START_OPTIONS[0]),
        "default_main_view_mode": st.session_state.get("default_main_view_mode", MAIN_VIEW_OPTIONS[0]),
        "language": st.session_state.get("language", LANGUAGE_OPTIONS[0]),
    }
    if current_ui_settings != ui_settings:
        save_ui_settings(current_ui_settings)
        if cloud_client:
            ok, msg = save_cloud_state(cloud_client, routines, logs, username, current_ui_settings)
            if not ok:
                st.warning(msg)

    with tab_map["주간 보기"]:
        week_number = week_of_month(target_date, week_start_idx)
        week_title = f"{target_date.year}년 {target_date.month}월 {week_number}째주"
        week_nav_cols = st.columns([1, 6, 1])
        if week_nav_cols[0].button("◀", use_container_width=True, key="week_prev"):
            st.session_state["pending_target_date"] = (target_date - timedelta(days=7)).isoformat()
            st.rerun()
        week_nav_cols[1].markdown(f"<div class='calendar-caption' style='text-align:center'>{week_title}</div>", unsafe_allow_html=True)
        if week_nav_cols[2].button("▶", use_container_width=True, key="week_next"):
            st.session_state["pending_target_date"] = (target_date + timedelta(days=7)).isoformat()
            st.rerun()

        week_start = target_date - timedelta(days=(target_date.weekday() - week_start_idx) % 7)
        st.markdown("<div class='calendar-caption'>날짜를 누르면 해당 날짜로 바로 이동합니다.</div>", unsafe_allow_html=True)
        week_counts = [len(get_routines_for_date(filtered_active_items, week_start + timedelta(days=i))) for i in range(7)]
        week_box_height = list_box_height_for_count(max(week_counts) if week_counts else 1)
        st.markdown("<div class='calendar-grid'>", unsafe_allow_html=True)
        cols = st.columns(7)
        for i in range(7):
            d = week_start + timedelta(days=i)
            weekday_idx = weekday_order[i]
            day_cls = "sun" if weekday_idx == 6 else "sat" if weekday_idx == 5 else "normal"
            cols[i].markdown(f"<div class='week-day-label {day_cls}'>{WEEKDAY_OPTIONS[weekday_idx]}</div>", unsafe_allow_html=True)
            selected_mark = "📌 " if d == target_date else ""
            if cols[i].button(
                f"{selected_mark}{d.day}일",
                use_container_width=True,
                key=f"weekly_pick_{d.isoformat()}",
            ):
                st.session_state["pending_target_date"] = d.isoformat()
                st.session_state["pending_main_tab"] = "일간 보기"
                st.rerun()
            cols[i].markdown(f"<div class='cal-list-wrap'>{day_items_list_html(filtered_active_items, d, min_height=week_box_height)}</div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

    with tab_map["월간 보기"]:
        month_title = f"{target_date.year}년 {target_date.month}월"
        month_nav_cols = st.columns([1, 6, 1])
        if month_nav_cols[0].button("◀", use_container_width=True, key="month_prev"):
            st.session_state["pending_target_date"] = add_months(target_date, -1).isoformat()
            st.rerun()
        month_nav_cols[1].markdown(f"<div class='calendar-caption' style='text-align:center'>{month_title}</div>", unsafe_allow_html=True)
        if month_nav_cols[2].button("▶", use_container_width=True, key="month_next"):
            st.session_state["pending_target_date"] = add_months(target_date, 1).isoformat()
            st.rerun()

        first_day = target_date.replace(day=1)
        first_weekday = (first_day.weekday() - week_start_idx) % 7
        _, last_day = monthrange(first_day.year, first_day.month)
        st.markdown("<div class='calendar-caption'>날짜를 누르면 체크리스트가 해당 날짜로 전환됩니다.</div>", unsafe_allow_html=True)
        day_cursor = 1
        total_slots = first_weekday + last_day
        rows = (total_slots + 6) // 7
        st.markdown("<div class='month-grid'><div class='calendar-grid'>", unsafe_allow_html=True)
        for row in range(rows):
            row_cols = st.columns(7)
            row_days: list[date] = []
            for col in range(7):
                slot = row * 7 + col
                if slot < first_weekday:
                    continue
                candidate_day = (slot - first_weekday) + 1
                if 1 <= candidate_day <= last_day:
                    row_days.append(first_day.replace(day=candidate_day))
            row_max_count = max((len(get_routines_for_date(filtered_active_items, d)) for d in row_days), default=1)
            row_box_height = list_box_height_for_count(row_max_count)
            for col in range(7):
                slot = row * 7 + col
                if row == 0:
                    weekday_index = weekday_order[col]
                    day_cls = "sun" if weekday_index == 6 else "sat" if weekday_index == 5 else "normal"
                    row_cols[col].markdown(f"<div class='week-day-label {day_cls}'>{WEEKDAY_OPTIONS[weekday_index]}</div>", unsafe_allow_html=True)
                if slot < first_weekday or day_cursor > last_day:
                    row_cols[col].write("")
                    continue

                current = first_day.replace(day=day_cursor)
                selected_mark = "📌 " if current == target_date else ""
                if row_cols[col].button(
                    f"{selected_mark}{day_cursor}일",
                    use_container_width=True,
                    key=f"month_pick_{current.isoformat()}",
                ):
                    st.session_state["pending_target_date"] = current.isoformat()
                    st.session_state["pending_main_tab"] = "일간 보기"
                    st.rerun()
                row_cols[col].markdown(f"<div class='cal-list-wrap'>{day_items_list_html(filtered_active_items, current, min_height=row_box_height)}</div>", unsafe_allow_html=True)
                day_cursor += 1
            if row < rows - 1:
                st.markdown("<div class='month-row-gap'></div>", unsafe_allow_html=True)
        st.markdown("</div></div>", unsafe_allow_html=True)

    with tab_map["친구 일정"]:
        st.markdown("<div class='calendar-caption'>친구의 날짜별 루틴/할일 상태를 확인할 수 있습니다.</div>", unsafe_allow_html=True)
        if not cloud_client or username == "local":
            st.info("친구 일정은 로그인(클라우드) 모드에서 확인할 수 있습니다.")
        else:
            social = normalize_social_state(st.session_state.get("social_state"))
            friends = social.get("friends", [])
            if not friends:
                st.info("일정을 확인하려면 먼저 친구를 추가해 주세요.")
            else:
                friend_options = {}
                for friend_username in friends:
                    friend_nickname = get_user_nickname(cloud_client, friend_username)
                    friend_options[f"{friend_nickname} (@{friend_username})"] = friend_username

                selected_friend_label = st.selectbox(
                    "친구 선택",
                    options=list(friend_options.keys()),
                    key="friend_schedule_target_main",
                )
                friend_date = st.date_input("조회 날짜", value=target_date, key="friend_schedule_date_main")

                selected_friend_username = friend_options.get(selected_friend_label, "")
                if selected_friend_username:
                    friend_bundle, friend_err = get_user_state_bundle(cloud_client, selected_friend_username)
                    if friend_err:
                        st.warning(friend_err)
                    else:
                        friend_profile = normalize_profile(selected_friend_username, friend_bundle.get("profile"))
                        if not bool(friend_profile.get("share_progress", True)):
                            st.info("이 친구는 현재 일정 공유를 비활성화했습니다.")
                        else:
                            friend_routines_raw = friend_bundle.get("routines", [])
                            friend_logs = friend_bundle.get("logs", {})
                            friend_routines, _ = normalize_routines(friend_routines_raw if isinstance(friend_routines_raw, list) else [])
                            friend_active_items = get_active_items(friend_routines)
                            if "friend_target_date_input" not in st.session_state:
                                st.session_state["friend_target_date_input"] = friend_date
                            selected_friend_date = st.session_state.get("friend_target_date_input", friend_date)
                            if not isinstance(selected_friend_date, date):
                                selected_friend_date = friend_date
                                st.session_state["friend_target_date_input"] = selected_friend_date

                            st.caption(f"{friend_profile.get('nickname', selected_friend_username)} 님 일정")
                            pending_friend_view_mode = st.session_state.pop("pending_friend_view_mode", None)
                            if pending_friend_view_mode in {"일간", "주간", "월간"}:
                                st.session_state["friend_view_mode"] = pending_friend_view_mode
                            if "friend_view_mode" not in st.session_state:
                                st.session_state["friend_view_mode"] = "일간"
                            friend_view_mode = st.radio("보기", ["일간", "주간", "월간"], horizontal=True, key="friend_view_mode")

                            if friend_view_mode == "일간":
                                day_nav_cols = st.columns([1, 6, 1])
                                if day_nav_cols[0].button("◀", use_container_width=True, key="friend_day_prev"):
                                    st.session_state["friend_target_date_input"] = selected_friend_date - timedelta(days=1)
                                    st.rerun()
                                day_nav_cols[1].markdown(
                                    f"<div class='calendar-caption' style='text-align:center'>{selected_friend_date.isoformat()}</div>",
                                    unsafe_allow_html=True,
                                )
                                if day_nav_cols[2].button("▶", use_container_width=True, key="friend_day_next"):
                                    st.session_state["friend_target_date_input"] = selected_friend_date + timedelta(days=1)
                                    st.rerun()

                                friend_day_items = get_routines_for_date(friend_active_items, selected_friend_date)
                                friend_day_log = friend_logs.get(selected_friend_date.isoformat(), {}) if isinstance(friend_logs, dict) else {}
                                if not friend_day_items:
                                    st.write("- 해당 날짜에 등록된 일정이 없습니다.")
                                else:
                                    render_readonly_status_board(friend_day_items, friend_day_log)

                            elif friend_view_mode == "주간":
                                week_nav_cols = st.columns([1, 6, 1])
                                if week_nav_cols[0].button("◀", use_container_width=True, key="friend_week_prev"):
                                    st.session_state["friend_target_date_input"] = selected_friend_date - timedelta(days=7)
                                    st.rerun()
                                week_number = week_of_month(selected_friend_date, week_start_idx)
                                week_title = f"{selected_friend_date.year}년 {selected_friend_date.month}월 {week_number}째주"
                                week_nav_cols[1].markdown(
                                    f"<div class='calendar-caption' style='text-align:center'>{week_title}</div>",
                                    unsafe_allow_html=True,
                                )
                                if week_nav_cols[2].button("▶", use_container_width=True, key="friend_week_next"):
                                    st.session_state["friend_target_date_input"] = selected_friend_date + timedelta(days=7)
                                    st.rerun()

                                week_start = selected_friend_date - timedelta(days=(selected_friend_date.weekday() - week_start_idx) % 7)
                                week_counts = [len(get_routines_for_date(friend_active_items, week_start + timedelta(days=i))) for i in range(7)]
                                week_box_height = list_box_height_for_count(max(week_counts) if week_counts else 1)
                                st.markdown("<div class='calendar-grid'>", unsafe_allow_html=True)
                                cols = st.columns(7)
                                for i in range(7):
                                    d = week_start + timedelta(days=i)
                                    weekday_idx = weekday_order[i]
                                    day_cls = "sun" if weekday_idx == 6 else "sat" if weekday_idx == 5 else "normal"
                                    cols[i].markdown(f"<div class='week-day-label {day_cls}'>{WEEKDAY_OPTIONS[weekday_idx]}</div>", unsafe_allow_html=True)
                                    selected_mark = "📌 " if d == selected_friend_date else ""
                                    if cols[i].button(
                                        f"{selected_mark}{d.day}일",
                                        use_container_width=True,
                                        key=f"friend_week_pick_{d.isoformat()}",
                                    ):
                                        st.session_state["friend_target_date_input"] = d
                                        st.session_state["pending_friend_view_mode"] = "일간"
                                        st.rerun()
                                    cols[i].markdown(f"<div class='cal-list-wrap'>{day_items_list_html(friend_active_items, d, min_height=week_box_height)}</div>", unsafe_allow_html=True)
                                st.markdown("</div>", unsafe_allow_html=True)

                            else:
                                month_nav_cols = st.columns([1, 6, 1])
                                if month_nav_cols[0].button("◀", use_container_width=True, key="friend_month_prev"):
                                    st.session_state["friend_target_date_input"] = add_months(selected_friend_date, -1)
                                    st.rerun()
                                month_nav_cols[1].markdown(
                                    f"<div class='calendar-caption' style='text-align:center'>{selected_friend_date.year}년 {selected_friend_date.month}월</div>",
                                    unsafe_allow_html=True,
                                )
                                if month_nav_cols[2].button("▶", use_container_width=True, key="friend_month_next"):
                                    st.session_state["friend_target_date_input"] = add_months(selected_friend_date, 1)
                                    st.rerun()

                                first_day = selected_friend_date.replace(day=1)
                                first_weekday = (first_day.weekday() - week_start_idx) % 7
                                _, last_day = monthrange(first_day.year, first_day.month)

                                day_cursor = 1
                                total_slots = first_weekday + last_day
                                rows = (total_slots + 6) // 7
                                st.markdown("<div class='month-grid'><div class='calendar-grid'>", unsafe_allow_html=True)
                                for row in range(rows):
                                    row_cols = st.columns(7)
                                    row_days: list[date] = []
                                    for col in range(7):
                                        slot = row * 7 + col
                                        if slot < first_weekday:
                                            continue
                                        candidate_day = (slot - first_weekday) + 1
                                        if 1 <= candidate_day <= last_day:
                                            row_days.append(first_day.replace(day=candidate_day))
                                    row_max_count = max((len(get_routines_for_date(friend_active_items, d)) for d in row_days), default=1)
                                    row_box_height = list_box_height_for_count(row_max_count)
                                    for col in range(7):
                                        slot = row * 7 + col
                                        if row == 0:
                                            weekday_index = weekday_order[col]
                                            day_cls = "sun" if weekday_index == 6 else "sat" if weekday_index == 5 else "normal"
                                            row_cols[col].markdown(f"<div class='week-day-label {day_cls}'>{WEEKDAY_OPTIONS[weekday_index]}</div>", unsafe_allow_html=True)
                                        if slot < first_weekday or day_cursor > last_day:
                                            row_cols[col].write("")
                                            continue

                                        current = first_day.replace(day=day_cursor)
                                        selected_mark = "📌 " if current == selected_friend_date else ""
                                        if row_cols[col].button(
                                            f"{selected_mark}{day_cursor}일",
                                            use_container_width=True,
                                            key=f"friend_month_pick_{current.isoformat()}",
                                        ):
                                            st.session_state["friend_target_date_input"] = current
                                            st.session_state["pending_friend_view_mode"] = "일간"
                                            st.rerun()
                                        row_cols[col].markdown(f"<div class='cal-list-wrap'>{day_items_list_html(friend_active_items, current, min_height=row_box_height)}</div>", unsafe_allow_html=True)
                                        day_cursor += 1
                                    if row < rows - 1:
                                        st.markdown("<div class='month-row-gap'></div>", unsafe_allow_html=True)
                                st.markdown("</div></div>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
