"""Demand forecasting core: dataset, methods, time-based validation (ТТ 17).

Unit of analysis: canteen × dish × date.
Target: total demand in portions for that day, measured as registered sales (pre-orders included).
Confirmed pre-orders are a feature and a floor for the suggestion; they are never added on top of the forecast.
Every feature of a row uses only days before that row's date and only pre-orders that existed at the forecast moment.
Days when a dish ran out early are censored: sales there are a lower bound of demand, so they are kept out of
the error metrics and out of the training target."""
import math
import statistics
from datetime import date, datetime, timedelta

FEATURES = ("weekday", "event", "price", "available", "preorders", "last", "mean7", "mean28", "weekday_mean", "weekday_last", "history_days", "cancel_rate", "shortage_rate")
MIN_ML_DATES, MIN_ML_ROWS, MIN_HISTORY = 28, 200, 3


def load_history(db, org_id=None):
    """Daily demand per canteen and dish, with what limits each observation."""
    where, args = ("WHERE s.org_id=?", (org_id,)) if org_id else ("", ())
    rows = {}
    for r in db.execute(f"SELECT s.org_id,s.dish_id,s.day,SUM(s.qty) AS qty,MIN(s.price_tiyn) AS price,MAX(COALESCE(s.is_demo,0)) AS demo FROM sales s {where} GROUP BY s.org_id,s.dish_id,s.day", args):
        rows[(r["org_id"], r["dish_id"], r["day"])] = {"org_id": r["org_id"], "dish_id": r["dish_id"], "day": r["day"], "sold": r["qty"], "price": r["price"] / 100, "synthetic": bool(r["demo"]), "censored": False, "available": None}
    for r in db.execute("SELECT org_id,dish_id,day FROM shortages"):
        if (r["org_id"], r["dish_id"], r["day"]) in rows:
            rows[(r["org_id"], r["dish_id"], r["day"])]["censored"] = True
    for r in db.execute("SELECT m.org_id,mi.dish_id,m.day,SUM(mi.available) AS n FROM menu_items mi JOIN menu_days m ON m.id=mi.menu_id GROUP BY m.org_id,mi.dish_id,m.day"):
        if (r["org_id"], r["dish_id"], r["day"]) in rows:
            rows[(r["org_id"], r["dish_id"], r["day"])]["available"] = r["n"]
    return sorted(rows.values(), key=lambda r: (r["day"], r["org_id"], r["dish_id"]))


def load_context(db):
    events = {r["day"] for r in db.execute("SELECT day FROM calendar_events")}
    orders = [dict(r) for r in db.execute("""SELECT o.org_id,oi.dish_id,o.day,oi.qty,o.status,o.created_at,o.cancelled_at FROM order_items oi JOIN orders o ON o.id=oi.order_id""")]
    return {"events": events, "orders": orders}


def explore(history, context):
    """What the data can and cannot support, before any model is fitted."""
    if not history:
        return {"rows": 0, "note": "Сатылым тарихы жоқ."}
    days = sorted({r["day"] for r in history})
    first, last = date.fromisoformat(days[0]), date.fromisoformat(days[-1])
    expected = sum(1 for i in range((last - first).days + 1) if (first + timedelta(days=i)).weekday() != 6)
    per_dish = {}
    for r in history:
        per_dish.setdefault((r["org_id"], r["dish_id"]), []).append(r)
    by_weekday = {}
    for r in history:
        by_weekday.setdefault(date.fromisoformat(r["day"]).weekday(), []).append(r["sold"])
    return {"rows": len(history), "canteens": len({r["org_id"] for r in history}), "dishes": len(per_dish), "first_day": days[0], "last_day": days[-1], "days_with_sales": len(days),
            "expected_working_days": expected, "missing_days": expected - len(days), "rows_per_dish_min": min(len(v) for v in per_dish.values()), "rows_per_dish_median": statistics.median(len(v) for v in per_dish.values()),
            "weekday_mean": {str(k): round(statistics.mean(v), 1) for k, v in sorted(by_weekday.items())}, "synthetic_share": round(sum(r["synthetic"] for r in history) / len(history), 3),
            "censored_share": round(sum(r["censored"] for r in history) / len(history), 3), "preorder_lines": len(context["orders"]), "known_events": len(context["events"])}


