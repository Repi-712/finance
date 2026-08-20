# -*- coding: utf-8 -*-
"""
株価CSV（price_data/ フォルダ）を読み込み、テクニカル条件でスクリーニングして
HTMLレポートを出力する。

使い方:
  1. price_data/ フォルダに証券会社からダウンロードしたCSVを入れる
     （銘柄ごとに1ファイル、または全銘柄まとまったロング形式の1ファイル）
  2. python screener.py を実行
  3. screening_report.html が生成される

シグナル種別:
  - golden_cross / dead_cross : SMA5とSMA25のクロス
  - rsi_oversold / rsi_overbought : RSI(14) が 30以下 / 70以上
  - bb_breakout_up / bb_breakout_down : 終値がボリンジャーバンド(20,2σ)の外側
  - volume_spike : 出来高が直近20日平均の2倍以上
  - price_spike : 前日比騰落率が±5%以上
  - new_high_5d / new_low_5d : 過去5営業日の高値/安値を更新
"""
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import indicators as ind
import jpx_master
import jquants_client
from price_data_loader import load_price_data

HERE = Path(__file__).parent
PRICE_DIR = HERE / "price_data"
OUT_PATH = HERE / "screening_report.html"

RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
VOLUME_MULTIPLIER = 2.0
PRICE_SPIKE_PCT = 5.0
LIQUIDITY_LOOKBACK = 5
NEW_EXTREME_LOOKBACK = 5

YAHOO_JP_URL = "https://finance.yahoo.co.jp/quote/{code}.T"


def screen_symbol(series, master):
    bars = series.sorted_bars()
    if len(bars) < 26:  # SMA25クロス判定に最低限必要な本数
        return []

    closes = [b.close for b in bars]
    volumes = [b.volume for b in bars if b.volume is not None]
    last_date = bars[-1].date
    last_close = closes[-1]

    info = master.get(series.code, {})
    name = info.get("name") or series.name
    sector = info.get("sector17") or "-"

    recent_vol = volumes[-LIQUIDITY_LOOKBACK:] if len(volumes) >= LIQUIDITY_LOOKBACK else volumes
    recent_closes = closes[-LIQUIDITY_LOOKBACK:] if len(closes) >= LIQUIDITY_LOOKBACK else closes
    avg_volume_5d = sum(recent_vol) / len(recent_vol) if recent_vol else None
    avg_turnover_5d = (
        sum(c * v for c, v in zip(recent_closes, recent_vol)) / len(recent_vol)
        if recent_vol else None
    )

    signals = []

    sma5 = ind.sma(closes, 5)
    sma25 = ind.sma(closes, 25)
    cross = ind.cross_signal(sma5, sma25)
    if cross == "golden":
        signals.append(("golden_cross", "SMA5がSMA25を上抜け", None))
    elif cross == "dead":
        signals.append(("dead_cross", "SMA5がSMA25を下抜け", None))

    rsi_vals = ind.rsi(closes, 14)
    last_rsi = rsi_vals[-1]
    if last_rsi is not None:
        if last_rsi <= RSI_OVERSOLD:
            signals.append(("rsi_oversold", f"RSI={last_rsi:.1f}（売られすぎ）", last_rsi))
        elif last_rsi >= RSI_OVERBOUGHT:
            signals.append(("rsi_overbought", f"RSI={last_rsi:.1f}（買われすぎ）", last_rsi))

    mid, upper, lower = ind.bollinger_bands(closes, 20, 2.0)
    if upper[-1] is not None and lower[-1] is not None:
        if last_close > upper[-1]:
            signals.append(("bb_breakout_up", f"終値がBB+2σを上抜け（+{last_close-upper[-1]:.1f}）", last_close - upper[-1]))
        elif last_close < lower[-1]:
            signals.append(("bb_breakout_down", f"終値がBB-2σを下抜け（{last_close-lower[-1]:.1f}）", last_close - lower[-1]))

    if len(volumes) == len(closes):
        vs = ind.volume_spike(volumes, lookback=20, multiplier=VOLUME_MULTIPLIER)
        if vs is not None:
            signals.append(("volume_spike", f"出来高が20日平均の{vs:.1f}倍", vs))

    ps = ind.pct_change_spike(closes, threshold=PRICE_SPIKE_PCT)
    if ps is not None:
        direction = "急騰" if ps > 0 else "急落"
        signals.append(("price_spike", f"前日比{ps:+.1f}%（{direction}）", ps))

    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    if all(h is not None for h in highs):
        nh = ind.new_high(highs, lookback=NEW_EXTREME_LOOKBACK)
        if nh is not None:
            signals.append(("new_high_5d", f"{NEW_EXTREME_LOOKBACK}日高値更新（高値{nh:,.1f}）", nh))
    if all(l is not None for l in lows):
        nl = ind.new_low(lows, lookback=NEW_EXTREME_LOOKBACK)
        if nl is not None:
            signals.append(("new_low_5d", f"{NEW_EXTREME_LOOKBACK}日安値更新（安値{nl:,.1f}）", nl))

    return [
        {
            "code": series.code,
            "name": name,
            "sector": sector,
            "date": last_date,
            "close": last_close,
            "avg_volume_5d": avg_volume_5d,
            "avg_turnover_5d": avg_turnover_5d,
            "signal_type": s_type,
            "detail": detail,
            "value": value,
        }
        for s_type, detail, value in signals
    ]


