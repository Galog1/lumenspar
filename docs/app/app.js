// Lumenspar viewer: reads the view-<uid>.json files the desktop app backs up
// to the user's hidden Google Drive app-data folder, and renders them. All in
// the browser: the access token never leaves this page except to Google.
"use strict";

const SCOPE = "https://www.googleapis.com/auth/drive.appdata";
const DRIVE = "https://www.googleapis.com/drive/v3/files";
const ASSETS = "https://gi.yatta.moe/assets/UI/";
const ELEMENT = { pyro: "#EF7938", hydro: "#4CC2F1", anemo: "#74C2A8", electro: "#B08FC2",
                  dendro: "#A5C83B", cryo: "#9FD6E3", geo: "#FAB632" };
// Roll value (RV), the same as the desktop app's builds.py: a substat as a percentage
// of the best single roll on a 5-star artifact. What counts follows the build: crit
// always, the scaling stat its sands/goblet/circlet point at (ATK% by default), and
// Energy Recharge when a main stat asks for it.
const MAX_ROLL = { hp: 298.75, hp_: 5.83, atk: 19.45, atk_: 5.83, def: 23.15, def_: 7.29,
                   critRate_: 3.89, critDMG_: 7.77, eleMas: 23.31, enerRech_: 6.48 };
const SCALING = ["atk_", "hp_", "def_", "eleMas"];
const SHORT = { critRate_: "CRIT Rate", critDMG_: "CRIT DMG", atk_: "ATK%", hp_: "HP%", def_: "DEF%",
                eleMas: "EM", enerRech_: "ER" };
const TRAVELER_ICON = { 10000005: "UI_AvatarIcon_PlayerBoy", 10000007: "UI_AvatarIcon_PlayerGirl" };
const METRIC_KEY = "lumenspar.cardMetric";

function countedStats(arts) {
  const votes = {};
  for (const a of arts) if (["sands", "goblet", "circlet"].includes(a.slot) && SCALING.includes(a.main.key))
    votes[a.main.key] = (votes[a.main.key] || 0) + 1;
  const scaling = SCALING.reduce((best, k) => ((votes[k] || 0) > (votes[best] || 0) ? k : best), "atk_");
  const keys = ["critRate_", "critDMG_", scaling];
  if (arts.some((a) => a.main.key === "enerRech_")) keys.push("enerRech_");
  return keys;
}

// A card with roll values worked out and the Traveler's art filled in (a copy).
function withRolls(b) {
  const arts = b.artifacts || [];
  const counted = countedStats(arts);
  const icon = b.icon || TRAVELER_ICON[b.avatarId] || "";
  const outArts = arts.map((a) => {
    const subs = (a.subs || []).map((x) => {
      const rv = MAX_ROLL[x.key] && x.value > 0 ? (x.value / MAX_ROLL[x.key]) * 100 : 0;
      return { ...x, rv, counted: counted.includes(x.key) };
    });
    return { ...a, subs, rv: subs.reduce((t, x) => t + (x.counted ? x.rv : 0), 0) };
  });
  return { ...b, icon, splash: b.splash || icon.replace("UI_AvatarIcon_", "UI_Gacha_AvatarImg_"),
           artifacts: outArts, rv: outArts.reduce((t, a) => t + a.rv, 0),
           rvLabels: counted.map((k) => SHORT[k] || k).join(", ") };
}
const pct = (n) => Math.round(n).toLocaleString() + "%";

const OWN_CLIENT_KEY = "lumenspar.webClientId";

const $ = (id) => document.getElementById(id);
let token = "";
let tokenClient = null;
let views = [];           // parsed view files, one per account
let current = 0;          // index into views
let metric = storageGet(METRIC_KEY) === "rv" ? "rv" : "cv";
let selectedBuild = 0;

// ── small DOM helper: el("div", {class: "x"}, child, "text") ─────────────
function el(tag, attrs, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "style") n.style.cssText = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    n.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return n;
}

function asset(name) {
  if (!name) return "";
  return ASSETS + (name.startsWith("UI_RelicIcon_") ? "reliquary/" : "") + name + ".png";
}

