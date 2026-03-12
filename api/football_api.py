import requests
import time
import os
from datetime import datetime, timedelta

BASE_URL = "http://api.isportsapi.com"
API_KEY = os.getenv("ISPORTS_API_KEY", "")

# status: 0=NS 1=1H 2=HT 3=2H 4=ET 5=PEN -1=FT -10=CANC -14=PST

def _get(path, params=None):
    if params is None:
        params = {}
    params["api_key"] = API_KEY
    try:
        r = requests.get(f"{BASE_URL}{path}", params=params, timeout=15)
        if r.status_code == 200:
            return r.json()
        print(f"iSports {path} HTTP {r.status_code}: {r.text[:200]}")
        return None
    except Exception as e:
        print(f"iSports {path} error: {e}")
        return None

def _items(data):
    if data is None:
        return []
    if isinstance(data, list):
        return data
    for k in ["data", "result", "results", "matches"]:
        if k in data and isinstance(data[k], list):
            return data[k]
    return []

def parse_status(code):
    return {0:"NS",1:"1H",2:"HT",3:"2H",4:"ET",5:"PEN",-1:"FT",
            -10:"CANC",-11:"TBD",-12:"ABD",-13:"INT",-14:"PST"}.get(code,"NS")

def is_live(code):
    return code in [1, 2, 3, 4, 5]

def calc_minute(m):
    status = m.get("status", 0)
    if status == 2:
        return "HT"
    if status not in [1, 3]:
        return None
    half_start = m.get("halfStartTime")
    if not half_start:
        return None
    try:
        # Unix timestamp
        start_utc = datetime.utcfromtimestamp(int(half_start))
        elapsed = int((datetime.utcnow() - start_utc).total_seconds() / 60)
        if status == 1:
            return max(1, min(45, elapsed))
        else:
            return max(46, min(90, 45 + elapsed))
    except:
        return None

def parse_match(m):
    code = m.get("status", 0)
    status = parse_status(code)
    elapsed = calc_minute(m)

    # matchTime Unix timestamp → UTC+3
    raw_time = m.get("matchTime", 0)
    try:
        ts = int(raw_time)
        dt_utc = datetime.utcfromtimestamp(ts)
        dt_local = dt_utc + timedelta(hours=3)  # UTC+3
        match_time = dt_local.strftime("%Y-%m-%dT%H:%M:%S+03:00")
        local_date = dt_local.strftime("%Y-%m-%d")
    except:
        match_time = str(raw_time)
        local_date = datetime.now().strftime("%Y-%m-%d")

    return {
        "fixture_id":     m.get("matchId"),
        "time":           match_time,
        "local_date":     local_date,
        "status":         status,
        "status_code":    code,
        "elapsed":        elapsed,
        "home_team_id":   m.get("homeId"),
        "home_team_name": m.get("homeName", ""),
        "away_team_id":   m.get("awayId"),
        "away_team_name": m.get("awayName", ""),
        "home_goals":     m.get("homeScore"),
        "away_goals":     m.get("awayScore"),
        "home_ht_goals":  m.get("homeHalfScore"),
        "away_ht_goals":  m.get("awayHalfScore"),
        "home_corner":    m.get("homeCorner", 0),
        "away_corner":    m.get("awayCorner", 0),
        "home_yellow":    m.get("homeYellow", 0),
        "away_yellow":    m.get("awayYellow", 0),
        "home_red":       m.get("homeRed", 0),
        "away_red":       m.get("awayRed", 0),
        "league_id":      m.get("leagueId"),
        "league_name":    m.get("leagueName", ""),
        "league_short":   m.get("leagueShortName", ""),
        "country":        m.get("countryName", ""),
        "round":          m.get("round", ""),
        "home_rank":      m.get("homeRank", ""),
        "away_rank":      m.get("awayRank", ""),
    }

# ─── CANLI MAÇLAR ─────────────────────────────────────────────────────────────
def get_live_matches():
    data = _get("/sport/football/livescores")
    items = _items(data)
    result = [parse_match(m) for m in items if is_live(m.get("status", 0))]
    print(f"iSports live: {len(result)} canlı maç")
    return result

# ─── GÜNLÜK MAÇLAR ────────────────────────────────────────────────────────────
def get_fixtures(date):
    dt = datetime.strptime(date, "%Y-%m-%d")
    seen = set()
    all_matches = []
    for delta in [-1, 0, 1]:
        d = (dt + timedelta(days=delta)).strftime("%Y-%m-%d")
        data = _get("/sport/football/schedule", {"date": d})
        for m in _items(data):
            mid = m.get("matchId")
            if mid and mid not in seen:
                seen.add(mid)
                all_matches.append(m)
        time.sleep(0.3)

    parsed = [parse_match(m) for m in all_matches]
    filtered = [m for m in parsed if m["local_date"] == date]
    filtered.sort(key=lambda x: x["time"])
    print(f"iSports fixtures: {len(filtered)} maç ({date})")
    return filtered

