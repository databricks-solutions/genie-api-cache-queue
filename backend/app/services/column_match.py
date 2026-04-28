"""Fuzzy column-name matching shared across the router and the cache-write validator.

The selector writes snake_case names often suffixed with `_id`, `_name`, `_code`.
Rooms return display-friendly names (`Donor`, `Trust Fund`, `Recipient Country`)
or raw snake_case (`donor_id`, `trust_fund_id`). These helpers paper over the
mismatch.
"""

from typing import Optional


# Columns ending in these are aggregates/metrics — never bind to them as id/key
# inputs for a downstream pick, and never accept them as the requested-output
# column at cache-write time.
METRIC_SUFFIXES = ("_count", "_total", "_sum", "_avg", "_mean", "_ratio",
                   "_pct", "_percent", "_usd", "_amount", "_value", "_rate")

# Suffixes stripped from the TARGET column name before matching candidates.
TARGET_STRIP_SUFFIXES = ("_id", "_ids", "_name", "_names", "_code", "_codes",
                         "_label", "_key", "_keys")


def norm(s: str) -> str:
    """Normalize a column name: lowercase, strip non-alphanumerics.

    `"Trust Fund"` → `"trustfund"`, `"donor_id"` → `"donorid"`, `"R1-ID"` →
    `"r1id"`. Lets the fuzzy matcher ignore the difference between display
    names with spaces/case and selector-produced `snake_case_id` names.
    """
    return "".join(ch for ch in s.lower() if ch.isalnum()) if isinstance(s, str) else ""


def is_metric_column(name: str) -> bool:
    lower = name.lower() if isinstance(name, str) else ""
    return any(lower.endswith(suf) for suf in METRIC_SUFFIXES)


def target_stems(target: str) -> list[str]:
    """Return the normalized stems to try for matching `target` against result columns.

    Starts with the full normalized target and, if it ends with a descriptive
    suffix (`_id`, `_name`, `_code`, etc.), adds the stripped-stem form so a
    selector-written `recipient_country_name` can match a `Recipient Country`
    column in the result.
    """
    t = norm(target)
    if not t:
        return []
    stems = [t]
    lower = target.lower()
    for suf in TARGET_STRIP_SUFFIXES:
        if lower.endswith(suf):
            bare = lower[: -len(suf)]
            stems.append(norm(bare))
            if suf.endswith("s") and len(suf) > 2:
                stems.append(norm(lower[: -(len(suf) - 1)]))
            break
    seen, out = set(), []
    for s in stems:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def fuzzy_column_match(target: str, col_names: list[str]) -> Optional[int]:
    """Conservative match for selector-produced column names vs actual results.

    Order:
    1. Exact match after normalization (case/space/punct-insensitive).
    2. Stem match: strip descriptive suffix (`_id`, `_name`, etc.) and look
       for a column whose normalized form equals the stem (or stem+"id").

    REJECTS metric-suffix candidates (`trust_fund_count`, `donor_total_usd`):
    binding to an aggregate column silently passes nonsense to downstream.
    """
    if not col_names or not isinstance(target, str):
        return None

    normed = [norm(c) if isinstance(c, str) else "" for c in col_names]

    t_full = norm(target)
    if t_full and t_full in normed:
        return normed.index(t_full)

    stems = target_stems(target)
    for stem in stems:
        if not stem:
            continue
        variants = {stem, stem + "id"}
        candidates = []
        for i, (orig, cand) in enumerate(zip(col_names, normed)):
            if not cand or is_metric_column(orig):
                continue
            if cand in variants:
                candidates.append(i)
        if len(candidates) == 1:
            return candidates[0]

    return None
