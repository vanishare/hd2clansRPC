import html
import json
import os
import re
import threading
import sys
import time
import urllib.parse
import urllib.request
import winreg
from dataclasses import dataclass
from html.parser import HTMLParser
import logging
from logging.handlers import RotatingFileHandler

import psutil
from pypresence import Presence


DEFAULT_CONFIG = {
    "client_id": "1518564205362413650",
    "process_name": "helldivers2.exe",
    "app_name": "hd2_custom_rpc_clan",
    "autostart": True,
    "clan_url": "https://hd2clans.com/clan/66",
    "hangar_url": "",
    "clan_name": "",
    "large_image": "icon",
    "small_image": "small_icon",
    "small_text": "Helldivers 2",
    "fallback_details": "Helldivers 2",
    "fallback_state": "Fighting for Managed Democracy",
    "operation_relation": "all",
    "show_concluded_operations": False,
    "launch_delay_seconds": 20,
    "process_check_seconds": 5,
    "presence_refresh_seconds": 30,
    "site_refresh_seconds": 300,
    "request_timeout_seconds": 12,
    "user_agent": "HD2 Clan RPC/1.1",
    "allow_homepage_operation_fallback": False,
    "log_enabled": True,
    "log_file": "hd2_rpc.log",
    "log_max_bytes": 262144,
    "log_backup_count": 3,
    "tray_enabled": True,
}

REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
COMMANDS = {
    "exit": False,
    "reload_config": False,
    "reconnect_rpc": False,
}


@dataclass
class PageLink:
    href: str
    text: str


@dataclass
class ClanStatus:
    kind: str
    details: str
    state: str
    url: str
    clan_name: str


class TextPage(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.headings = []
        self.text_parts = []
        self.title = ""
        self._current_link = None
        self._current_heading = None
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self._current_link = {"href": attrs["href"], "text": ""}
        elif tag in {"h1", "h2", "h3"}:
            self._current_heading = ""
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "a" and self._current_link:
            self.links.append(PageLink(self._current_link["href"], clean(self._current_link["text"])))
            self._current_link = None
        elif tag in {"h1", "h2", "h3"} and self._current_heading is not None:
            self.headings.append(clean(self._current_heading))
            self._current_heading = None
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if not data:
            return
        self.text_parts.append(data)
        if self._current_link is not None:
            self._current_link["text"] += data
        if self._current_heading is not None:
            self._current_heading += data
        if self._in_title:
            self.title += data

    @property
    def text(self):
        return clean(" ".join(self.text_parts))


def clean(value):
    value = html.unescape(value or "")
    return re.sub(r"\s+", " ", value).strip()


def short(value, max_len=128):
    value = clean(value)
    if len(value) <= max_len:
        return value
    return value[: max_len - 1].rstrip() + "..."


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def config_path():
    return os.path.join(app_dir(), "hd2_rpc_config.json")


def config_mtime():
    try:
        return os.path.getmtime(config_path())
    except OSError:
        return 0


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    path = config_path()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("hd2_rpc_config.json must contain an object")
        cfg.update(data)
    return cfg


def setup_logging(cfg):
    logger = logging.getLogger("hd2_rpc")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    if not cfg.get("log_enabled", True):
        logger.addHandler(logging.NullHandler())
        return logger

    log_file = str(cfg.get("log_file") or "hd2_rpc.log")
    if not os.path.isabs(log_file):
        log_file = os.path.join(app_dir(), log_file)
    handler = RotatingFileHandler(
        log_file,
        maxBytes=int(cfg.get("log_max_bytes") or 262144),
        backupCount=int(cfg.get("log_backup_count") or 3),
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


def open_path(path, logger):
    try:
        if os.path.exists(path):
            os.startfile(path)
        else:
            logger.info("Cannot open missing path: %s", path)
    except Exception:
        logger.exception("Failed to open path: %s", path)


def log_path(cfg):
    log_file = str(cfg.get("log_file") or "hd2_rpc.log")
    if not os.path.isabs(log_file):
        return os.path.join(app_dir(), log_file)
    return log_file


def start_tray_icon(cfg, logger):
    try:
        import pystray
        from PIL import Image, ImageDraw
    except Exception:
        logger.info("Tray icon disabled: install pystray and Pillow to enable it")
        return None

    def make_icon():
        image = Image.new("RGBA", (64, 64), (18, 24, 38, 255))
        draw = ImageDraw.Draw(image)
        draw.ellipse((8, 8, 56, 56), fill=(249, 196, 72, 255))
        draw.rectangle((28, 14, 36, 50), fill=(18, 24, 38, 255))
        draw.rectangle((14, 28, 50, 36), fill=(18, 24, 38, 255))
        return image

    def open_config(icon=None, item=None):
        open_path(config_path(), logger)

    def open_log(icon=None, item=None):
        open_path(log_path(cfg), logger)

    def reload_config(icon=None, item=None):
        COMMANDS["reload_config"] = True

    def reconnect_rpc(icon=None, item=None):
        COMMANDS["reconnect_rpc"] = True

    def quit_app(icon=None, item=None):
        COMMANDS["exit"] = True
        if icon:
            icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Open config", open_config),
        pystray.MenuItem("Open log", open_log),
        pystray.MenuItem("Reload config", reload_config),
        pystray.MenuItem("Reconnect RPC", reconnect_rpc),
        pystray.MenuItem("Exit", quit_app),
    )
    icon = pystray.Icon("hd2_rpc", make_icon(), "HD2 Clan RPC", menu)
    thread = threading.Thread(target=icon.run, daemon=True)
    thread.start()
    logger.info("Tray icon started")
    return icon


def setup_autostart(cfg):
    if not cfg.get("autostart", True):
        return
    exe_path = os.path.abspath(sys.argv[0])
    app_name = str(cfg.get("app_name") or DEFAULT_CONFIG["app_name"])
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, app_name)
            if os.path.normcase(value.replace('"', "").strip()) == os.path.normcase(exe_path):
                return
    except Exception:
        pass
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, f'"{exe_path}"')
    except Exception:
        pass


