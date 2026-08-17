import hashlib
import json
import os
import re

import requests

URL = "https://www.district.in/movies/magic-frames-cinemas-kakkanad-in-kochi-CD1102417"
NOT_STARTED_TEXT = "No shows playing at the moment"

# The theatre-specific block on the page sits between these two markers.
# Everything before START_MARKER (nav bars, footers) and after END_MARKER
# (city-wide movie lists, FAQ boilerplate) is noisy and unrelated to this
# specific cinema, so we scope our change-detection to just this window.
START_MARKER = "Get directions"
END_MARKER = "Where is Magic Frames Cinemas"

NTFY_TOPIC = os.environ.get("NTFY_TOPIC")
STATE_FILE = "state.json"

DEFAULT_STATE = {
    "status": "not_started",   # "not_started" -> "started"
    "last_hash": None,         # hash of the scoped section, last run
    "last_change_notified_hash": None,  # hash we already alerted about
}


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return dict(DEFAULT_STATE)


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def fetch_scoped_section(html):
    start = html.find(START_MARKER)
    end = html.find(END_MARKER)
    if start == -1 or end == -1 or end <= start:
        # Markers not found (page structure changed) - fall back to
        # hashing the whole page so we still catch SOMETHING changed.
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
            "Click": URL,
        },
        timeout=15,
    )


def main():
    state = load_state()

    if state["status"] == "started":
        print("Already marked as started. Skipping.")
        return

    resp = requests.get(URL, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    html = resp.text

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

    # Still shows the "not started" text, but check if ANYTHING else in
    # that section changed (new date field, extra note, wording tweak, etc.)
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
