# -*- coding: utf-8 -*-
"""
Yahoo Finance（yfinance）から東証銘柄の日足OHLCVを取得し、
price_data/ フォルダに screener.py が読める形式のCSVで保存する。

証券会社のAPIやログインは不要（無料・無登録）。

事前準備:
  pip install yfinance pandas

銘柄リストの指定方法（優先順）:
  - screening/codes.csv があればそれを使う（1列目に銘柄コード。例: 7203 でも 72030 でも可）
  - なければ JPX上場銘柄一覧から東証プライム（内国株式）全銘柄を自動取得（約1560銘柄）
  - JPXの一覧が取得できない場合のみ ../TradingHistory_20260819.csv の銘柄で代用

使い方:
  python yahoo_fetch.py               # プライム全銘柄（またはcodes.csv）を取得
  python yahoo_fetch.py --days 180    # 遡る日数を変更（デフォルト120暦日）
  python yahoo_fetch.py --chunk-size 200  # 1回のリクエストで束ねる銘柄数
"""
import argparse
import csv
import io
import sys
import time
from pathlib import Path

try:
    import yfinance as yf
except ImportError:
    print("yfinance がインストールされていません。次を実行してください:")
    print("  pip install yfinance")
    sys.exit(1)

import jpx_master

HERE = Path(__file__).parent
PRICE_DIR = HERE / "price_data"
CODES_FILE = HERE / "codes.csv"
TRADING_HISTORY = HERE.parent / "TradingHistory_20260819.csv"

CHUNK_PAUSE_SEC = 1.0  # チャンク間の小休止（サーバーへの配慮）


def normalize_code(code):
    """
    証券会社CSVの銘柄コードは5桁（実コード4桁+末尾パディング"0"）で
    出力される場合がある（例: "83060"→実コード"8306"、"285A0"→"285A"）。
    Yahoo Financeのティッカーは実コード + ".T" の形式。
    """
    code = code.strip().upper()
    if len(code) == 5 and code.endswith("0"):
        code = code[:4]
    return code


def load_codes_from_trading_history(path):
    codes = set()
    with io.open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        next(reader, None)  # header
        for row in reader:
            if len(row) > 2 and row[2].strip():
                codes.add(normalize_code(row[2].strip()))
    return sorted(codes)


def load_codes_from_file(path):
    codes = []
    with io.open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or not row[0].strip():
                continue
            first = row[0].strip()
            if first.lower().startswith("code") or "銘柄" in first:
                continue  # ヘッダー行はスキップ
            codes.append(normalize_code(first))
    return codes


def resolve_codes():
    if CODES_FILE.exists():
        print(f"{CODES_FILE.name} から銘柄リストを読み込みます")
        return load_codes_from_file(CODES_FILE)

    try:
        prime = jpx_master.get_prime_domestic()
        print(f"東証プライム（内国株式）全銘柄を対象にします: {len(prime)}銘柄")
        return sorted(prime["code"].tolist())
    except Exception as e:
        print("JPX上場銘柄一覧の取得に失敗しました:", e)

    if TRADING_HISTORY.exists():
        print(f"代わりに {TRADING_HISTORY.name} から取引実績のある銘柄を抽出します")
        return load_codes_from_trading_history(TRADING_HISTORY)

    print("銘柄リストが見つかりません。screening/codes.csv を用意してください。")
    sys.exit(1)


def save_series(code, sub_df):
    sub_df = sub_df.dropna()
    if sub_df.empty:
        return 0
    out_path = PRICE_DIR / f"{code}.csv"
    with io.open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["日付", "始値", "高値", "安値", "終値", "出来高"])
        for date, row in sub_df.iterrows():
            date_s = date.strftime("%Y/%m/%d")
            writer.writerow([
                date_s,
                round(float(row["Open"]), 2),
                round(float(row["High"]), 2),
                round(float(row["Low"]), 2),
                round(float(row["Close"]), 2),
                int(row["Volume"]),
            ])
    return len(sub_df)


def fetch_chunk(codes, days):
    tickers = [f"{c}.T" for c in codes]
    df = yf.download(
        tickers, period=f"{days}d", interval="1d",
        group_by="ticker", threads=True, progress=False, auto_adjust=False,
    )
    ok, failed = 0, []
    for code, ticker in zip(codes, tickers):
        try:
            sub = df[ticker] if len(tickers) > 1 else df
            n = save_series(code, sub)
        except Exception:
            n = 0
        if n > 0:
            ok += 1
        else:
            failed.append(ticker)
    return ok, failed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=120, help="何暦日前まで遡って取得するか（デフォルト120）")
    parser.add_argument("--chunk-size", type=int, default=250, help="1回のリクエストで束ねる銘柄数（デフォルト250）")
    args = parser.parse_args()

    PRICE_DIR.mkdir(exist_ok=True)

    codes = resolve_codes()
    print(f"取得対象: {len(codes)}銘柄 / {args.days}日分")

    total_ok, total_failed = 0, []
    chunks = [codes[i:i + args.chunk_size] for i in range(0, len(codes), args.chunk_size)]
    for i, chunk in enumerate(chunks, 1):
        ok, failed = fetch_chunk(chunk, args.days)
        total_ok += ok
        total_failed.extend(failed)
        print(f"[chunk {i}/{len(chunks)}] {ok}/{len(chunk)}件 成功")
        if i < len(chunks):
            time.sleep(CHUNK_PAUSE_SEC)

    print(f"完了: 成功{total_ok}件 / 失敗{len(total_failed)}件 → {PRICE_DIR}")
    if total_failed:
        preview = ", ".join(total_failed[:20])
        more = f" 他{len(total_failed)-20}件" if len(total_failed) > 20 else ""
        print(f"取得失敗（データなし・上場廃止等の可能性）: {preview}{more}")
    print("続けて screener.py を実行するとスクリーニングレポートが生成されます。")


if __name__ == "__main__":
    main()
