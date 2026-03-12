import os, sys
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, jsonify, render_template, request
from datetime import datetime, timedelta
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev")

from api.football_api import (
    get_fixtures, get_live_matches, get_live_stats, get_team_form
)
from api import cache as cache_module
from models.predictor import analyze_match

# ─── CACHE YARDIMCILARI ───────────────────────────────────────────────────────
def get_fixtures_cached(date):
    today = datetime.now().strftime("%Y-%m-%d")
    ttl = 2 if date == today else 30
    cached = cache_module.get(f"fix_{date}", ttl_minutes=ttl)
    if cached:
        return cached
    fixtures = get_fixtures(date)
    cache_module.set(f"fix_{date}", fixtures)
    return fixtures

def get_stats_cached(team_id, fixture_id=None):
    key = f"form_{team_id}_{fixture_id}"
    cached = cache_module.get(key, ttl_minutes=120)
    if cached:
        return cached
    stats = get_team_form(team_id, fixture_id)
    if stats:
        cache_module.set(key, stats)
    return stats

def get_live_stats_cached(match_id):
    key = f"lstats_{match_id}"
    cached = cache_module.get(key, ttl_minutes=1)
    if cached:
        return cached
    stats = get_live_stats(match_id)
    if stats:
        cache_module.set(key, stats)
    return stats

# ─── ROUTES ───────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/fixtures")
def api_fixtures():
    date = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))
    try:
        fixtures = get_fixtures_cached(date)
        # Canlı maçları da birleştir
        live = get_live_matches()
        live_ids = {m["fixture_id"] for m in live}
        # Fixture listesindeki canlıları güncelle
        for i, f in enumerate(fixtures):
            if f["fixture_id"] in live_ids:
                updated = next(m for m in live if m["fixture_id"] == f["fixture_id"])
                fixtures[i] = updated
        # Fixture'da olmayan canlı maçları ekle
        fix_ids = {f["fixture_id"] for f in fixtures}
        for m in live:
            if m["fixture_id"] not in fix_ids:
                fixtures.append(m)
        def sort_key(x):
            s = x.get("status", "NS")
            if s in ["1H", "2H", "ET", "PEN"]: order = 0
            elif s == "HT": order = 1
            elif s == "NS": order = 2
            else: order = 3
            return (order, x.get("time", ""))
        fixtures.sort(key=sort_key)
        return jsonify({"fixtures": fixtures, "date": date, "count": len(fixtures)})
    except Exception as e:
        print(f"Fixtures error: {e}")
        return jsonify({"error": str(e), "fixtures": []}), 500

@app.route("/api/analyze/<int:fixture_id>")
def api_analyze(fixture_id):
    date = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))
    force = request.args.get("force", "0") == "1"
    try:
        cache_key = f"analysis_{fixture_id}"
        if not force:
            cached = cache_module.get(cache_key, ttl_minutes=3)
            if cached:
                return jsonify(cached)

        # Fixture bul
        fixtures = get_fixtures_cached(date)
        print(f"Fixtures count: {len(fixtures)}, looking for: {fixture_id}")
        print(f"Fixture IDs sample: {[f['fixture_id'] for f in fixtures[:5]]}")
        fix = next((f for f in fixtures if str(f["fixture_id"]) == str(fixture_id)), None)
        if not fix:
            live = get_live_matches()
            fix = next((f for f in live if str(f["fixture_id"]) == str(fixture_id)), None)
        if not fix:
            return jsonify({"error": "Maç bulunamadı", "fixtures_count": len(fixtures), "date": date}), 404

        home_id = fix.get("home_team_id")
        away_id = fix.get("away_team_id")
        if not home_id or not away_id:
            return jsonify({"error": "Takım ID bulunamadı"}), 422

        # Form verileri
        home_stats = get_stats_cached(home_id, fixture_id)
        away_stats = get_stats_cached(away_id, fixture_id)

        # Canlı istatistikler
        live_stats = None
        if fix.get("status") in ["1H", "2H", "HT", "ET"]:
            live_stats = get_live_stats_cached(fixture_id)

        result = analyze_match(fix, home_stats, away_stats, live_stats)
        if not result:
            return jsonify({"error": "Yetersiz veri (min 3 maç gerekli)"}), 422

        result["fixture"] = fix
        cache_module.set(cache_key, result)
        return jsonify(result)

    except Exception as e:
        print(f"Analyze error [{fixture_id}]: {e}")
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/api/dates")
def api_dates():
    today = datetime.now()
    dates = [(today + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(-1, 5)]
    return jsonify({"dates": dates})

@app.route("/api/clear-cache")
def clear_cache():
    cache_module.clear()
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        fixtures = get_fixtures(today)
        cache_module.set(f"fix_{today}", fixtures)
        return jsonify({"status": "ok", "message": f"Cache temizlendi, {len(fixtures)} maç yüklendi"})
    except Exception as e:
        return jsonify({"status": "ok", "message": f"Cache temizlendi ({e})"})

@app.route("/api/debug")
def debug():
    """API bağlantısını test et"""
    from api.football_api import _get
    data = _get("/sport/football/livescores")
    return jsonify({"raw": data, "key_set": bool(os.getenv("ISPORTS_API_KEY"))})

if __name__ == "__main__":
    app.run(debug=True, port=5001)
