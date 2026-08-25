#!/usr/bin/env python3
"""Build the bundled €2 commemorative coin catalogue from ECB pages."""
import hashlib
import html
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://www.ecb.europa.eu/euro/coins/comm/html/"
OUT = Path(__file__).resolve().parents[1] / "resources" / "euro2-catalog.json"
COUNTRIES = {
    "Andorra": ("AD", "安道尔", "协议发行国"), "Austria": ("AT", "奥地利", "欧元区"),
    "Belgium": ("BE", "比利时", "欧元区"), "Croatia": ("HR", "克罗地亚", "欧元区"),
    "Cyprus": ("CY", "塞浦路斯", "欧元区"), "Estonia": ("EE", "爱沙尼亚", "欧元区"),
    "Finland": ("FI", "芬兰", "欧元区"), "France": ("FR", "法国", "欧元区"),
    "Germany": ("DE", "德国", "欧元区"), "Greece": ("GR", "希腊", "欧元区"),
    "Ireland": ("IE", "爱尔兰", "欧元区"), "Italy": ("IT", "意大利", "欧元区"),
    "Latvia": ("LV", "拉脱维亚", "欧元区"), "Lithuania": ("LT", "立陶宛", "欧元区"),
    "Luxembourg": ("LU", "卢森堡", "欧元区"), "Malta": ("MT", "马耳他", "欧元区"),
    "Monaco": ("MC", "摩纳哥", "协议发行国"), "Netherlands": ("NL", "荷兰", "欧元区"),
    "Portugal": ("PT", "葡萄牙", "欧元区"), "San Marino": ("SM", "圣马力诺", "协议发行国"),
    "Slovakia": ("SK", "斯洛伐克", "欧元区"), "Slovenia": ("SI", "斯洛文尼亚", "欧元区"),
    "Spain": ("ES", "西班牙", "欧元区"), "Vatican City": ("VA", "梵蒂冈", "协议发行国"),
}

def text(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()

def main():
    records = []
    pattern = re.compile(
        r'<source srcset="([^"]+\.(?:webp|jpg))"[^>]*>.*?'
        r'<div class="content-box">\s*<h3>(.*?)</h3>\s*<div>(.*?)</div>', re.S)
    for year in range(2004, 2026):
        page = f"comm_{year}.en.html"
        url = urllib.parse.urljoin(BASE, page)
        request = urllib.request.Request(url, headers={"User-Agent": "Shiguang-Catalog/1.0"})
        source = urllib.request.urlopen(request, timeout=30).read().decode("utf-8")
        occurrence = {}
        for image, country_html, body in pattern.findall(source):
            country_en = text(country_html)
            if country_en not in COUNTRIES:
                continue
            fields = {text(k).rstrip(":").lower(): text(v) for k, v in re.findall(
                r"<strong>(.*?)</strong>(.*?)(?=<strong>|</p>)", body, re.S)}
            feature = fields.get("feature", "€2 commemorative coin")
            occurrence[(country_en, feature)] = occurrence.get((country_en, feature), 0) + 1
            code, country_zh, issuer_group = COUNTRIES[country_en]
            raw_id = f"ecb:{year}:{code}:{feature}:{occurrence[(country_en, feature)]}"
            records.append({
                "id": hashlib.sha256(raw_id.encode()).hexdigest()[:20], "year": year,
                "country_code": code, "country": country_zh, "country_en": country_en,
                "issuer_group": issuer_group, "feature": feature,
                "description": fields.get("description", ""),
                "mintage": fields.get("issuing volume", ""),
                "issue_date": fields.get("issuing date", ""),
                "image_url": urllib.parse.urljoin(url, image), "official_url": url,
            })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"source": BASE + "index.en.html", "through_year": 2025,
                               "count": len(records), "coins": records},
                              ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(records)} coins to {OUT}")

if __name__ == "__main__":
    main()