# ─── CANLI İSTATİSTİK ─────────────────────────────────────────────────────────
def get_live_stats(match_id):
    data = _get("/sport/football/live/stats", {"matchId": match_id})
    items = _items(data)
    if not items:
        return None

    STAT_MAP = {
        "attack": "attacks", "dangerousAttack": "dangerous_attacks",
        "possession": "ball_possession", "shotOnTarget": "shots_on_target",
        "shotOffTarget": "shots_off_target", "totalShot": "total_shots",
        "cornerKick": "corner_kicks", "yellowCard": "yellow_cards",
        "redCard": "red_cards", "foul": "fouls", "offside": "offsides",
        "save": "saves", "freeKick": "free_kicks",
    }
    result = {"home": {}, "away": {}}
    for item in items:
        raw = item.get("type", item.get("key", ""))
        key = STAT_MAP.get(raw, raw.lower().replace(" ", "_"))
        result["home"][key] = item.get("homeValue", item.get("home", 0))
        result["away"][key] = item.get("awayValue", item.get("away", 0))
    return result

# ─── TAKIM FORM VERİSİ ────────────────────────────────────────────────────────
def get_team_form(team_id, fixture_id=None):
    CUP_KW = ["cup","kupa","copa","coupe","pokal","supercup","friendly","super cup"]
    data = _get("/sport/football/team/schedule", {"teamId": team_id, "type": "last"})
    items = _items(data)

    finished = []
    for m in items:
        if m.get("status", 0) != -1:
            continue
        if any(kw in (m.get("leagueName") or "").lower() for kw in CUP_KW):
            continue
        if fixture_id and m.get("matchId") == fixture_id:
            continue
        finished.append(m)

    finished = sorted(finished, key=lambda x: x.get("matchTime", 0))[-8:]
    if len(finished) < 3:
        return None

    DECAY = 0.75
    LIG_ORT = 1.25
    n = len(finished)
    weights = [DECAY ** (n - 1 - i) for i in range(n)]
    w_total = sum(weights)

    home_sc = home_co = home_w = 0.0
    away_sc = away_co = away_w = 0.0
    sc_w = co_w = ht_w = btts_w = 0.0

    for idx, m in enumerate(finished):
        w = weights[idx]
        is_home = m.get("homeId") == team_id
        ft_h = m.get("homeScore")
        ft_a = m.get("awayScore")
        ht_h = m.get("homeHalfScore") or 0
        ht_a = m.get("awayHalfScore") or 0
        if ft_h is None or ft_a is None:
            continue
        gf = ft_h if is_home else ft_a
        ga = ft_a if is_home else ft_h
        ht_gf = ht_h if is_home else ht_a
        sc_w   += gf * w
        co_w   += ga * w
        ht_w   += ht_gf * w
        btts_w += (1 if gf > 0 and ga > 0 else 0) * w
        if is_home:
            home_sc += gf * w; home_co += ga * w; home_w += w
        else:
            away_sc += gf * w; away_co += ga * w; away_w += w

    avg_st = sc_w / w_total
    avg_ct = co_w / w_total
    avg_sh = (home_sc / home_w) if home_w > 0 else avg_st * 1.1
    avg_sa = (away_sc / away_w) if away_w > 0 else avg_st * 0.9
    avg_ch = (home_co / home_w) if home_w > 0 else avg_ct * 0.9
    avg_ca = (away_co / away_w) if away_w > 0 else avg_ct * 1.1
    ht_ratio = max(0.18, min(0.45, (ht_w / w_total) / avg_st)) if avg_st > 0 else 0.28
    btts = btts_w / w_total

    def cap_att(v): return max(0.3, min(2.5, v))
    def cap_def(v): return max(0.4, min(2.5, v))

    return {
        "home_attack":  round(cap_att(avg_sh / LIG_ORT), 4),
        "home_defence": round(cap_def(avg_ch / LIG_ORT), 4),
        "away_attack":  round(cap_att(avg_sa / LIG_ORT), 4),
        "away_defence": round(cap_def(avg_ca / LIG_ORT), 4),
        "general": {
            "avg_scored":    round(avg_st, 3),
            "btts_rate":     round(btts, 3),
            "ht_goal_ratio": round(ht_ratio, 3),
        }
    }
