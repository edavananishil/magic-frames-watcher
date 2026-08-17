import hashlib
import json
import os
import re

import requests
from curl_cffi import requests as cffi_requests

TARGET_URL = "https://www.district.in/movies/magic-frames-cinemas-kakkanad-in-kochi-CD1102417"
READER_URL = "https://r.jina.ai/" + TARGET_URL

NOT_STARTED_TEXT = "No shows playing at the moment"

# The theatre-specific block on the page sits between these two markers.
START_MARKER = "Get directions"
END_MARKER = "Where is Magic Frames Cinemas"

NTFY_TOPIC = os.environ.get("NTFY_TOPIC")
STATE_FILE = "state.json"

DEFAULT_STATE = {
    "status": "not_started",
    "last_hash": None,
    "last_change_notified_hash": None,
}

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
}


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return dict(DEFAULT_STATE)


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def fetch_page():
    # Attempt 1: curl_cffi impersonating a real Chrome browser's TLS/network
    # fingerprint. This gets past bot-detection systems that block based on
    # low-level connection signatures, not just headers.
    try:
        resp = cffi_requests.get(TARGET_URL, impersonate="chrome124", timeout=20)
        if resp.status_code == 200:
            print("Fetched via curl_cffi (Chrome impersonation).")
            return resp.text
        print(f"curl_cffi fetch returned status {resp.status_code}, trying next method...")
    except Exception as e:
        print(f"curl_cffi fetch failed ({e}), trying next method...")

    # Attempt 2: plain requests with realistic browser-like headers.
    try:
        resp = requests.get(TARGET_URL, timeout=20, headers=BROWSER_HEADERS)
        if resp.status_code == 200:
            print("Fetched via plain requests.")
            return resp.text
        print(f"Direct fetch returned status {resp.status_code}, trying proxy fallback...")
    except requests.RequestException as e:
        print(f"Direct fetch failed ({e}), trying proxy fallback...")

    # Attempt 3: r.jina.ai reader proxy as a last resort.
    resp = requests.get(
        READER_URL,
        timeout=30,
        headers={"User-Agent": BROWSER_HEADERS["User-Agent"]},
    )
    resp.raise_for_status()
    print("Fetched via r.jina.ai proxy.")
    return resp.text


def fetch_scoped_section(html):
    start = html.find(START_MARKER)
    end = html.find(END_MARKER)
    if start == -1 or end == -1 or end <= start:
        return html
    return html[start:end]


def normalize(text):
    return re.sub(r"\s+", " ", text).strip()


def hash_of(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def notify(title, message, priority="urgent", tags="movie_camera,tada"):
    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=message.encode("utf-8"),
        headers={
            "Title": title,
            "Priority": priority,
            "Tags": tags,
            "Click": TARGET_URL,
        },
        timeout=15,
    )


def main():
    state = load_state()

    if state["status"] == "started":
        print("Already marked as started. Skipping.")
        return

    html = fetch_page()

    section = normalize(fetch_scoped_section(html))
    current_hash = hash_of(section)

    booking_open = NOT_STARTED_TEXT not in section

    if booking_open:
        print("Booking text is gone - booking appears to have opened!")
        notify(
            "Booking Started - Magic Frames Kakkanad",
            "The 'no shows' message is gone from the page - booking may be open. Go check now!",
            priority="urgent",
            tags="movie_camera,tada",
        )
        state["status"] = "started"
        state["last_hash"] = current_hash
        save_state(state)
        return

    if state["last_hash"] is not None and current_hash != state["last_hash"]:
        if current_hash != state.get("last_change_notified_hash"):
            print("Section changed but booking text still present - alerting.")
            notify(
                "Magic Frames Kakkanad - page changed",
                "Something changed on the theatre's booking section, but it doesn't "
                "clearly say booking is open yet. Worth a manual check.",
                priority="default",
                tags="eyes",
            )
            state["last_change_notified_hash"] = current_hash
        else:
            print("Section changed but we already alerted about this exact change.")
    else:
        print("No change detected. Still not started.")

    state["last_hash"] = current_hash
    save_state(state)


if __name__ == "__main__":
    main()
