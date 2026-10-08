"""Scorecard for one candidate (EVALUATION.md §3), from its per-user, per-year aggregates.

Input: analysis/out/cand/<name>/agg.parquet written by the candidate builder, one row per
(user, year of bet, random half of their bets):
    user, year, half, n, sw, swe, swe2, swe_p0..swe_p{K-1}
where e is a bet's excess outcome, w its weight, and swe_pk the same sum after shuffling outcomes among
comparable bets (luck baseline). Plus meta.json (candidate settings, horizon).
Output: analysis/out/cand/<name>/scorecard.json

Uncertainty: Poisson bootstrap over users (each user gets weight ~ Poisson(1)), 200 replicates. Ranks
and quintile thresholds are computed once on the full sample (a standard approximation).
"""

import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
FEATS = ["listens", "history_years", "join_year", "listens_per_active_month", "unmatched_share", "no_id_share",
         "new_artists_per_year", "committed_per_year", "mainstream_share", "commit_rate"]
LOG_FEATS = {"listens", "listens_per_active_month"}
B = 200
MIN_BETS = 20      # whole-history score
MIN_PERIOD = 10    # forward test: bets needed in the past and in the future window
MIN_YEAR = 5       # yearly scores
RNG = np.random.default_rng(11)


def wcorr(x, y, w):
    w = w / w.sum()
    mx, my = (w * x).sum(), (w * y).sum()
    cov = (w * (x - mx) * (y - my)).sum()
    return cov / np.sqrt((w * (x - mx) ** 2).sum() * (w * (y - my) ** 2).sum())


def ci(vals):
    vals = np.asarray([v for v in vals if np.isfinite(v)])
    return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))] if len(vals) > 10 else [None, None]


def rank(x):
    return pl.Series(x).rank("average").to_numpy() / len(x)


