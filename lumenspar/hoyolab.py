"""Build cards from HoYoLAB's battle chronicle: every character, not just the showcase.

HoYoLAB's public record endpoints (the ones its own character pages call)
list all of a player's characters and give each one's weapon, artifacts with
how many times every substat rolled, constellations, talents and the stats
panel. They answer only to a signed-in session, so Lumenspar signs the player
in inside a window of its own and runs the requests from that page
(`fetch_script`); the session lives in memory only and is discarded with the
window (see ui/hoyolab_backend.py and qml/HoyolabWindow.qml). This module is
the pure part: the script that runs in the page and the parsing of its
result into the same card shape the Enka.Network showcase produces.

The endpoints are unofficial; `parse` reads defensively and reports what it
could not use instead of failing.
"""

from __future__ import annotations

import json
import re
import time

from . import builds, enka

API = "https://sg-act-public-api.hoyolab.com/event/game_record/genshin/api/"
LOGIN_URL = "https://www.hoyolab.com/home"
# Requests from this origin are allowed by the API's CORS rules.
ACT_ORIGIN = "https://act.hoyolab.com"
NOT_SIGNED_IN = 10001

# The first digit of a UID says which server its account lives on.
SERVERS = {"6": "os_usa", "7": "os_euro", "8": "os_asia", "9": "os_cht"}


class HoyolabError(Exception):
    """A response HoYoLAB refused or Lumenspar cannot read."""

    def __init__(self, message: str, signed_out: bool = False) -> None:
        super().__init__(message)
        self.signed_out = signed_out


def server_for(uid: str) -> str | None:
    """The HoYoLAB server name for a global UID, None for other regions."""
    uid = uid.strip()
    return SERVERS.get(uid[:1]) if uid.isdigit() and len(uid) >= 9 else None


def page_url(uid: str, server: str) -> str:
    """A page on the API's own origin to run the requests from."""
    return (f"{ACT_ORIGIN}/app/community-game-records-sea/index.html"
            f"#/ys/role/all?role_id={uid}&server={server}")


def fetch_script(uid: str, server: str) -> str:
    """JavaScript that reads the character list and every character's detail.

    It returns at once; progress and the result are left in `window.__ls`,
    read back with PROGRESS_JS and RESULT_JS. Three requests run at a time.
    Only the player's own game data is requested: nothing reads cookies,
    storage or form fields.
    """
    return """
(function () {
  const S = window.__ls = { done: 0, total: 0, finished: false, error: "", retcode: 0,
                            list: null, details: {}, errors: {} };
  const API = %(api)s, role_id = %(uid)s, server = %(server)s;
  const headers = {
    'content-type': 'application/json',
    'x-rpc-lang': 'en-us', 'x-rpc-language': 'en-us',
    'x-rpc-client_type': '5', 'x-rpc-platform': '4',
    'x-rpc-app_version': '1.5.0', 'x-rpc-env': 'default',
    'x-rpc-page': 'v7.0.3-gr-sea_#/ys/role/all'
  };
  const post = async (path, body) => {
    const r = await fetch(API + path, { method: 'POST', headers: headers,
                                        body: JSON.stringify(body), credentials: 'include' });
    const j = await r.json();
    if (j.retcode !== undefined && j.retcode !== 0) {
      const e = new Error(j.message || ('retcode ' + j.retcode));
      e.retcode = j.retcode;
      throw e;
    }
    return j;
  };
  (async () => {
    try {
      const list = await post('character/list', { role_id: role_id, server: server, sort_type: 1 });
      S.list = list;
      const chars = (list.data && (list.data.list || list.data.avatars)) || [];
      const ids = chars.map(c => c.id ?? c.avatar_id ?? (c.base && c.base.id)).filter(Boolean);
      S.total = ids.length;
      const queue = ids.slice();
      const worker = async () => {
        while (queue.length) {
          const cid = queue.shift();
          try {
            S.details[cid] = await post('character/detail',
                { server: server, role_id: role_id, character_ids: [cid] });
          } catch (e) {
            if (e.retcode === 10001) throw e;
            S.errors[cid] = String(e.message || e);
          }
          S.done++;
        }
      };
      await Promise.all([worker(), worker(), worker()]);
    } catch (e) {
      S.error = String(e.message || e);
      S.retcode = e.retcode || 0;
    }
    S.finished = true;
  })();
  return 'started';
})()
""" % {"api": json.dumps(API), "uid": json.dumps(str(uid)), "server": json.dumps(server)}


