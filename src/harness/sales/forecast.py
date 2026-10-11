"""Tomorrow's sales for a small business: plain statistics, small data, honest
ranges. No model calls; pure numpy, so it runs per request in milliseconds.

The method grows with the data:

  < 14 days logged     no forecast ("learning")
  2-8 weeks            same weekday, recent weeks weighted more, nudged by the recent trend
  8+ weeks             also a ridge regression on log sales: weekday, festivals (and the eve and
                       the days after), rain, temperature, salary days, month end, the owner's
                       own offers, and a trend

Every model is **backtested** on the last weeks (one day ahead, only data
before that day) against the plain baseline "same day last week", on the
same days. The lowest average error wins; when nothing beats the baseline,
the baseline is what's shown. The range comes from that model's own backtest
errors (10th-90th percentile), and the accuracy is its average % error, so the
page can say "we were within 11% over the last 4 weeks".

The reasons are the regression's own contributions against an average day
(or, for the weekday model, the weekday's and the trend's ratios): never
written by a language model.
"""

import math
from dataclasses import asdict, dataclass, field
from datetime import date

import numpy as np

from harness.sales import festivals

MIN_DAYS = 14
RIDGE_MIN = 56
RIDGE_MIN_TRAIN = 42
BACKTEST = 28
RIDGE_ALPHA = 0.5
RAINY_MM = 2.5                    # a day with at least this much rain counts as rainy
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MODEL_LABEL = {"naive": "the same day last week", "weekday": "your recent weeks", "regression": "a model of your sales"}


@dataclass
class Day:
    day: date
    sales: float
    rain: float | None = None        # mm that day
    tmax: float | None = None        # °C
    promo: bool = False              # the owner ran an offer


@dataclass
class Target:
    day: date
    rain: float | None = None
    tmax: float | None = None
    promo: bool = False
    closed: bool = False


@dataclass
class Forecast:
    status: str                      # learning | ready | closed
    day: str
    days_logged: int
    days_needed: int = 0
    value: float | None = None
    low: float | None = None
    high: float | None = None
    model: str | None = None         # naive | weekday | regression
    model_label: str = ""
    accuracy: float | None = None    # mean absolute % error in the backtest (0.11 = 11%)
    backtest_days: int = 0
    beats_baseline: bool = False
    typical: float | None = None     # this weekday, usually (no trend): what "slow" is measured against
    reasons: list[dict] = field(default_factory=list)   # [{key, label, effect}] effect 0.12 = +12%
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------ the simple models

def _naive(hist: list[Day], t: Target) -> float:
    week_ago = next((d.sales for d in reversed(hist) if (t.day - d.day).days == 7), None)
    if week_ago is not None:
        return week_ago
    last = [d.sales for d in hist[-7:]]
    return float(np.mean(last)) if last else 0.0


def weekday_typical(hist: list[Day], target_day: date) -> float | None:
    """This weekday over the last 8 weeks, the most recent weighted most."""
    same = [d for d in reversed(hist) if d.day.weekday() == target_day.weekday() and 0 < (target_day - d.day).days <= 56]
    if not same:
        return None
    w = np.array([0.8 ** k for k in range(len(same))])
    return float(np.dot(w, [d.sales for d in same]) / w.sum())


def _trend(hist: list[Day], target_day: date) -> float:
    recent = [d.sales for d in hist if 0 < (target_day - d.day).days <= 14]
    before = [d.sales for d in hist if 14 < (target_day - d.day).days <= 42]
    if len(recent) < 7 or len(before) < 7 or np.mean(before) <= 0:
        return 1.0
    return float(min(1.25, max(0.8, np.mean(recent) / np.mean(before))))


def _weekday(hist: list[Day], t: Target) -> float:
    base = weekday_typical(hist, t.day)
    if base is None:
        base = float(np.mean([d.sales for d in hist[-14:]]))
    return base * math.sqrt(_trend(hist, t.day))


# ------------------------------------------------------------ the regression

