# -*- coding: utf-8 -*-
"""
Avito Bulk Uploader with automatic image selection.

This script reads advertisement data from a CSV or XLSX file and
prepares payloads for Avito's bulk API. For each ad, it selects a
random set of images from subfolders under a base directory.

Actual uploading of images is stubbed out because the documented
endpoint returns 404 in testing. The script therefore always returns
"dummy_id" for uploaded images. Replace `upload_image` with a real
implementation if necessary.
"""

import os
import sys
import time
import random
from itertools import islice
from typing import Dict, List, Iterable

import pandas as pd
import requests
try:
    import PySimpleGUI as sg
except ImportError:  # pragma: no cover - handled in runtime
    raise ImportError(
        "PySimpleGUI is not installed. Install it via:\n"
        "python -m pip uninstall PySimpleGUI\n"
        "python -m pip cache purge\n"
        "python -m pip install --upgrade --extra-index-url https://PySimpleGUI.net/install PySimpleGUI"
    )

API_BASE = "https://api.avito.ru"
RATE_LIMIT_SLEEP = 1.1  # seconds between bulk requests (limit 60 req/min)

# ----------------------------------------------------------------------------
# Credentials are read from environment variables to avoid hard-coding secrets
# ----------------------------------------------------------------------------
CLIENT_ID = os.getenv("AVITO_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("AVITO_CLIENT_SECRET", "")

# ----------------------------------------------------------------------------
# Path to a directory containing subfolders with images
# ----------------------------------------------------------------------------
BASE_IMAGE_PATH = os.getenv("AVITO_IMAGE_PATH", "./images")
# ---------------------------------------------------------------------------
#  Avito helpers
# ---------------------------------------------------------------------------

def get_token() -> str:
    """Return OAuth2 access token using the provided credentials."""
    try:
        resp = requests.post(
            f"{API_BASE}/token",
            auth=(CLIENT_ID, CLIENT_SECRET),
            data={"grant_type": "client_credentials"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("access_token", "")
    except Exception as e:  # pragma: no cover - network failures are ignored
        print(f"Could not obtain token ({e}), running in test mode.")
        return ""


def upload_image(file_path: str, token: str) -> str:
    """Stub for image upload: always return a dummy ID."""
    print(f"Using dummy_id instead of uploading: {file_path}")
    return "dummy_id"
# ---------------------------------------------------------------------------
#  Utility helpers
# ---------------------------------------------------------------------------

def chunked(iterable: Iterable, size: int = 50) -> Iterable[List]:
    """Yield items from *iterable* in chunks of length *size*."""
    it = iter(iterable)
    while (batch := list(islice(it, size))):
        yield batch
# ---------------------------------------------------------------------------
#  GUI helpers (version-safe)
# ---------------------------------------------------------------------------

def _init_theme() -> None:
    try:
        sg.theme("SystemDefault")
    except Exception:
        try:
            sg.ChangeLookAndFeel("SystemDefault")
        except Exception:
            pass


def _create_window(title: str, layout, **kwargs):
    if hasattr(sg, "Window"):
        return sg.Window(title, layout, **kwargs)
    if hasattr(sg, "FlexForm"):
        return sg.FlexForm(title, layout, **kwargs)
    raise RuntimeError("Your PySimpleGUI version is too old. Update pip.")


def _build_layout():
    return [
        [sg.Text("Avito Bulk Uploader", font=(None, 16, "bold"))],
        [sg.Text("Source file (.csv/.xlsx):"), sg.Input(key="-FILE-", enable_events=True), sg.FileBrowse()],
        [sg.Table(values=[], headings=[], key="-TABLE-", auto_size_columns=True, num_rows=10, justification="left", alternating_row_color="#f0f0ff")],
        [sg.Button("Send to Avito", key="-SEND-", disabled=True), sg.ProgressBar(max_value=100, orientation="h", size=(40,20), key="-PROG-")],
        [sg.Multiline(key="-LOG-", size=(100,15), autoscroll=True, write_only=True)],
    ]

def log(window, *msg):
    window["-LOG-"].print(*msg)
# ---------------------------------------------------------------------------
#  Image path generation
# ---------------------------------------------------------------------------

def generate_image_paths(base_path: str, num_ads: int = 200, per_ad: int = 10) -> List[str]:
    subdirs = [os.path.join(base_path, d) for d in os.listdir(base_path) if os.path.isdir(os.path.join(base_path, d))]
    if not subdirs:
        raise RuntimeError(f"No subfolders with images in {base_path}")
    files_by_folder: Dict[str, List[str]] = {}
    for folder in subdirs:
        imgs = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith((".jpg", ".jpeg", ".png"))]
        files_by_folder[folder] = imgs.copy()
    total_needed = num_ads * per_ad
    total_available = sum(len(lst) for lst in files_by_folder.values())
    if total_available < total_needed:
        raise RuntimeError(f"Not enough files: need {total_needed}, have {total_available}")
    used_files = set()
    image_path_rows: List[str] = []
    folder_list = list(files_by_folder.keys())
    for _ in range(num_ads):
        chosen_folders = random.sample(folder_list, per_ad)
        selected_paths: List[str] = []
        for fld in chosen_folders:
            pool = [f for f in files_by_folder[fld] if f not in used_files]
            if not pool:
                raise RuntimeError(f"Images in folder {fld} are exhausted")
            img = random.choice(pool)
            used_files.add(img)
            selected_paths.append(img)
        image_path_rows.append("|".join(selected_paths))
    return image_path_rows
# ---------------------------------------------------------------------------
#  Preparing data and payload
# ---------------------------------------------------------------------------

def prepare_items_with_local_images(df: pd.DataFrame) -> List[Dict]:
    required_cols = {"title", "description", "price", "category_id", "region_id", "city_id", "image_path"}
    missing = required_cols - {c.lower() for c in df.columns}
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")
    token = get_token()
    items: List[Dict] = []
    for idx, row in df.iterrows():
        paths = [p.strip() for p in str(row["image_path"]).split("|") if p.strip()]
        if not paths:
            image_ids = [{"id": "dummy_id"}]
        else:
            image_ids: List[Dict[str, str]] = []
            for p in paths:
                if not os.path.isfile(p):
                    print(f"Warning: file not found, skipping: {p}")
                    continue
                img_id = upload_image(p, token)
                image_ids.append({"id": img_id})
                time.sleep(0.2)  # small delay
            if not image_ids:
                image_ids = [{"id": "dummy_id"}]
        payload = {
            "external_id": str(row.get("external_id", idx)),
            "title": row["title"],
            "description": row["description"],
            "category_id": int(row["category_id"]),
            "price": {"value": float(row["price"]), "currency": str(row.get("currency", "RUB"))},
            "images": image_ids,
            "location": {"region_id": int(row["region_id"]), "city_id": int(row["city_id"])}
        }
        items.append(payload)
    return items
# ---------------------------------------------------------------------------
#  Avito bulk send workers (GUI)
# ---------------------------------------------------------------------------

def _send_bulk(items: List[Dict], token: str) -> List[Dict]:
    resp = requests.post(
        f"{API_BASE}/core/v1/items/bulk",
        json={"items": items},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _poll_task(task_id: str, token: str, interval: float = 10.0) -> Dict:
    url = f"{API_BASE}/core/v1/items/bulk/{task_id}"
    while True:
        resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") not in {"QUEUED", "PROCESSING", "VERIFICATION"}:
            return data
        time.sleep(interval)


def _worker_send(window, items: List[Dict]):
    try:
        token = get_token()
        total = len(items)
        window["-PROG-"].update(current_count=0, max=total)
        sent = 0
        for batch in chunked(items, 50):
            for task in _send_bulk(batch, token):
                status = _poll_task(task["task_id"], token, interval=5)
                log(window, f"{task['external_id']}: {status['status']}")
            sent += len(batch)
            window["-PROG-"].update(current_count=sent)
            time.sleep(RATE_LIMIT_SLEEP)
        log(window, "Upload finished!")
    except Exception as exc:  # pragma: no cover - GUI errors
        log(window, "ERROR:", exc)
# ---------------------------------------------------------------------------
#  GUI Entry Point
# ---------------------------------------------------------------------------

def main_gui() -> None:
    _init_theme()
    window = _create_window("Avito Bulk Uploader", _build_layout(), finalize=True, resizable=True)
    df = None
    while True:
        event, values = window.read()
        if event in (sg.WIN_CLOSED, "Exit"):
            break
        if event == "-FILE-":
            path = values["-FILE-"]
            if path:
                try:
                    df = pd.read_csv(path) if path.lower().endswith(".csv") else pd.read_excel(path)
                    window["-TABLE-"].update(values=df.values.tolist(), headings=list(df.columns))
                    window["-SEND-"].update(disabled=False)
                    log(window, f"Loaded {len(df)} rows from {os.path.basename(path)}")
                except Exception as exc:  # pragma: no cover - file errors
                    log(window, f"Could not read file: {exc}")
        if event == "-SEND-" and df is not None:
            items_to_send = prepare_items_with_local_images(df)
            import threading
            threading.Thread(target=_worker_send, args=(window, items_to_send), daemon=True).start()
            window["-SEND-"].update(disabled=True)
    window.close()
# ---------------------------------------------------------------------------
#  Example without GUI
# ---------------------------------------------------------------------------

def main_example() -> None:
    num_ads = 200
    per_ad = 10
    image_paths = generate_image_paths(BASE_IMAGE_PATH, num_ads=num_ads, per_ad=per_ad)
    data = {
        "title": [f"Item{i}" for i in range(1, num_ads + 1)],
        "description": [f"Description{i}" for i in range(1, num_ads + 1)],
        "price": [1000 + i for i in range(num_ads)],
        "category_id": [23] * num_ads,
        "region_id": [653240] * num_ads,
        "city_id": [645680] * num_ads,
        "image_path": image_paths,
    }
    df = pd.DataFrame(data)
    print("Preparing payload...")
    items = prepare_items_with_local_images(df)
    print("Payload ready:")
    for it in items:
        print(it)
# ---------------------------------------------------------------------------
#  Self-tests (optional)
# ---------------------------------------------------------------------------

def _run_tests() -> None:
    assert list(chunked([], 2)) == []
    assert list(chunked(range(4), 2)) == [[0, 1], [2, 3]]
    assert list(chunked(range(5), 2)) == [[0, 1], [2, 3], [4]]
    print("chunked works correctly")

    # Skip tests requiring actual images if the base path doesn't exist
    if os.path.isdir(BASE_IMAGE_PATH):
        paths = generate_image_paths(BASE_IMAGE_PATH, num_ads=5, per_ad=10)
        assert len(paths) == 5
        for row in paths:
            assert row.count("|") == 9
        print("generate_image_paths works correctly")

    df = pd.DataFrame({
        "title": ["X"],
        "description": ["Y"],
        "price": [1],
        "category_id": [23],
        "region_id": [653240],
        "city_id": [645680],
        "image_path": ["no_such_file.jpg"],
    })
    items = prepare_items_with_local_images(df)
    assert items[0]["images"][0]["id"] == "dummy_id"
    print("upload_image test mode: using dummy_id ✅")

if __name__ == "__main__":
    if "--test" in sys.argv:
        _run_tests()
    else:
        main_example()
