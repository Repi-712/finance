# -*- coding: utf-8 -*-
"""
J-Quants API v2 から東証プライム銘柄の日足OHLCVを取得し、
price_data/ フォルダに screener.py が読める形式のCSVで保存する。

Yahoo Financeと違い、正式確定した終値を取得できる
（J-Quants Lightプランでは引け後16:30頃に当日分が配信される）。

事前準備:
  pip install requests
  screening/jquants_credentials.json を用意する（.gitignore対象、詳細は jquants_client.py 参照）

銘柄リストの指定方法（優先順）:
  - screening/codes.csv があればそれを使う
  - なければ J-Quants の /equities/master から東証プライム全銘柄を自動取得し、
    codes.csv として保存する

使い方:
  python jquants_fetch.py               # プライム全銘柄（またはcodes.csv）を取得
  python jquants_fetch.py --days 120    # 遡る日数を変更（デフォルト120暦日）
"""
import argparse
import csv
import io
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import jquants_client as jq

HERE = Path(__file__).parent
PRICE_DIR = HERE / "price_data"
CODES_FILE = HERE / "codes.csv"


def load_codes_from_file(path):
    codes = []
    with io.open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or not row[0].strip():
                continue
            first = row[0].strip()
            if first.lower().startswith("code") or "銘柄" in first:
                continue
            codes.append(jq.normalize_code(first))
    return codes


def resolve_codes():
    if CODES_FILE.exists():
        print(f"{CODES_FILE.name} から銘柄リストを読み込みます")
        return set(load_codes_from_file(CODES_FILE))

    print("codes.csv が無いため、J-Quantsからプライム全銘柄を取得して作成します...")
    codes = jq.get_prime_codes()
    with io.open(CODES_FILE, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["code"])
        for c in codes:
            writer.writerow([c])
    print(f"{len(codes)}銘柄を {CODES_FILE.name} に保存しました")
    return set(codes)


def save_series(code, rows):
    rows = sorted(rows, key=lambda r: r["Date"])
    out_path = PRICE_DIR / f"{code}.csv"
    with io.open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["日付", "始値", "高値", "安値", "終値", "出来高"])
        for r in rows:
            date_s = r["Date"].replace("-", "/")
            writer.writerow([date_s, r["O"], r["H"], r["L"], r["C"], r["Vo"]])
    return len(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=120, help="何暦日前まで遡って取得するか（デフォルト120）")
    args = parser.parse_args()

    PRICE_DIR.mkdir(exist_ok=True)

    if not jq.has_credentials():
        print(f"認証情報ファイルが見つかりません: {jq.CRED_PATH}")
        sys.exit(1)

    codes = resolve_codes()
    print(f"取得対象: {len(codes)}銘柄")

    by_code = defaultdict(list)
    end = datetime.now()
    start = end - timedelta(days=args.days)
    d = start
    n_days_queried = 0
    n_days_with_data = 0
    while d <= end:
        if d.weekday() < 5:  # 平日のみ問い合わせ（土日はスキップ）
            date_str = d.strftime("%Y-%m-%d")
            try:
                bars = jq.get_daily_bars_by_date(date_str)
            except Exception as e:
                print(f"  {date_str}: 取得エラー ({e})、スキップ")
                d += timedelta(days=1)
                continue
            n_days_queried += 1
            if bars:
                n_days_with_data += 1
            for b in bars:
                code = jq.normalize_code(b.get("Code", ""))
                if code in codes and b.get("C") is not None:
                    b["Code"] = code
                    by_code[code].append(b)
        d += timedelta(days=1)

    print(f"営業日照会: {n_days_queried}日中 {n_days_with_data}日に取引データあり")

    ok = 0
    for code, rows in by_code.items():
        if save_series(code, rows) > 0:
            ok += 1

    print(f"完了: {ok}/{len(codes)}銘柄 分のデータを保存 → {PRICE_DIR}")
    if ok < len(codes):
        missing = len(codes) - ok
        print(f"（{missing}銘柄は期間中データが取得できませんでした。新規上場・休業等の可能性）")
    print("続けて screener.py を実行するとスクリーニングレポートが生成されます。")


if __name__ == "__main__":
    main()