def absolute(base_url, href):
    return urllib.parse.urljoin(base_url, href or "")


def fetch(url, cfg):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": str(cfg.get("user_agent") or DEFAULT_CONFIG["user_agent"]),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    timeout = float(cfg.get("request_timeout_seconds") or 12)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, "replace")


def parse_url(url, cfg):
    parser = TextPage()
    parser.feed(fetch(url, cfg))
    parser.close()
    return parser


def strip_tags(markup):
    markup = re.sub(r"<script\b.*?</script>", " ", markup, flags=re.I | re.S)
    markup = re.sub(r"<style\b.*?</style>", " ", markup, flags=re.I | re.S)
    markup = re.sub(r"<[^>]+>", " ", markup)
    return clean(markup)


def clan_id_from_url(url):
    match = re.search(r"/clan/(\d+)", url)
    return match.group(1) if match else ""


def get_clan_name(page, cfg):
    configured = clean(cfg.get("clan_name", ""))
    if configured:
        return configured
    for heading in page.headings:
        if heading and "operations history" not in heading.lower():
            return heading
    title = clean(page.title).split(" - ")[0]
    return title or "HD2 Clan"


def find_hangar_url(clan_url, clan_page, cfg):
    configured = clean(cfg.get("hangar_url", ""))
    if configured:
        return absolute(clan_url, configured)
    for link in clan_page.links:
        haystack = f"{link.href} {link.text}".lower()
        if "hangar" in haystack or "dreadnought" in haystack:
            return absolute(clan_url, link.href)
    clan_id = clan_id_from_url(clan_url)
    if clan_id:
        return absolute(clan_url, f"/clan/{clan_id}/hangar")
    return ""


def operation_links_from_page(page, base_url):
    links = []
    seen = set()
    for link in page.links:
        haystack = f"{link.href} {link.text}".lower()
        if not re.search(r"(operation|order|briefing|stats)", haystack):
            continue
        url = absolute(base_url, link.href)
        if url in seen:
            continue
        seen.add(url)
        links.append(PageLink(url, link.text))
    return links


def text_window(text, marker, before=350, after=950):
    text = clean(text)
    marker = clean(marker)
    if marker and marker in text:
        index = text.find(marker)
        return text[max(0, index - before): index + len(marker) + after]
    return text[: before + after]


