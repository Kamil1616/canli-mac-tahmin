import requests
import time
import os
from datetime import datetime, timedelta

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
ODDS_BASE = "https://api.odds-api.io/v3"
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"

# ─── ESPN LİG SLUG TABLOSU ────────────────────────────────────────────────────
ESPN_LEAGUES = {
    "eng.1": ["english premier league", "premier league"],
    "eng.2": ["english championship", "championship"],
    "eng.3": ["english league one"],
    "esp.1": ["spanish la liga", "la liga", "laliga"],
    "esp.2": ["spanish segunda", "segunda division"],
    "ger.1": ["german bundesliga", "bundesliga", "1. bundesliga"],
    "ger.2": ["2. bundesliga", "german 2. bundesliga"],
    "ita.1": ["italian serie a", "serie a"],
    "ita.2": ["italian serie b", "serie b"],
    "fra.1": ["french ligue 1", "ligue 1"],
    "fra.2": ["ligue 2"],
    "tur.1": ["turkish super lig", "super lig", "süper lig"],
    "ned.1": ["dutch eredivisie", "eredivisie"],
    "por.1": ["portuguese primeira liga", "primeira liga", "liga portugal"],
    "bel.1": ["belgian first division a", "jupiler pro league"],
    "sco.1": ["scottish premiership"],
    "rus.1": ["russian premier league"],
    "usa.1": ["major league soccer", "mls"],
    "bra.1": ["brazilian serie a", "brasileirao"],
    "arg.1": ["argentine primera division", "liga profesional"],
    "mex.1": ["liga mx"],
    "ukr.1": ["ukrainian premier league"],
    "gre.1": ["greek super league"],
    "aut.1": ["austrian bundesliga"],
    "sui.1": ["swiss super league"],
    "den.1": ["danish superliga"],
    "nor.1": ["norwegian eliteserien"],
    "swe.1": ["swedish allsvenskan"],
    "jpn.1": ["j1 league", "japanese j1 league"],
    "sau.1": ["saudi professional league", "saudi pro league"],
    "chn.1": ["chinese super league"],
    "uefa.champions": ["uefa champions league", "champions league"],
    "uefa.europa": ["uefa europa league", "europa league"],
    "uefa.conference": ["uefa conference league"],
}

def _get_espn_slug(league_name):
    if not league_name:
        return None
    ln = league_name.lower().strip()
    for slug, names in ESPN_LEAGUES.items():
        if any(n in ln or ln in n for n in names):
            return slug
    return None

# ─── ESPN: CANLI MAÇLAR ───────────────────────────────────────────────────────
def get_live_matches():
    """Tüm ESPN futbol liglerinden canlı maçları topla"""
    live = []
    seen = set()
    priority_slugs = ["eng.1","esp.1","ger.1","ita.1","fra.1","tur.1",
                      "ned.1","por.1","bel.1","sco.1","usa.1","bra.1",
                      "arg.1","mex.1","ukr.1","sui.1","uefa.champions","uefa.europa"]
    for slug in priority_slugs:
        try:
            r = requests.get(
                f"{ESPN_BASE}/{slug}/scoreboard",
                timeout=8
            )
            if r.status_code != 200:
                continue
            events = r.json().get("events", [])
            for e in events:
                eid = e.get("id")
                if eid in seen:
                    continue
                parsed = _parse_espn_event(e, slug)
                if parsed and parsed["status"] in ["1H","HT","2H","ET","PEN"]:
                    seen.add(eid)
                    live.append(parsed)
        except:
            continue
        time.sleep(0.1)
    print(f"ESPN live: {len(live)} canlı maç")
    return live

# ─── ESPN: GÜNLÜK MAÇLAR ──────────────────────────────────────────────────────
def get_fixtures(date):
    """Belirli tarih için ESPN'den tüm maçları çek"""
    fixtures = []
    seen = set()
    priority_slugs = ["eng.1","esp.1","ger.1","ita.1","fra.1","tur.1",
                      "ned.1","por.1","bel.1","sco.1","usa.1","bra.1",
                      "arg.1","mex.1","ukr.1","sui.1","gre.1","aut.1",
                      "den.1","nor.1","swe.1","sau.1","jpn.1",
                      "uefa.champions","uefa.europa","uefa.conference"]
    for slug in priority_slugs:
        try:
            r = requests.get(
                f"{ESPN_BASE}/{slug}/scoreboard",
                params={"dates": date.replace("-", "")},
                timeout=8
            )
            if r.status_code != 200:
                continue
            events = r.json().get("events", [])
            for e in events:
                eid = e.get("id")
                if eid in seen:
                    continue
                parsed = _parse_espn_event(e, slug)
                if parsed:
                    seen.add(eid)
                    fixtures.append(parsed)
        except:
            continue
        time.sleep(0.1)

    fixtures.sort(key=lambda x: x["time"])
    print(f"ESPN fixtures: {len(fixtures)} maç ({date})")
    return fixtures