def features_for(series, day, context, org_id, dish_id, cutoff, price=None, available=None):
    """Features for one canteen × dish × date from `series` (that dish's earlier rows) and the forecast moment `cutoff`."""
    target = date.fromisoformat(day)
    past = [r for r in series if r["day"] < day and (target - date.fromisoformat(r["day"])).days <= 56]
    past.sort(key=lambda r: r["day"], reverse=True)
    same = [r["sold"] for r in past if date.fromisoformat(r["day"]).weekday() == target.weekday()]
    values = [r["sold"] for r in past]
    recent28 = [r for r in past if (target - date.fromisoformat(r["day"])).days <= 28]
    orders = [o for o in context["orders"] if o["org_id"] == org_id and o["dish_id"] == dish_id]
    # Pre-orders count only if they existed at the forecast moment and were not cancelled before it.
    known = sum(o["qty"] for o in orders if o["day"] == day and o["created_at"] <= cutoff and not (o["status"] == "cancelled" and (o["cancelled_at"] or "") <= cutoff))
    earlier = [o for o in orders if o["day"] < day]
    lost = sum(o["qty"] for o in earlier if o["status"] in ("cancelled", "no_show"))
    nan = float("nan")
    return {"weekday": target.weekday(), "event": 1 if day in context["events"] else 0, "price": price if price is not None else (past[0]["price"] if past else nan),
            # -1 marks "no published limit": a column that is unknown in every row cannot be binned by the model
            "available": available if available is not None else -1, "preorders": known, "last": values[0] if values else nan,
            "mean7": statistics.mean(values[:7]) if values else nan, "mean28": statistics.mean(r["sold"] for r in recent28) if recent28 else nan,
            "weekday_mean": statistics.mean(same[:8]) if same else nan, "weekday_last": same[0] if same else nan, "history_days": len(past),
            "cancel_rate": lost / sum(o["qty"] for o in earlier) if earlier else 0.0, "shortage_rate": sum(r["censored"] for r in recent28) / len(recent28) if recent28 else 0.0,
            "_same": same, "_values": values}


def build_dataset(history, context):
    """One row per observed canteen × dish × date. The forecast moment of a historical row is the evening before."""
    by_dish = {}
    for r in history:
        by_dish.setdefault((r["org_id"], r["dish_id"]), []).append(r)
    dataset = []
    for (org_id, dish_id), series in by_dish.items():
        for r in series:
            cutoff = (datetime.fromisoformat(r["day"]) - timedelta(hours=6)).isoformat()
            f = features_for(series, r["day"], context, org_id, dish_id, cutoff, r["price"], r["available"])
            dataset.append({**r, "features": f})
    return sorted(dataset, key=lambda r: (r["day"], r["org_id"], r["dish_id"]))


def existing_rule(f):
    """The rule already used in Qaldyq: median of the same weekday (3+ days), otherwise of the latest days."""
    sample = f["_same"][:8] if len(f["_same"]) >= MIN_HISTORY else f["_values"][:8]
    return float(statistics.median(sample)) if len(sample) >= MIN_HISTORY else None


def weekday_seasonal(f):
    sample = f["_same"][:8] or f["_values"][:8]
    return float(statistics.mean(sample)) if len(sample) >= MIN_HISTORY else None


def vector(f):
    return [f[name] for name in FEATURES]


def split_by_date(dataset, test_share=0.2, minimum=14):
    """Train and test are separated by date: every row of one date is on the same side."""
    days = sorted({r["day"] for r in dataset})
    size = max(minimum, math.ceil(len(days) * test_share))
    if len(days) - size < minimum:
        return None
    border = days[-size]
    return [r for r in dataset if r["day"] < border], [r for r in dataset if r["day"] >= border], border


def score(pairs):
    """Errors in portions over uncensored rows: mean absolute error, bias, over-production and shortage."""
    pairs = [(p, a) for p, a in pairs if p is not None]
    if not pairs:
        return None
    errors = [p - a for p, a in pairs]
    return {"rows": len(pairs), "mae": round(statistics.mean(abs(e) for e in errors), 2), "bias": round(statistics.mean(errors), 2),
            "overproduction": round(sum(max(e, 0) for e in errors), 1), "shortage": round(sum(max(-e, 0) for e in errors), 1)}