def score_operation(window):
    score = 0
    low = window.lower()
    if "active" in low:
        score += 60
    if "launches in" in low or "pending" in low:
        score += 50
    if "goal progress" in low or re.search(r"\b\d{1,3}%\b", window):
        score += 20
    if "participants" in low or "reports" in low:
        score += 10
    if "concluded" in low or "goals achieved" in low:
        score -= 30
    return score


def extract_progress(window):
    patterns = [
        r"Goal Progress:\s*\d{1,3}%",
        r"\b\d{1,3}%\b",
        r"\d[\d,]*\s*/\s*\d[\d,]*(?:\s*-\s*COMPLETE!)?",
        r"\d+\s+participants?\s*\|\s*\d+\s+reports?",
        r"Launches in\s+[^.]{1,60}",
        r"Timed Order\s*\|\s*[^.]{1,40}",
        r"Goals Achieved",
        r"Concluded",
    ]
    for pattern in patterns:
        match = re.search(pattern, window, re.I)
        if match:
            return clean(match.group(0))
    return ""


def data_attr(markup, name):
    match = re.search(rf'\bdata-{re.escape(name)}="([^"]*)"', markup, re.I)
    return clean(match.group(1)) if match else ""


def find_best_operation_from_api(clan_url, clan_name, cfg):
    clan_id = clan_id_from_url(clan_url)
    if not clan_id:
        return None

    api_url = absolute(clan_url, f"/api/clan/{clan_id}/operations?limit=30&offset=0")
    body = fetch(api_url, cfg)
    starts = [match.start() for match in re.finditer(r'\bdata-opcode="', body, re.I)]
    if not starts:
        return None
    starts.append(len(body))

    relation = clean(cfg.get("operation_relation", "all")).lower()
    show_concluded = bool(cfg.get("show_concluded_operations", False))
    candidates = []

    for index in range(len(starts) - 1):
        card = body[starts[index]:starts[index + 1]]
        opcode = data_attr(card, "opcode")
        status = data_attr(card, "status").lower()
        is_issued = data_attr(card, "is-issued") == "1"
        is_participated = data_attr(card, "is-participated") == "1"

        if relation == "issued" and not is_issued:
            continue
        if relation == "participated" and not is_participated:
            continue
        if status == "concluded" and not show_concluded:
            continue

        link_match = re.search(r'<a\s+href="([^"]*?/operation/[^"]+)"[^>]*>(.*?)</a>', card, re.I | re.S)
        title = strip_tags(link_match.group(2)) if link_match else opcode
        url = absolute(clan_url, link_match.group(1) if link_match else f"/operation/{opcode}")
        text = strip_tags(card)
        progress = extract_progress(text)

        score = 0
        if status == "active":
            score += 200
        elif status in {"pending", "incoming"}:
            score += 180
        elif status == "concluded":
            score += 10
        if is_issued:
            score += 30
        if is_participated:
            score += 10
        if progress:
            score += 5

        state = progress or status.title() or "Clan order"
        candidates.append((score, ClanStatus("operation", f"Order: {title}", state, url, clan_name)))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def find_best_operation(clan_url, clan_page, clan_name, cfg):
    try:
        api_operation = find_best_operation_from_api(clan_url, clan_name, cfg)
        if api_operation:
            return api_operation
    except Exception:
        pass

    candidates = []
    pages_to_scan = [(clan_url, clan_page)]

    if cfg.get("allow_homepage_operation_fallback", False):
        try:
            home_url = urllib.parse.urljoin(clan_url, "/")
            pages_to_scan.append((home_url, parse_url(home_url, cfg)))
        except Exception:
            pass

    for page_url, page in pages_to_scan:
        page_text = page.text
        for link in operation_links_from_page(page, page_url):
            if not link.text or link.text.lower() in {"view briefing", "view full stats"}:
                continue
            window = text_window(page_text, link.text)
            if clan_name and clan_name.lower() not in window.lower() and page_url != clan_url:
                continue
            candidates.append((score_operation(window), link, window))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    score, link, window = candidates[0]
    if score < 0:
        return None

    progress = extract_progress(window)
    if progress:
        state = progress
    elif "active" in window.lower():
        state = "Active order"
    elif "launches in" in window.lower():
        state = extract_progress(window) or "Incoming order"
    else:
        state = "Clan order"

    return ClanStatus(
        kind="operation",
        details=f"Order: {short(link.text, 90)}",
        state=short(state),
        url=link.href,
        clan_name=clan_name,
    )


