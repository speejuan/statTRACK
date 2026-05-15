'use strict';

// ── Toast ─────────────────────────────────────────────────────────────────
function showToast(msg, isError = false) {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = msg;
  el.className = isError ? 'error show' : 'success show';
  clearTimeout(el._timer);
  el._timer = setTimeout(() => { el.className = isError ? 'error' : 'success'; }, 3000);
}

// ── API helper ─────────────────────────────────────────────────────────────
async function apiFetch(url, method = 'GET', body = null) {
  const opts = {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
  };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(url, opts);
  const json = await res.json();
  if (!res.ok) throw new Error(json.error || `HTTP ${res.status}`);
  return json;
}

// ── Event delegation for data-action buttons ──────────────────────────────
document.addEventListener('click', e => {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  const action = btn.dataset.action;
  const d = btn.dataset;

  if (action === 'edit-library') {
    openEditModal(+d.id, d.title, d.type, d.status, d.rating || null, d.notes || '', d.coverUrl || '');
  }
  if (action === 'delete-library') {
    deleteLibraryItem(+d.id, d.title);
  }
  if (action === 'delete-watchlist') {
    deleteWatchlistItem(+d.id);
  }
  if (action === 'move-watchlist') {
    openMoveModal(+d.id, d.title, d.type);
  }
  if (action === 'disc-watchlist') {
    addDiscoverToWatchlist(btn, d.title, d.type, d.coverUrl || null);
  }
  if (action === 'disc-library') {
    openDiscoverLibraryModal(d.title, d.type, d.coverUrl || null);
  }
});

// ── Modal system ──────────────────────────────────────────────────────────
let _modalContext = null;   // 'add-library' | 'edit-library' | 'watchlist' | 'move' | 'discover-library'
let _editId = null;
let _discoverCoverUrl = null;
let _discoverType = null;

const STATUS_LABELS = {
  movie: [
    { value: 'plan_to_watch', label: 'Plan to Watch' },
    { value: 'in_progress',   label: 'Watching' },
    { value: 'completed',     label: 'Completed' },
    { value: 'dropped',       label: 'Dropped' },
  ],
  show: [
    { value: 'plan_to_watch', label: 'Plan to Watch' },
    { value: 'in_progress',   label: 'Watching' },
    { value: 'completed',     label: 'Completed' },
    { value: 'dropped',       label: 'Dropped' },
  ],
  book: [
    { value: 'plan_to_watch', label: 'Plan to Read' },
    { value: 'in_progress',   label: 'Reading' },
    { value: 'completed',     label: 'Completed' },
    { value: 'dropped',       label: 'Dropped' },
  ],
  manga: [
    { value: 'plan_to_watch', label: 'Plan to Read' },
    { value: 'in_progress',   label: 'Reading' },
    { value: 'completed',     label: 'Completed' },
    { value: 'dropped',       label: 'Dropped' },
  ],
  anime: [
    { value: 'plan_to_watch', label: 'Plan to Watch' },
    { value: 'in_progress',   label: 'Watching' },
    { value: 'completed',     label: 'Completed' },
    { value: 'dropped',       label: 'Dropped' },
  ],
};

function _buildStatusOptions(type, selected) {
  const opts = STATUS_LABELS[type] || STATUS_LABELS.movie;
  return opts.map(o =>
    `<option value="${o.value}"${o.value === selected ? ' selected' : ''}>${o.label}</option>`
  ).join('');
}

function _updateStatusOptions(type, selected) {
  const sel = document.getElementById('modal-status');
  if (!sel) return;
  sel.innerHTML = _buildStatusOptions(type, selected);
}

function _coverPreviewField(currentUrl) {
  return `
    <div class="form-group">
      <label for="modal-cover-url">Cover Image URL</label>
      <input type="text" id="modal-cover-url" name="cover_url" placeholder="https://..." value="${escHtml(currentUrl || '')}">
      <img id="cover-preview" style="display:${currentUrl ? 'block' : 'none'};" src="${escHtml(currentUrl || '')}" alt="Cover preview">
    </div>`;
}

function initCoverPreview() {
  const input = document.getElementById('modal-cover-url');
  const preview = document.getElementById('cover-preview');
  if (!input || !preview) return;
  input.addEventListener('input', () => {
    const url = input.value.trim();
    if (url) {
      preview.src = url;
      preview.style.display = 'block';
    } else {
      preview.style.display = 'none';
    }
  });
}