def _parse_espn_event(e, slug):
    """ESPN event'ini standart formata çevir"""
    try:
        comps = e.get("competitions", [])
        if not comps:
            return None
        comp = comps[0]
        competitors = comp.get("competitors", [])
        if len(competitors) < 2:
            return None

        home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

        # Status
        status_obj = comp.get("status", {})
        status_type = status_obj.get("type", {})
        status_name = status_type.get("name", "").lower()
        status_desc = status_type.get("description", "").lower()
        clock = status_obj.get("displayClock", "")

        if "final" in status_name or "final" in status_desc:
            status = "FT"
        elif "halftime" in status_desc or "half time" in status_desc:
            status = "HT"
        elif "progress" in status_name or "in progress" in status_desc:
            # dakikaya göre 1H/2H
            try:
                mins = int(clock.replace("'","").split(":")[0])
                status = "2H" if mins > 45 else "1H"
            except:
                status = "1H"
        elif "postponed" in status_desc:
            status = "PST"
        elif "canceled" in status_desc:
            status = "CANC"
        else:
            status = "NS"

        # Dakika
        elapsed = None
        if status in ["1H","2H","ET"]:
            try:
                elapsed = int(clock.replace("'","").split(":")[0])
            except:
                pass

        # Skor
        home_goals = away_goals = home_ht = away_ht = None
        try:
            home_goals = int(home.get("score", 0)) if status != "NS" else None
            away_goals = int(away.get("score", 0)) if status != "NS" else None
        except:
            pass

        # HT skoru
        ls_h = home.get("linescores", [])
        ls_a = away.get("linescores", [])
        if ls_h and ls_a:
            try:
                home_ht = int(ls_h[0].get("value", 0))
                away_ht = int(ls_a[0].get("value", 0))
            except:
                pass

        # Saat (UTC+3)
        date_str = e.get("date", "")
        try:
            dt_utc = datetime.strptime(date_str, "%Y-%m-%dT%H:%MZ")
            dt_local = dt_utc + timedelta(hours=3)
            match_time = dt_local.strftime("%Y-%m-%dT%H:%M:%S+03:00")
            local_date = dt_local.strftime("%Y-%m-%d")
        except:
            match_time = date_str
            local_date = (datetime.utcnow() + timedelta(hours=3)).strftime("%Y-%m-%d")

        # Lig
        league_info = e.get("competitions", [{}])[0].get("league", {})
        if not league_info:
            season = e.get("season", {})
            league_name = season.get("displayName", slug)
        else:
            league_name = league_info.get("name", slug)

        return {
            "fixture_id":     e.get("id"),
            "time":           match_time,
            "local_date":     local_date,
            "status":         status,
            "elapsed":        elapsed,
            "home_team_id":   home.get("id"),
            "home_team_name": home.get("team", {}).get("displayName", ""),
            "away_team_id":   away.get("id"),
            "away_team_name": away.get("team", {}).get("displayName", ""),
            "home_goals":     home_goals,
            "away_goals":     away_goals,
            "home_ht_goals":  home_ht,
            "away_ht_goals":  away_ht,
            "league_slug":    slug,
            "league_name":    league_name,
            "country":        "",
        }
    except Exception as ex:
        print(f"ESPN parse error: {ex}")
        return None

# ─── ESPN: CANLI İSTATİSTİK ───────────────────────────────────────────────────
def get_live_stats(match_id, league_slug=None):
    """ESPN'den maç istatistiklerini çek"""
    if not league_slug:
        return None
    try:
        r = requests.get(
            f"{ESPN_BASE}/{league_slug}/summary",
            params={"event": match_id},
            timeout=10
        )
        if r.status_code != 200:
            return None

        data = r.json()
        boxscore = data.get("boxscore", {})
        players = boxscore.get("teams", [])

        stats_raw = {}
        for team_data in players:
            side = "home" if team_data.get("homeAway") == "home" else "away"
            stats_raw[side] = {}
            for stat_group in team_data.get("statistics", []):
                for stat in stat_group.get("stats", []):
                    name = stat.get("name", "").lower().replace(" ", "_")
                    stats_raw[side][name] = stat.get("value", 0)

        return stats_raw if stats_raw else None
    except Exception as e:
        print(f"ESPN stats error: {e}")
        return None

