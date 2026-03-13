import math

LIG_ORT = 1.25
EV_AVANTAJI = 1.08
DC_RHO = -0.13

# ─── TEMEL ────────────────────────────────────────────────────────────────────
def poisson_prob(lam, k):
    if lam <= 0: return 1.0 if k == 0 else 0.0
    return (math.exp(-lam) * (lam ** k)) / math.factorial(k)

def dc_correction(h, a, lh, la, rho=DC_RHO):
    if h == 0 and a == 0: return 1 - lh * la * rho
    if h == 0 and a == 1: return 1 + lh * rho
    if h == 1 and a == 0: return 1 + la * rho
    if h == 1 and a == 1: return 1 - rho
    return 1.0

def score_matrix(lh, la, max_goals=7):
    m = {}
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            p = poisson_prob(lh, h) * poisson_prob(la, a)
            p *= dc_correction(h, a, lh, la)
            m[(h, a)] = p
    total = sum(m.values())
    return {k: v / total for k, v in m.items()} if total > 0 else m

# ─── LAMBDA HESAPLAMA ─────────────────────────────────────────────────────────
def compute_lambdas(home_stats, away_stats):
    h_att = home_stats.get("home_attack", 1.0)
    h_def = home_stats.get("home_defence", 1.0)
    a_att = away_stats.get("away_attack", 1.0)
    a_def = away_stats.get("away_defence", 1.0)
    lh = max(0.3, min(3.5, h_att * a_def * LIG_ORT * EV_AVANTAJI))
    la = max(0.2, min(3.5, a_att * h_def * LIG_ORT))
    return round(lh, 3), round(la, 3)

def compute_lambda_iy(lh, la, home_stats, away_stats):
    lt = lh + la
    ht_h = home_stats.get("general", {}).get("ht_goal_ratio", 0.28)
    ht_a = away_stats.get("general", {}).get("ht_goal_ratio", 0.28)
    ratio = max(0.18, min(0.45, (ht_h + ht_a) / 2))
    liy = lt * ratio
    btts = (home_stats.get("general", {}).get("btts_rate", 0.45) +
            away_stats.get("general", {}).get("btts_rate", 0.45)) / 2
    if btts > 0.65: liy *= 1.06
    elif btts < 0.30: liy *= 0.94
    return round(liy, 3)

# ─── CANLI DÜZELTME ───────────────────────────────────────────────────────────
def adjust_lambda_live(lh, la, live_stats, minute, home_score, away_score):
    """
    Canlı istatistiklere göre lambda'yı güncelle.
    Şut oranı + top kontrolü + dakika kalan hesabı.
    """
    if not live_stats:
        return lh, la

    h_stats = live_stats.get("home", {})
    a_stats = live_stats.get("away", {})

    # Şut istatistikleri
    h_shots = float(h_stats.get("total_shots", h_stats.get("shots_total", 0)) or 0)
    a_shots = float(a_stats.get("total_shots", a_stats.get("shots_total", 0)) or 0)
    h_on_target = float(h_stats.get("shots_on_target", 0) or 0)
    a_on_target = float(a_stats.get("shots_on_target", 0) or 0)

    # Top kontrolü
    h_poss_raw = h_stats.get("ball_possession", h_stats.get("possession", "50%"))
    try:
        h_poss = float(str(h_poss_raw).replace("%", "")) / 100
    except:
        h_poss = 0.5
    a_poss = 1 - h_poss

    # Şut oranı düzeltmesi
    total_shots = h_shots + a_shots
    if total_shots > 3:
        h_shot_ratio = h_shots / total_shots
        a_shot_ratio = a_shots / total_shots
        # Beklenen: 0.5/0.5, gerçek farklıysa lambda'yı düzelt
        h_shot_factor = 0.7 + 0.6 * h_shot_ratio  # 0.7-1.3 arası
        a_shot_factor = 0.7 + 0.6 * a_shot_ratio
        lh = lh * h_shot_factor
        la = la * a_shot_factor

    # Top kontrolü düzeltmesi (hafif)
    lh = lh * (0.85 + 0.3 * h_poss)
    la = la * (0.85 + 0.3 * a_poss)

    # Dakika kalan — kalan süreye göre lambda ölçekle
    # (lambda = tam maç için, canlıda kalan dakika için ayarla)
    total_min = 90
    remaining = max(1, total_min - minute)
    scale = remaining / total_min
    lh = lh * scale
    la = la * scale

    lh = max(0.05, min(3.5, lh))
    la = max(0.05, min(3.5, la))
    return round(lh, 3), round(la, 3)