GROUPS = ("weekday", "festival", "rain", "temp", "salary", "month_end", "promo", "trend")


def _row(day: date, rain: float | None, tmax: float | None, promo: bool, *, rain_fill: float, t_mean: float,
         start: date) -> list[float]:
    wd = [1.0 if day.weekday() == k else 0.0 for k in range(1, 7)]           # Monday is the base
    return wd + [
        1.0 if festivals.festival_on(day) else 0.0,
        1.0 if festivals.eve_of(day) else 0.0,
        1.0 if festivals.just_after(day) else 0.0,
        (1.0 if rain >= RAINY_MM else 0.0) if rain is not None else rain_fill,
        ((tmax - t_mean) / 10.0) if tmax is not None else 0.0,
        1.0 if day.day <= 5 else 0.0,
        1.0 if day.day >= 26 else 0.0,
        1.0 if promo else 0.0,
        (day - start).days / 365.0,
    ]


# column index -> group
_COL_GROUP = ["weekday"] * 6 + ["festival"] * 3 + ["rain", "temp", "salary", "month_end", "promo", "trend"]


class _Ridge:
    def __init__(self, hist: list[Day]):
        rains = [1.0 if d.rain >= RAINY_MM else 0.0 for d in hist if d.rain is not None]
        temps = [d.tmax for d in hist if d.tmax is not None]
        self.rain_fill = float(np.mean(rains)) if rains else 0.0
        self.t_mean = float(np.mean(temps)) if temps else 25.0
        self.start = hist[0].day
        X = np.array([self._x(d.day, d.rain, d.tmax, d.promo) for d in hist])
        y = np.log1p(np.array([max(0.0, d.sales) for d in hist]))
        self.mean_x = X[:, 1:].mean(axis=0)
        penalty = np.eye(X.shape[1]) * RIDGE_ALPHA
        penalty[0, 0] = 0.0                                                     # never shrink the intercept
        self.beta = np.linalg.solve(X.T @ X + penalty, X.T @ y)

    def _x(self, day, rain, tmax, promo) -> list[float]:
        return [1.0] + _row(day, rain, tmax, promo, rain_fill=self.rain_fill, t_mean=self.t_mean, start=self.start)

    def predict(self, t: Target) -> float:
        return float(np.expm1(np.dot(self.beta, self._x(t.day, t.rain, t.tmax, t.promo))))

    def contributions(self, t: Target) -> dict[str, float]:
        """Each group's effect on the target against an average training day (0.1 = +10%)."""
        x = np.array(self._x(t.day, t.rain, t.tmax, t.promo))[1:]
        out: dict[str, float] = {}
        for j, g in enumerate(_COL_GROUP):
            out[g] = out.get(g, 0.0) + float(self.beta[j + 1] * (x[j] - self.mean_x[j]))
        return {g: math.expm1(v) for g, v in out.items()}


def _ridge(hist: list[Day], t: Target) -> float:
    return _Ridge(hist).predict(t)


MODELS = {"naive": (_naive, 7), "weekday": (_weekday, MIN_DAYS), "regression": (_ridge, RIDGE_MIN_TRAIN)}


# ------------------------------------------------------------ backtest and choice

def backtest(hist: list[Day], names: list[str]) -> dict[str, list[tuple[float, float]]]:
    """(actual, predicted) per model, one day ahead, on the same recent days for every model."""
    n = len(hist)
    start = max(n - BACKTEST, max(MODELS[m][1] for m in names))
    out: dict[str, list[tuple[float, float]]] = {m: [] for m in names}
    for i in range(start, n):
        train, d = hist[:i], hist[i]
        t = Target(d.day, d.rain, d.tmax, d.promo)
        for m in names:
            out[m].append((d.sales, max(0.0, MODELS[m][0](train, t))))
    return out


def _mae(pairs: list[tuple[float, float]]) -> float:
    return float(np.mean([abs(a - p) for a, p in pairs])) if pairs else math.inf


