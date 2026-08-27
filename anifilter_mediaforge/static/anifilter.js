(() => {
  "use strict";
  const cfg = window.ANIFILTER_CONFIG || {};
  const $ = (id) => document.getElementById(id);
  if (!$('afApp')) return;

  const state = {
    q: "", include: new Set(), exclude: new Set(), genreMode: "all",
    ageMode: "all", ages: new Set(), ageMax: "", sort: "title_asc",
    page: 1, perPage: 36, anime: "", facets: { genres: [], ages: [] },
  };
  let requestSeq = 0;
  let queryTimer = 0;
  let lastFocus = null;

  const esc = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  }[char]));
  const proxy = (url) => url ? `/api/img?url=${encodeURIComponent(url)}` : "";
  const animeApi = (slug) => cfg.animeBase.replace("__slug__", encodeURIComponent(slug));

  function readUrl() {
    const p = new URLSearchParams(location.search);
    state.q = p.get("q") || "";
    state.include = new Set((p.get("genres") || "").split(",").filter(Boolean));
    state.exclude = new Set((p.get("exclude") || "").split(",").filter(Boolean));
    state.genreMode = p.get("genre_mode") === "any" ? "any" : "all";
    state.ageMode = ["exact", "max"].includes(p.get("age_mode")) ? p.get("age_mode") : "all";
    state.ages = new Set((p.get("ages") || "").split(",").filter((v) => /^\d+$/.test(v)));
    state.ageMax = /^\d+$/.test(p.get("age_max") || "") ? p.get("age_max") : "";
    state.sort = ["title_desc", "year_desc", "year_asc", "updated_desc"].includes(p.get("sort")) ? p.get("sort") : "title_asc";
    state.page = Math.max(1, Number(p.get("page")) || 1);
    state.anime = p.get("anime") || "";
  }

  function writeUrl(mode = "replace") {
    const p = new URLSearchParams();
    if (state.q) p.set("q", state.q);
    if (state.include.size) p.set("genres", [...state.include].join(","));
    if (state.exclude.size) p.set("exclude", [...state.exclude].join(","));
    if (state.genreMode !== "all") p.set("genre_mode", state.genreMode);
    if (state.ageMode !== "all") p.set("age_mode", state.ageMode);
    if (state.ageMode === "exact" && state.ages.size) p.set("ages", [...state.ages].join(","));
    if (state.ageMode === "max" && state.ageMax) p.set("age_max", state.ageMax);
    if (state.sort !== "title_asc") p.set("sort", state.sort);
    if (state.page > 1) p.set("page", String(state.page));
    if (state.anime) p.set("anime", state.anime);
    const next = `${location.pathname}${p.size ? `?${p}` : ""}`;
    history[mode === "push" ? "pushState" : "replaceState"]({}, "", next);
  }

  function syncControls() {
    $('afQuery').value = state.q;
    $('afSort').value = state.sort;
    [...$('afGenreMode').querySelectorAll("button")].forEach((b) => b.classList.toggle("active", b.dataset.value === state.genreMode));
    [...$('afAgeMode').querySelectorAll("button")].forEach((b) => b.classList.toggle("active", b.dataset.value === state.ageMode));
    $('afExactAges').hidden = state.ageMode !== "exact";
    $('afMaxAgeField').hidden = state.ageMode !== "max";
    if (state.ageMax) $('afMaxAge').value = state.ageMax;
    renderGenres();
    renderAges();
    const active = state.include.size + state.exclude.size + (state.ageMode !== "all" ? 1 : 0) + (state.q ? 1 : 0);
    $('afFilterSummary').textContent = active ? `${active} Filter aktiv` : "Keine Filter aktiv";
  }

  function renderGenres() {
    const needle = $('afGenreSearch').value.trim().toLocaleLowerCase("de");
    const genres = state.facets.genres.filter((g) => g.toLocaleLowerCase("de").includes(needle));
    $('afGenres').innerHTML = genres.map((genre) => {
      const cls = state.include.has(genre) ? " is-include" : state.exclude.has(genre) ? " is-exclude" : "";
      const pressed = state.include.has(genre) ? "true" : state.exclude.has(genre) ? "mixed" : "false";
      return `<button type="button" class="af-genre${cls}" data-genre="${esc(genre)}" aria-pressed="${pressed}">${esc(genre)}</button>`;
    }).join("") || '<span class="af-help">Kein Genre gefunden.</span>';
  }

  function renderAges() {
    const ages = state.facets.ages || [];
    $('afExactAges').innerHTML = ages.map((age) => `<label class="af-age"><input type="checkbox" value="${age}" ${state.ages.has(String(age)) ? "checked" : ""}><span>FSK ${age}</span></label>`).join("");
    $('afMaxAge').innerHTML = ages.map((age) => `<option value="${age}">Bis FSK ${age}</option>`).join("");
    if (!state.ageMax && ages.length) state.ageMax = String(ages[ages.length - 1]);
    $('afMaxAge').value = state.ageMax;
  }

  function params() {
    const p = new URLSearchParams({
      q: state.q, include: [...state.include].join(","), exclude: [...state.exclude].join(","),
      genre_mode: state.genreMode, age_mode: state.ageMode, ages: [...state.ages].join(","),
      age_max: state.ageMax, sort: state.sort, page: String(state.page), per_page: String(state.perPage),
    });
    return p;
  }

  async function loadCatalogue() {
    const seq = ++requestSeq;
    $('afGrid').classList.add("is-loading");
    try {
      const response = await fetch(`${cfg.catalogue}?${params()}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Katalog konnte nicht geladen werden");
      if (seq !== requestSeq) return;
      state.facets = data.facets || state.facets;
      state.page = data.page;
      renderResults(data);
      syncControls();
      writeUrl();
    } catch (error) {
      if (seq !== requestSeq) return;
      $('afGrid').innerHTML = `<div class="mf-empty is-error"><div class="mf-empty-title">Katalog nicht verfügbar</div><p class="mf-empty-hint">${esc(error.message)}</p></div>`;
    } finally {
      if (seq === requestSeq) $('afGrid').classList.remove("is-loading");
    }
  }

  function renderResults(data) {
    $('afCount').textContent = `${data.total.toLocaleString("de-DE")} Anime gefunden`;
    $('afEmpty').hidden = data.items.length !== 0;
    $('afGrid').innerHTML = data.items.map((item) => {
      const art = item.poster_url
        ? `<img src="${esc(proxy(item.poster_url))}" alt="" loading="lazy">`
        : '<span class="af-poster-placeholder" aria-hidden="true">Kein Cover</span>';
      const fsk = item.age_rating == null ? "FSK —" : `FSK ${item.age_rating}`;
      return `<button type="button" class="mf-poster-card af-card" data-anime="${esc(item.slug)}">
        <span class="mf-poster-art">${art}<span class="mf-poster-scrim"></span></span>
        <span class="mf-poster-meta"><strong class="mf-poster-title">${esc(item.title)}</strong>
          <span class="mf-poster-foot"><span>${esc(item.release_year || "Jahr —")}</span><span>${fsk}</span></span>
        </span></button>`;
    }).join("");
    $('afPagination').hidden = data.pages <= 1;
    $('afPageCount').textContent = `Seite ${data.page} von ${data.pages}`;
    $('afPrev').disabled = data.page <= 1;
    $('afNext').disabled = data.page >= data.pages;
  }

  async function loadReleases() {
    try {
      const response = await fetch(`${cfg.releases}?limit=6`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Releases nicht verfügbar");
      if (!data.items.length) {
        $('afReleaseRail').innerHTML = '<div class="mf-empty"><p class="mf-empty-hint">Noch keine bestätigten deutschen Releases erfasst.</p></div>';
        return;
      }
      $('afReleaseRail').innerHTML = data.items.map((item) => `<button type="button" class="af-release-card" data-anime="${esc(item.slug)}">
        ${item.poster_url ? `<img src="${esc(proxy(item.poster_url))}" alt="" loading="lazy">` : '<span class="af-poster-placeholder" style="aspect-ratio:2/3">Kein Cover</span>'}
        <span class="af-period">${esc(item.period_label)}</span>
        <span class="af-release-card-body"><strong>${esc(item.title)}</strong><span>${esc(item.released_on)} · S${item.season} E${item.episode}</span></span>
      </button>`).join("");
    } catch (error) {
      $('afReleaseRail').innerHTML = `<div class="mf-empty is-error"><p class="mf-empty-hint">${esc(error.message)}</p></div>`;
    }
  }

  async function loadStatus() {
    try {
      const response = await fetch(cfg.status);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Statusfehler");
      $('afScanText').textContent = `${data.completed.toLocaleString("de-DE")} von ${data.found.toLocaleString("de-DE")} Details · ${data.genres} Genres · ${data.errors} Fehler`;
      $('afScan').classList.toggle("is-done", data.found > 0 && data.pending === 0);
      $('afScan').classList.toggle("is-error", Boolean(data.catalogue_error));
    } catch (error) {
      $('afScanText').textContent = error.message;
      $('afScan').classList.add("is-error");
    }
  }

  async function openAnime(slug, historyMode = "push") {
    lastFocus = document.activeElement;
    state.anime = slug;
    writeUrl(historyMode);
    $('afModal').hidden = false;
    document.body.style.overflow = "hidden";
    $('afDetail').innerHTML = '<div class="af-detail-art mf-skeleton"></div><div class="af-detail-body"><h2 id="afModalTitle">Anime wird geladen …</h2><div class="mf-skeleton-text is-medium"></div></div>';
    $('afModal').querySelector(".af-modal-panel").focus();
    try {
      const response = await fetch(animeApi(slug));
      const item = await response.json();
      if (!response.ok) throw new Error(item.error || "Details nicht verfügbar");
      renderDetail(item);
      loadSeasons(item);
    } catch (error) {
      $('afDetail').innerHTML = `<div class="mf-empty is-error"><div class="mf-empty-title">Details nicht verfügbar</div><p class="mf-empty-hint">${esc(error.message)}</p></div>`;
    }
  }

  function renderDetail(item) {
    const meta = [item.release_year, item.age_rating == null ? "FSK nicht angegeben" : `FSK ${item.age_rating}`, item.rating ? `Bewertung ${item.rating}` : ""].filter(Boolean);
    $('afDetail').innerHTML = `<div class="af-detail-art">${item.poster_url ? `<img src="${esc(proxy(item.poster_url))}" alt="Cover von ${esc(item.title)}">` : '<span class="af-poster-placeholder" style="aspect-ratio:2/3">Kein Cover</span>'}</div>
      <div class="af-detail-body">
        <h2 id="afModalTitle">${esc(item.title)}</h2>
        <div class="af-detail-meta">${meta.map((v) => `<span class="badge badge-neutral">${esc(v)}</span>`).join("")}</div>
        <div class="af-detail-genres">${item.genres.map((g) => `<span class="badge badge-accent">${esc(g)}</span>`).join("")}</div>
        <p class="af-detail-description">${esc(item.description || "AniWorld enthält noch keine Beschreibung für diesen Titel.")}</p>
        <div class="af-detail-actions">
          <a class="btn btn-secondary" href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">Auf AniWorld öffnen</a>
          <button class="btn btn-primary" type="button" id="afAutoSync">Zu Auto-Sync</button>
        </div>
        <section class="af-episodes"><div class="af-section-head"><div><h3>Staffeln und Episoden</h3><p>Wähle Episoden für die MediaForge-Queue.</p></div><select id="afSeason" aria-label="Staffel"></select></div><div id="afEpisodeHost"><span class="af-help">Staffeln werden geladen …</span></div></section>
      </div>`;
    $('afAutoSync').addEventListener("click", () => addAutoSync(item));
  }

  async function loadSeasons(item) {
    const host = $('afEpisodeHost');
    try {
      const response = await fetch(`/api/seasons?url=${encodeURIComponent(item.url)}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Staffeln nicht verfügbar");
      const select = $('afSeason');
      select.innerHTML = (data.seasons || []).map((season, index) => `<option value="${index}">${season.are_movies ? "Filme" : `Staffel ${season.season_number}`} · ${season.episode_count} Episoden</option>`).join("");
      if (!data.seasons?.length) { host.innerHTML = '<span class="af-help">Keine Staffeln gefunden.</span>'; return; }
      const open = () => loadEpisodes(item, data.seasons[Number(select.value) || 0]);
      select.addEventListener("change", open);
      open();
    } catch (error) { host.innerHTML = `<span class="af-help">${esc(error.message)}</span>`; }
  }

  async function loadEpisodes(item, season) {
    const host = $('afEpisodeHost');
    host.innerHTML = '<span class="af-help">Episoden werden geladen …</span>';
    try {
      const response = await fetch(`/api/episodes?url=${encodeURIComponent(season.url)}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Episoden nicht verfügbar");
      host.innerHTML = `<div class="af-episode-list">${(data.episodes || []).map((episode) => `<label class="af-episode"><input type="checkbox" value="${esc(episode.url)}" ${episode.downloaded ? "disabled" : "checked"}><span><strong>Episode ${episode.episode_number}</strong>${episode.title_de ? ` · ${esc(episode.title_de)}` : ""}${episode.downloaded ? " · bereits vorhanden" : ""}</span></label>`).join("")}</div><div class="af-detail-actions"><button type="button" class="btn btn-primary" id="afQueue">Ausgewählte zur Queue</button><button type="button" class="btn btn-ghost" id="afToggleEpisodes">Auswahl umkehren</button></div>`;
      $('afToggleEpisodes').addEventListener("click", () => host.querySelectorAll('input[type="checkbox"]:not(:disabled)').forEach((box) => { box.checked = !box.checked; }));
      $('afQueue').addEventListener("click", () => queueEpisodes(item, host));
    } catch (error) { host.innerHTML = `<span class="af-help">${esc(error.message)}</span>`; }
  }

  async function queueEpisodes(item, host) {
    const button = $('afQueue');
    const episodes = [...host.querySelectorAll('input[type="checkbox"]:checked')].map((box) => box.value);
    if (!episodes.length) { notify("Wähle mindestens eine Episode.", true); return; }
    button.disabled = true; button.classList.add("is-loading"); button.textContent = "Wird eingereiht …";
    try {
      const response = await fetch("/api/download", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: item.title, series_url: item.url, episodes, language: "German Dub", provider: "VOE" }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Queue-Aktion fehlgeschlagen");
      button.textContent = "Zur Queue hinzugefügt"; button.classList.add("is-success-state");
      notify(`${episodes.length} Episoden wurden zur Queue hinzugefügt.`);
    } catch (error) { button.disabled = false; button.classList.remove("is-loading"); button.classList.add("is-error-state"); button.textContent = "Erneut versuchen"; notify(error.message, true); }
  }

  async function addAutoSync(item) {
    const button = $('afAutoSync');
    button.disabled = true; button.classList.add("is-loading"); button.textContent = "Wird angelegt …";
    try {
      const response = await fetch("/api/autosync", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: item.title, series_url: item.url, language: "German Dub", provider: "VOE", cover_url: item.poster_url || "" }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Auto-Sync konnte nicht angelegt werden");
      button.textContent = "Auto-Sync aktiv"; button.classList.add("is-success-state"); notify("Auto-Sync wurde angelegt.");
    } catch (error) { button.disabled = false; button.classList.remove("is-loading"); button.classList.add("is-error-state"); button.textContent = "Erneut versuchen"; notify(error.message, true); }
  }

  function closeModal(historyMode = "push") {
    $('afModal').hidden = true; document.body.style.overflow = ""; state.anime = ""; writeUrl(historyMode);
    if (lastFocus?.focus) lastFocus.focus();
  }
  function notify(message, isError = false) {
    if (typeof window.showToast === "function") window.showToast(message, isError ? "error" : "success");
    else if (isError) window.alert(message);
  }

  $('afGenres').addEventListener("click", (event) => {
    const button = event.target.closest("[data-genre]"); if (!button) return;
    const genre = button.dataset.genre;
    if (state.include.has(genre)) { state.include.delete(genre); state.exclude.add(genre); }
    else if (state.exclude.has(genre)) state.exclude.delete(genre);
    else state.include.add(genre);
    state.page = 1; syncControls(); loadCatalogue();
  });
  $('afGenreSearch').addEventListener("input", renderGenres);
  $('afGenreMode').addEventListener("click", (event) => { const b = event.target.closest("button[data-value]"); if (!b) return; state.genreMode = b.dataset.value; state.page = 1; syncControls(); loadCatalogue(); });
  $('afAgeMode').addEventListener("click", (event) => { const b = event.target.closest("button[data-value]"); if (!b) return; state.ageMode = b.dataset.value; state.page = 1; syncControls(); loadCatalogue(); });
  $('afExactAges').addEventListener("change", (event) => { if (!event.target.matches("input")) return; event.target.checked ? state.ages.add(event.target.value) : state.ages.delete(event.target.value); state.page = 1; loadCatalogue(); });
  $('afMaxAge').addEventListener("change", () => { state.ageMax = $('afMaxAge').value; state.page = 1; loadCatalogue(); });
  $('afQuery').addEventListener("input", () => { clearTimeout(queryTimer); state.q = $('afQuery').value.trim(); state.page = 1; writeUrl(); queryTimer = setTimeout(loadCatalogue, 220); });
  $('afSort').addEventListener("change", () => { state.sort = $('afSort').value; state.page = 1; loadCatalogue(); });
  $('afPrev').addEventListener("click", () => { state.page--; loadCatalogue(); scrollTo({ top: $('afGrid').getBoundingClientRect().top + scrollY - 100, behavior: "smooth" }); });
  $('afNext').addEventListener("click", () => { state.page++; loadCatalogue(); scrollTo({ top: $('afGrid').getBoundingClientRect().top + scrollY - 100, behavior: "smooth" }); });
  $('afReset').addEventListener("click", () => { Object.assign(state, { q: "", include: new Set(), exclude: new Set(), genreMode: "all", ageMode: "all", ages: new Set(), ageMax: "", sort: "title_asc", page: 1 }); $('afGenreSearch').value = ""; syncControls(); loadCatalogue(); });
  $('afShowGer').addEventListener("click", () => { state.include = new Set(["Ger"]); state.exclude.clear(); state.genreMode = "all"; state.page = 1; syncControls(); loadCatalogue(); $('afGrid').scrollIntoView({ behavior: "smooth", block: "start" }); });
  $('afMobileFilter').addEventListener("click", () => { const open = $('afFilters').classList.toggle("is-open"); $('afMobileFilter').setAttribute("aria-expanded", String(open)); });
  document.addEventListener("click", (event) => { const button = event.target.closest("[data-anime]"); if (button) openAnime(button.dataset.anime); });
  $('afModal').addEventListener("click", (event) => { if (event.target.closest("[data-close]")) closeModal(); });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !$('afModal').hidden) closeModal(); });
  window.addEventListener("popstate", () => { const was = state.anime; readUrl(); syncControls(); loadCatalogue(); if (state.anime && state.anime !== was) openAnime(state.anime, "replace"); else if (!state.anime && !$('afModal').hidden) { $('afModal').hidden = true; document.body.style.overflow = ""; } });

  readUrl(); syncControls(); loadCatalogue(); loadReleases(); loadStatus(); setInterval(loadStatus, 20000);
  if (state.anime) openAnime(state.anime, "replace");
})();