def extract_recent_fleet_activity(hangar_url, cfg):
    if not hangar_url:
        return None
    page = parse_url(hangar_url, cfg)
    text = page.text
    low = text.lower()
    marker = "recent activity" if "recent activity" in low else "recent fleet activity"
    if marker in low:
        start = low.find(marker) + len(marker)
        end_candidates = [
            low.find("clan fleet registry", start),
            low.find("fleet registry", start),
            low.find("featured ship", start),
        ]
        end_candidates = [pos for pos in end_candidates if pos != -1]
        end = min(end_candidates) if end_candidates else start + 600
        activity = text[start:end]
    else:
        activity = text[:800]

    activity = clean(activity)
    if not activity:
        return None

    readiness = ""
    readiness_match = re.search(r"CLAN FLEET STATUS\s+(.{1,160}?\b\d{1,3}%\s+Operational)", text, re.I)
    if readiness_match:
        readiness = clean(readiness_match.group(1))

    # Common shapes:
    # Jul 1 Reserve SES Star of Freedom Super Destroyer
    # Jun 23 Full Repair Complete SES Wings of Judgment Super Destroyer Freedom Alliance Orbital Hub
    actions = [
        "Full Repair Complete",
        "Preparing to Deploy",
        "Escorting DSS",
        "Drydocked",
        "Deployed",
        "Anchored",
        "Reserve",
    ]
    action_pattern = "|".join(re.escape(action) for action in actions)
    next_date = r"(?=\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+|$)"
    match = re.search(
        rf"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{{1,2}})\s+"
        rf"({action_pattern})\s+"
        rf"(.+?){next_date}",
        activity,
        re.I,
    )
    if match:
        date = clean(match.group(1))
        action = clean(match.group(2))
        rest = clean(match.group(3))
        details = f"Fleet: {action}"
        if readiness:
            details = f"Fleet: {readiness}"
        return ClanStatus(
            kind="fleet",
            details=short(details, 128),
            state=short(f"{date} - {action} {rest}", 128),
            url=hangar_url,
            clan_name="",
        )

    first_sentence = re.split(r"(?<=[.!?])\s+", activity)[0]
    return ClanStatus(
        kind="fleet",
        details="Fleet Activity",
        state=short(first_sentence or activity, 128),
        url=hangar_url,
        clan_name="",
    )


def get_clan_status(cfg):
    clan_url = clean(cfg.get("clan_url") or DEFAULT_CONFIG["clan_url"])
    clan_page = parse_url(clan_url, cfg)
    clan_name = get_clan_name(clan_page, cfg)

    operation = find_best_operation(clan_url, clan_page, clan_name, cfg)
    if operation:
        operation.clan_name = clan_name
        return operation

    hangar_url = find_hangar_url(clan_url, clan_page, cfg)
    try:
        fleet = extract_recent_fleet_activity(hangar_url, cfg)
        if fleet:
            fleet.clan_name = clan_name
            return fleet
    except Exception:
        pass

    return ClanStatus(
        kind="fallback",
        details=short(cfg.get("fallback_details")),
        state=short(cfg.get("fallback_state")),
        url=clan_url,
        clan_name=clan_name,
    )


def get_game_pid(process_name):
    process_name = process_name.lower()
    try:
        for proc in psutil.process_iter(["name", "pid"]):
            if proc.info["name"] and proc.info["name"].lower() == process_name:
                return proc.info["pid"]
    except Exception:
        return None
    return None


def build_payload(cfg, status, start_time):
    buttons = [{"label": "Clan Page", "url": clean(cfg.get("clan_url"))}]
    if status.url and status.url != cfg.get("clan_url"):
        buttons.append({"label": "Open Status", "url": status.url})

    payload = {
        "details": short(status.details),
        "state": short(status.state),
        "start": start_time,
        "large_text": short(status.clan_name or cfg.get("clan_name") or "HD2 Clan"),
        "small_text": short(cfg.get("small_text") or "Helldivers 2"),
        "buttons": buttons[:2],
    }
    if cfg.get("large_image"):
        payload["large_image"] = str(cfg["large_image"])
    if cfg.get("small_image"):
        payload["small_image"] = str(cfg["small_image"])
    return payload