function openAddModal(context) {
  _modalContext = context === 'watchlist' ? 'watchlist' : 'add-library';
  _editId = null;

  const overlay = document.getElementById('modal-overlay');
  const title   = document.getElementById('modal-title');
  const body    = document.getElementById('modal-body');
  const footer  = document.getElementById('modal-footer');

  title.textContent = context === 'watchlist' ? 'Add to My List' : 'Add to Library';

  const statusSection = context === 'watchlist' ? '' : `
    <div class="form-group">
      <label for="modal-status">Status</label>
      <select id="modal-status" name="status">${_buildStatusOptions('movie', 'plan_to_watch')}</select>
    </div>
    <div class="form-group">
      <label for="modal-rating">Rating (0–10)</label>
      <input type="number" id="modal-rating" name="rating" min="0" max="10" step="0.5" placeholder="e.g. 8.5">
    </div>`;

  body.innerHTML = `
    <form id="modal-form">
      <div class="form-group">
        <label for="modal-item-title">Title</label>
        <input type="text" id="modal-item-title" name="title" required placeholder="e.g. Inception">
      </div>
      <div class="form-group">
        <label for="modal-type">Type</label>
        <select id="modal-type" name="type">
          <option value="movie">Movie</option>
          <option value="show">TV Show</option>
          <option value="book">Book</option>
          <option value="manga">Manga</option>
          <option value="anime">Anime</option>
        </select>
      </div>
      ${statusSection}
      <div class="form-group">
        <label for="modal-notes">Notes</label>
        <textarea id="modal-notes" name="notes" placeholder="Optional notes..."></textarea>
      </div>
      ${_coverPreviewField('')}
    </form>`;

  footer.innerHTML = `
    <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
    <button class="btn btn-primary" onclick="submitModal()">Add</button>`;

  const typeSelect = document.getElementById('modal-type');
  if (typeSelect && context !== 'watchlist') {
    typeSelect.addEventListener('change', () => _updateStatusOptions(typeSelect.value, 'plan_to_watch'));
  }

  initCoverPreview();
  overlay.classList.remove('hidden');
}

function openEditModal(id, title, type, status, rating, notes, coverUrl) {
  _modalContext = 'edit-library';
  _editId = id;

  const overlay = document.getElementById('modal-overlay');
  const mTitle  = document.getElementById('modal-title');
  const body    = document.getElementById('modal-body');
  const footer  = document.getElementById('modal-footer');

  mTitle.textContent = 'Edit Item';

  const ratingVal = rating != null && rating !== '' ? rating : '';

  body.innerHTML = `
    <form id="modal-form">
      <div class="form-group">
        <label>Title</label>
        <input type="text" value="${escHtml(title)}" disabled style="opacity:0.5">
      </div>
      <div class="form-group">
        <label for="modal-status">Status</label>
        <select id="modal-status" name="status" data-type="${escHtml(type)}">
          ${_buildStatusOptions(type, status)}
        </select>
      </div>
      <div class="form-group">
        <label for="modal-rating">Rating (0–10)</label>
        <input type="number" id="modal-rating" name="rating" min="0" max="10" step="0.5" value="${ratingVal}" placeholder="e.g. 8.5">
      </div>
      <div class="form-group">
        <label for="modal-notes">Notes</label>
        <textarea id="modal-notes" name="notes" placeholder="Optional notes...">${escHtml(notes || '')}</textarea>
      </div>
      ${_coverPreviewField(coverUrl || '')}
    </form>`;

  footer.innerHTML = `
    <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
    <button class="btn btn-primary" onclick="submitModal()">Save</button>`;

  initCoverPreview();
  overlay.classList.remove('hidden');
}

function openMoveModal(id, title, type) {
  _modalContext = 'move';
  _editId = id;

  const overlay = document.getElementById('modal-overlay');
  const mTitle  = document.getElementById('modal-title');
  const body    = document.getElementById('modal-body');
  const footer  = document.getElementById('modal-footer');

  mTitle.textContent = 'Move to Library';

  body.innerHTML = `
    <form id="modal-form">
      <p style="color:var(--text-muted);font-size:0.875rem;margin-bottom:1rem;">
        Moving <strong style="color:var(--text)">${escHtml(title)}</strong> to your library.
      </p>
      <div class="form-group">
        <label for="modal-status">Status</label>
        <select id="modal-status" name="status">
          ${_buildStatusOptions(type, 'plan_to_watch')}
        </select>
      </div>
    </form>`;

  footer.innerHTML = `
    <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
    <button class="btn btn-primary" onclick="submitModal()">Move</button>`;

  overlay.classList.remove('hidden');
}

