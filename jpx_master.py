# -*- coding: utf-8 -*-
"""
JPX（日本取引所グループ）が公開している「東証上場銘柄一覧」を取得し、
銘柄コード -> 銘柄名・市場区分・業種 のマスタ情報を提供する。

配布元:
  https://www.jpx.co.jp/markets/statistics-equities/misc/01.html
  （ファイル名 data_j.xls、月次更新）

ローカルにキャッシュし、CACHE_MAX_AGE_DAYS を超えたら再取得する。
"""
import io
import time
import urllib.request
from pathlib import Path

import pandas as pd

JPX_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls"
HERE = Path(__file__).parent
CACHE_PATH = HERE / "jpx_master_cache.xls"
CACHE_MAX_AGE_DAYS = 7

COLUMNS = [
    "date", "code", "name", "market",
    "sector33_code", "sector33", "sector17_code", "sector17",
    "scale_code", "scale",
]

PRIME_DOMESTIC = "プライム（内国株式）"


def _download(dest):
    req = urllib.request.Request(JPX_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        dest.write_bytes(resp.read())


def _ensure_cache():
    if CACHE_PATH.exists():
        age_days = (time.time() - CACHE_PATH.stat().st_mtime) / 86400
        if age_days < CACHE_MAX_AGE_DAYS:
            return
    print("JPX上場銘柄一覧を取得しています...")
    _download(CACHE_PATH)


def load_master(force_refresh=False):
    if force_refresh and CACHE_PATH.exists():
        CACHE_PATH.unlink()
    _ensure_cache()
    df = pd.read_excel(CACHE_PATH, dtype={1: str})
    df.columns = COLUMNS
    return df


def get_prime_domestic(force_refresh=False):
    df = load_master(force_refresh=force_refresh)
    return df[df["market"] == PRIME_DOMESTIC].reset_index(drop=True)


def get_master_dict(force_refresh=False):
    """{code: {"name":..., "market":..., "sector33":..., "sector17":...}}"""
    df = load_master(force_refresh=force_refresh)
    out = {}
    for _, row in df.iterrows():
        out[row["code"]] = {
            "name": row["name"],
            "market": row["market"],
            "sector33": row["sector33"],
            "sector17": row["sector17"],
        }
    return out


if __name__ == "__main__":
    prime = get_prime_domestic()
    print(f"プライム（内国株式）: {len(prime)}銘柄")
    print(prime[["code", "name", "sector17"]].head(10).to_string())
