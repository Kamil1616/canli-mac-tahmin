import os, json, time

CACHE_DIR = "instance/cache"
os.makedirs(CACHE_DIR, exist_ok=True)

def _path(key):
    safe = key.replace("/", "_").replace(":", "_")
    return os.path.join(CACHE_DIR, f"{safe}.json")

def get(key, ttl_minutes=5):
    p = _path(key)
    if not os.path.exists(p):
        return None
    if time.time() - os.path.getmtime(p) > ttl_minutes * 60:
        return None
    try:
        return json.loads(open(p).read())
    except:
        return None

def set(key, value):
    try:
        open(_path(key), "w").write(json.dumps(value, ensure_ascii=False))
    except:
        pass

def clear():
    import shutil
    if os.path.exists(CACHE_DIR):
        shutil.rmtree(CACHE_DIR)
    os.makedirs(CACHE_DIR, exist_ok=True)

def clear_all():
    clear()