function openDiscoverLibraryModal(title, type, coverUrl) {
  _modalContext = 'discover-library';
  _editId = null;
  _discoverCoverUrl = coverUrl || null;
  _discoverType = type || 'movie';

  const overlay = document.getElementById('modal-overlay');
  const mTitle  = document.getElementById('modal-title');
  const body    = document.getElementById('modal-body');
  const footer  = document.getElementById('modal-footer');

  mTitle.textContent = 'Add to Library';

  body.innerHTML = `
    <form id="modal-form">
      <p style="color:var(--text-muted);font-size:0.875rem;margin-bottom:1rem;">
        Adding <strong style="color:var(--text)">${escHtml(title)}</strong> to your library.
      </p>
      <input type="hidden" name="title" value="${escHtml(title)}">
      <input type="hidden" name="type" value="${escHtml(type || 'movie')}">
      <div class="form-group">
        <label for="modal-status">Status</label>
        <select id="modal-status" name="status">
          ${_buildStatusOptions(type || 'movie', 'plan_to_watch')}
        </select>
      </div>
      <div class="form-group">
        <label for="modal-rating">Rating (0–10)</label>
        <input type="number" id="modal-rating" name="rating" min="0" max="10" step="0.5" placeholder="e.g. 8.5">
      </div>
    </form>`;

  footer.innerHTML = `
    <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
    <button class="btn btn-primary" onclick="submitModal()">Add</button>`;

  overlay.classList.remove('hidden');
}

function closeModal() {
  document.getElementById('modal-overlay').classList.add('hidden');
  _modalContext = null;
  _editId = null;
  _discoverCoverUrl = null;
  _discoverType = null;
}

async function submitModal() {
  const form = document.getElementById('modal-form');
  if (!form) return;

  const fd = new FormData(form);
  const get = (k) => (fd.get(k) || '').trim();

  try {
    if (_modalContext === 'add-library') {
      await submitAddLibrary(fd);
    } else if (_modalContext === 'edit-library') {
      await submitEditLibrary(_editId, fd);
    } else if (_modalContext === 'watchlist') {
      await submitAddWatchlist(fd);
    } else if (_modalContext === 'move') {
      await _doMove(_editId, get('status'));
    } else if (_modalContext === 'discover-library') {
      await _doDiscoverLibraryAdd(fd);
    }
  } catch (err) {
    showToast(err.message, true);
  }
}

// ── Library actions ────────────────────────────────────────────────────────
async function submitAddLibrary(fd) {
  const title    = (fd.get('title') || '').trim();
  const type     = fd.get('type') || 'movie';
  const status   = fd.get('status') || 'plan_to_watch';
  const rating   = fd.get('rating') || null;
  const notes    = (fd.get('notes') || '').trim() || null;
  const cover_url = (fd.get('cover_url') || '').trim() || null;

  if (!title) { showToast('Title is required', true); return; }

  await apiFetch('/api/library', 'POST', { title, type, status, rating, notes, cover_url });
  showToast('Added to library!');
  closeModal();
  setTimeout(() => location.reload(), 400);
}

async function submitEditLibrary(id, fd) {
  const status    = fd.get('status');
  const rating    = fd.get('rating') || null;
  const notes     = (fd.get('notes') || '').trim() || null;
  const cover_url = (fd.get('cover_url') || '').trim() || null;

  await apiFetch(`/api/library/${id}`, 'PATCH', { status, rating, notes, cover_url });
  showToast('Updated!');
  closeModal();
  setTimeout(() => location.reload(), 400);
}

async function deleteLibraryItem(id, title) {
  if (!confirm(`Delete "${title}" from your library?`)) return;
  try {
    await apiFetch(`/api/library/${id}`, 'DELETE');
    showToast('Item deleted.');
    setTimeout(() => location.reload(), 400);
  } catch (err) {
    showToast(err.message, true);
  }
}

// ── Watchlist actions ──────────────────────────────────────────────────────
async function submitAddWatchlist(fd) {
  const title    = (fd.get('title') || '').trim();
  const type     = fd.get('type') || 'movie';
  const notes    = (fd.get('notes') || '').trim() || null;
  const cover_url = (fd.get('cover_url') || '').trim() || null;

  if (!title) { showToast('Title is required', true); return; }

  await apiFetch('/api/watchlist', 'POST', { title, type, notes, cover_url });
  showToast('Added to My List!');
  closeModal();
  setTimeout(() => location.reload(), 400);
}

async function deleteWatchlistItem(id) {
  if (!confirm('Remove this item from My List?')) return;
  try {
    await apiFetch(`/api/watchlist/${id}`, 'DELETE');
    showToast('Removed from My List.');
    setTimeout(() => location.reload(), 400);
  } catch (err) {
    showToast(err.message, true);
  }
}

