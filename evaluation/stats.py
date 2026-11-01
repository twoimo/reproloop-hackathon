"""Small-sample statistical inference and timing summaries for ReproLoop evaluation.

All intervals and p-values explicitly label their conditioning assumptions:
- 5 PILOT scenarios and 3 FINAL scenarios belong to ONE fault family (F01).
- Intervals quantify within-family seed/layout repeatability, NEVER cross-app or
  cross-bug-family generalization.
"""
from __future__ import annotations

import math
import statistics


def wilson_score_interval(successes: int, total: int, z: float = 1.959963984540054) -> dict:
    """Compute Wilson score interval for a binomial proportion k/n."""
    if type(successes) is not int or type(total) is not int or total < 0 or not 0 <= successes <= total:
        raise ValueError(f"invalid binomial counts: successes={successes!r}, total={total!r}")
    if type(z) not in (int, float) or not math.isfinite(z) or z <= 0:
        raise ValueError("z must be positive finite number")
    if total == 0:
        return {
            "successes": 0,
            "total": 0,
            "point": None,
            "lower": None,
            "upper": None,
            "model_status": "ILLUSTRATIVE_CONDITIONAL_BINOMIAL_MODEL_ONLY",
            "independence_and_common_p_established": False,
            "scope_limit": "Zero denominator; not measurable.",
        }
    p_hat = successes / total
    z2 = z * z
    denom = 1.0 + z2 / total
    center = (p_hat + z2 / (2.0 * total)) / denom
    half = (z / denom) * math.sqrt((p_hat * (1.0 - p_hat) / total) + (z2 / (4.0 * total * total)))
    return {
        "successes": successes,
        "total": total,
        "point": round(p_hat, 6),
        "lower": round(max(0.0, center - half), 6),
        "upper": round(min(1.0, center + half), 6),
        "model_status": "ILLUSTRATIVE_CONDITIONAL_BINOMIAL_MODEL_ONLY",
        "independence_and_common_p_established": False,
        "scope_limit": (
            "Illustrative conditional binomial model only. Independence and an identical success "
            "probability (common p) are NOT established across the 5 fixed correlated scenarios "
            "(2 Variant A, 2 Variant B, 1 Variant C) of single fault family F01. Not a valid empirical "
            "confidence interval for general bug reproduction or model quality."
        ),
    }


def clopper_pearson_interval(successes: int, total: int, alpha: float = 0.05) -> dict:
    """Exact Clopper-Pearson binomial confidence interval via bisection on cumulative binomial tails."""
    if type(successes) is not int or type(total) is not int or total < 0 or not 0 <= successes <= total:
        raise ValueError(f"invalid binomial counts: successes={successes!r}, total={total!r}")
    if type(alpha) is not float or not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be float in (0, 1)")
    if total == 0:
        return {
            "successes": 0,
            "total": 0,
            "point": None,
            "lower": None,
            "upper": None,
            "model_status": "ILLUSTRATIVE_CONDITIONAL_BINOMIAL_MODEL_ONLY",
            "independence_and_common_p_established": False,
        }

    def binom_pmf(k: int, n: int, p: float) -> float:
        if p <= 0.0:
            return 1.0 if k == 0 else 0.0
        if p >= 1.0:
            return 1.0 if k == n else 0.0
        return math.comb(n, k) * (p ** k) * ((1.0 - p) ** (n - k))

    # Lower bound: P(X >= successes | p_low) = alpha / 2
    if successes == 0:
        low = 0.0
    else:
        lo, hi = 0.0, 1.0
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            tail = sum(binom_pmf(i, total, mid) for i in range(successes, total + 1))
            if tail < alpha / 2.0:
                 lo = mid
            else:
                hi = mid
        low = 0.5 * (lo + hi)

    # Upper bound: P(X <= successes | p_high) = alpha / 2
    if successes == total:
        high = 1.0
    else:
        lo, hi = 0.0, 1.0
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            tail = sum(binom_pmf(i, total, mid) for i in range(0, successes + 1))
            if tail > alpha / 2.0:
                lo = mid
            else:
                hi = mid
        high = 0.5 * (lo + hi)

    return {
        "successes": successes,
        "total": total,
        "point": round(successes / total, 6),
        "lower": round(low, 6),
        "upper": round(high, 6),
        "alpha": alpha,
        "model_status": "ILLUSTRATIVE_CONDITIONAL_BINOMIAL_MODEL_ONLY",
        "independence_and_common_p_established": False,
        "scope_limit": (
            "Illustrative exact binomial interval under an unverified i.i.d. common-p model. "
            "Independence and common p are NOT established across the fixed correlated A2/B2/C1 "
            "scenarios of single fault family F01; not an empirical generalization or precision guarantee."
        ),
    }


