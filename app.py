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

# \u2500\u2500\u2500 CACHE HELPERS \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
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

# \u2500\u2500\u2500 ROUTES \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/fixtures")
def api_fixtures():
    today_utc3 = (datetime.utcnow() + timedelta(hours=3)).strftime("%Y-%m-%d")
    date = request.args.get("date", today_utc3)
    try:
        fixtures = get_fixtures_cached(date)

        # Canl\u0131 ma\u00e7lar\u0131 \u00fcst\u00fcne yaz
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
            if s in ["1H", "ET", "PEN"]: return (0, x.get("time", ""))
            elif s == "HT":              return (1, x.get("time", ""))
            elif s == "2H":              return (2, x.get("time", ""))
            elif s == "NS":              return (3, x.get("time", ""))
            else:                        return (4, x.get("time", ""))
        fixtures.sort(key=sort_key)

        return jsonify({"fixtures": fixtures, "date": date, "count": len(fixtures)})
    except Exception as e:
        import traceback
        print(f"Fixtures error: {traceback.format_exc()}")
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
            return jsonify({"error": "Ma\u00e7 bulunamad\u0131", "date": date}), 404

        home_id   = fix.get("home_team_id")
        away_id   = fix.get("away_team_id")
        home_name = fix.get("home_team_name", "")
        away_name = fix.get("away_team_name", "")
        league    = fix.get("league_name", "")
        slug      = fix.get("league_slug", "")

        if not home_id or not away_id:
            return jsonify({"error": "Tak\u0131m ID bulunamad\u0131"}), 422

        # Form verileri
        home_stats = get_stats_cached(home_id, fixture_id, home_name, league, slug)
        away_stats = get_stats_cached(away_id, fixture_id, away_name, league, slug)

        # Canl\u0131 istatistikler
        live_stats = None
        if fix.get("status") in ["1H", "HT", "2H", "ET", "PEN"]:
            live_stats = get_live_stats(fixture_id, slug)

        # Canl\u0131 oranlar
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
    """
    predictor.py'deki analyze_match \u00e7\u0131kt\u0131s\u0131ndan sinyal \u00fcret.
    predictor probs: {"1": float, "X": float, "2": float} \u2014 y\u00fczde olarak (\u00f6rn. 45.2)
    predictor over:  {"0.5": float, "1.5": float, "2.5": float, "3.5": float} \u2014 y\u00fczde
    """
    signals = []
    if not pred:
        return signals

    pregame  = pred.get("pregame", {})
    probs    = pregame.get("probs", {})   # {"1": 45.2, "X": 28.1, "2": 26.7}
    over_raw = pregame.get("over", {})    # {"0.5": 88.0, "1.5": 65.0, "2.5": 42.0, "3.5": 22.0}

    # Y\u00fczdeden orana \u00e7evir
    home_p  = probs.get("1", 0) / 100
    draw_p  = probs.get("X", 0) / 100
    away_p  = probs.get("2", 0) / 100
    over_p  = over_raw.get("2.5", 0) / 100
    under_p = 1 - over_p

    if home_p >= 0.55:
        signals.append({"type": "MS_HOME",    "prob": round(home_p, 3),  "label": "Ev Sahibi Kazan\u0131r"})
    if draw_p >= 0.35:
        signals.append({"type": "MS_