async function _doMove(id, status) {
  await apiFetch(`/api/watchlist/${id}/move`, 'POST', { status });
  showToast('Moved to library!');
  closeModal();
  setTimeout(() => location.reload(), 400);
}

// ── Discover page tab system ───────────────────────────────────────────────
let _activeDiscoverTab = 'movie';

function switchDiscoverTab(tab) {
  _activeDiscoverTab = tab;
  document.querySelectorAll('.discover-tab').forEach(el =>
    el.classList.toggle('active', el.dataset.tab === tab)
  );
  document.querySelectorAll('.discover-panel').forEach(el => {
    el.style.display = el.dataset.panel === tab ? 'block' : 'none';
  });
}

// ── TMDB search ────────────────────────────────────────────────────────────
async function searchTmdb(type) {
  // type = 'movie' or 'show' (maps to tmdb 'tv')
  const inputId   = type === 'show' ? 'show-search'   : 'movie-search';
  const spinnerId = type === 'show' ? 'show-spinner'  : 'movie-spinner';
  const errorId   = type === 'show' ? 'show-error'    : 'movie-error';
  const gridId    = type === 'show' ? 'show-results-grid' : 'movie-results-grid';

  const q       = (document.getElementById(inputId)?.value || '').trim();
  const spinner = document.getElementById(spinnerId);
  const errorEl = document.getElementById(errorId);
  const grid    = document.getElementById(gridId);

  if (!q) { showToast('Enter a title to search.', true); return; }

  if (errorEl) errorEl.innerHTML = '';
  if (grid) grid.innerHTML = '';
  if (spinner) spinner.style.display = 'flex';

  try {
    const tmdbType = type === 'show' ? 'tv' : 'movie';
    const results = await apiFetch(`/api/tmdb/search?q=${encodeURIComponent(q)}&type=${tmdbType}`);
    if (spinner) spinner.style.display = 'none';
    renderTmdbCards(results, type, grid);
  } catch (err) {
    if (spinner) spinner.style.display = 'none';
    if (err.message === 'no_key' || err.message.includes('no_key')) {
      if (errorEl) errorEl.innerHTML = `
        <div class="key-setup-banner">
          <h3>TMDB API Key Required</h3>
          <p>Movie and TV search needs a free API key from TMDB.</p>
          <input type="text" id="inline-tmdb-key" placeholder="Paste your TMDB API key...">
          <br>
          <button class="btn btn-primary btn-sm" onclick="saveTmdbKeyInline()">Save &amp; Search</button>
          <br>
          <a href="https://www.themoviedb.org/settings/api" target="_blank" style="font-size:0.78rem;color:var(--accent);">Get your free key at themoviedb.org →</a>
        </div>`;
      // Store query for retry
      window._pendingTmdbSearch = { type, q };
    } else {
      if (errorEl) errorEl.textContent = err.message;
    }
  }
}