function img(name, alt) {
  const src = asset(name);
  if (!src) return null;
  const i = el("img", { src, alt: alt || "", loading: "lazy", decoding: "async" });
  i.addEventListener("error", () => { i.style.visibility = "hidden"; });
  return i;
}

function setStatus(text, isError) {
  const s = $("status");
  s.textContent = text || "";
  s.classList.toggle("err", !!isError);
}

function storageGet(key) { try { return localStorage.getItem(key) || ""; } catch { return ""; } }
function storageSet(key, value) {
  try { value ? localStorage.setItem(key, value) : localStorage.removeItem(key); } catch { /* private mode */ }
}

// ── sign-in ───────────────────────────────────────────────────────────────
function clientId() {
  return storageGet(OWN_CLIENT_KEY) || window.LUMENSPAR_WEB_CLIENT_ID || "";
}

function initSignIn() {
  const id = clientId();
  $("client-id").value = storageGet(OWN_CLIENT_KEY);
  if (!id) {
    $("signin").disabled = true;
    $("signin-note").textContent = "Sign-in is not set up on this page yet. If you use your own Google project, enter its web client ID below.";
    return;
  }
  if (!(window.google && google.accounts && google.accounts.oauth2)) {
    setTimeout(initSignIn, 200);          // the Google script is still loading
    return;
  }
  tokenClient = google.accounts.oauth2.initTokenClient({
    client_id: id,
    scope: SCOPE,
    callback: (resp) => {
      if (resp.error) { setStatus("Google sign-in failed: " + resp.error, true); return; }
      if (!google.accounts.oauth2.hasGrantedAllScopes(resp, SCOPE)) {
        setStatus("Lumenspar needs access to its own Drive folder to show your data. Sign in again and allow it.", true);
        return;
      }
      token = resp.access_token;
      load();
    },
    error_callback: (err) => setStatus(err && err.type === "popup_closed" ? "" : "Google sign-in did not finish.", false),
  });
  $("signin").disabled = false;
  $("signin-note").textContent = "";
}

async function drive(url) {
  const r = await fetch(url, { headers: { Authorization: "Bearer " + token } });
  if (r.status === 401) { token = ""; throw new Error("Your Google sign-in expired. Sign in again."); }
  if (!r.ok) {
    let msg = "";
    try { msg = (await r.json()).error.message; } catch { /* not JSON */ }
    throw new Error("Google Drive refused the request (" + r.status + (msg ? ": " + msg : "") + ")");
  }
  return r;
}

async function load() {
  setStatus("Reading your Lumenspar backup from Google Drive…");
  try {
    const q = new URLSearchParams({ spaces: "appDataFolder", pageSize: "1000", fields: "files(id,name,modifiedTime)" });
    const files = (await (await drive(DRIVE + "?" + q)).json()).files || [];
    const viewFiles = files.filter((f) => /^view-\d+\.json$/.test(f.name));
    if (!viewFiles.length) { showDiagnosis(files); return; }
    views = [];
    for (const f of viewFiles) {
      try {
        const v = await (await drive(DRIVE + "/" + encodeURIComponent(f.id) + "?alt=media")).json();
        if (v && v.uid) { v._modified = f.modifiedTime; views.push(v); }
      } catch (e) { console.warn("unreadable", f.name, e); }
    }
    views.sort((a, b) => (b.generated || "").localeCompare(a.generated || ""));
    current = 0;
    setStatus("");
    showContent();
  } catch (e) {
    setStatus(e.message, true);
    if (!token) showSignedOut();
  }
}

