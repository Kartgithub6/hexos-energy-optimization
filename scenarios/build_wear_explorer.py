"""
build_wear_explorer.py
======================
Turn the battery-wear results into one self-contained interactive page:
pick a price year, slide the cell value, scrub through the weeks of the year.

Reads, for every tag given:
    results/wear_value_<tag>.csv        (run_wear_value.py)
    results/wear_value_<tag>_soc.json   (run_wear_value.py)
    data/year_<tag>.csv                 (for the day-ahead price)
and writes
    results/wear_explorer.html          (open it in a browser, or host it,
                                         e.g. with GitHub Pages)

Run the experiments with the same capex list for every year first, e.g.
    python scenarios/run_wear_value.py --data 2024 --capex 50,100,150,200,250,300,350,400
then
    python scenarios/build_wear_explorer.py --tags DE_2019,DE_2024,DE_2024_retail,DE_2025
"""
import _paths  # noqa

import argparse
import base64
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RES = os.path.join(ROOT, "results")
TEMPLATE = os.path.join(os.path.dirname(__file__), "explorer_template.html")
LABEL = {"DE_2019": "2019 · retail", "DE_2024": "2024 · spot-linked",
         "DE_2024_retail": "2024 · retail", "DE_2025": "2025 · spot-linked"}
CASE = {"B  wear-blind": "B", "C  throughput": "C", "D  cycle-depth": "D"}


def b64(arr):
    return base64.b64encode(arr.tobytes()).decode("ascii")


def wholesale_eur_mwh(tag):
    path = os.path.join(ROOT, "data", f"year_{tag}.csv")
    with open(path) as f:
        tariff = next((ln for ln in f if ln.startswith("# tariff")), "")
    df = pd.read_csv(path, comment="#")
    fee = 0.015 if "spot" in tariff else 0.0
    return np.round((df["price_exp"].to_numpy() + fee) * 1000).astype(np.int16)


def one_set(tag):
    rows = pd.read_csv(os.path.join(RES, f"wear_value_{tag}.csv"))
    with open(os.path.join(RES, f"wear_value_{tag}_soc.json")) as f:
        js = json.load(f)
    E = js["meta"]["E_cap"]
    capex = sorted(rows.capex_eur_per_kwh.unique().tolist())
    out_rows = {"B": [], "C": [], "D": []}
    for cx in capex:
        for label, key in CASE.items():
            r = rows[(rows.capex_eur_per_kwh == cx) & (rows.case == label)].iloc[0]
            out_rows[key].append({"gross": round(float(r.gross_saving_eur), 1),
                                  "wear": round(float(r.cycle_wear_eur), 1),
                                  "net": round(float(r.net_value_eur), 1),
                                  "efc": round(float(r.efc_per_year), 1),
                                  "depth": round(float(r.mean_cycle_depth), 3),
                                  "life": round(float(r.years_to_eol), 2)})
    pct = lambda tr: np.clip(np.round(100.0 * np.asarray(tr) / E), 0, 100).astype(np.uint8)
    soc = {"B": b64(pct(js["traces"]["B  wear-blind"]))}
    for cx in capex:
        soc[f"D{cx:g}"] = b64(pct(js["traces"][f"D  cycle-depth @{cx:g}"]))
    hours = len(js["traces"]["B  wear-blind"])
    price = wholesale_eur_mwh(tag)[:hours]
    year = int(tag.split("_")[1])
    return capex, {"label": LABEL.get(tag, tag), "year": year, "hours": hours,
                   "rows": out_rows, "soc": soc, "price": b64(price)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tags", default="DE_2019,DE_2024,DE_2024_retail,DE_2025")
    ap.add_argument("--out", default=os.path.join(RES, "wear_explorer.html"))
    ap.add_argument("--fragment", action="store_true",
                    help="write the page body only (no <html>/<head>), for hosts that add their own")
    a = ap.parse_args()
    tags = [t for t in a.tags.split(",")
            if os.path.exists(os.path.join(RES, f"wear_value_{t}.csv"))]
    if not tags:
        sys.exit("No results/wear_value_<tag>.csv found. Run run_wear_value.py first.")
    built = {t: one_set(t) for t in tags}
    capex = max((cx for cx, _ in built.values()), key=len)     # the fullest sweep is the reference
    short = [t for t, (cx, _) in built.items() if cx != capex]
    if short:
        want = ",".join(f"{c:g}" for c in capex)
        cmds = "\n".join(f"  python scenarios/run_wear_value.py --data {t.replace('DE_', '')} --capex {want}"
                         for t in short)
        sys.exit(f"{', '.join(short)} {'was' if len(short) == 1 else 'were'} run with other cell values "
                 f"than the rest ({want}). Rerun:\n{cmds}")
    sets = {t: s for t, (_, s) in built.items()}
    data = {"capex": [int(c) for c in capex], "order": tags, "sets": sets}
    with open(TEMPLATE, encoding="utf-8") as f:
        page = f.read().replace("/*DATA*/null", json.dumps(data, separators=(",", ":")))
    if not a.fragment:
        page = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
                '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                '</head>\n<body>\n' + page + '\n</body>\n</html>\n')
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"wrote {a.out} ({len(page)/1e6:.2f} MB) with {', '.join(tags)}")


if __name__ == "__main__":
    main()