def main(name):
    out = ROOT / "analysis" / "out" / "cand" / name
    meta = json.loads((out / "meta.json").read_text())
    half = meta.get("half", "explore")
    gap = meta["horizon"] // 12 + 1  # years between past and future bets so return windows never overlap
    agg = pl.read_parquet(out / "agg.parquet")
    perms = sorted(c for c in agg.columns if c.startswith("swe_p"))
    users = agg.select("user").unique().sort("user").with_row_index("ui")
    agg = agg.join(users, on="user")
    U = users.height
    boot = RNG.poisson(1.0, size=(B, U)).astype(np.float64)

    def per_user(df, cols=("n", "sw", "swe")):
        g = df.group_by("ui").agg([pl.col(c).sum() for c in cols])
        return g

    card = {"candidate": name, "meta": meta, "users_with_bets": U}

    # --- whole-history scores, luck baseline, reliability, impostors -------------------------------------
    tot = per_user(agg, ["n", "sw", "swe", "swe2"] + perms).filter(pl.col("n") >= MIN_BETS)
    s = (tot["swe"] / tot["sw"]).to_numpy()
    ui = tot["ui"].to_numpy()
    card["users_scored"] = int(len(s))
    card["coverage"] = len(s) / U
    obs_var = s.var()
    null_var = np.mean([(tot[p] / tot["sw"]).to_numpy().var() for p in perms]) if perms else float("nan")
    card["not_luck_share"] = float(1 - null_var / obs_var)
    nl = []
    for b in range(B):
        w = boot[b, ui]
        m = (w * s).sum() / w.sum()
        v = (w * (s - m) ** 2).sum() / w.sum()
        nl.append(1 - null_var / v)
    card["not_luck_share_ci"] = ci(nl)

    halves = agg.group_by("ui", "half").agg(pl.col("n").sum(), pl.col("sw").sum(), pl.col("swe").sum())
    h0 = halves.filter(pl.col("half") == 0).select("ui", s0=pl.col("swe") / pl.col("sw"), n0="n")
    h1 = halves.filter(pl.col("half") == 1).select("ui", s1=pl.col("swe") / pl.col("sw"), n1="n")
    hh = h0.join(h1, on="ui").filter((pl.col("n0") >= MIN_BETS // 2) & (pl.col("n1") >= MIN_BETS // 2))
    a, bb, hu = hh["s0"].to_numpy(), hh["s1"].to_numpy(), hh["ui"].to_numpy()
    r = np.corrcoef(a, bb)[0, 1]
    card["reliability"] = float(2 * r / (1 + r))
    rels = []
    for k in range(B):
        rk = wcorr(a, bb, boot[k, hu])
        rels.append(2 * rk / (1 + rk))
    card["reliability_ci"] = ci(rels)
    # Typical percentile uncertainty for one person: with reliability rho, the true-score SD given the
    # observed score is sqrt(1 - rho); expressed as the 80% range in percentile points around the median.
    rho = max(card["reliability"], 0.0)
    from statistics import NormalDist
    nd = NormalDist()
    z = nd.inv_cdf(0.75) * rho  # someone observed at the 75th percentile
    sd = np.sqrt(max(1 - rho ** 2, 1e-9))
    card["percentile_range_for_observed_75th"] = [100 * nd.cdf(z - 1.2816 * sd), 100 * nd.cdf(z + 1.2816 * sd)]

    feats = pl.read_parquet(ROOT / "data" / "derived" / "user_features" / f"{half}.parquet")
    fu = tot.select("ui", score=pl.col("swe") / pl.col("sw"), n="n").join(users, on="ui").join(feats, on="user").drop_nulls()
    Z = fu.select([pl.col(c).cast(pl.Float64) for c in FEATS] + [pl.col("n").cast(pl.Float64)]).with_columns(
        [pl.col(c).log() for c in LOG_FEATS] + [pl.col("n").log()]).to_numpy()
    Z = (Z - Z.mean(0)) / np.where(Z.std(0) > 0, Z.std(0), 1)
    Z = np.column_stack([np.ones(len(Z)), Z])
    y = fu["score"].to_numpy()
    fui = fu["ui"].to_numpy()

    def r2(w):
        sw = np.sqrt(w)
        beta, *_ = np.linalg.lstsq(Z * sw[:, None], y * sw, rcond=None)
        res = y - Z @ beta
        my = (w * y).sum() / w.sum()
        return 1 - (w * res ** 2).sum() / (w * (y - my) ** 2).sum()

    card["impostor_r2"] = float(r2(np.ones(len(y))))
    card["impostor_r2_ci"] = ci([r2(boot[k, fui]) for k in range(B)])
    card["impostor_corr"] = {c: float(np.corrcoef(Z[:, i + 1], y)[0, 1]) for i, c in enumerate(FEATS + ["n_bets"])}

    # --- forward test ---------------------------------------------------------------------------------
    # Impostor features for the adjustment: from the past period only (years <= cutoff) when the per-year
    # table exists, otherwise whole-history features (small leak, flagged in the card).
    uyf_path = ROOT / "data" / "derived" / "user_year_features" / f"{half}.parquet"
    uyf = pl.read_parquet(uyf_path) if uyf_path.exists() else None
    card["impostor_features_past_only"] = uyf is not None

    def past_feats(cut):
        if uyf is None:
            return feats
        g = uyf.filter(pl.col("year") <= cut).group_by("user").agg(pl.all().exclude("user", "year").sum())
        base = feats.select("user", "start_week", "join_year", "no_id_share")
        return g.join(base, on="user").with_columns(
            history_years=((cut + 1 - 1970) * 52.18 - pl.col("start_week")) / 52.18,
            listens_per_active_month=pl.col("listens") / pl.col("active_months"),
            unmatched_share=pl.col("unmatched_listens") / pl.col("listens"),
            new_artists_per_year=pl.col("new_artists") / (((cut + 1 - 1970) * 52.18 - pl.col("start_week")) / 52.18).clip(0.25),
            committed_per_year=pl.col("committed") / (((cut + 1 - 1970) * 52.18 - pl.col("start_week")) / 52.18).clip(0.25),
            mainstream_share=pl.col("mainstream_plays") / pl.col("artist_plays"),
            commit_rate=pl.col("committed") / pl.col("new_artists").clip(1),
        )

    years = sorted(agg["year"].unique().to_list())
    fwd = []
    for cut in [yy for yy in years if yy + gap in years and yy >= 2006]:
        past = per_user(agg.filter(pl.col("year") <= cut)).filter(pl.col("n") >= MIN_PERIOD)
        fut = per_user(agg.filter((pl.col("year") >= cut + gap) & (pl.col("year") <= cut + gap + 1))).filter(
            pl.col("n") >= MIN_PERIOD)
        j = past.select("ui", p=pl.col("swe") / pl.col("sw")).join(fut.select("ui", f=pl.col("swe") / pl.col("sw")), on="ui")
        if j.height < 500:
            continue
        p, f, ju = j["p"].to_numpy(), j["f"].to_numpy(), j["ui"].to_numpy()
        rp, rf = rank(p), rank(f)
        top_p, bot_p, top_f = rp > 0.8, rp <= 0.2, rf > 0.8
        # impostor-adjusted past score (residual on features) for the gate
        jf = j.join(users, on="ui").join(past_feats(cut).select("user", *FEATS), on="user").drop_nulls()
        Zj = jf.select([pl.col(c).cast(pl.Float64) for c in FEATS]).with_columns([pl.col(c).log() for c in LOG_FEATS]).to_numpy()
        Zj = np.column_stack([np.ones(len(Zj)), (Zj - Zj.mean(0)) / np.where(Zj.std(0) > 0, Zj.std(0), 1)])
        resid_p = jf["p"].to_numpy() - Zj @ np.linalg.lstsq(Zj, jf["p"].to_numpy(), rcond=None)[0]
        fwd.append({
            "cutoff": int(cut), "users": int(j.height),
            "p": p, "f": f, "rp": rp, "rf": rf, "ui": ju, "top_p": top_p, "bot_p": bot_p, "top_f": top_f,
            "resid_corr": float(np.corrcoef(rank(resid_p), rank(jf["f"].to_numpy()))[0, 1]),
            "res_rp": rank(resid_p), "res_rf": rank(jf["f"].to_numpy()), "res_ui": jf["ui"].to_numpy(),
        })

    def fwd_stats(wfun):
        cs, sp, rr, ns = [], [], [], []
        for d in fwd:
            w = wfun(d["ui"])
            cs.append(wcorr(d["rp"], d["rf"], w))
            sp.append((w * d["f"] * d["top_p"]).sum() / (w * d["top_p"]).sum()
                      - (w * d["f"] * d["bot_p"]).sum() / (w * d["bot_p"]).sum())
            rr.append((w * (d["top_p"] & d["top_f"])).sum() / (w * d["top_p"]).sum())
            ns.append(w.sum())
        ns = np.array(ns)
        return [float((np.array(v) * ns).sum() / ns.sum()) for v in (cs, sp, rr)]

    if fwd:
        point = fwd_stats(lambda u: np.ones(len(u)))
        bs = [fwd_stats(lambda u, k=k: boot[k, u]) for k in range(B)]
        card["forward"] = {
            "rank_corr": point[0], "rank_corr_ci": ci([b[0] for b in bs]),
            "top_minus_bottom": point[1], "top_minus_bottom_ci": ci([b[1] for b in bs]),
            "repeat_rate_top20": point[2], "repeat_rate_top20_ci": ci([b[2] for b in bs]), "repeat_rate_chance": 0.2,
            "impostor_adjusted_rank_corr": float(np.average([d["resid_corr"] for d in fwd], weights=[d["users"] for d in fwd])),
            "impostor_adjusted_rank_corr_ci": ci([np.average([wcorr(d["res_rp"], d["res_rf"], boot[k, d["res_ui"]]) for d in fwd],
                                                             weights=[d["users"] for d in fwd]) for k in range(B)]),
            "by_cutoff": [{"cutoff": d["cutoff"], "users": d["users"],
                           "rank_corr": float(np.corrcoef(d["rp"], d["rf"])[0, 1])} for d in fwd],
            "gap_years": gap,
        }

    # --- stability curve -------------------------------------------------------------------------------
    yr = agg.group_by("ui", "year").agg(pl.col("n").sum(), pl.col("sw").sum(), pl.col("swe").sum()).filter(
        pl.col("n") >= MIN_YEAR).with_columns(sc=pl.col("swe") / pl.col("sw"))
    yh = agg.group_by("ui", "year", "half").agg(pl.col("n").sum(), pl.col("sw").sum(), pl.col("swe").sum())
    rel_y = {}
    for y0 in years:
        a0 = yh.filter((pl.col("year") == y0) & (pl.col("half") == 0) & (pl.col("n") >= 3)).select("ui", a=pl.col("swe") / pl.col("sw"))
        a1 = yh.filter((pl.col("year") == y0) & (pl.col("half") == 1) & (pl.col("n") >= 3)).select("ui", b=pl.col("swe") / pl.col("sw"))
        jj = a0.join(a1, on="ui")
        if jj.height > 500:
            rr_ = np.corrcoef(jj["a"], jj["b"])[0, 1]
            rel_y[y0] = max(2 * rr_ / (1 + rr_), 1e-3)
    curve = []
    for lag in range(1, 6):
        raws, cors, ns = [], [], []
        for y0 in years:
            if y0 + lag not in years or y0 not in rel_y or y0 + lag not in rel_y:
                continue
            jj = yr.filter(pl.col("year") == y0).select("ui", a="sc").join(
                yr.filter(pl.col("year") == y0 + lag).select("ui", b="sc"), on="ui")
            if jj.height < 500:
                continue
            rr_ = np.corrcoef(jj["a"], jj["b"])[0, 1]
            raws.append(rr_)
            cors.append(rr_ / np.sqrt(rel_y[y0] * rel_y[y0 + lag]))
            ns.append(jj.height)
        if ns:
            curve.append({"lag_years": lag, "raw": float(np.average(raws, weights=ns)),
                          "corrected": float(np.average(cors, weights=ns)), "users": int(sum(ns)),
                          "overlapping_windows": lag < gap})
    card["stability_curve"] = curve
    card["yearly_reliability"] = {int(k): float(v) for k, v in rel_y.items()}
    c3 = [c for c in curve if c["lag_years"] == 3]
    card["stability_3y_corrected"] = c3[0]["corrected"] if c3 else None
    pairs = []
    for y0 in years:
        if y0 + 3 in rel_y and y0 in rel_y:
            jj = yr.filter(pl.col("year") == y0).select("ui", a="sc").join(
                yr.filter(pl.col("year") == y0 + 3).select("ui", b="sc"), on="ui")
            if jj.height >= 500:
                pairs.append((jj["a"].to_numpy(), jj["b"].to_numpy(), jj["ui"].to_numpy(),
                              np.sqrt(rel_y[y0] * rel_y[y0 + 3]), jj.height))
    if pairs:
        card["stability_3y_corrected_ci"] = ci([np.average([wcorr(a_, b_, boot[k, u_]) / d_ for a_, b_, u_, d_, _ in pairs],
                                                           weights=[n_ for *_, n_ in pairs]) for k in range(B)])

    # --- gates ----------------------------------------------------------------------------------------
    f = card.get("forward", {})
    # Incremental validity: the headline is the forward prediction after removing the impostors; the only
    # impostor-related gate is that it stays above zero. No arbitrary share cutoff (impostor R^2 is reported).
    if f:
        card["headline_adjusted_forward"] = f["impostor_adjusted_rank_corr"]
        card["headline_adjusted_forward_ci"] = f["impostor_adjusted_rank_corr_ci"]
        card["share_of_prediction_kept_after_impostors"] = f["impostor_adjusted_rank_corr"] / f["rank_corr"] if f["rank_corr"] else None
    card["gates"] = {
        "beats_luck": card["not_luck_share_ci"][0] is not None and card["not_luck_share_ci"][0] > 0,
        "impostor_adjusted_still_predicts": (f.get("impostor_adjusted_rank_corr_ci") or [None])[0] is not None
                                            and f["impostor_adjusted_rank_corr_ci"][0] > 0,
        "stable_3y": (card.get("stability_3y_corrected_ci") or [None])[0] is not None
                     and card["stability_3y_corrected_ci"][0] > 0,
    }
    card["passes_gates"] = all(card["gates"].values())
    (out / "scorecard.json").write_text(json.dumps(card, indent=1))
    print(json.dumps({k: card.get(k) for k in ["candidate", "headline_adjusted_forward", "headline_adjusted_forward_ci",
                                               "share_of_prediction_kept_after_impostors", "users_scored", "not_luck_share",
                                               "reliability", "impostor_r2", "stability_3y_corrected", "passes_gates"]}
                     | {"forward": {k: v for k, v in f.items() if k != "by_cutoff"}}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