// Why there is nothing to show -- this also tells apart "not backed up yet"
// from the Drive folder being separate per sign-in client.
function showDiagnosis(files) {
  const d = $("diag");
  d.replaceChildren();
  $("welcome").hidden = true;
  $("signout").hidden = false;
  const others = files.filter((f) => /^(wishes|builds)-\d+\.json$/.test(f.name));
  if (others.length) {
    d.append(el("h2", {}, "Almost there"),
      el("p", {}, "Your backup is here, but it was made by an older Lumenspar. Update the desktop app and press ",
        el("b", {}, "Back up now"), " (Wish Counter → Google Drive backup), then reload this page."));
  } else {
    d.append(el("h2", {}, "No Lumenspar backup in this Google account yet"),
      el("p", {}, "If the desktop app is signed in to this same Google account and shows “last synced”, ",
        "this page cannot see the folder the app writes to. Please report it at ",
        el("a", { href: "https://github.com/Galog1/lumenspar/issues" }, "github.com/Galog1/lumenspar/issues"),
        " — it means the web viewer needs a different way to reach your backup."),
      el("p", { class: "dim" }, "Otherwise: in the desktop app, open Wish Counter → Google Drive backup, sign in with this account and press Back up now. Then reload this page."));
  }
  d.hidden = false;
  setStatus("");
}

function showSignedOut() {
  $("welcome").hidden = false;
  $("content").hidden = true;
  $("diag").hidden = true;
  $("account").hidden = true;
  $("signout").hidden = true;
}

// ── content ───────────────────────────────────────────────────────────────
function showContent() {
  $("welcome").hidden = true;
  $("diag").hidden = true;
  $("content").hidden = false;
  $("signout").hidden = !token;
  const sel = $("account");
  sel.replaceChildren(...views.map((v, i) => el("option", { value: i },
    (v.player && v.player.nickname ? v.player.nickname + " · " : "") + "UID " + v.uid)));
  sel.hidden = views.length < 2;
  sel.value = String(current);
  selectedBuild = 0;
  render();
}

function render() {
  const v = views[current];
  const p = v.player || {};
  const bits = [];
  if (p.nickname) bits.push(el("b", {}, p.nickname));
  bits.push("UID " + v.uid);
  if (p.level) bits.push("AR " + p.level);
  if (p.worldLevel) bits.push("WL " + p.worldLevel);
  if (p.abyss) bits.push("Abyss " + p.abyss);
  if (v.generated) bits.push("synced " + new Date(v.generated).toLocaleString());
  $("player").replaceChildren(...bits.flatMap((b, i) => (i ? [" · ", b] : [b])));
  renderWishes(v);
  renderBuilds(v);
}

// Share of decided 50/50s that were won, to one decimal (older backups have no precomputed rate).
function rate(won, lost) { return (Math.round((1000 * won) / (won + lost)) / 10).toString(); }

function pityColour(pity, hard) {
  const d = pity / Math.max(1, hard);
  return d <= 0.66 ? "var(--ok)" : d <= 0.83 ? "var(--r5)" : "var(--danger)";
}

function meter(label, value, max, colour) {
  return el("div", { class: "meter" },
    el("div", { class: "lbl" }, label),
    el("div", { class: "num" }, String(value), el("small", {}, " / " + max)),
    el("div", { class: "bar" }, el("i", { style: `width:${Math.min(100, (100 * value) / Math.max(1, max))}%;background:${colour}` })));
}

