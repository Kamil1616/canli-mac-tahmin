from flask import Flask, jsonify, render_template, request
from datetime import datetime, timedelta
import os
import api.cache as cache_module
from api.football_api import (
    get_fixtures, get_live_matches, get_live_stats,
    get_team_form, get_live_odds
)
from models.predictor import analyze_match

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "canli-mac-secret")

# ─── CACHE HELPERS ────────────────────────────────────────────────────────────
def get_fixtures_cached(date):
    cached = cache_module.get(f"fix_{date}", ttl_minutes=5)
    if cached:
        return cached
    fixtures = get_fixtures(date)
    cache_module.set(f"fix_{date}", fixtures)
    return fixtures

def get_stats_cached(team_id, fixture_id=None, team_name=None,
                     league_name=None, league_slug=None):
    key = f"form_{team_id}_{fixture_id}"
    cached = cache_module.get(key, ttl_minutes=120)
    if cached:
        return cached
    stats = get_team_form(
        team_id=team_id, fixture_id=fixture_id,
        team_name=team_name, league_name=league_name, league_slug=league_slug
    )
    if stats:
        cache_module.set(key, stats)
    return stats

def get_odds_cached(home_team, away_team, fixture_id):
    key = f"odds_{fixture_id}"
    cached = cache_module.get(key, ttl_minutes=2)
    if cached:
        return cached
    odds = get_live_odds(home_team, away_team)
    if odds:
        cache_module.set(key, odds)
    return odds

# ─── ROUTES ───────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/fixtures")
def api_fixtures():
    today_utc3 = (datetime.utcnow() + timedelta(hours=3)).strftime("%Y-%m-%d")
    date = request.args.get("date", today_utc3)
    try:
        fixtures = get_fixtures_cached(date)

        # Canlı maçları üstüne yaz
        live = get_live_matches()
        live_ids = {m["fixture_id"] for m in live}
        for i, f in enumerate(fixtures):
            if f["fixture_id"] in live_ids:
                updated = next(m for m in live if m["fixture_id"] == f["fixture_id"])
                fixtures[i] = updated
        fix_ids = {f["fixture_id"] for f in fixtures}
        for m in live:
            if m["fixture_id"] not in fix_ids:
                fixtures.append(m)

        def sort_key(x):
            s = x.get("status", "NS")
            if s in ["1H","ET","PEN"]: return (0, x.get("time",""))
            elif s == "HT":            return (1, x.get("time",""))
            elif s == "2H":            return (2, x.get("time",""))
            elif s == "NS":            return (3, x.get("time",""))
            else:                      return (4, x.get("time",""))
        fixtures.sort(key=sort_key)

        return jsonify({"fixtures": fixtures, "date": date, "count": len(fixtures)})
    except Exception as e:
        print(f"Fixtures error: {e}")
        return jsonify({"error": str(e), "fixtures": []}), 500

