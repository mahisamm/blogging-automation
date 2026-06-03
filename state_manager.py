import json
import os
from datetime import datetime

STATE_FILE = "workflow_state.json"

DEFAULT_STATE = {
    "is_running": False,
    "current_step": 0,
    "steps": [
        {"id": 1, "name": "Read Pending Topic", "status": "pending", "details": ""},
        {"id": 2, "name": "Generate Article (Gemini)", "status": "pending", "details": ""},
        {"id": 3, "name": "Generate SEO Metadata", "status": "pending", "details": ""},
        {"id": 4, "name": "Publish to Blogger", "status": "pending", "details": ""},
        {"id": 5, "name": "Update Google Sheets", "status": "pending", "details": ""}
    ],
    "last_error": "",
    "last_updated": ""
}

def init_state():
    with open(STATE_FILE, "w") as f:
        json.dump(DEFAULT_STATE, f, indent=2)

def read_state():
    if not os.path.exists(STATE_FILE):
        init_state()
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return DEFAULT_STATE

def write_state(state):
    state["last_updated"] = datetime.now().isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def start_run():
    state = DEFAULT_STATE.copy()
    state["is_running"] = True
    write_state(state)

def update_step(step_id, status, details=""):
    state = read_state()
    state["current_step"] = step_id
    for step in state["steps"]:
        if step["id"] == step_id:
            step["status"] = status
            step["details"] = details
    write_state(state)

def end_run(error=""):
    state = read_state()
    state["is_running"] = False
    state["current_step"] = 0
    if error:
        state["last_error"] = error
    write_state(state)

if not os.path.exists(STATE_FILE):
    init_state()