def _reasons(hist: list[Day], t: Target, model: str) -> list[dict]:
    hotter = False
    if model == "regression":
        r = _Ridge(hist)
        eff, hotter = r.contributions(t), t.tmax is not None and t.tmax > r.t_mean
    elif model == "weekday":
        typical = weekday_typical(hist, t.day)
        overall = float(np.mean([d.sales for d in hist[-56:]]))
        eff = {"weekday": (typical / overall - 1) if typical and overall else 0.0,
               "trend": math.sqrt(_trend(hist, t.day)) - 1}
    else:
        return []
    out = []
    for g in GROUPS:
        e = eff.get(g, 0.0)
        if abs(e) < 0.03:
            continue
        out.append({"key": g, "label": _label(g, e, t, hotter), "effect": round(e, 3)})
    return sorted(out, key=lambda r: -abs(r["effect"]))[:4]


def _label(group: str, effect: float, t: Target, hotter: bool = False) -> str:
    up = effect > 0
    if group == "weekday":
        return f"{WEEKDAYS[t.day.weekday()]}s are usually {'busier' if up else 'quieter'}"
    if group == "festival":
        name = festivals.festival_on(t.day) or festivals.eve_of(t.day) or festivals.just_after(t.day) or "a festival"
        when = "" if festivals.festival_on(t.day) else ("the day before " if festivals.eve_of(t.day) else "just after ")
        return f"It's {when}{name}"
    if group == "rain":
        return "Rain is likely" if (t.rain or 0) >= RAINY_MM else "A dry day"
    if group == "temp":
        return "Hotter than usual" if hotter else "Cooler than usual"
    if group == "salary":
        return "Start of the month (salary days)"
    if group == "month_end":
        return "End of the month"
    if group == "promo":
        return "Your offer"
    return "Your recent trend"


def forecast(hist: list[Day], target: Target) -> Forecast:
    """``hist``: complete, open days, oldest first."""
    hist = sorted(hist, key=lambda d: d.day)
    n = len(hist)
    f = Forecast(status="learning", day=target.day.isoformat(), days_logged=n)
    if target.closed:
        f.status, f.value, f.low, f.high = "closed", 0.0, 0.0, 0.0
        return f
    if n < MIN_DAYS:
        f.days_needed = MIN_DAYS - n
        return f
    names = ["naive", "weekday"] + (["regression"] if n >= RIDGE_MIN else [])
    bt = backtest(hist, names)
    maes = {m: _mae(p) for m, p in bt.items()}
    best = min(names, key=lambda m: (maes[m], names.index(m)))
    value = max(0.0, MODELS[best][0](hist, target))
    pairs = bt[best]
    errs = [a / p - 1 for a, p in pairs if p > 0]
    if len(errs) >= 8:
        q10, q90 = np.quantile(errs, [0.1, 0.9])
        low, high = value * (1 + min(0.0, q10)), value * (1 + max(0.0, q90))
    else:
        low, high = value * 0.75, value * 1.25
    pct = [abs(a - p) / a for a, p in pairs if a > 0]
    f.status = "ready"
    f.value, f.low, f.high = round(value), round(max(0.0, low)), round(high)
    f.model, f.model_label = best, MODEL_LABEL[best]
    f.accuracy = round(float(np.mean(pct)), 3) if pct else None
    f.backtest_days = len(pairs)
    f.beats_baseline = best != "naive" and maes[best] < maes["naive"]
    typical = weekday_typical(hist, target.day)
    f.typical = round(typical) if typical else None
    f.reasons = _reasons(hist, target, best)
    if not festivals.covers(target.day):
        f.notes.append("Festival dates aren't known this far ahead yet.")
    fest = festivals.festival_on(target.day) or festivals.eve_of(target.day)
    if fest and not any(festivals.festival_on(d.day) for d in hist):
        f.notes.append(f"{fest} is close, and there's no festival in your history yet, so the forecast can't "
                       "account for it. Festivals usually change sales a lot.")
    return f
