#!/usr/bin/env python3
"""Build a catalogue of Chinese circulating commemorative coin issues."""
import hashlib, html, json, re, urllib.parse, urllib.request
from pathlib import Path

URL = "https://zh.wikipedia.org/wiki/中华人民共和国普通纪念币"
OUT = Path(__file__).resolve().parents[1] / "resources" / "china-coin-catalog.json"

def plain(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()

def main():
    req = urllib.request.Request(urllib.parse.quote(URL, safe=":/"), headers={"User-Agent": "Shiguang-Catalog/1.0"})
    source = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
    start = source.index('id="流通纪念币目录"')
    end = source.index('id="流通纪念钞目录"', start)
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", source[start:end], re.S):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)
        values = [plain(x) for x in cells]
        if len(values) < 8 or not values[0].isdigit(): continue
        date_index = next((i for i in range(len(values)-1, 1, -1)
                           if re.search(r"(?:19|20)\d{2}[.年/-]\d{1,2}", values[i])), None)
        if date_index is None: continue
        name, issue_date = values[1], values[date_index]
        links = re.findall(r'href="([^"]+)"', cells[date_index + 1], re.S) if date_index + 1 < len(cells) else []
        official = next((x for x in links if "pbc.gov.cn" in x), URL)
        raw_id = f"cn:{issue_date}:{name}"
        rows.append({"id": hashlib.sha256(raw_id.encode()).hexdigest()[:20], "region": "中国",
            "name": name, "year": int(re.search(r"(?:19|20)\d{2}", issue_date).group()), "issue_date": issue_date,
            "face_value": values[2], "mintage": values[date_index-3] if date_index >= 3 else "",
            "material": values[date_index-2] if date_index >= 2 else "",
            "diameter_mm": values[date_index-1] if date_index >= 1 else "",
            "official_url": official, "image_url": ""})
    OUT.write_text(json.dumps({"source": URL, "verified_at": "2026-08-25", "count": len(rows),
                               "coins": rows}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"wrote {len(rows)} issues")

if __name__ == "__main__": main()