# ─── ESPN: TAKIM FORM VERİSİ ──────────────────────────────────────────────────
_espn_team_cache = {}

def _find_espn_team_id(team_name, slug):
    key = (team_name.lower(), slug)
    if key in _espn_team_cache:
        return _espn_team_cache[key]
    try:
        r = requests.get(f"{ESPN_BASE}/{slug}/teams", timeout=10)
        if r.status_code != 200:
            return None
        teams = (r.json().get("sports", [{}])[0]
                         .get("leagues", [{}])[0]
                         .get("teams", []))
        name_lower = team_name.lower()
        for t in teams:
            team = t.get("team", {})
            dn = team.get("displayName", "").lower()
            loc = team.get("location", "").lower()
            nick = team.get("nickname", "").lower()
            if name_lower in dn or dn in name_lower or name_lower in loc:
                tid = team.get("id")
                _espn_team_cache[key] = tid
                return tid
        return None
    except Exception as e:
        print(f"ESPN find team error ({team_name}): {e}")
        return None

def get_team_form(team_id=None, fixture_id=None, team_name=None, league_name=None, league_slug=None):
    """ESPN'den takım form verisi çek"""
    if not team_name:
        return None

    slug = league_slug or _get_espn_slug(league_name)
    if not slug:
        return None

    try:
        espn_id = _find_espn_team_id(team_name, slug)
        if not espn_id:
            return None

        time.sleep(0.2)
        r = requests.get(
            f"{ESPN_BASE}/{slug}/teams/{espn_id}/schedule",
            timeout=10
        )
        if r.status_code != 200:
            return None

        events = r.json().get("events", [])
        return _calc_form(events, espn_id, fixture_id)

    except Exception as e:
        print(f"get_team_form error ({team_name}): {e}")
        return None

def _calc_form(events, team_id, fixture_id=None):
    DECAY = 0.75
    LIG_ORT = 1.25

    finished = []
    for e in events:
        comps = e.get("competitions", [])
        if not comps:
            continue
        comp = comps[0]
        status = comp.get("status", {}).get("type", {}).get("name", "").lower()
        if "final" not in status:
            continue
        if fixture_id and str(e.get("id")) == str(fixture_id):
            continue
        finished.append((e, comp))

    finished = sorted(finished, key=lambda x: x[0].get("date", ""))[-8:]
    if len(finished) < 3:
        return None

    n = len(finished)
    weights = [DECAY ** (n - 1 - i) for i in range(n)]
    w_total = sum(weights)

    home_sc = home_co = home_w = 0.0
    away_sc = away_co = away_w = 0.0
    sc_w = co_w = ht_w = btts_w = 0.0
    recent_matches = []

    for idx, (e, comp) in enumerate(finished):
        w = weights[idx]
        competitors = comp.get("competitors", [])
        if len(competitors) < 2:
            continue
        hc = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        ac = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
        is_home = str(hc.get("id")) == str(team_id)

        try:
            ft_h = int(hc.get("score", 0))
            ft_a = int(ac.get("score", 0))
        except:
            continue

        ls_h = hc.get("linescores", [])
        ls_a = ac.get("linescores", [])
        ht_h = ht_a = 0
        if ls_h and ls_a:
            try:
                ht_h = int(ls_h[0].get("value", 0))
                ht_a = int(ls_a[0].get("value", 0))
            except:
                pass

        gf = ft_h if is_home else ft_a
        ga = ft_a if is_home else ft_h
        ht_gf = ht_h if is_home else ht_a

        sc_w   += gf * w; co_w += ga * w
        ht_w   += ht_gf * w
        btts_w += (1 if gf > 0 and ga > 0 else 0) * w

        if is_home:
            home_sc += gf*w; home_co += ga*w; home_w += w
        else:
            away_sc += gf*w; away_co += ga*w; away_w += w

        recent_matches.append({
            "date":       e.get("date","")[:10],
            "home_team":  hc.get("team",{}).get("displayName",""),
            "away_team":  ac.get("team",{}).get("displayName",""),
            "score":      f"{ft_h} - {ft_a}",
            "ht_score":   f"{ht_h} - {ht_a}",
        })

    if sc_w == 0:
        return None

    avg_st = sc_w / w_total
    avg_ct = co_w / w_total
    avg_sh = (home_sc/home_w) if home_w > 0 else avg_st*1.1
    avg_sa = (away_sc/away_w) if away_w > 0 else avg_st*0.9
    avg_ch = (home_co/home_w) if home_w > 0 else avg_ct*0.9
    avg_ca = (away_co/away_w) if away_w > 0 else avg_ct*1.1
    ht_ratio = max(0.18, min(0.45, (ht_w/w_total)/avg_st)) if avg_st > 0 else 0.28
    btts = btts_w / w_total

    def cap_att(v): return max(0.3, min(2.5, v))
    def cap_def(v): return max(0.4, min(2.5, v))

    return {
        "home_attack":  round(cap_att(avg_sh/LIG_ORT), 4),
        "home_defence": round(cap_def(avg_ch/LIG_ORT), 4),
        "away_attack":  round(cap_att(avg_sa/LIG_ORT), 4),
        "away_defence": round(cap_def(avg_ca/LIG_ORT), 4),
        "general": {
            "avg_scored":    round(avg_st, 3),
            "btts_rate":     round(btts, 3),
            "ht_goal_ratio": round(ht_ratio, 3),
        },
        "recent_matches": recent_matches,
        "source": "espn",
    }