function renderWishes(v) {
  const box = $("tab-wishes");
  box.replaceChildren();
  if (!v.banners || !v.banners.length) {
    box.append(el("p", { class: "dim" }, "No wish history backed up for this account yet."));
    return;
  }
  const won = v.banners.reduce((t, b) => t + (b.hasFiftyFifty ? b.won : 0), 0);
  const lost = v.banners.reduce((t, b) => t + (b.hasFiftyFifty ? b.lost : 0), 0);
  box.append(el("p", { class: "dim small" },
    `${(v.totalWishes || 0).toLocaleString()} wishes on record` +
    (v.wishesUpdated ? " · last imported " + new Date(v.wishesUpdated).toLocaleString() : "") +
    (won + lost ? ` · average 50/50 win rate ${rate(won, lost)}% (won ${won} · lost ${lost})` : "")));
  const grid = el("div", { class: "banners" });
  for (const b of v.banners) {
    const pulls = el("div", { class: "pulls" }, ...(b.fives || []).map((f) => {
      const res = ["won", "lost", "guaranteed"].includes(f.result) ? f.result : "";
      return el("div", { class: "pull " + res, title: `${f.name}\n${f.time}${f.result ? " · " + f.result : ""}` },
        el("div", { class: "art" },
          img(f.iconName, f.name),
          res && el("span", { class: "res " + res }, res === "guaranteed" ? "guar." : res),
          el("span", { class: "pity", style: "background:" + pityColour(f.pity, b.hardPity) }, String(f.pity))),
        el("div", { class: "name" }, f.name));
    }));
    grid.append(el("article", { class: "banner" },
      el("h2", {}, b.label),
      el("div", { class: "sub" }, `${b.total.toLocaleString()} wishes · ${b.primogems.toLocaleString()} primogems`),
      el("div", { class: "meters" },
        meter("5★ pity", b.pity5, b.hardPity, "var(--r5)"),
        meter("4★ pity", b.pity4, 10, "var(--r4)")),
      b.hasFiftyFifty && el("div", { class: "badges" },
        el("span", { class: "badge" + (b.guaranteed ? " guar" : "") },
          b.guaranteed ? "Next 5★ guaranteed featured" : "Next 5★ is a 50/50"),
        el("span", {}, `50/50: won ${b.won} · lost ${b.lost}` + (b.won + b.lost ? ` · ${rate(b.won, b.lost)}% win rate` : ""))),
      el("div", { class: "dim small" },
        `5★ ×${b.fiveCount} · 4★ ×${b.fourCount}` + (b.fiveCount ? ` · average 5★ pity ${b.averagePity}` : "")),
      b.scheduleStale && el("div", { class: "stale" }, "A 5★ is newer than the banner data, so its 50/50 result is unknown."),
      (b.fives || []).length ? pulls : null));
  }
  box.append(grid);
}

function renderBuilds(v) {
  const box = $("tab-builds");
  box.replaceChildren();
  const builds = v.builds || [];
  if (!builds.length) {
    box.append(el("p", { class: "dim" }, "No build cards backed up for this account yet. Fetch your showcase in the desktop app's Build Cards."));
    return;
  }
  selectedBuild = Math.min(selectedBuild, builds.length - 1);
  box.append(el("div", { class: "chips" }, ...builds.map((b, i) =>
    el("button", { class: "chip", type: "button", "aria-pressed": String(i === selectedBuild),
                   style: "--tint:" + (ELEMENT[b.element] || "var(--accent)"),
                   onclick: () => { selectedBuild = i; renderBuilds(v); } },
      img(b.icon, ""), el("span", {}, b.name)))));
  box.append(el("div", { class: "metric" },
    el("span", {}, "Artifact score"),
    ...["cv", "rv"].map((m) => el("button", { type: "button", "aria-pressed": String(metric === m),
      onclick: () => { metric = m; storageSet(METRIC_KEY, m); renderBuilds(v); } }, m.toUpperCase()))));
  box.append(card(withRolls(builds[selectedBuild])));
}

