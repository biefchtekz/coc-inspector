#!/usr/bin/env python3
"""Збирає слім-довідник для оглядача бази.

Читає сирі таблиці ClashKing (--src), викидає все, чого застосунок не
використовує (описи, TID, бойову статистику), і пише два файли:

  ref.min.json  — один бандл з усіма сутностями (замість 8+ запитів)
  meta.json     — версія, походження, лічильники; за нею клієнт вирішує,
                  чи можна взяти довідник із localStorage

Дорогою перевіряє дані на осудність: якщо upstream зламався, скрипт падає
і воркфлоу не комітить биту копію.

  python3 tools/build_ref.py --src data --out data --prev data/meta.json
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):      # щоб українські логи не падали в cp1251
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# Таблиці, які тягнемо. Ті, що позначені required, критичні для роботи:
# без них рахувати нічого. Решта — довідка назв для розділів дампу,
# які трапляються рідко (косметика, перешкоди, магічні предмети).
FILES = {
    "buildings":           {"required": True,  "min": 70},
    "traps":               {"required": True,  "min": 10},
    "troops":              {"required": True,  "min": 90},
    "spells":              {"required": True,  "min": 18},
    "heroes":              {"required": True,  "min": 6},
    "pets":                {"required": True,  "min": 10},
    "equipment":           {"required": True,  "min": 40},
    "helpers":             {"required": True,  "min": 3},
    "guardians":           {"required": False, "min": 1},
    "magic_items":         {"required": False, "min": 5},
    "decorations":         {"required": False, "min": 20},
    "obstacles":           {"required": False, "min": 20},
    "skins":               {"required": False, "min": 20},
    "sceneries":           {"required": False, "min": 10},
    "capital_house_parts": {"required": False, "min": 20},
}

# Поля сутності, які реально читає index.html.
KEEP_TOP = {
    "_id", "name", "type", "village", "upgrade_resource", "build_resource",
    "clear_resource", "clear_cost", "build_cost", "gear_up", "hero", "rarity",
    "superchargeable", "production_building", "production_building_level",
    "housing_space", "max_count", "gem_value", "max_inventory", "slot_type",
    "tier", "character",
}

# Поля рівня. Все інше (hitpoints, dps, radius, abilities…) — у бандл не йде.
KEEP_LVL = {
    "level", "build_cost", "upgrade_cost", "build_time", "upgrade_time",
    "required_townhall", "required_lab_level", "required_blacksmith_level",
    "required_hero_tavern_level", "required_pet_house_level",
    "unlocks", "supercharge", "merge_requirement", "alt_upgrade_resource",
    "strength_weight",
}

# Якірні ID: якщо якогось із них немає — таблиці приїхали биті.
ANCHORS = {
    1000001: "Town Hall",
    1000010: "Wall",
    1000034: "Builder Hall",
    1000078: "O.T.T.O's Outpost",
    4000000: "Barbarian",
    26000000: "Lightning Spell",
    28000000: "Barbarian King",
    90000000: "Barbarian Puppet",
}

UPSTREAM_REPO = "ClashKingInc/ClashKingAssets"


class Bad(Exception):
    """Дані не пройшли перевірку — комітити не можна."""


def items_of(raw):
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for value in raw.values():
            if isinstance(value, list):
                return value
    raise Bad("не знайшов масив сутностей")


def slim_level(level):
    out = {k: v for k, v in level.items() if k in KEEP_LVL and v is not None}
    if "supercharge" in out:
        sc = out["supercharge"]
        levels = [
            {k: v for k, v in l.items()
             if k in ("level", "build_cost", "build_time", "hitpoints_buff", "dps_buff")}
            for l in sc.get("levels", [])
        ]
        out["supercharge"] = {"upgrade_resource": sc.get("upgrade_resource"), "levels": levels}
    return out


def slim_item(item, src):
    out = {k: v for k, v in item.items() if k in KEEP_TOP and v is not None}
    out["src"] = src
    levels = item.get("levels")
    if isinstance(levels, list) and levels:
        out["levels"] = [slim_level(l) for l in levels if isinstance(l, dict)]
    return out


def load(src_dir, stem, rules):
    path = os.path.join(src_dir, stem + ".json")
    if not os.path.exists(path):
        if rules["required"]:
            raise Bad("немає обов'язкового файлу %s.json" % stem)
        return None
    blob = open(path, encoding="utf-8").read()
    if len(blob) < 500:
        raise Bad("%s.json підозріло малий (%d Б)" % (stem, len(blob)))
    try:
        items = items_of(json.loads(blob))
    except json.JSONDecodeError as err:
        raise Bad("%s.json не читається: %s" % (stem, err))
    if len(items) < rules["min"]:
        raise Bad("у %s.json лише %d записів, чекав щонайменше %d"
                  % (stem, len(items), rules["min"]))
    return items


def max_level(items, ident):
    for item in items:
        if item.get("_id") == ident:
            levels = item.get("levels") or []
            return max((l.get("level") or 0) for l in levels) if levels else 0
    return 0


def build(src_dir, out_dir, prev_path, upstream_sha, upstream_date):
    bundle, counts, seen = [], {}, {}
    for stem, rules in FILES.items():
        items = load(src_dir, stem, rules)
        if items is None:
            print("  · %-20s немає (не обов'язковий)" % stem)
            continue
        kept = 0
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("_id"), int):
                continue
            ident = item["_id"]
            if ident in seen:
                raise Bad("ID %d трапляється двічі: %s і %s" % (ident, seen[ident], stem))
            seen[ident] = stem
            bundle.append(slim_item(item, stem))
            kept += 1
        counts[stem] = kept
        print("  · %-20s %4d записів" % (stem, kept))

    missing = [f"{i} ({n})" for i, n in ANCHORS.items() if i not in seen]
    if missing:
        raise Bad("у довіднику немає якірних ID: " + ", ".join(missing))

    for entry in bundle:
        for level in entry.get("levels", []):
            if not isinstance(level.get("level"), int):
                raise Bad("у %s (%s) рівень без номера" % (entry.get("name"), entry["_id"]))

    buildings = [b for b in bundle if b.get("src") == "buildings"]
    th_max = max_level(buildings, 1000001)
    bh_max = max_level(buildings, 1000034)
    if th_max < 15 or bh_max < 9:
        raise Bad("стелі залів виглядають битими: ратуша %d, дім будівельника %d" % (th_max, bh_max))

    prev = {}
    if prev_path and os.path.exists(prev_path):
        try:
            prev = json.load(open(prev_path, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            prev = {}
    prev_th = (prev.get("game") or {}).get("town_hall_max", 0)
    if th_max < prev_th:
        raise Bad("стеля ратуші впала з %d до %d — це регрес, не оновлення" % (prev_th, th_max))

    bundle.sort(key=lambda x: x["_id"])
    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "upstream": {"repo": UPSTREAM_REPO, "sha": upstream_sha, "date": upstream_date},
        "items": bundle,
    }
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    raw = text.encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()

    meta = {
        "version": digest[:12],
        "generated_at": payload["generated_at"],
        "upstream": payload["upstream"],
        "counts": counts,
        "totals": {
            "items": len(bundle),
            "levels": sum(len(b.get("levels", [])) for b in bundle),
        },
        "game": {"town_hall_max": th_max, "builder_hall_max": bh_max},
        "bundle": {"file": "ref.min.json", "bytes": len(raw), "sha256": digest},
    }

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "ref.min.json"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    print("  стеля: ратуша %d · дім будівельника %d" % (th_max, bh_max))
    print("  bundle %d КБ, версія %s" % (len(raw) // 1024, meta["version"]))
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="data")
    ap.add_argument("--out", default="data")
    ap.add_argument("--prev", default="data/meta.json")
    ap.add_argument("--upstream-sha", default=None)
    ap.add_argument("--upstream-date", default=None)
    args = ap.parse_args()
    try:
        build(args.src, args.out, args.prev, args.upstream_sha, args.upstream_date)
    except Bad as err:
        print("ЗУПИНКА: %s" % err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