function renderTmdbCards(results, type, grid) {
  if (!grid) return;
  if (!results || results.length === 0) {
    grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1">
      <p>No results found. Try a different title.</p>
    </div>`;
    return;
  }
  const badge = type === 'show' ? 'badge-show' : 'badge-movie';
  const label = type === 'show' ? 'Show' : 'Movie';
  grid.innerHTML = results.map(r => {
    const cover = r.cover_url
      ? `<div class="card-cover"><img src="${escHtml(r.cover_url)}" alt="" loading="lazy" onerror="this.parentElement.className='card-cover card-cover-placeholder ${type}';this.remove()"></div>`
      : `<div class="card-cover card-cover-placeholder ${type}">${escHtml((r.title || '?')[0])}</div>`;
    const year    = r.year    ? `<span class="card-year">${escHtml(r.year)}</span>` : '';
    const rating  = r.rating  ? `<span class="card-score">★ ${r.rating}</span>` : '';
    const overview = r.overview ? `<div class="card-notes">${escHtml(r.overview)}</div>` : '';
    return `
      <div class="card">
        ${cover}
        <div class="card-body">
          <div class="card-top">
            <span class="badge ${badge}">${label}</span>
            ${year}
            ${rating}
          </div>
          <div class="card-title">${escHtml(r.title)}</div>
          ${overview}
        </div>
        <div class="card-actions">
          <button class="btn-icon primary"
            data-action="disc-watchlist"
            data-title="${escHtml(r.title)}"
            data-type="${type}"
            data-cover-url="${escHtml(r.cover_url || '')}">+ My List</button>
        </div>
      </div>`;
  }).join('');
}

async function saveTmdbKey() {
  const key = (document.getElementById('tmdb-key-input')?.value || '').trim();
  if (!key) { showToast('Enter a key first.', true); return; }
  await apiFetch('/api/config/tmdb', 'POST', { key });
  showToast('TMDB key saved!');
  document.getElementById('tmdb-setup').style.display = 'none';
  loadSidebar();
}

async function saveTmdbKeyInline() {
  const key = (document.getElementById('inline-tmdb-key')?.value || '').trim();
  if (!key) { showToast('Enter a key first.', true); return; }
  await apiFetch('/api/config/tmdb', 'POST', { key });
  showToast('TMDB key saved! Searching...');
  const pending = window._pendingTmdbSearch;
  if (pending) { window._pendingTmdbSearch = null; searchTmdb(pending.type); }
}

// ── Sidebar ────────────────────────────────────────────────────────────────
function switchSidebarTab(tab) {
  document.querySelectorAll('.sidebar-tab').forEach(el =>
    el.classList.toggle('active', el.dataset.tab === tab)
  );
  document.getElementById('sb-top-rated').style.display  = tab === 'top-rated'  ? '' : 'none';
  document.getElementById('sb-top-airing').style.display = tab === 'top-airing' ? '' : 'none';
}

function switchSidebarCat(cat) {
  document.querySelectorAll('.sidebar-cat-tab').forEach(el =>
    el.classList.toggle('active', el.dataset.cat === cat)
  );
  document.querySelectorAll('.sb-cat-block').forEach(el => {
    el.style.display = el.dataset.cat === cat ? '' : 'none';
  });
}

async function loadSidebar() {
  try {
    const data = await apiFetch('/api/sidebar');

    const setupEl = document.getElementById('tmdb-setup');
    if (setupEl) setupEl.style.display = data.has_tmdb ? 'none' : 'block';

    fillPanel('tr', data.top_rated);
    fillPanel('ta', data.top_airing);
  } catch (_) {}
}

function fillPanel(prefix, panel) {
  renderSidebarSection(`sb${prefix}-movies`, panel.movies, 'movie');
  renderSidebarSection(`sb${prefix}-shows`,  panel.shows,  'show');
  renderSidebarSection(`sb${prefix}-manga`,  panel.manga,  'manga');
  renderSidebarSection(`sb${prefix}-anime`,  panel.anime,  'anime');
  renderSidebarSection(`sb${prefix}-books`,  panel.books,  'book');
}

function renderSidebarSection(sectionId, items, type) {
  const list = document.getElementById(`${sectionId}-list`);
  if (!list) return;
  if (!items || items.length === 0) {
    const msg = (type === 'movie' || type === 'show')
      ? 'Add a TMDB key to see movies &amp; shows.'
      : 'No data available.';
    list.innerHTML = `<div class="sidebar-loading">${msg}</div>`;
    return;
  }
  list.innerHTML = items.map(item => {
    const firstChar = escHtml((item.title || '?')[0]);
    const thumb = item.cover_url
      ? `<img class="sidebar-thumb" src="${escHtml(item.cover_url)}" alt="" loading="lazy" onerror="this.outerHTML='<div class=&quot;sidebar-thumb-placeholder&quot;>${firstChar}</div>'">`
      : `<div class="sidebar-thumb-placeholder">${firstChar}</div>`;
    const meta = [
      item.rating ? `★ ${item.rating}` : null,
      item.year   ? item.year           : null,
    ].filter(Boolean).join(' · ');
    return `
      <div class="sidebar-item"
           data-action="disc-watchlist"
           data-title="${escHtml(item.title)}"
           data-type="${type}"
           data-cover-url="${escHtml(item.cover_url || '')}">
        ${thumb}
        <div class="sidebar-info">
          <div class="sidebar-title">${escHtml(item.title)}</div>
          ${meta ? `<div class="sidebar-meta">${escHtml(meta)}</div>` : ''}
        </div>
      </div>`;
  }).join('');
}

async function addDiscoverToWatchlist(btn, title, type, coverUrl) {
  try {
    await apiFetch('/api/watchlist', 'POST', { title, type: type || 'movie', cover_url: coverUrl || null });
    showToast(`"${title}" added to My List!`);
    // Only update button appearance on actual <button> elements, not sidebar item divs
    if (btn && btn.tagName === 'BUTTON') {
      btn.textContent = '✓ Added';
      btn.classList.add('btn-added');
      btn.disabled = true;
    }
  } catch (err) {
    showToast(err.message, true);
  }
}

async function _doDiscoverLibraryAdd(fd) {
  const title    = (fd.get('title') || '').trim();
  const type     = fd.get('type') || _discoverType || 'movie';
  const status   = fd.get('status') || 'plan_to_watch';
  const rating   = fd.get('rating') || null;
  const cover_url = _discoverCoverUrl || null;

  await apiFetch('/api/library', 'POST', { title, type, status, rating, cover_url });
  showToast(`"${title}" added to library!`);
  closeModal();
}

// ── Book search ────────────────────────────────────────────────────────────
async function searchBooks() {
  const input   = document.getElementById('book-search');
  const spinner = document.getElementById('book-spinner');
  const grid    = document.getElementById('book-results-grid');
  const errorEl = document.getElementById('book-error');

  const q = input ? input.value.trim() : '';
  if (!q) return;

  if (errorEl) errorEl.textContent = '';
  if (grid) grid.innerHTML = '';
  if (spinner) spinner.style.display = 'flex';

  try {
    const results = await apiFetch(`/api/books/search?q=${encodeURIComponent(q)}`);
    if (spinner) spinner.style.display = 'none';

    if (!results || results.length === 0) {
      if (grid) grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1">
        <div class="empty-icon">&#128218;</div>
        <p>No books found for "${escHtml(q)}".</p>
      </div>`;
      return;
    }

    if (grid) {
      grid.innerHTML = results.map(r => {
        const cover = r.cover_url
          ? `<div class="card-cover"><img src="${escHtml(r.cover_url)}" alt="" loading="lazy" onerror="this.parentElement.className='card-cover card-cover-placeholder book';this.remove()"></div>`
          : `<div class="card-cover card-cover-placeholder book">${escHtml((r.title || 'B')[0])}</div>`;
        const year = r.year ? `<span class="card-year">${r.year}</span>` : '';
        const bkRating = r.rating ? `<span class="card-score">★ ${r.rating}</span>` : '';
        const author = r.author ? `<div class="card-author">by ${escHtml(r.author)}</div>` : '';
        const subjects = r.subjects && r.subjects.length
          ? `<div class="card-genres">${escHtml(r.subjects.slice(0,3).join(' · '))}</div>` : '';
        return `
          <div class="card">
            ${cover}
            <div class="card-body">
              <div class="card-top"><span class="badge badge-book">Book</span>${year}${bkRating}</div>
              <div class="card-title">${escHtml(r.title)}</div>
              ${author}
              ${subjects}
            </div>
            <div class="card-actions">
              <button class="btn-icon primary"
                data-action="disc-watchlist"
                data-title="${escHtml(r.title)}"
                data-type="book"
                data-cover-url="${escHtml(r.cover_url || '')}">+ My List</button>
              <button class="btn-icon" style="display:none"
                data-action="disc-library"
                data-title="${escHtml(r.title)}"
                data-type="book"
                data-cover-url="${escHtml(r.cover_url || '')}">+ Library</button>
            </div>
          </div>`;
      }).join('');
    }
  } catch (err) {
    if (spinner) spinner.style.display = 'none';
    if (errorEl) errorEl.textContent = err.message;
    else showToast(err.message, true);
  }
}

