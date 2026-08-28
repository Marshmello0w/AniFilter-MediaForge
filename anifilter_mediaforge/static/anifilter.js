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
  let suppressNativeCloseUrl = false;

  const esc = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  }[char]));
  const proxy = (url) => {
    if (!url) return "";
    if (url.startsWith("/api/img?")) return url;
    return typeof window.proxyImg === "function"
      ? window.proxyImg(url)
      : `/api/img?url=${encodeURIComponent(url)}`;
  };
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
      return `<button type="button" class="mf-poster-card af-card" data-anime="${esc(item.slug)}" data-url="${esc(item.url)}">
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
      $('afReleaseRail').innerHTML = data.items.map((item) => `<button type="button" class="af-release-card" data-anime="${esc(item.slug)}" data-url="${esc(item.url)}">
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

  async function openAnime(slug, historyMode = "push", knownUrl = "") {
    state.anime = slug;
    writeUrl(historyMode);
    try {
      let seriesUrl = knownUrl;
      let title = slug;
      if (!seriesUrl) {
        const response = await fetch(animeApi(slug));
        const item = await response.json();
        if (!response.ok) throw new Error(item.error || "Details nicht verfügbar");
        seriesUrl = item.url;
        title = item.title || title;
      }
      if (typeof window.openSeries !== "function") {
        throw new Error("Die native MediaForge-Detailansicht ist nicht verfügbar");
      }
      await window.openSeries(seriesUrl);
    } catch (error) {
      state.anime = "";
      writeUrl("replace");
      notify(error.message, true);
    }
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
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-anime]");
    if (button) openAnime(button.dataset.anime, "push", button.dataset.url || "");
  });

  const coreCloseModal = typeof window.closeModal === "function" ? window.closeModal : null;
  if (coreCloseModal) {
    window.closeModal = function (...args) {
      const result = coreCloseModal.apply(this, args);
      if (!suppressNativeCloseUrl && state.anime) {
        state.anime = "";
        writeUrl("push");
      }
      return result;
    };
  }

  window.addEventListener("popstate", () => {
    const was = state.anime;
    readUrl();
    syncControls();
    loadCatalogue();
    if (state.anime && state.anime !== was) {
      openAnime(state.anime, "replace");
    } else if (!state.anime && was && coreCloseModal) {
      suppressNativeCloseUrl = true;
      coreCloseModal();
      suppressNativeCloseUrl = false;
    }
  });

  readUrl(); syncControls(); loadCatalogue(); loadReleases(); loadStatus(); setInterval(loadStatus, 20000);
  if (state.anime) openAnime(state.anime, "replace");
})();