# ─── OLASILIKLAR ──────────────────────────────────────────────────────────────
def compute_probs(lh, la):
    matrix = score_matrix(lh, la)
    probs = {"1": 0, "X": 0, "2": 0}
    for (h, a), p in matrix.items():
        if h > a: probs["1"] += p
        elif h == a: probs["X"] += p
        else: probs["2"] += p
    return probs

def compute_over_probs(lam_total):
    def p_atleast(lam, k):
        return 1 - sum(poisson_prob(lam, i) for i in range(k))
    return {
        "0.5": round(p_atleast(lam_total, 1) * 100, 1),
        "1.5": round(p_atleast(lam_total, 2) * 100, 1),
        "2.5": round(p_atleast(lam_total, 3) * 100, 1),
        "3.5": round(p_atleast(lam_total, 4) * 100, 1),
    }

# ─── SİNYAL MOTORU ───────────────────────────────────────────────────────────
def generate_signals(pregame, live_pred, live_stats, minute, home_score, away_score):
    """
    Canlı sinyaller üret:
    - Gol beklentisi
    - Sonuç değişimi
    - Baskı analizi
    """
    signals = []
    if not live_stats:
        return signals

    h_stats = live_stats.get("home", {})
    a_stats = live_stats.get("away", {})

    h_shots = float(h_stats.get("total_shots", 0) or 0)
    a_shots = float(a_stats.get("total_shots", 0) or 0)
    h_on = float(h_stats.get("shots_on_target", 0) or 0)
    a_on = float(a_stats.get("shots_on_target", 0) or 0)
    h_corners = float(h_stats.get("corner_kicks", 0) or 0)
    a_corners = float(a_stats.get("corner_kicks", 0) or 0)

    score_diff = home_score - away_score
    live_lh = live_pred.get("lambda_home", 0)
    live_la = live_pred.get("lambda_away", 0)

    # 1. Gol beklentisi yüksek
    if live_lh + live_la > 0.8 and minute < 80:
        signals.append({
            "type": "GOL_BEKLENTI",
            "icon": "⚽",
            "label": "Gol Beklentisi Yüksek",
            "desc": f"Kalan sürede {round(live_lh + live_la, 1)} gol bekleniyor",
            "strength": "GÜÇLÜ" if live_lh + live_la > 1.2 else "ORTA",
            "color": "green"
        })

    # 2. Ev baskısı
    if h_shots - a_shots >= 4 and h_on >= 3:
        signals.append({
            "type": "EV_BASKI",
            "icon": "🔥",
            "label": "Ev Takımı Baskıda",
            "desc": f"Şut: {int(h_shots)}-{int(a_shots)}, İsabetli: {int(h_on)}-{int(a_on)}",
            "strength": "GÜÇLÜ",
            "color": "blue"
        })

    # 3. Deplasman baskısı
    if a_shots - h_shots >= 4 and a_on >= 3:
        signals.append({
            "type": "DEP_BASKI",
            "icon": "⚡",
            "label": "Deplasman Baskıda",
            "desc": f"Şut: {int(h_shots)}-{int(a_shots)}, İsabetli: {int(h_on)}-{int(a_on)}",
            "strength": "GÜÇLÜ",
            "color": "orange"
        })

    # 4. Mağlup takım baskı kuruyor (sonuç değişebilir)
    if score_diff > 0 and a_shots > h_shots and minute > 60:
        signals.append({
            "type": "SONUC_DEGISIMI",
            "icon": "🔄",
            "label": "Sonuç Değişebilir",
            "desc": f"Mağlup deplasman baskı kuruyor ({int(a_shots)} şut)",
            "strength": "ORTA",
            "color": "yellow"
        })
    elif score_diff < 0 and h_shots > a_shots and minute > 60:
        signals.append({
            "type": "SONUC_DEGISIMI",
            "icon": "🔄",
            "label": "Sonuç Değişebilir",
            "desc": f"Mağlup ev takımı baskı kuruyor ({int(h_shots)} şut)",
            "strength": "ORTA",
            "color": "yellow"
        })

    # 5. Güvenli sonuç
    if abs(score_diff) >= 2 and minute > 70:
        leader = "Ev" if score_diff > 0 else "Deplasman"
        signals.append({
            "type": "GUVENLI_SONUC",
            "icon": "🔒",
            "label": f"{leader} Güvenli",
            "desc": f"{minute}. dakika, {abs(score_diff)} gol fark",
            "strength": "GÜÇLÜ",
            "color": "gray"
        })

    return signals