PROGRESS_JS = ("JSON.stringify(window.__ls ? { done: window.__ls.done, total: window.__ls.total,"
               " finished: window.__ls.finished, error: window.__ls.error,"
               " retcode: window.__ls.retcode } : null)")
RESULT_JS = ("(function () { const s = window.__ls;"
             " return JSON.stringify({ list: s.list, details: s.details, errors: s.errors }); })()")


# -- parsing ---------------------------------------------------------------------

# Stat ids as HoYoLAB numbers them (the same as the game's fight properties).
_KEY = {"1": "baseHp", "4": "baseAtk", "7": "baseDef", "2": "hp", "3": "hp_", "5": "atk",
        "6": "atk_", "8": "def", "9": "def_", "20": "critRate_", "22": "critDMG_",
        "23": "enerRech_", "24": "eleMas", "28": "eleMas", "26": "heal_",
        "30": "physical_dmg_", "40": "pyro_dmg_", "41": "electro_dmg_", "42": "hydro_dmg_",
        "43": "dendro_dmg_", "44": "anemo_dmg_", "45": "geo_dmg_", "46": "cryo_dmg_"}
_LABEL = {**{k: label for k, label in builds.STATS.values()},
          "baseHp": "Base HP", "baseDef": "Base DEF"}
_SLOT = {1: "flower", 2: "plume", 3: "sands", 4: "goblet", 5: "circlet"}
# Enka's icon number for each slot of a set (UI_RelicIcon_<set>_<n>).
_ICON_NO = {"flower": 4, "plume": 2, "sands": 5, "goblet": 1, "circlet": 3}
_PANEL = (("2000", "hp"), ("2001", "atk"), ("2002", "def"), ("28", "eleMas"),
          ("20", "critRate_"), ("22", "critDMG_"), ("23", "enerRech_"), ("26", "heal_"))
_DMG_IDS = {"30": "physical", "40": "pyro", "41": "electro", "42": "hydro",
            "43": "dendro", "44": "anemo", "45": "geo", "46": "cryo"}


def _first(*values):
    return next((v for v in values if v not in (None, "")), None)