@app.route("/api/analyze/<fixture_id>")
def api_analyze(fixture_id):
    today_utc3 = (datetime.utcnow() + timedelta(hours=3)).strftime("%Y-%m-%d")
    date = request.args.get("date", today_utc3)
    force = request.args.get("force", "0") == "1"
    try:
        cache_key = f"analysis_{fixture_id}"
        if not force:
            cached = cache_module.get(cache_key, ttl_minutes=3)
            if cached:
                return jsonify(cached)

        # Fixture bul
        fixtures = get_fixtures_cached(date)
        fix = next((f for f in fixtures if str(f["fixture_id"]) == str(fixture_id)), None)
        if not fix:
            live = get_live_matches()
            fix = next((f for f in live if str(f["fixture_id"]) == str(fixture_id)), None)
        if not fix:
            return jsonify({"error": "Maç bulunamadı", "date": date}), 404

        home_id   = fix.get("home_team_id")
        away_id   = fix.get("away_team_id")
        home_name = fix.get("home_team_name", "")
        away_name = fix.get("away_team_name", "")
        league    = fix.get("league_name", "")
        slug      = fix.get("league_slug", "")

        if not home_id or not away_id:
            return jsonify({"error": "Takım ID bulunamadı"}), 422

        # Form verileri
        home_stats = get_stats_cached(home_id, fixture_id, home_name, league, slug)
        away_stats = get_stats_cached(away_id, fixture_id, away_name, league, slug)

        # Canlı istatistikler
        live_stats = None
        if fix.get("status") in ["1H","HT","2H","ET","PEN"]:
            live_stats = get_live_stats(fixture_id, slug)

        # Canlı oranlar
        odds = get_odds_cached(home_name, away_name, fixture_id)

        # Tahmin
        if not home_stats or not away_stats:
            result = {
                "fixture": fix,
                "home_stats": home_stats,
                "away_stats": away_stats,
                "live_stats": live_stats,
                "odds": odds,
                "prediction": None,
                "signals": [],
                "error": "Yetersiz form verisi"
            }
        else:
            prediction = analyze_match(fix, home_stats, away_stats, live_stats)
            signals = _extract_signals(prediction, odds)
            result = {
                "fixture": fix,
                "home_stats": home_stats,
                "away_stats": away_stats,
                "live_stats": live_stats,
                "odds": odds,
                "prediction": prediction,
                "signals": signals,
            }

        cache_module.set(cache_key, result)
        return jsonify(result)

    except Exception as e:
        import traceback
        print(f"Analyze error: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500

def _extract_signals(pred, odds):
    """Tahmin sinyalleri"""
    signals = []
    if not pred:
        return signals

    probs = pred.get("probabilities", {})
    iy_ms = pred.get("iy_ms", {})

    # MS sinyalleri
    home_p = probs.get("home_win", 0)
    draw_p = probs.get("draw", 0)
    away_p = probs.get("away_win", 0)

    if home_p >= 0.55:
        signals.append({"type": "MS_HOME", "prob": round(home_p, 3), "label": "Ev Sahibi Kazanır"})
    if draw_p >= 0.35:
        signals.append({"type": "MS_DRAW", "prob": round(draw_p, 3), "label": "Beraberlik"})
    if away_p >= 0.50:
        signals.append({"type": "MS_AWAY", "prob": round(away_p, 3), "label": "Deplasman Kazanır"})

    # Gol sinyalleri
    over_p = probs.get("over_2_5", 0)
    under_p = probs.get("under_2_5", 0)
    btts_p = probs.get("btts", 0)

    if over_p >= 0.60:
        signals.append({"type": "OVER_2_5", "prob": round(over_p, 3), "label": "2.5 Üst"})
    if under_p >= 0.60:
        signals.append({"type": "UNDER_2_5", "prob": round(under_p, 3), "label": "2.5 Alt"})
    if btts_p >= 0.60:
        signals.append({"type": "BTTS", "prob": round(btts_p, 3), "label": "KG Var"})

    # Value bet (oran varsa)
    if odds:
        for outcome, prob, key in [
            ("home", home_p, "home"),
            ("draw", draw_p, "draw"),
            ("away", away_p, "away"),
        ]:
            odd_val = odds.get(key)
            if odd_val and prob > 0:
                ev = round(prob * float(odd_val) - 1, 3)
                if ev > 0.05:
                    for s in signals:
                        if s["type"] == f"MS_{outcome.upper()}":
                            s["ev"] = ev
                            s["odd"] = odd_val
                            s["value"] = True

    return sorted(signals, key=lambda x: x["prob"], reverse=True)

@app.route("/api/clear-cache")
def clear_cache():
    cache_module.clear_all()
    return jsonify({"status": "ok", "message": "Cache temizlendi"})

@app.route("/api/debug")
def debug():
    from api.football_api import get_fixtures
    today = (datetime.utcnow() + timedelta(hours=3)).strftime("%Y-%m-%d")
    fixtures = get_fixtures(today)
    return jsonify({
        "espn_fixtures": len(fixtures),
        "sample": fixtures[:3] if fixtures else [],
        "odds_key_set": bool(os.getenv("ODDS_API_KEY")),
    })

if __name__ == "__main__":
    app.run(debug=True, port=5001)

@app.route("/api/debug-form/<league_slug>/<team_name>")
def debug_form(league_slug, team_name):
    from api.football_api import _find_espn_team_id, ESPN_BASE
    import requests
    # Takım listesi çek
    r = requests.get(f"{ESPN_BASE}/{league_slug}/teams", timeout=10)
    if r.status_code != 200:
        return jsonify({"error": f"HTTP {r.status_code}"})
    teams = (r.json().get("sports", [{}])[0]
                     .get("leagues", [{}])[0]
                     .get("teams", []))
    team_list = [{"id": t["team"]["id"], "name": t["team"]["displayName"]} for t in teams]
    espn_id = _find_espn_team_id(team_name, league_slug)
    return jsonify({
        "league_slug": league_slug,
        "team_name": team_name,
        "espn_id": espn_id,
        "all_teams": team_list
    })

@app.route("/api/debug-schedule/<league_slug>/<team_id>")
def debug_schedule(league_slug, team_id):
    from api.football_api import ESPN_BASE
    import requests
    r = requests.get(f"{ESPN_BASE}/{league_slug}/teams/{team_id}/schedule", timeout=10)
    if r.status_code != 200:
        return jsonify({"error": f"HTTP {r.status_code}"})
    events = r.json().get("events", [])
    finished = []
    for e in events:
        comps = e.get("competitions", [])
        if not comps: continue
        status = comps[0].get("status",{}).get("type",{}).get("name","")
        finished.append({
            "id": e.get("id"),
            "date": e.get("date","")[:10],
            "name": e.get("name",""),
            "status": status
        })
    return jsonify({"total": len(events), "events": finished})