# ─── DEVRE ARASI ANALİZİ ──────────────────────────────────────────────────────
def halftime_analysis(home_stats, away_stats, ht_home, ht_away, live_stats=None):
    """
    Devre arası: 2. yarı tahmini üret.
    IY skoru + istatistik + form verisi kullan.
    """
    lh, la = compute_lambdas(home_stats, away_stats)

    # 2. yarı için lambda: tam maç lambdasının %55'i
    lh_2h = lh * 0.55
    la_2h = la * 0.55

    # İstatistik varsa düzelt
    if live_stats:
        h_st = live_stats.get("home", {})
        a_st = live_stats.get("away", {})
        h_shots = float(h_st.get("total_shots", 0) or 0)
        a_shots = float(a_st.get("total_shots", 0) or 0)
        total = h_shots + a_shots
        if total > 0:
            lh_2h *= (0.7 + 0.6 * h_shots / total)
            la_2h *= (0.7 + 0.6 * a_shots / total)

    lh_2h = max(0.1, min(3.0, lh_2h))
    la_2h = max(0.1, min(3.0, la_2h))

    probs_2h = compute_probs(lh_2h, la_2h)
    over_2h = compute_over_probs(lh_2h + la_2h)

    # MS tahmini (IY skoru + 2. yarı tahmini)
    # En olası MS sonuçları
    ms_probs = compute_probs(lh, la)
    top_iyms = []
    for ht in ["1", "X", "2"]:
        for ft in ["1", "X", "2"]:
            # IY gerçek sonucu biliyoruz
            actual_ht = "1" if ht_home > ht_away else ("2" if ht_away > ht_home else "X")
            if ht != actual_ht:
                continue
            p_ft = ms_probs.get(ft, 0)
            if (ht == ft):
                p_ft *= 1.35
            elif (ht == "1" and ft == "2") or (ht == "2" and ft == "1"):
                p_ft *= 0.45
            else:
                p_ft *= 0.80
            top_iyms.append({"combo": f"IY {ht_home}-{ht_away} / MS ?", "ft": ft, "prob": round(p_ft * 100, 1)})

    top_iyms = sorted(top_iyms, key=lambda x: x["prob"], reverse=True)[:3]

    return {
        "lambda_2h_home": round(lh_2h, 3),
        "lambda_2h_away": round(la_2h, 3),
        "probs_2h": {k: round(v * 100, 1) for k, v in probs_2h.items()},
        "over_2h": over_2h,
        "top_ms": top_iyms,
    }

# ─── ANA ANALİZ ───────────────────────────────────────────────────────────────
def analyze_match(fixture, home_stats, away_stats, live_stats=None):
    """Tam maç analizi — maç öncesi + canlı güncelleme"""
    if not home_stats or not away_stats:
        return None

    lh, la = compute_lambdas(home_stats, away_stats)
    liy = compute_lambda_iy(lh, la, home_stats, away_stats)
    lt = lh + la

    # Maç öncesi olasılıklar
    pregame_probs = compute_probs(lh, la)
    pregame_over = compute_over_probs(lt)

    # Canlı güncelleme
    live_pred = {}
    signals = []
    ht_analysis = None

    status = fixture.get("status")
    minute = fixture.get("elapsed")
    home_score = fixture.get("home_goals") or 0
    away_score = fixture.get("away_goals") or 0
    home_ht = fixture.get("home_ht_goals")
    away_ht = fixture.get("away_ht_goals")

    if status == "LIVE" and isinstance(minute, int):
        live_lh, live_la = adjust_lambda_live(lh, la, live_stats, minute, home_score, away_score)
        live_probs = compute_probs(live_lh, live_la)
        live_over = compute_over_probs(live_lh + live_la)
        live_pred = {
            "lambda_home": live_lh,
            "lambda_away": live_la,
            "probs": {k: round(v * 100, 1) for k, v in live_probs.items()},
            "over": live_over,
        }
        signals = generate_signals(pregame_probs, live_pred, live_stats, minute, home_score, away_score)

    # Devre arası analizi
    if status == "LIVE" and minute == "HT" and home_ht is not None and away_ht is not None:
        ht_analysis = halftime_analysis(home_stats, away_stats, home_ht, away_ht, live_stats)

    iy_over = compute_over_probs(liy)

    return {
        "lambda_home": lh,
        "lambda_away": la,
        "lambda_total": lt,
        "lambda_iy": liy,
        "pregame": {
            "probs": {k: round(v * 100, 1) for k, v in pregame_probs.items()},
            "over": pregame_over,
            "iy_over": iy_over,
        },
        "live": live_pred,
        "signals": signals,
        "halftime": ht_analysis,
        "live_stats": live_stats,
    }