def fit_ml(train, random_state=7):
    """Gradient boosting on training dates only. The depth is chosen on the last fifth of the training dates,
    never on the test period; then the model is refitted on all training rows."""
    from sklearn.ensemble import HistGradientBoostingRegressor
    rows = [r for r in train if not r["censored"] and r["features"]["history_days"] >= MIN_HISTORY]
    days = sorted({r["day"] for r in rows})
    inner = days[-max(7, len(days) // 5)]
    fit_part, check_part = [r for r in rows if r["day"] < inner], [r for r in rows if r["day"] >= inner]
    best = None
    for depth in (2, 3):
        model = HistGradientBoostingRegressor(max_depth=depth, max_iter=150, learning_rate=0.06, min_samples_leaf=10, l2_regularization=1.0, random_state=random_state)
        model.fit([vector(r["features"]) for r in fit_part], [r["sold"] for r in fit_part])
        error = statistics.mean(abs(p - r["sold"]) for p, r in zip(model.predict([vector(r["features"]) for r in check_part]), check_part))
        if best is None or error < best[0]:
            best = (error, depth)
    model = HistGradientBoostingRegressor(max_depth=best[1], max_iter=150, learning_rate=0.06, min_samples_leaf=10, l2_regularization=1.0, random_state=random_state)
    model.fit([vector(r["features"]) for r in rows], [r["sold"] for r in rows])
    return model, {"max_depth": best[1], "max_iter": 150, "learning_rate": 0.06, "min_samples_leaf": 10, "l2_regularization": 1.0, "random_state": random_state,
                   "inner_validation_from": inner, "rows_fit": len(rows)}


def evaluate(dataset, with_ml=True):
    """Compare the three methods on the test period and pick the one with the smallest error in portions."""
    parts = split_by_date(dataset)
    if not parts:
        return {"status": "insufficient", "reason": "Тексеруге күн жеткіліксіз: оқыту мен тексеруге кемінде 14 күннен қажет."}
    train, test, border = parts
    usable = [r for r in test if not r["censored"]]
    report = {"status": "ok", "train_start": train[0]["day"], "train_end": train[-1]["day"], "test_start": border, "test_end": test[-1]["day"], "rows_train": len(train), "rows_test": len(test),
              "censored_excluded": len(test) - len(usable), "methods": {}}
    report["methods"]["existing"] = score([(existing_rule(r["features"]), r["sold"]) for r in usable])
    report["methods"]["weekday"] = score([(weekday_seasonal(r["features"]), r["sold"]) for r in usable])
    model, params = None, None
    train_days = len({r["day"] for r in train})
    if not with_ml:
        report["ml_note"] = "ML бағаланбады: scikit-learn орнатылмаған немесе өшірілген."
    elif train_days < MIN_ML_DATES or len(train) < MIN_ML_ROWS:
        report["ml_note"] = f"ML бағаланбады: оқытуға {train_days} күн, {len(train)} жол бар (кемінде {MIN_ML_DATES} күн, {MIN_ML_ROWS} жол қажет)."
    else:
        model, params = fit_ml(train)
        scored = [r for r in usable if r["features"]["history_days"] >= MIN_HISTORY]
        report["methods"]["ml"] = score(list(zip((max(0.0, float(p)) for p in model.predict([vector(r["features"]) for r in scored])), (r["sold"] for r in scored))))
    ranked = sorted(((m["mae"], name) for name, m in report["methods"].items() if m), key=lambda x: (x[0], {"existing": 0, "weekday": 1, "ml": 2}[x[1]]))
    report["chosen"] = ranked[0][1] if ranked else None
    report["interval"] = interval(usable, report["chosen"], model)
    return {**report, "model": model, "params": params}


def predict_one(method, f, model=None):
    if method == "ml" and model is not None and f["history_days"] >= MIN_HISTORY:
        return max(0.0, float(model.predict([vector(f)])[0]))
    return weekday_seasonal(f) if method == "weekday" else existing_rule(f)


def interval(usable, method, model):
    """Empirical 80% interval from residuals on the first half of the test dates; its coverage is then measured on the
    second half. Without enough rows no interval is reported at all."""
    days = sorted({r["day"] for r in usable})
    if not method or len(days) < 8:
        return None
    middle = days[len(days) // 2]
    def residuals(rows):
        return [(r["sold"] - p, r, p) for r in rows for p in [predict_one(method, r["features"], model)] if p is not None]
    calibration, check = residuals([r for r in usable if r["day"] < middle]), residuals([r for r in usable if r["day"] >= middle])
    if len(calibration) < 30 or len(check) < 30:
        return None
    ordered = sorted(e for e, _, _ in calibration)
    low, high = ordered[int(len(ordered) * 0.1)], ordered[min(len(ordered) - 1, int(len(ordered) * 0.9))]
    covered = sum(1 for e, _, _ in check if low <= e <= high)
    return {"low": round(low, 1), "high": round(high, 1), "nominal": 0.8, "coverage": round(covered / len(check), 2), "calibration_rows": len(calibration), "check_rows": len(check)}