function card(b) {
  const tint = ELEMENT[b.element] || "#4FD8E8";
  const w = b.weapon;
  const cons = el("div", { class: "cons" },
    ...[1, 2, 3, 4, 5, 6].map((n) => el("i", { class: n <= b.constellation ? "on" : "" }, String(n))),
    el("b", {}, "C" + b.constellation));
  const talents = el("div", { class: "talents" }, ...(b.talents || []).map((t) =>
    el("div", { class: t.boosted ? "up" : "" },
      el("small", {}, t.slot === "auto" ? "Normal" : t.slot === "skill" ? "Skill" : "Burst"),
      el("strong", {}, String(t.level)))));
  const rv = metric === "rv";
  const hero = el("div", { class: "hero", style: b.splash ? `--splash:url("${asset(b.splash)}")` : "" },
    el("div", { class: "who" },
      el("div", { class: "tags" }, el("span", { class: "elem" }, (b.element || "").toUpperCase()),
        el("span", { class: "stars" }, "★".repeat(b.rarity || 0))),
      el("h2", {}, b.name),
      el("div", { class: "lv" }, `Lv. ${b.level} / ${b.maxLevel}` + (b.friendship > 0 ? ` · Friendship ${b.friendship}` : "")),
      cons, talents));
  const mid = el("div", { class: "mid" },
    el("div", { class: "weapon" },
      el("div", { class: "ico" }, w && img(w.icon, w.name)),
      el("div", {},
        el("b", {}, w ? w.name : "No weapon"),
        w && el("div", { class: "ref", style: "color:" + (w.rarity >= 5 ? "var(--r5)" : w.rarity === 4 ? "var(--r4)" : "var(--dim)") },
          `Lv. ${w.level}` + (w.refinement > 0 ? `  R${w.refinement}` : "")),
        w && el("div", { class: "ws" }, (w.stats || []).map((s) => `${s.label} ${s.text}`).join(" · ")))),
    el("hr"),
    el("div", { class: "stats" }, ...(b.stats || []).map((s) => el("div", {}, el("span", {}, s.label), el("b", {}, s.text)))),
    el("hr"),
    el("div", { class: "cv" }, el("span", {}, rv ? "Roll Value" : "Crit Value"),
      el("b", {}, rv ? pct(b.rv) : (b.critValue || 0).toFixed(1))),
    rv && el("div", { class: "cv-note" }, "Share of a perfect roll, counting " + b.rvLabels),
    el("div", { class: "sets" }, ...(b.sets || []).map((s) =>
      el("div", { title: (s.bonuses || []).join("\n\n") }, el("i", {}, s.count >= 4 ? "4" : "2"), s.name))));
  const arts = el("div", { class: "arts" }, ...(b.artifacts || []).map((a) =>
    el("div", { class: "art" },
      el("div", {}, el("div", { class: "art-ico" }, img(a.icon, a.slot)), el("div", { class: "lvl" }, "+" + a.level)),
      el("div", { class: "main" },
        el("small", {}, a.main.label), el("b", {}, a.main.text),
        el("div", { class: "acv" }, rv ? "RV " + pct(a.rv) : "CV " + (a.critValue || 0).toFixed(1))),
      el("div", { class: "subs" }, ...(a.subs || []).map((s) => {
        const hot = rv ? s.counted : s.key === "critRate_" || s.key === "critDMG_";
        return el("div", { class: hot ? "crit" : "" },
          el("span", {}, s.label.replace("Elemental Mastery", "EM").replace("Energy Recharge", "ER")),
          el("b", {}, s.text),
          rv ? el("span", { class: "dots", title: "share of a perfect roll" }, pct(s.rv))
             : el("span", { class: "dots", title: s.rolls + " roll(s)" }, "•".repeat(Math.max(0, s.rolls))));
      })))));
  const noArts = !(b.artifacts || []).length;
  return el("div", {},
    el("article", { class: "card", style: "--tint:" + tint }, hero, mid,
      noArts ? el("div", { class: "arts empty" }, el("p", {}, "No artifacts equipped")) : arts),
    el("p", { class: "card-foot" }, "Read " + new Date((b.fetchedAt || 0) * 1000).toLocaleString()));
}

// ── wiring ────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  $("signin").addEventListener("click", () => tokenClient && tokenClient.requestAccessToken({ prompt: token ? "" : "select_account" }));
  $("signout").addEventListener("click", () => {
    if (token && window.google) google.accounts.oauth2.revoke(token, () => {});
    token = ""; views = [];
    showSignedOut();
    setStatus("Signed out.");
  });
  $("account").addEventListener("change", (e) => { current = Number(e.target.value); selectedBuild = 0; render(); });
  $("client-save").addEventListener("click", () => {
    storageSet(OWN_CLIENT_KEY, $("client-id").value.trim());
    initSignIn();
    setStatus(clientId() ? "Client ID saved in this browser." : "Using Lumenspar's own sign-in.");
  });
  for (const t of document.querySelectorAll(".tabs button")) {
    t.addEventListener("click", () => {
      for (const o of document.querySelectorAll(".tabs button")) o.setAttribute("aria-selected", String(o === t));
      $("tab-wishes").hidden = t.dataset.tab !== "wishes";
      $("tab-builds").hidden = t.dataset.tab !== "builds";
    });
  }
  initSignIn();
});

// For previewing with a local file during development: lumensparShow([view, ...]).
window.lumensparShow = (list) => { views = list; current = 0; showContent(); };