// ── Manga search ───────────────────────────────────────────────────────────
async function searchManga() {
  const input   = document.getElementById('manga-search');
  const spinner = document.getElementById('manga-spinner');
  const grid    = document.getElementById('manga-results-grid');
  const errorEl = document.getElementById('manga-error');

  const q = input ? input.value.trim() : '';
  if (!q) return;

  if (errorEl) errorEl.textContent = '';
  if (grid) grid.innerHTML = '';
  if (spinner) spinner.style.display = 'flex';

  try {
    const results = await apiFetch(`/api/manga/search?q=${encodeURIComponent(q)}`);
    if (spinner) spinner.style.display = 'none';

    if (!results || results.length === 0) {
      if (grid) grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1">
        <div class="empty-icon">&#128444;</div>
        <p>No manga found for "${escHtml(q)}".</p>
      </div>`;
      return;
    }

    if (grid) {
      grid.innerHTML = results.map(r => {
        const cover = r.cover_url
          ? `<div class="card-cover"><img src="${escHtml(r.cover_url)}" alt="" loading="lazy" onerror="this.parentElement.className='card-cover card-cover-placeholder manga';this.remove()"></div>`
          : `<div class="card-cover card-cover-placeholder manga">${escHtml((r.title || 'M')[0])}</div>`;
        const genres = r.genres && r.genres.length
          ? `<div class="card-genres">${escHtml(r.genres.join(' · '))}</div>` : '';
        const synopsis = r.synopsis
          ? `<div class="card-notes">${escHtml(r.synopsis)}</div>` : '';
        const rating = r.rating ? `<span class="card-score">★ ${r.rating}</span>` : '';
        return `
          <div class="card">
            ${cover}
            <div class="card-body">
              <div class="card-top"><span class="badge badge-manga">Manga</span>${rating}</div>
              <div class="card-title">${escHtml(r.title)}</div>
              ${genres}
              ${synopsis}
            </div>
            <div class="card-actions">
              <button class="btn-icon primary"
                data-action="disc-watchlist"
                data-title="${escHtml(r.title)}"
                data-type="manga"
                data-cover-url="${escHtml(r.cover_url || '')}">+ My List</button>
            </div>
          </div>`;
      }).join('');
    }
  } catch (err) {
    if (spinner) spinner.style.display = 'none';
    if (errorEl) errorEl.textContent = err.message;
    else showToast(err.message, true);
  }
}

// ── Library recommendations ────────────────────────────────────────────────
let _allRecs = [];

function filterRecs(type) {
  document.querySelectorAll('.recs-type-tab').forEach(el =>
    el.classList.toggle('active', el.dataset.type === type)
  );
  const scroll = document.getElementById('recs-scroll');
  if (!scroll) return;
  scroll.querySelectorAll('.rec-card').forEach(el => {
    el.style.display = (type === 'all' || el.dataset.recType === type) ? '' : 'none';
  });
  // Update subtitle to reflect sources for the current type
  const subtitle = document.getElementById('recs-subtitle');
  if (subtitle && _allRecs.length) {
    const visible = type === 'all' ? _allRecs : _allRecs.filter(r => r.type === type);
    const sources = [...new Set(visible.map(r => r.because).filter(b => b && b !== 'Trending'))].slice(0, 2);
    subtitle.textContent = sources.length
      ? `Because you liked: ${sources.join(', ')}`
      : 'Trending picks for you';
  }
}

async function loadLibraryRecs(force = false) {
  const loading  = document.getElementById('recs-loading');
  const empty    = document.getElementById('recs-empty');
  const scroll   = document.getElementById('recs-scroll');
  const subtitle = document.getElementById('recs-subtitle');
  const btn      = document.getElementById('recs-refresh-btn');
  const tabs     = document.getElementById('recs-type-tabs');
  if (!scroll) return;

  if (loading) loading.style.display = '';
  if (empty)   empty.style.display   = 'none';
  if (scroll)  scroll.style.display  = 'none';
  if (tabs)    tabs.style.display    = 'none';
  if (btn)     btn.disabled = true;

  try {
    const recs = await apiFetch('/api/recs/library');
    if (loading) loading.style.display = 'none';
    if (btn)     btn.disabled = false;

    if (!recs || recs.length === 0) {
      if (empty) empty.style.display = '';
      return;
    }

    _allRecs = recs;

    const typeLabels = { movie:'Movie', show:'Show', book:'Book', manga:'Manga', anime:'Anime' };
    scroll.innerHTML = recs.map(r => {
      const firstChar = escHtml((r.title || '?')[0]);
      const coverHtml = r.cover_url
        ? `<img src="${escHtml(r.cover_url)}" alt="" loading="lazy" onerror="this.outerHTML='<div class=&quot;rec-card-cover-placeholder ${escHtml(r.type)}&quot;>${firstChar}</div>'">`
        : `<div class="rec-card-cover-placeholder ${escHtml(r.type)}">${firstChar}</div>`;
      const badge = `<span class="badge badge-${escHtml(r.type)}">${escHtml(typeLabels[r.type] || r.type)}</span>`;
      const score = r.score != null ? `<span class="card-score" style="font-size:0.65rem;margin-left:auto">★ ${r.score}</span>` : '';
      return `
        <div class="rec-card"
             data-rec-type="${escHtml(r.type)}"
             data-action="disc-watchlist"
             data-title="${escHtml(r.title)}"
             data-type="${escHtml(r.type)}"
             data-cover-url="${escHtml(r.cover_url || '')}">
          <div class="rec-card-cover">${coverHtml}</div>
          <div class="rec-card-body">
            <div class="rec-card-meta">${badge}${score}</div>
            <div class="rec-card-title">${escHtml(r.title)}</div>
            <div class="rec-card-because">↳ ${escHtml(r.because)}</div>
          </div>
        </div>`;
    }).join('');

    scroll.style.display = 'flex';

    // Show type tabs; hide tabs for types with no results
    const presentTypes = new Set(recs.map(r => r.type));
    if (tabs) {
      tabs.style.display = 'flex';
      tabs.querySelectorAll('.recs-type-tab').forEach(el => {
        const t = el.dataset.type;
        el.style.display = (t === 'all' || presentTypes.has(t)) ? '' : 'none';
      });
      filterRecs('all');
    }

    // Initial subtitle is set by filterRecs('all') above
  } catch (err) {
    if (loading) loading.style.display = 'none';
    if (btn)     btn.disabled = false;
    if (empty)   { empty.textContent = 'Could not load recommendations.'; empty.style.display = ''; }
  }
}

// ── Anime search ───────────────────────────────────────────────────────────
async function searchAnime() {
  const input   = document.getElementById('anime-search');
  const spinner = document.getElementById('anime-spinner');
  const grid    = document.getElementById('anime-results-grid');
  const errorEl = document.getElementById('anime-error');

  const q = input ? input.value.trim() : '';
  if (!q) return;

  if (errorEl) errorEl.textContent = '';
  if (grid) grid.innerHTML = '';
  if (spinner) spinner.style.display = 'flex';

  try {
    const results = await apiFetch(`/api/anime/search?q=${encodeURIComponent(q)}`);
    if (spinner) spinner.style.display = 'none';

    if (!results || results.length === 0) {
      if (grid) grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1">
        <div class="empty-icon">&#127910;</div>
        <p>No anime found for "${escHtml(q)}".</p>
      </div>`;
      return;
    }

    if (grid) {
      grid.innerHTML = results.map(r => {
        const cover = r.cover_url
          ? `<div class="card-cover"><img src="${escHtml(r.cover_url)}" alt="" loading="lazy" onerror="this.parentElement.className='card-cover card-cover-placeholder anime';this.remove()"></div>`
          : `<div class="card-cover card-cover-placeholder anime">${escHtml((r.title || 'A')[0])}</div>`;
        const genres  = r.genres && r.genres.length ? `<div class="card-genres">${escHtml(r.genres.join(' · '))}</div>` : '';
        const synopsis = r.synopsis ? `<div class="card-notes">${escHtml(r.synopsis)}</div>` : '';
        const rating  = r.rating ? `<span class="card-score">★ ${r.rating}</span>` : '';
        const year    = r.year   ? `<span class="card-year">${escHtml(r.year)}</span>` : '';
        return `
          <div class="card">
            ${cover}
            <div class="card-body">
              <div class="card-top"><span class="badge badge-anime">Anime</span>${year}${rating}</div>
              <div class="card-title">${escHtml(r.title)}</div>
              ${genres}
              ${synopsis}
            </div>
            <div class="card-actions">
              <button class="btn-icon primary"
                data-action="disc-watchlist"
                data-title="${escHtml(r.title)}"
                data-type="anime"
                data-cover-url="${escHtml(r.cover_url || '')}">+ My List</button>
            </div>
          </div>`;
      }).join('');
    }
  } catch (err) {
    if (spinner) spinner.style.display = 'none';
    if (errorEl) errorEl.textContent = err.message;
    else showToast(err.message, true);
  }
}