SIGNAL_LABELS = {
    "golden_cross": ("ゴールデンクロス", "#2f8f4e"),
    "dead_cross": ("デッドクロス", "#c0392b"),
    "rsi_oversold": ("RSI売られすぎ", "#2f8f4e"),
    "rsi_overbought": ("RSI買われすぎ", "#c0392b"),
    "bb_breakout_up": ("BB上抜けブレイク", "#2f8f4e"),
    "bb_breakout_down": ("BB下抜けブレイク", "#c0392b"),
    "volume_spike": ("出来高急増", "#1f6fb2"),
    "price_spike": ("値動き急変", "#a3691a"),
    "new_high_5d": ("5日新高値", "#2f8f4e"),
    "new_low_5d": ("5日新安値", "#c0392b"),
}

SIGNAL_DESCRIPTIONS = {
    "golden_cross": "短期線(SMA5)が中期線(SMA25)を下から上に突き抜けた銘柄。上昇トレンドへの転換を示唆する強気シグナル。",
    "dead_cross": "短期線(SMA5)が中期線(SMA25)を上から下に突き抜けた銘柄。下降トレンドへの転換を示唆する弱気シグナル。",
    "rsi_oversold": "RSI(14日)が30以下まで下落した銘柄。売られすぎで、反発（自律反発）が期待できる可能性がある。",
    "rsi_overbought": "RSI(14日)が70以上まで上昇した銘柄。買われすぎで、目先の反落・利益確定売りに注意。",
    "bb_breakout_up": "終値がボリンジャーバンド(20日,+2σ)の上限を上抜けた銘柄。強い上昇モメンタム・ブレイクアウト。",
    "bb_breakout_down": "終値がボリンジャーバンド(20日,-2σ)の下限を下抜けた銘柄。強い下落モメンタム・ブレイクダウン。",
    "volume_spike": "出来高が直近20日平均の2倍以上に急増した銘柄。ニュースや材料が出て注目度が上がっている可能性。",
    "price_spike": "前日比の値動きが±5%以上あった銘柄。好材料・悪材料による急騰・急落。",
    "new_high_5d": "本日の高値が過去5営業日で最も高い銘柄（直近4日の高値をすべて上回った）。短期的な上昇の勢いが強い。",
    "new_low_5d": "本日の安値が過去5営業日で最も安い銘柄（直近4日の安値をすべて下回った）。短期的な下落の勢いが強い。",
}


def fmt_int(v):
    return "{:,.0f}".format(v) if v is not None else "-"


def fmt_oku(v):
    """円 -> 百万円表記"""
    return "{:,.0f}百万円".format(v / 1_000_000) if v is not None else "-"


def render_html(all_results, n_symbols, latest_date):
    by_type = defaultdict(list)
    for r in all_results:
        by_type[r["signal_type"]].append(r)

    cards = "".join(
        f'<a class="card" href="#sig-{t}"><div class="label">{SIGNAL_LABELS[t][0]}</div>'
        f'<div class="value" style="color:{SIGNAL_LABELS[t][1]}">{len(rows)}銘柄</div></a>'
        for t, rows in sorted(by_type.items(), key=lambda kv: -len(kv[1]))
    )

    sections = []
    for t, rows in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        label, color = SIGNAL_LABELS[t]
        rows_sorted = sorted(rows, key=lambda r: r["code"])
        trs = "".join(
            f"<tr><td data-sort=\"{r['code']}\"><a href=\"{YAHOO_JP_URL.format(code=r['code'])}\" target=\"_blank\" rel=\"noopener\">{r['code']}</a></td>"
            f"<td>{r['name']}</td><td>{r['sector']}</td>"
            f"<td class='num' data-sort=\"{r['close']}\">{r['close']:,.1f}</td>"
            f"<td class='num' data-sort=\"{r['avg_volume_5d'] if r['avg_volume_5d'] is not None else -1}\">{fmt_int(r['avg_volume_5d'])}</td>"
            f"<td class='num' data-sort=\"{r['avg_turnover_5d'] if r['avg_turnover_5d'] is not None else -1}\">{fmt_oku(r['avg_turnover_5d'])}</td>"
            f"<td>{r['detail']}</td></tr>"
            for r in rows_sorted
        )
        desc = SIGNAL_DESCRIPTIONS.get(t, "")
        sections.append(f"""
<h2 id="sig-{t}" style="border-left-color:{color}">{label}（{len(rows)}銘柄）</h2>
<p class="note">{desc}</p>
<table class="sortable">
  <tr><th>コード</th><th>銘柄名</th><th>セクター</th><th>終値</th><th>5日平均出来高</th><th>5日平均売買代金</th><th>詳細</th></tr>
  {trs if trs else "<tr><td colspan='7'>該当なし</td></tr>"}
</table>
""")

    html = f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>東証プライム スクリーニング</title>
