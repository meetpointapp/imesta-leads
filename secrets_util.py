"""API anahtarları: secrets.json (git'e girmez) ya da ortam değişkenleri. Hiçbiri zorunlu değil."""
import json
import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "secrets.json")
KEYS = ["brave_api_key", "google_api_key", "google_cx", "anthropic_api_key", "libretranslate_url", "libretranslate_key"]


def load():
    try:
        with open(PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def get(name):
    return (os.environ.get(name.upper()) or load().get(name) or "").strip()


def save(values):
    cur = load()
    for k, v in values.items():
        if k in KEYS and v is not None:
            if v.strip():
                cur[k] = v.strip()
            elif k in cur and v == "":
                pass  # boş bırakılan alan mevcut anahtarı silmez
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(cur, f, indent=2)
    try:
        os.chmod(PATH, 0o600)
    except OSError:
        pass


def clear(name):
    cur = load()
    cur.pop(name, None)
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(cur, f, indent=2)


def mask(v):
    return "" if not v else (v[:4] + "…" + v[-3:] if len(v) > 10 else "•••")
