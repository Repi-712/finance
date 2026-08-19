# -*- coding: utf-8 -*-
"""
証券会社/株価配信サイトからダウンロードしたCSVを読み込む。

対応フォーマット:
  A) 銘柄ごとに1ファイル（例: 7203.csv, 7203_トヨタ自動車.csv）
     ヘッダー例: 日付,始値,高値,安値,終値,出来高
  B) 全銘柄が1ファイルにまとまったロング形式
     ヘッダー例: 銘柄コード,銘柄名,日付,始値,高値,安値,終値,出来高

列名は日本語/英語どちらでもある程度自動判定する。
実際のファイルで列名が一致しない場合は HEADER_ALIASES に追記して調整する。
"""
import csv
import io
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HEADER_ALIASES = {
    "code": ["銘柄コード", "コード", "code", "symbol", "ticker"],
    "name": ["銘柄名", "名称", "name"],
    "date": ["日付", "年月日", "date"],
    "open": ["始値", "open"],
    "high": ["高値", "high"],
    "low": ["安値", "low"],
    "close": ["終値", "調整後終値", "close", "adj close"],
    "volume": ["出来高", "volume"],
}

DATE_FORMATS = ["%Y/%m/%d", "%Y-%m-%d", "%Y%m%d"]


class Bar:
    __slots__ = ("date", "open", "high", "low", "close", "volume")

    def __init__(self, date, o, h, l, c, v):
        self.date = date
        self.open = o
        self.high = h
        self.low = l
        self.close = c
        self.volume = v


class Series:
    def __init__(self, code, name):
        self.code = code
        self.name = name
        self.bars = []

    def sorted_bars(self):
        return sorted(self.bars, key=lambda b: b.date)

    @property
    def closes(self):
        return [b.close for b in self.sorted_bars()]

    @property
    def volumes(self):
        return [b.volume for b in self.sorted_bars()]

    @property
    def dates(self):
        return [b.date for b in self.sorted_bars()]


def _parse_date(s):
    s = s.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"日付を解釈できません: {s!r}")


def _parse_float(s):
    if s is None:
        return None
    s = str(s).strip().replace(",", "")
    if s in ("", "-", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _map_header(header):
    lower = [h.strip().lower() for h in header]
    idx = {}
    for field, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            alias_l = alias.lower()
            for i, h in enumerate(lower):
                if h == alias_l:
                    idx[field] = i
                    break
            if field in idx:
                break
    return idx


CODE_FROM_FILENAME = re.compile(r"^([0-9A-Za-z]{3,5})")


def _code_name_from_filename(path):
    stem = path.stem
    m = CODE_FROM_FILENAME.match(stem)
    code = m.group(1) if m else stem
    name = stem[len(code):].lstrip("_- ") or code
    return code, name


def load_price_data(dir_path):
    """
    dir_path 以下の *.csv を読み込み、{code: Series} を返す。
    """
    dir_path = Path(dir_path)
    series_by_code = {}

    csv_files = sorted(dir_path.glob("*.csv"))
    for path in csv_files:
        with io.open(path, encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                continue
            idx = _map_header(header)
            if "date" not in idx or "close" not in idx:
                continue  # 想定フォーマット外のCSVはスキップ

            is_bulk = "code" in idx

            for row in reader:
                if not row or len(row) <= idx["date"]:
                    continue
                try:
                    d = _parse_date(row[idx["date"]])
                except ValueError:
                    continue
                o = _parse_float(row[idx["open"]]) if "open" in idx else None
                h = _parse_float(row[idx["high"]]) if "high" in idx else None
                l = _parse_float(row[idx["low"]]) if "low" in idx else None
                c = _parse_float(row[idx["close"]])
                v = _parse_float(row[idx["volume"]]) if "volume" in idx else None
                if c is None:
                    continue

                if is_bulk:
                    code = row[idx["code"]].strip()
                    name = row[idx["name"]].strip() if "name" in idx else code
                else:
                    code, name = _code_name_from_filename(path)

                if code not in series_by_code:
                    series_by_code[code] = Series(code, name)
                series_by_code[code].bars.append(Bar(d, o, h, l, c, v))

    return series_by_code
