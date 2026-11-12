"""Train and evaluate the demand forecast. Run as a separate command, never inside an HTTP request.

    python train_forecast.py --db data/qaldyq-v5.4.sqlite3            # explore, compare methods, save the chosen version
    python train_forecast.py --db data/qaldyq-v5.4.sqlite3 --explore  # only describe the data

The three methods are compared on the last dates of the history (all rows of a date on one side of the split).
The method with the smallest error in portions becomes active; machine learning is not assumed to be better."""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import forecast_core as core
import mod_forecast
from server import connect, initialize


def train(db_path, org_id=None, explore_only=False, out=print):
    initialize(db_path)
    with connect(db_path) as db:
        history, context = core.load_history(db, org_id), core.load_context(db)
        exploration = core.explore(history, context)
        out("Дерек шолуы / Обзор данных:")
        out(json.dumps(exploration, ensure_ascii=False, indent=2))
        if explore_only or not history:
            return {"exploration": exploration}
        try:
            import sklearn
            with_ml, library = True, f"scikit-learn {sklearn.__version__}"
        except ImportError:
            with_ml, library = False, None
            out("scikit-learn орнатылмаған: тек статистикалық әдістер салыстырылады.")
        result = core.evaluate(core.build_dataset(history, context), with_ml)
        model, params = result.pop("model", None), result.pop("params", None)
        if result["status"] != "ok":
            out(result["reason"])
            return {"exploration": exploration, "report": result}
        result["library"], result["synthetic_share"] = library, exploration["synthetic_share"]
        if exploration["synthetic_share"] > 0:
            result["warning"] = "Оқыту дерегінде синтетикалық (демо) жазбалар бар: көрсеткіштер нақты пайдалануды сипаттамайды."
        version = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        file, digest = None, None
        if result["chosen"] == "ml":
            import joblib
            mod_forecast.MODEL_DIR.mkdir(parents=True, exist_ok=True)
            file = f"forecast-{version}.joblib"
            joblib.dump(model, mod_forecast.MODEL_DIR / file)
            digest = hashlib.sha256((mod_forecast.MODEL_DIR / file).read_bytes()).hexdigest()
        db.execute("UPDATE forecast_models SET active=0")
        db.execute("INSERT INTO forecast_models(version,chosen,params,report,exploration,file,sha256,active,created_at) VALUES (?,?,?,?,?,?,?,1,?)",
                   (version, result["chosen"], json.dumps(params or {}), json.dumps(result, ensure_ascii=False), json.dumps(exploration, ensure_ascii=False), file, digest,
                    datetime.now(timezone.utc).isoformat(timespec="seconds")))
        out(f"\nТексеру кезеңі / Проверочный период: {result['test_start']} … {result['test_end']} (оқыту / обучение: {result['train_start']} … {result['train_end']})")
        for name, metrics in result["methods"].items():
            out(f"  {name:9} {json.dumps(metrics, ensure_ascii=False)}")
        if result.get("ml_note"):
            out("  " + result["ml_note"])
        out(f"Таңдалған әдіс / Выбранный метод: {result['chosen']} · нұсқа / версия: {version}")
        if result.get("warning"):
            out(result["warning"])
        return {"exploration": exploration, "report": result, "version": version}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Qaldyq demand forecast: explore, evaluate, save")
    parser.add_argument("--db", default=str(Path(__file__).resolve().parent / "data" / "qaldyq-v5.4.sqlite3"))
    parser.add_argument("--org", type=int, default=None)
    parser.add_argument("--explore", action="store_true")
    args = parser.parse_args()
    sys.exit(0 if train(args.db, args.org, args.explore) else 1)
