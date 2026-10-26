"""
derive_tariff_variant.py
========================
Build the retail-tariff version of a year file from its spot-linked version,
without calling Energy-Charts again.

Why derive instead of re-downloading: a tariff comparison should change ONE
thing. Pulling the year twice risks small upstream revisions between pulls.
Deriving guarantees that PV, demand, heat, COP and the wholesale price are
identical, and only the tariff differs.

The spot file stores   import = wholesale + fee,  export = wholesale - fee
The retail file stores import = wholesale + markup, export = wholesale
(the same rules prepare_year_ec.py applies), so the wholesale price is
recovered exactly and the retail prices are rebuilt from it.

Run:
    python scenarios/derive_tariff_variant.py --data 2024
    -> writes data/year_DE_2024_retail.csv
"""
import _paths  # noqa

import argparse
import os
import re
import sys

import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(ROOT, "data")
IMPORT_MARKUP_EUR_KWH = 0.12   # must match prepare_year_ec.py


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="2024", help="year of the spot file")
    args = ap.parse_args()

    src = os.path.join(DATA_DIR, f"year_DE_{args.data}.csv")
    if not os.path.isfile(src):
        sys.exit(f"Missing {src}")
    with open(src) as f:
        header = [ln for ln in f if ln.startswith("#")]

    tariff = next((ln for ln in header if ln.startswith("# tariff")), "")
    m = re.search(r"\+/-([0-9.]+) EUR/kWh", tariff)
    if "spot" not in tariff or not m:
        sys.exit(f"{os.path.basename(src)} is not a spot-linked file "
                 f"(tariff line: {tariff.strip() or 'missing'}). Nothing to derive.")
    fee = float(m.group(1))

    df = pd.read_csv(src, comment="#")
    wholesale = df["price_el"] - fee
    mismatch = (wholesale - (df["price_exp"] + fee)).abs().max()
    if mismatch > 1e-5:
        sys.exit(f"Import and export prices disagree on the wholesale price "
                 f"(max {mismatch:.2e} EUR/kWh). Not a clean spot file.")

    df["price_el"] = (wholesale + IMPORT_MARKUP_EUR_KWH).round(6)
    df["price_exp"] = wholesale.round(6)

    out = os.path.join(DATA_DIR, f"year_DE_{args.data}_retail.csv")
    new_header = []
    for ln in header:
        if ln.startswith("# tariff"):
            ln = (f"# tariff : retail: +{IMPORT_MARKUP_EUR_KWH} EUR/kWh import "
                  f"markup, export at wholesale\n"
                  f"# derived: from {os.path.basename(src)}; every column except "
                  f"the two prices is identical\n")
        new_header.append(ln)
    with open(out, "w", newline="") as f:
        f.writelines(new_header)
        df.to_csv(f, index=False)

    print(f"Recovered wholesale prices from {os.path.basename(src)} "
          f"(spot fee {fee} EUR/kWh, consistency {mismatch:.1e})")
    print(f"Wrote {out}")
    print(f"\nNext: python scenarios/run_baselines.py --data {args.data}_retail")


if __name__ == "__main__":
    main()