<style>
  body {{ font-family: "Segoe UI", "Yu Gothic", sans-serif; margin: 24px; color: #222; background: #fafafa; }}
  h1 {{ font-size: 20px; }}
  h2 {{ font-size: 16px; margin-top: 32px; border-left: 4px solid #2f8f4e; padding-left: 8px; }}
  .cards {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0; }}
  .card {{ display: block; background: #fff; border: 1px solid #ddd; border-radius: 8px; padding: 12px 16px; min-width: 150px; box-shadow: 0 1px 2px rgba(0,0,0,0.05); text-decoration: none; color: inherit; cursor: pointer; transition: box-shadow 0.15s, transform 0.15s; }}
  .card:hover {{ box-shadow: 0 3px 8px rgba(0,0,0,0.12); transform: translateY(-1px); }}
  .card .label {{ font-size: 12px; color: #777; }}
  .card .value {{ font-size: 20px; font-weight: 600; margin-top: 4px; }}
  h2[id] {{ scroll-margin-top: 12px; }}
  table {{ border-collapse: collapse; width: 100%; background: #fff; margin-top: 8px; }}
  th, td {{ border: 1px solid #e0e0e0; padding: 6px 10px; font-size: 13px; }}
  th {{ background: #f0f0f0; text-align: left; }}
  td.num {{ text-align: right; }}
  table tr:nth-child(even) {{ background: #f4f6f5; }}
  table tr:hover td {{ background: #eef3ff; }}
  .note {{ font-size: 12px; color: #888; margin-top: 4px; }}
  table.sortable th {{ cursor: pointer; user-select: none; white-space: nowrap; }}
  table.sortable th:hover {{ background: #e4e4e4; }}
  table.sortable th::after {{ content: ""; display: inline-block; width: 10px; margin-left: 2px; opacity: 0.4; }}
  table.sortable th.sort-asc::after {{ content: "▲"; opacity: 1; }}
  table.sortable th.sort-desc::after {{ content: "▼"; opacity: 1; }}
</style>
</head>
<body>
<h1>スクリーニングレポート</h1>
<p class="note">対象銘柄数: {n_symbols}　最新データ日付: {latest_date.strftime("%Y-%m-%d") if latest_date else "-"}　生成日時: {datetime.now().strftime("%Y-%m-%d %H:%M")}</p>

<h2>シグナル別ヒット数</h2>
<div class="cards">{cards if cards else "<p>該当銘柄なし</p>"}</div>

{"".join(sections)}

<script>
document.querySelectorAll("table.sortable").forEach(function(table) {{
  var headerRow = table.rows[0];
  Array.prototype.forEach.call(headerRow.cells, function(th, colIndex) {{
    th.addEventListener("click", function() {{
      var tbody = table.tBodies[0];
      var rows = Array.prototype.slice.call(table.rows, 1);
      var asc = !th.classList.contains("sort-asc");
      Array.prototype.forEach.call(headerRow.cells, function(h) {{
        h.classList.remove("sort-asc", "sort-desc");
      }});
      th.classList.add(asc ? "sort-asc" : "sort-desc");

      rows.sort(function(r1, r2) {{
        var c1 = r1.cells[colIndex], c2 = r2.cells[colIndex];
        var v1 = c1.getAttribute("data-sort");
        var v2 = c2.getAttribute("data-sort");
        var cmp;
        if (v1 !== null && v2 !== null) {{
          cmp = parseFloat(v1) - parseFloat(v2);
        }} else {{
          cmp = c1.textContent.localeCompare(c2.textContent, "ja");
        }}
        return asc ? cmp : -cmp;
      }});
      rows.forEach(function(row) {{ tbody.appendChild(row); }});
    }});
  }});
}});
</script>
</body>
</html>
"""
    return html


def main():
    if not PRICE_DIR.exists() or not any(PRICE_DIR.glob("*.csv")):
        print(f"price_data フォルダにCSVが見つかりません: {PRICE_DIR}")
        print("証券会社からダウンロードした株価CSVをこのフォルダに入れてから再実行してください。")
        return

    series_by_code = load_price_data(PRICE_DIR)
    if not series_by_code:
        print("CSVは見つかりましたが、列名を認識できませんでした。ヘッダー列名を確認してください。")
        return

    try:
        if jquants_client.has_credentials():
            master = jquants_client.get_master_dict()
        else:
            master = jpx_master.get_master_dict()
    except Exception as e:
        print("銘柄マスタの取得に失敗しました（銘柄名・セクターなしで続行）:", e)
        master = {}

    all_results = []
    latest_date = None
    for series in series_by_code.values():
        results = screen_symbol(series, master)
        all_results.extend(results)
        bars = series.sorted_bars()
        if bars and (latest_date is None or bars[-1].date > latest_date):
            latest_date = bars[-1].date

    html = render_html(all_results, len(series_by_code), latest_date)
    OUT_PATH.write_text(html, encoding="utf-8")

    print(f"対象銘柄数: {len(series_by_code)}")
    print(f"シグナル検出数: {len(all_results)}")
    print(f"レポート出力: {OUT_PATH}")


if __name__ == "__main__":
    main()