def exact_paired_mcnemar(base_only_pass: int, candidate_only_pass: int) -> dict:
    """Exact two-sided binomial sign / McNemar calculation on discordant pairs (b vs c)."""
    for val in (base_only_pass, candidate_only_pass):
        if type(val) is not int or val < 0:
            raise ValueError("discordant counts must be non-negative ints")
    n_disc = base_only_pass + candidate_only_pass
    if n_disc == 0:
        return {
            "base_only_pass": 0,
            "candidate_only_pass": 0,
            "discordant_total": 0,
            "exact_p_two_sided": 1.0,
            "net_direction": "TIE",
            "model_status": "ILLUSTRATIVE_CONDITIONAL_SIGN_TEST_MODEL_ONLY",
            "independence_established": False,
            "scope_limit": "No discordant pairs; illustrative conditional sign model only.",
        }
    k = min(base_only_pass, candidate_only_pass)
    tail = sum(math.comb(n_disc, i) for i in range(0, k + 1)) / (2 ** n_disc)
    p_two_sided = min(1.0, 2.0 * tail)
    direction = (
        "CANDIDATE_BETTER"
        if candidate_only_pass > base_only_pass
        else ("BASE_BETTER" if base_only_pass > candidate_only_pass else "TIE")
    )
    return {
        "base_only_pass": base_only_pass,
        "candidate_only_pass": candidate_only_pass,
        "discordant_total": n_disc,
        "exact_p_two_sided": round(p_two_sided, 6),
        "net_direction": direction,
        "model_status": "ILLUSTRATIVE_CONDITIONAL_SIGN_TEST_MODEL_ONLY",
        "independence_established": False,
        "scope_limit": (
            "Illustrative conditional sign-test calculation under an unverified independent-discordance "
            "assumption. Does NOT establish empirical superiority, model quality, or winning probability."
        ),
    }


def summarize_timings_ns(samples_ns: list[int]) -> dict:
    """Summarize raw nanosecond timing samples with explicit small-sample p95 warnings."""
    if not isinstance(samples_ns, list) or not samples_ns or any(type(x) is not int or x < 0 for x in samples_ns):
        raise ValueError("samples_ns must be non-empty list of non-negative ints")
    ordered = sorted(samples_ns)
    n = len(ordered)
    p50_idx = (n - 1) // 2
    p95_idx = min(n - 1, math.ceil(0.95 * n) - 1)
    return {
        "count": n,
        "min_ns": ordered[0],
        "p50_median_ns": int(statistics.median(ordered)),
        "mean_ns": round(statistics.fmean(ordered), 2),
        "stdev_ns": round(statistics.stdev(ordered), 2) if n >= 2 else 0.0,
        "p95_order_stat_ns": ordered[p95_idx],
        "max_ns": ordered[-1],
        "p95_stability_note": (
            "UNSTABLE_SMALL_SAMPLE (n < 30; p95 equals high order statistic, not a production SLA)"
            if n < 30
            else "ORDER_STATISTIC_N_GE_30"
        ),
        "median_index": p50_idx,
    }