// ── Utility ───────────────────────────────────────────────────────────────
function escHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ── DOMContentLoaded setup ────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Close modal on overlay click
  const overlay = document.getElementById('modal-overlay');
  if (overlay) {
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) closeModal();
    });
  }

  // Init sidebar category tabs
  switchSidebarCat('manga');

  // Load sidebar data
  loadSidebar();

  // Wire Enter key for TMDB search inputs
  ['movie-search', 'show-search'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('keydown', e => {
      if (e.key === 'Enter') searchTmdb(id.replace('-search', ''));
    });
  });

  // Wire book/manga Enter keys
  const bookInput  = document.getElementById('book-search');
  const mangaInput = document.getElementById('manga-search');
  const animeInput = document.getElementById('anime-search');
  if (bookInput)  bookInput.addEventListener('keydown',  e => { if (e.key === 'Enter') searchBooks(); });
  if (mangaInput) mangaInput.addEventListener('keydown', e => { if (e.key === 'Enter') searchManga(); });
  if (animeInput) animeInput.addEventListener('keydown', e => { if (e.key === 'Enter') searchAnime(); });

  // Init discover tabs
  const firstTab = document.querySelector('.discover-tab');
  if (firstTab) switchDiscoverTab(firstTab.dataset.tab || 'movie');

  // Load library recommendations if on library page
  if (document.getElementById('recs-scroll')) loadLibraryRecs();
});