# ─── ODDS-API.IO: CANLI ORANLAR ───────────────────────────────────────────────
def get_live_odds(home_team, away_team, league_name=None):
    """odds-api.io'dan canlı oranları çek"""
    if not ODDS_API_KEY:
        return None
    try:
        # Maçı ara
        r = requests.get(
            f"{ODDS_BASE}/events",
            params={
                "apiKey": ODDS_API_KEY,
                "sport": "football",
                "status": "live",
                "limit": 50,
            },
            timeout=10
        )
        if r.status_code != 200:
            print(f"Odds API events HTTP {r.status_code}")
            return None

        events = r.json() if isinstance(r.json(), list) else r.json().get("data", [])
        home_lower = home_team.lower()
        away_lower = away_team.lower()

        event_id = None
        for ev in events:
            h = (ev.get("home_team") or ev.get("homeTeam") or "").lower()
            a = (ev.get("away_team") or ev.get("awayTeam") or "").lower()
            if (home_lower in h or h in home_lower) and (away_lower in a or a in away_lower):
                event_id = ev.get("id") or ev.get("eventId")
                break

        if not event_id:
            return None

        # Oranları çek
        r2 = requests.get(
            f"{ODDS_BASE}/odds",
            params={
                "apiKey": ODDS_API_KEY,
                "eventId": event_id,
                "markets": "1x2,over_under_2.5",
            },
            timeout=10
        )
        if r2.status_code != 200:
            return None

        return _parse_odds(r2.json())

    except Exception as e:
        print(f"Odds API error: {e}")
        return None

def _parse_odds(data):
    """odds-api.io response'unu parse et"""
    try:
        odds_list = data if isinstance(data, list) else data.get("data", [])
        result = {"home": None, "draw": None, "away": None,
                  "over_2_5": None, "under_2_5": None,
                  "bookmaker": None, "updated_at": None}

        for item in odds_list:
            market = (item.get("market") or item.get("marketType") or "").lower()
            bm = item.get("bookmaker") or item.get("sportsbook") or ""
            outcomes = item.get("outcomes") or item.get("odds") or []

            if "1x2" in market or "h2h" in market or "match_winner" in market:
                for o in outcomes:
                    name = (o.get("name") or o.get("label") or "").lower()
                    price = o.get("price") or o.get("odds") or o.get("value")
                    if "home" in name or name == "1":
                        result["home"] = price
                    elif "draw" in name or name == "x":
                        result["draw"] = price
                    elif "away" in name or name == "2":
                        result["away"] = price
                result["bookmaker"] = bm

            elif "over_under" in market or "total" in market or "2.5" in market:
                for o in outcomes:
                    name = (o.get("name") or o.get("label") or "").lower()
                    price = o.get("price") or o.get("odds") or o.get("value")
                    if "over" in name:
                        result["over_2_5"] = price
                    elif "under" in name:
                        result["under_2_5"] = price

        if result["home"] or result["over_2_5"]:
            return result
        return None
    except Exception as e:
        print(f"Odds parse error: {e}")
        return None
