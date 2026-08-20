# -*- coding: utf-8 -*-
"""
J-Quants API v2（JPX公式の株価データAPI、x-api-keyヘッダー認証）クライアント。

認証情報は screening/jquants_credentials.json に保存する（.gitignore対象、
絶対にリポジトリにコミットしないこと）。
形式:
  {"api_key": "あなたのAPIキー"}

APIキーの取得方法: jpx-jquants.com にログイン → 設定 » APIキー → 発行
（Googleログインのアカウントでも、APIキー方式ならメール/パスワード不要）
"""
import json
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).parent
CRED_PATH = HERE / "jquants_credentials.json"

BASE_URL = "https://api.jquants.com/v2"


def has_credentials():
    return CRED_PATH.exists()


def _load_api_key():
    if not CRED_PATH.exists():
        print(f"認証情報ファイルが見つかりません: {CRED_PATH}")
        print('次の内容のJSONファイルを作成してください: {"api_key": "..."}')
        print("APIキーは jpx-jquants.com にログイン後、設定 » APIキー から発行できます。")
        sys.exit(1)
    creds = json.loads(CRED_PATH.read_text(encoding="utf-8"))
    return creds["api_key"]


def _get_paginated(path, params):
    api_key = _load_api_key()
    headers = {"x-api-key": api_key}
    items = []
    params = dict(params)
    while True:
        r = requests.get(f"{BASE_URL}{path}", headers=headers, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        items.extend(data.get("data", []))
        pagination_key = data.get("pagination_key")
        if not pagination_key:
            break
        params["pagination_key"] = pagination_key
        time.sleep(0.2)
    return items


def normalize_code(code):
    """v2 APIは銘柄コードを5桁（実コード4桁+末尾0）で返すことがあるため4桁に丸める"""
    code = str(code).strip().upper()
    if len(code) == 5 and code.endswith("0"):
        code = code[:4]
    return code


def get_daily_bars_by_date(date_str):
    """date_str: 'YYYY-MM-DD'. その日の全銘柄の四本値を返す（休場日は空リスト）。"""
    return _get_paginated("/equities/bars/daily", {"date": date_str})


def get_master(date_str=None):
    """全上場銘柄の基本情報（銘柄名・市場区分・業種）を返す。"""
    params = {"date": date_str} if date_str else {}
    return _get_paginated("/equities/master", params)


def get_master_dict(date_str=None):
    """{code(4桁): {"name":..., "market":..., "sector33":..., "sector17":...}}"""
    info = get_master(date_str)
    out = {}
    for item in info:
        code = normalize_code(item["Code"])
        out[code] = {
            "name": item.get("CoName"),
            "market": item.get("MktNm"),
            "sector33": item.get("S33Nm"),
            "sector17": item.get("S17Nm"),
        }
    return out


def get_prime_codes(date_str=None):
    info = get_master(date_str)
    return sorted({
        normalize_code(item["Code"]) for item in info
        if item.get("MktNm") and "プライム" in item["MktNm"]
    })
