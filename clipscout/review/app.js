"use strict";
// Clipscout review page: watch the suggested clips, keep or skip them, nudge their edges, export.

const COLORS = ["#ff7ab6", "#b48cff", "#5fd3c8", "#f5c46b", "#7aa2ff", "#f0707f", "#9fe07a", "#c9c3d3"];
const $ = (id) => document.getElementById(id);
let project = null;
let sort = "time", onlyOpen = false;
const hidden = new Set();
const color = {};

const fmt = (s) => {
    s = Math.max(0, s);
    const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, sec = (s % 60).toFixed(1).padStart(4, "0");
    return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
};
const label = (k) => k.replace(/_/g, " ");

function toast(text, ms = 4000) {
    const t = $("toast");
    t.textContent = text;
    t.hidden = false;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => { t.hidden = true; }, ms);
}

async function api(path, body) {
    const res = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || res.statusText);
    return data;
}

function renderHeader() {
    const name = project.video.split(/[\\/]/).pop();
    $("title").textContent = name;
    const kept = project.clips.filter((c) => c.keep === true).length;
    $("meta").textContent = `${project.game} · ${fmt(project.duration)} · ${project.events.length} events · ${project.clips.length} clips · ${kept} kept`;
    const kinds = [...new Set(project.events.map((e) => e.kind))];
    kinds.forEach((k, i) => { color[k] ??= COLORS[i % COLORS.length]; });
    $("filters").innerHTML = kinds.map((k) =>
        `<button class="chip" data-kind="${k}" aria-pressed="${!hidden.has(k)}"><span class="dot" style="background:${color[k]}"></span>${label(k)}</button>`).join("");
}

function renderTimeline() {
    const d = project.duration || 1;
    const pct = (t) => `${(t / d) * 100}%`;
    $("timeline").innerHTML =
        project.clips.map((c) => `<div class="range ${c.keep === true ? "kept" : c.keep === false ? "skipped" : ""}" data-id="${c.id}" style="left:${pct(c.start)};width:${pct(c.end - c.start)}" title="${c.title}"></div>`).join("") +
        project.events.map((e) => `<div class="tick" style="left:${pct(e.t)};background:${color[e.kind]}" title="${label(e.kind)} · ${fmt(e.t)}"></div>`).join("");
}

function visibleClips() {
    let list = project.clips.filter((c) => c.events.some((e) => !hidden.has(e.kind)));
    if (onlyOpen) list = list.filter((c) => c.keep == null);
    return sort === "score" ? [...list].sort((a, b) => b.score - a.score) : list;
}

function fillCard(card, c) {
    card.dataset.id = c.id;
    card.classList.toggle("kept", c.keep === true);
    card.classList.toggle("skipped", c.keep === false);
    card.querySelector("h2").textContent = c.title;
    card.querySelector(".score").textContent = c.score.toFixed(1);
    card.querySelector(".time").textContent = `${fmt(c.start)} – ${fmt(c.end)} · ${(c.end - c.start).toFixed(0)} s`;
    card.querySelector(".events").innerHTML = c.events.map((e) =>
        `<button class="ev" data-seek="${(e.t - c.start).toFixed(2)}" style="box-shadow: inset 3px 0 ${color[e.kind]}">${label(e.kind)} ${fmt(e.t - c.start)}</button>`).join("");
}

function renderGrid() {
    const grid = $("grid");
    const clips = visibleClips();
    grid.replaceChildren(...clips.map((c) => {
        const card = $("card").content.firstElementChild.cloneNode(true);
        card.querySelector("video").src = `/clips/${c.id}.mp4?v=${c.start}-${c.end}`;
        fillCard(card, c);
        return card;
    }));
    $("empty").hidden = clips.length > 0;
}

function renderAll() {
    renderHeader();
    renderTimeline();
    renderGrid();
}

async function update(id, change) {
    const clip = project.clips.find((c) => c.id === id);
    const updated = await api("/api/clip", { id, ...change });
    Object.assign(clip, updated);
    const card = document.querySelector(`.card[data-id="${id}"]`);
    if (card) {
        fillCard(card, clip);
        if ("start" in change || "end" in change) card.querySelector("video").src = `/clips/${id}.mp4?v=${clip.start}-${clip.end}`;
    }
    renderHeader();
    renderTimeline();
}

document.addEventListener("click", async (e) => {
    const b = e.target.closest("button");
    const card = e.target.closest(".card");
    try {
        if (b?.dataset.keep && card) {
            const clip = project.clips.find((c) => c.id === card.dataset.id);
            const want = b.dataset.keep === "true";
            await update(card.dataset.id, { keep: clip.keep === want ? null : want });
        } else if (b?.dataset.trim && card) {
            const clip = project.clips.find((c) => c.id === card.dataset.id);
            b.disabled = true;
            await update(card.dataset.id, { [b.dataset.trim]: clip[b.dataset.trim] + Number(b.dataset.d) });
        } else if (b?.dataset.seek && card) {
            const v = card.querySelector("video");
            v.currentTime = Math.max(0, Number(b.dataset.seek) - 1.5);
            v.play();
        } else if (b?.dataset.kind) {
            hidden.has(b.dataset.kind) ? hidden.delete(b.dataset.kind) : hidden.add(b.dataset.kind);
            renderHeader();
            renderGrid();
        } else if (b?.dataset.sort) {
            sort = b.dataset.sort;
            document.querySelectorAll("[data-sort]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
            renderGrid();
        } else if (b?.dataset.show) {
            onlyOpen = !onlyOpen;
            b.setAttribute("aria-pressed", String(onlyOpen));
            renderGrid();
        } else if (e.target.closest(".range")) {
            document.querySelector(`.card[data-id="${e.target.closest(".range").dataset.id}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
        }
    } catch (err) {
        toast(err.message);
    } finally {
        if (b) b.disabled = false;
    }
});

// K = keep, X = skip on the focused card.
document.addEventListener("keydown", (e) => {
    const card = document.activeElement?.closest?.(".card");
    if (!card || e.target.tagName === "VIDEO" && e.key === " ") return;
    if (e.key === "k" || e.key === "x") card.querySelector(`[data-keep="${e.key === "k"}"]`).click();
});

$("export").addEventListener("click", async () => {
    const btn = $("export");
    btn.disabled = true;
    btn.textContent = "Exporting…";
    try {
        const r = await api("/api/export", { accurate: $("accurate").checked });
        toast(`Exported ${r.files.length} clip${r.files.length === 1 ? "" : "s"} to ${r.folder}`, 8000);
    } catch (err) {
        toast(err.message, 6000);
    } finally {
        btn.disabled = false;
        btn.textContent = "Export kept clips";
    }
});

api("/api/project").then((p) => { project = p; renderAll(); }).catch((err) => toast(err.message));
