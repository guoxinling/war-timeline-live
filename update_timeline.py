#!/usr/bin/env python3
import argparse
import datetime as dt
import email.utils
import html
import json
import os
import re
import ssl
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
LOG_DIR = os.path.join(ROOT, "logs")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

OFFICIAL_DOMAINS = {
    "idf.il",
    "gov.il",
    "state.gov",
    "defense.gov",
    "centcom.mil",
    "whitehouse.gov",
    "irna.ir",
    "isna.ir",
    "mehrnews.com",
    "mfa.gov.ir",
    "mod.gov.il",
}

INDEPENDENT_MEDIA_DOMAINS = {
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "aljazeera.com",
    "cnn.com",
    "nytimes.com",
    "theguardian.com",
    "washingtonpost.com",
    "france24.com",
    "dw.com",
    "timesofisrael.com",
    "haaretz.com",
}

ACTOR_RULES = [
    ("US", ["u.s.", "us ", "american", "united states", "pentagon", "centcom", "white house"]),
    ("Israel", ["israel", "idf", "israeli"]),
    ("Iran", ["iran", "iranian", "irgc", "tehran"]),
    ("Hezbollah", ["hezbollah"]),
    ("Hamas", ["hamas"]),
    ("Houthis", ["houthi", "houthis", "yemen's houthi"]),
]

ACTION_RULES = [
    ("发射", ["launch", "fired", "missile", "rocket", "drone attack"]),
    ("拦截", ["intercept", "shot down", "air defense", "defended"]),
    ("空袭", ["airstrike", "air strike", "strike", "bombard", "raid"]),
    ("通报", ["said", "announced", "statement", "claimed", "reported"]),
    ("撤离", ["evacuat", "withdraw", "pull out"]),
]

RESULT_RULES = [
    ("拦截", ["intercepted", "shot down", "neutralized"]),
    ("命中", ["hit", "struck", "impact"]),
    ("伤亡", ["killed", "injured", "casualties", "dead", "wounded"]),
    ("设施受损", ["damaged", "facility", "infrastructure", "fire at", "destroyed"]),
]

PLACE_HINTS = [
    "tehran", "isfahan", "natanz", "qom", "tabriz", "iran",
    "tel aviv", "jerusalem", "haifa", "eilat", "israel",
    "beirut", "tyre", "baalbek", "lebanon",
    "gaza", "rafah", "khan younis", "west bank",
    "damascus", "syria", "iraq", "yemen", "red sea",
]


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def parse_pubdate(pub: str):
    if not pub:
        return None
    try:
        t = email.utils.parsedate_to_datetime(pub)
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        return t.astimezone(dt.timezone.utc)
    except Exception:
        return None


def host_of(url: str):
    try:
        h = urllib.parse.urlparse(url).netloc.lower()
        if h.startswith("www."):
            h = h[4:]
        return h
    except Exception:
        return ""


def fetch_rss(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=20) as r:
        return r.read()


def parse_feed(xml_bytes: bytes):
    root = ET.fromstring(xml_bytes)
    items = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        source_el = item.find("source")
        source = (source_el.text or "").strip() if source_el is not None and source_el.text else ""
        source_url = source_el.get("url", "") if source_el is not None else ""
        items.append({
            "title": title,
            "link": link,
            "pubDate": pub,
            "source": source,
            "sourceUrl": source_url,
        })
    return items