def _num(value) -> float:
    """A displayed stat ("4,780", "46.6%", 46.6) as a number (percent points)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    try:
        return float(str(value or "").replace(",", "").replace("%", "").strip())
    except ValueError:
        return 0.0


def _norm(name) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def _prop(p: dict) -> tuple[str, float]:
    """(stat key, value in percent points for % stats) of a property entry."""
    key = _KEY.get(str(p.get("property_type")), "")
    raw = _first(p.get("value"), p.get("final"))
    value = _num(raw)
    # A bare fraction (0.466) for a percent stat instead of "46.6%".
    if key.endswith("_") and not isinstance(raw, str) and 0 < abs(value) < 3:
        value *= 100
    return key, value


def _stat(p: dict) -> dict:
    key, value = _prop(p)
    return {"key": key, "label": _LABEL.get(key, str(p.get("name") or p.get("label") or "")),
            "value": value, "text": builds.fmt(key, value)}


def _ascension(level: int) -> int:
    return next((a for a, cap in enumerate(builds._MAX_LEVEL) if level <= cap), 6)


def _artifact(r: dict, sets_by_id: dict, sets_by_name: dict) -> dict | None:
    slot = _SLOT.get(int(r.get("pos") or 0))
    if not slot:
        return None
    s = r.get("set") or {}
    art_set = sets_by_id.get(str(s.get("id"))) or sets_by_name.get(_norm(s.get("name"))) or {}
    set_id = str(art_set.get("id") or s.get("id") or "")
    main_key, main_value = _prop(r.get("main_property") or {})
    subs = []
    for p in r.get("sub_property_list") or []:
        key, value = _prop(p)
        subs.append({"key": key, "label": _LABEL.get(key, str(p.get("name") or "")),
                     "value": value, "text": builds.fmt(key, value),
                     "rolls": int(p.get("times") or 0)})
    cv = sum(2 * x["value"] for x in subs if x["key"] == "critRate_") + \
        sum(x["value"] for x in subs if x["key"] == "critDMG_")
    return {
        "slot": slot, "setId": set_id, "setKey": art_set.get("key", ""),
        "setName": art_set.get("name") or s.get("name") or "Unknown set",
        "rarity": int(r.get("rarity") or 0), "level": int(r.get("level") or 0),
        "icon": f"UI_RelicIcon_{set_id}_{_ICON_NO[slot]}" if art_set else "",
        "main": {"key": main_key, "label": _LABEL.get(main_key, ""), "value": main_value,
                 "text": builds.fmt(main_key, main_value)},
        "subs": subs, "critValue": round(cv, 1),
    }


def _weapon(w: dict, by_id: dict, by_name: dict) -> dict | None:
    if not w:
        return None
    info = by_id.get(str(w.get("id"))) or by_name.get(_norm(w.get("name"))) or {}
    level = int(w.get("level") or 1)
    stats = []
    for p in (w.get("main_property"), w.get("sub_property")):
        if isinstance(p, dict) and p:
            s = _stat(p)
            stats.append({"key": s["key"], "label": s["label"], "text": s["text"]})
    return {
        "id": str(info.get("id") or w.get("id") or ""), "key": info.get("key", ""),
        "name": info.get("name") or w.get("name") or "Unknown weapon",
        "rarity": int(_first(w.get("rarity"), info.get("rarity")) or 0),
        "level": level,
        "ascension": int(_first(w.get("promote_level"), _ascension(level))),
        "refinement": int(_first(w.get("affix_level"), 1)),
        "icon": info.get("icon", ""), "stats": stats,
    }


def parse(raw: dict) -> tuple[list[dict], list[str]]:
    """(cards, problems) for a fetch's {"list", "details", "errors"} result."""
    lst = raw.get("list") or {}
    if lst.get("retcode") == NOT_SIGNED_IN:
        raise HoyolabError("HoYoLAB says you are not signed in.", signed_out=True)
    rows = (lst.get("data") or {}).get("list") or (lst.get("data") or {}).get("avatars") or []
    if not rows:
        raise HoyolabError("HoYoLAB returned no characters for this UID. Check the UID, and "
                           "that this account's characters are visible to you.")
    table = enka._avatar_map()
    chars = builds._items("characters.json", "key")
    weapons_id = builds._items("weapons.json", "id")
    weapons_name = {_norm(w["name"]): w for w in weapons_id.values()}
    sets_id = builds._items("artifact_sets.json", "id")
    sets_name = {_norm(s["name"]): s for s in sets_id.values()}
    details = raw.get("details") or {}
    errors = raw.get("errors") or {}
    cards, problems = [], []
    now = int(time.time())
    for row in rows:
        base = row.get("base") or row
        cid = str(_first(base.get("id"), row.get("id"), row.get("avatar_id")) or "")
        name = base.get("name") or cid
        detail = (((details.get(cid) or {}).get("data") or {}).get("list") or [None])[0]
        if detail is None:
            problems.append(f"{name}: no details ({errors.get(cid, 'not returned')})")
            continue
        dbase = detail.get("base") or {}
        element = str(_first(dbase.get("element"), base.get("element")) or "").lower()
        entry = table.get(cid)
        key = entry["key"] if entry else (
            f"Traveler{element.capitalize()}" if cid in ("10000005", "10000007") and element
            else "")
        if not key or key not in chars:
            problems.append(f"{name}: newer than Lumenspar's game data (update Lumenspar)")
            continue
        char = chars[key]
        level = int(_first(dbase.get("level"), base.get("level")) or 1)
        ascension = int(_first(dbase.get("promote_level"), _ascension(level)))
        weapon = _weapon(detail.get("weapon") or row.get("weapon") or {}, weapons_id,
                         weapons_name)
        artifacts = [a for a in (_artifact(r, sets_id, sets_name)
                                 for r in detail.get("relics") or []) if a]
        artifacts.sort(key=lambda a: builds.SLOT_ORDER.index(a["slot"]))
        cons = [c for c in detail.get("constellations") or [] if c.get("is_actived")]
        constellation = int(_first(dbase.get("actived_constellation_num"),
                                   base.get("actived_constellation_num"), len(cons)) or 0)

        # Levelled talents (type 1) in game order: attack, skill, burst. HoYoLAB
        # shows the in-game level, constellation bonuses included, and does not
        # say how much of it is a bonus, so the base level is unknown here.
        levelled = [s for s in detail.get("skills") or []
                    if _first(s.get("skill_type"), s.get("type")) == 1][:3]
        talents = [{"slot": slot, "label": label, "base": None,
                    "level": int(s.get("level") or 1), "boosted": False}
                   for (slot, label), s in zip(
                       (("auto", "Normal Attack"), ("skill", "Elemental Skill"),
                        ("burst", "Elemental Burst")), levelled)]

        panel: dict[str, dict] = {}
        for group in ("selected_properties", "base_properties", "element_properties",
                      "extra_properties"):
            for p in detail.get(group) or []:
                panel.setdefault(str(p.get("property_type")), p)

        def final(pid: str) -> float:
            p = panel.get(pid) or {}
            raw_v = _first(p.get("final"), p.get("value"))
            v = _num(raw_v)
            if _KEY.get(pid, "").endswith("_") and not isinstance(raw_v, str) and 0 < abs(v) < 3:
                v *= 100
            return v

        stats = []
        for pid, k in _PANEL:
            if pid not in panel:
                continue
            value = final(pid)
            if k == "heal_" and not value:
                continue
            stats.append({"key": k, "label": _LABEL.get(k, k), "text": builds.fmt(k, value)})
        # The highest elemental/physical bonus, or the character's own element.
        best = max(_DMG_IDS, key=lambda i: (final(i), _DMG_IDS[i] == element))
        if final(best) > 0:
            n = _DMG_IDS[best]
            stats.append({"key": f"{n}_dmg_", "label": f"{n.capitalize()} DMG Bonus",
                          "text": builds.fmt(f"{n}_dmg_", final(best))})

        cards.append({
            "avatarId": cid, "key": key, "source": "hoyolab",
            "name": char.get("name") or name,
            "element": element or char.get("element") or "",
            "rarity": int(_first(dbase.get("rarity"), base.get("rarity"), char.get("rarity"))
                          or 5),
            "icon": char.get("icon", ""),
            "splash": (char["icon"].replace("UI_AvatarIcon_", "UI_Gacha_AvatarImg_")
                       if char.get("icon") else ""),
            "level": level, "ascension": ascension,
            "maxLevel": max(level, builds._MAX_LEVEL[min(ascension, 6)]),
            "constellation": constellation, "friendship": 0,
            "talents": talents, "weapon": weapon, "artifacts": artifacts,
            "sets": builds.sets_of(artifacts), "stats": stats,
            "critValue": round(sum(a["critValue"] for a in artifacts), 1),
            "fetchedAt": now,
        })
    return cards, problems