def main():
    cfg = load_config()
    logger = setup_logging(cfg)
    setup_autostart(cfg)
    tray_icon = start_tray_icon(cfg, logger) if cfg.get("tray_enabled", True) else None

    rpc = None
    first_seen = None
    game_start = None
    current_pid = None
    status = ClanStatus("fallback", cfg["fallback_details"], cfg["fallback_state"], cfg["clan_url"], cfg.get("clan_name", ""))
    last_site_refresh = 0
    last_presence = 0
    last_cfg_mtime = config_mtime()

    while True:
        try:
            if COMMANDS["exit"]:
                break

            now = time.time()

            new_mtime = config_mtime()
            if COMMANDS["reload_config"] or new_mtime != last_cfg_mtime:
                old_client_id = str(cfg.get("client_id", ""))
                cfg = load_config()
                logger = setup_logging(cfg)
                last_cfg_mtime = new_mtime
                COMMANDS["reload_config"] = False
                last_site_refresh = 0
                last_presence = 0
                status = ClanStatus("fallback", cfg["fallback_details"], cfg["fallback_state"], cfg["clan_url"], cfg.get("clan_name", ""))
                logger.info("Config reloaded")
                if str(cfg.get("client_id", "")) != old_client_id and rpc:
                    try:
                        rpc.clear()
                        rpc.close()
                    except Exception:
                        pass
                    rpc = None
                    logger.info("Discord RPC reconnect scheduled because client_id changed")

            if COMMANDS["reconnect_rpc"]:
                COMMANDS["reconnect_rpc"] = False
                if rpc:
                    try:
                        rpc.clear()
                        rpc.close()
                    except Exception:
                        pass
                rpc = None
                last_presence = 0
                logger.info("Discord RPC reconnect requested")

            pid = get_game_pid(str(cfg.get("process_name") or "helldivers2.exe"))

            if not pid:
                if rpc:
                    try:
                        rpc.clear()
                        rpc.close()
                    except Exception:
                        pass
                rpc = None
                first_seen = None
                game_start = None
                current_pid = None
                time.sleep(float(cfg.get("process_check_seconds") or 5))
                continue

            if current_pid != pid:
                current_pid = pid
                first_seen = now
                game_start = None
                last_presence = 0
                last_site_refresh = 0

            if now - first_seen < float(cfg.get("launch_delay_seconds") or 20):
                time.sleep(float(cfg.get("process_check_seconds") or 5))
                continue

            if game_start is None:
                try:
                    game_start = int(psutil.Process(pid).create_time())
                except Exception:
                    game_start = int(now)

            if now - last_site_refresh >= float(cfg.get("site_refresh_seconds") or 300):
                try:
                    status = get_clan_status(cfg)
                    logger.info("Selected status kind=%s details=%r state=%r url=%s", status.kind, status.details, status.state, status.url)
                except Exception:
                    logger.exception("Failed to refresh clan status")
                last_site_refresh = now

            if rpc is None:
                try:
                    rpc = Presence(str(cfg["client_id"]))
                    rpc.connect()
                    logger.info("Discord RPC connected")
                except Exception:
                    rpc = None
                    logger.exception("Failed to connect Discord RPC")
                    time.sleep(10)
                    continue

            if now - last_presence >= float(cfg.get("presence_refresh_seconds") or 30):
                try:
                    rpc.update(**build_payload(cfg, status, game_start))
                    last_presence = now
                except Exception:
                    logger.exception("Failed to update Discord RPC")
                    try:
                        rpc.close()
                    except Exception:
                        pass
                    rpc = None

            time.sleep(float(cfg.get("process_check_seconds") or 5))
        except KeyboardInterrupt:
            break
        except Exception:
            logger.exception("Unexpected main loop error")
            time.sleep(float(cfg.get("process_check_seconds") or 5))

    if rpc:
        try:
            rpc.clear()
            rpc.close()
        except Exception:
            pass
    if tray_icon:
        try:
            tray_icon.stop()
        except Exception:
            pass


if __name__ == "__main__":
    main()