def norm(s: str):
    s = s.lower()
    s = re.sub(r"https?://\S+", " ", s)
    s = re.sub(r"[^a-z0-9\u4e00-\u9fff\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def find_actor(text: str):
    t = norm(text)
    for actor, kws in ACTOR_RULES:
        for kw in kws:
            if kw in t:
                return actor
    return "未明确"


def find_action(text: str):
    t = norm(text)
    for action, kws in ACTION_RULES:
        for kw in kws:
            if kw in t:
                return action
    return "通报"


def find_result(text: str):
    t = norm(text)
    for result, kws in RESULT_RULES:
        for kw in kws:
            if kw in t:
                return result
    return "待确认"


def find_place(text: str):
    t = norm(text)
    for p in PLACE_HINTS:
        if p in t:
            return p.title()
    return "未明确"


def cluster_key(title: str):
    t = norm(title)
    words = [w for w in t.split() if len(w) > 2]
    return " ".join(words[:10])


def confidence_for_sources(domains):
    has_official = any(any(d == od or d.endswith("." + od) for od in OFFICIAL_DOMAINS) for d in domains)
    has_independent = any(any(d == md or d.endswith("." + md) for md in INDEPENDENT_MEDIA_DOMAINS) for d in domains)
    if has_official and has_independent:
        return "A"
    if has_official:
        return "B"
    return "C"


def confidence_note(label: str):
    if label == "A":
        return "A 多源交叉（官方+独立媒体）"
    if label == "B":
        return "B 单方官方声明"
    return "C 现场初报待核实"


def load_config():
    p = os.path.join(ROOT, "config.json")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def to_bj_time(utc_dt):
    cst = dt.timezone(dt.timedelta(hours=8))
    return utc_dt.astimezone(cst)


def build_timeline(cfg):
    lookback_hours = int(cfg.get("lookback_hours", 12))
    max_entries = int(cfg.get("max_entries", 30))
    since = now_utc() - dt.timedelta(hours=lookback_hours)

    raw = []
    for feed in cfg.get("feeds", []):
        try:
            items = parse_feed(fetch_rss(feed))
            for it in items:
                pub_dt = parse_pubdate(it.get("pubDate", ""))
                if pub_dt and pub_dt < since:
                    continue
                d = host_of(it.get("link", "")) or host_of(it.get("sourceUrl", ""))
                raw.append({
                    "timeUtc": pub_dt.isoformat() if pub_dt else "",
                    "title": it.get("title", ""),
                    "link": it.get("link", ""),
                    "source": it.get("source", ""),
                    "domain": d,
                })
        except Exception as e:
            print("feed_failed", feed, str(e), file=sys.stderr)

    raw.sort(key=lambda x: x.get("timeUtc", ""), reverse=True)

    clusters = {}
    for it in raw:
        k = cluster_key(it["title"])
        if not k:
            continue
        if k not in clusters:
            clusters[k] = {
                "items": [],
                "latest": it,
            }
        clusters[k]["items"].append(it)
        if it.get("timeUtc", "") > clusters[k]["latest"].get("timeUtc", ""):
            clusters[k]["latest"] = it

    entries = []
    for c in clusters.values():
        latest = c["latest"]
        merged_text = " ".join(i["title"] for i in c["items"])
        domains = sorted(set(i.get("domain", "") for i in c["items"] if i.get("domain")))
        t = parse_pubdate(email.utils.format_datetime(dt.datetime.fromisoformat(latest["timeUtc"]))) if latest.get("timeUtc") else None
        if not t and latest.get("timeUtc"):
            try:
                t = dt.datetime.fromisoformat(latest["timeUtc"])
                if t.tzinfo is None:
                    t = t.replace(tzinfo=dt.timezone.utc)
            except Exception:
                t = now_utc()
        if t is None:
            t = now_utc()
        bj = to_bj_time(t)
        confidence = confidence_for_sources(domains)
        entries.append({
            "time": bj.strftime("%Y-%m-%d %H:%M"),
            "actor": find_actor(merged_text),
            "action": find_action(merged_text),
            "place": find_place(merged_text),
            "result": find_result(merged_text),
            "confidence": confidence,
            "confidenceNote": confidence_note(confidence),
            "headline": latest["title"],
            "sources": [i["source"] or i["domain"] for i in c["items"]][:5],
            "links": [i["link"] for i in c["items"]][:5],
        })

    entries.sort(key=lambda x: x["time"], reverse=True)
    return entries[:max_entries], raw


def write_outputs(entries):
    generated_at = to_bj_time(now_utc()).strftime("%Y-%m-%d %H:%M")
    json_path = os.path.join(DATA_DIR, "timeline.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"generatedAt": generated_at, "entries": entries}, f, ensure_ascii=False, indent=2)

    md_lines = [
        "# 战争实况 Timeline（US / Israel / Iran / Hezbollah）",
        "",
        f"更新时间（北京时间）: {generated_at}",
        "",
        "可信度说明: A 多源交叉（官方+独立媒体） | B 单方官方声明 | C 现场初报待核实",
        "",
        "| 时间(北京时间) | 行动方 | 动作 | 地点 | 结果 | 可信度 | 事件摘要 |",
        "|---|---|---|---|---|---|---|",
    ]
    for e in entries:
        md_lines.append(
            f"| {e['time']} | {e['actor']} | {e['action']} | {e['place']} | {e['result']} | {e['confidence']} | {e['headline'].replace('|', '/')} |"
        )
    md_path = os.path.join(ROOT, "TIMELINE.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")

    rows = []
    for e in entries:
        src_html = "<br>".join(html.escape(s) for s in e["sources"]) if e["sources"] else "-"
        link_html = "<br>".join(f'<a href="{html.escape(u)}" target="_blank">source</a>' for u in e["links"] if u)
        rows.append(
            "<tr>"
            f"<td>{html.escape(e['time'])}</td>"
            f"<td>{html.escape(e['actor'])}</td>"
            f"<td>{html.escape(e['action'])}</td>"
            f"<td>{html.escape(e['place'])}</td>"
            f"<td>{html.escape(e['result'])}</td>"
            f"<td><strong>{html.escape(e['confidence'])}</strong><br>{html.escape(e['confidenceNote'])}</td>"
            f"<td>{html.escape(e['headline'])}<br><small>{src_html}</small><br>{link_html}</td>"
            "</tr>"
        )

    html_body = f"""<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>战争实况 Timeline</title>
  <style>
    :root {{ --bg:#f8f7f3; --fg:#1f2937; --card:#ffffff; --line:#d1d5db; --accent:#0b4f6c; }}
    body {{ margin:0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:linear-gradient(120deg,#f8f7f3,#eef4f8); color:var(--fg); }}
    .wrap {{ max-width:1200px; margin:32px auto; padding:0 16px; }}
    .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; box-shadow:0 6px 24px rgba(0,0,0,.06); overflow:hidden; }}
    h1 {{ margin:0; padding:18px 20px; background:var(--accent); color:#fff; font-size:20px; }}
    .meta {{ padding:12px 20px; font-size:14px; border-bottom:1px solid var(--line); }}
    table {{ width:100%; border-collapse:collapse; font-size:14px; }}
    th,td {{ border-bottom:1px solid var(--line); padding:10px; text-align:left; vertical-align:top; }}
    th {{ background:#f3f4f6; position:sticky; top:0; z-index:1; }}
    small {{ color:#6b7280; }}
    a {{ color:#0b63ce; text-decoration:none; }}
    a:hover {{ text-decoration:underline; }}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <div class=\"card\">
      <h1>战争实况 Timeline（US / Israel / Iran / Hezbollah）</h1>
      <div class=\"meta\">更新时间（北京时间）: {html.escape(generated_at)} | 可信度: A 多源交叉（官方+独立媒体） / B 单方官方声明 / C 现场初报待核实</div>
      <div style=\"overflow:auto;max-height:78vh\">
        <table>
          <thead>
            <tr>
              <th>时间(北京时间)</th><th>行动方</th><th>动作</th><th>地点</th><th>结果</th><th>可信度</th><th>事件摘要</th>
            </tr>
          </thead>
          <tbody>
            {''.join(rows)}
          </tbody>
        </table>
      </div>
    </div>
  </div>
</body>
</html>
"""
    html_path = os.path.join(ROOT, "index.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_body)

    return md_path, html_path, json_path, generated_at


def build_push_text(entries, generated_at, limit=12):
    lines = [
        f"战争实况 Timeline 更新（北京时间 {generated_at}）",
        "可信度: A多源交叉 | B官方单方 | C初报待核实",
        "",
    ]
    for i, e in enumerate(entries[:limit], 1):
        lines.append(
            f"{i}. {e['time']} | {e['actor']} | {e['action']} | {e['place']} | {e['result']} | {e['confidence']}"
        )
        lines.append(f"   {e['headline']}")
    if not entries:
        lines.append("本周期未抓取到有效更新。")
    lines.append("")
    lines.append("完整网页: 本机文件 war_timeline/index.html")
    return "\n".join(lines)


def push_to_feishu(cfg, message):
    fei = (cfg.get("feishu") or {})
    if not fei.get("enabled"):
        return
    node_bin = os.environ.get("OPENCLAW_NODE", "/Users/guoxl/.nvm/versions/node/v22.12.0/bin/node")
    openclaw_bin = os.environ.get("OPENCLAW_BIN", "/Users/guoxl/.nvm/versions/node/v22.12.0/bin/openclaw")
    cmd = [
        node_bin, openclaw_bin, "message", "send",
        "--channel", fei.get("channel", "feishu"),
        "--account", fei.get("account", "main"),
        "--target", fei["target"],
        "--message", message,
    ]
    subprocess.run(cmd, check=True)


def main():
    parser = argparse.ArgumentParser(description="Generate war timeline and push to Feishu")
    parser.add_argument("--push", action="store_true", help="Push summary to Feishu")
    parser.add_argument("--limit", type=int, default=None, help="Override max entries")
    args = parser.parse_args()

    cfg = load_config()
    if args.limit is not None:
        cfg["max_entries"] = args.limit

    entries, _raw = build_timeline(cfg)
    md_path, html_path, json_path, generated_at = write_outputs(entries)

    log_line = f"[{generated_at}] entries={len(entries)} md={md_path} html={html_path} json={json_path}\n"
    with open(os.path.join(LOG_DIR, "run.log"), "a", encoding="utf-8") as f:
        f.write(log_line)

    print(log_line.strip())
    if args.push:
        message = build_push_text(entries, generated_at)
        try:
            push_to_feishu(cfg, message)
            print("push=ok")
        except Exception as e:
            print(f"push=failed err={e}", file=sys.stderr)


if __name__ == "__main__":
    main()
