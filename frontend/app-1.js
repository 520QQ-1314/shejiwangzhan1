'use strict';

const state = {
  page: 1, lastQ: '', loading: false, source: 'all',
  currentItem: null, favorites: new Set(),
  viewMode: 'search',          // 'search' | 'favorites'
  selectMode: false,
  selectedIds: new Set(),
};
const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);

async function search(q, append = false) {
  if (!q || state.loading) return;
  state.lastQ = q; state.loading = true; state.viewMode = 'search';
  $('#favToolbar').classList.add('hidden');
  if (!append) {
    state.page = 1;
    $('#grid').innerHTML = '';
    $('#empty').classList.add('hidden');
    $('#filters').classList.remove('hidden');
  }
  $('#loading').classList.remove('hidden');
  try {
    const res = await fetch(`/api/search?q=${encodeURIComponent(q)}&sources=${state.source}&page=${state.page}`);
    const data = await res.json();
    if (data.message) showStatus(data.message);
    if (data.results && data.results.length) {
      data.results.forEach(renderPin);
    } else if (!append) {
      $('#empty').classList.remove('hidden');
      $('#empty').innerHTML = `<div class="text-6xl mb-4">😅</div><h2 class="text-2xl font-bold mb-2">未找到内容</h2><p class="text-neutral-500">试试别的关键词</p>`;
    }
  } catch (e) {
    showStatus('搜索失败：' + e.message);
  } finally {
    $('#loading').classList.add('hidden');
    state.loading = false;
  }
}

function showStatus(msg, duration = 4000) {
  const el = $('#status');
  el.textContent = msg;
  el.classList.remove('hidden');
  setTimeout(() => el.classList.add('hidden'), duration);
}

function quickSearch(q) { $('#q').value = q; search(q); }

function goHome() {
  state.lastQ = ''; state.page = 1; state.viewMode = 'search';
  state.selectMode = false; state.selectedIds.clear();
  $('#q').value = '';
  $('#grid').innerHTML = '';
  $('#filters').classList.add('hidden');
  $('#favToolbar').classList.add('hidden');
  $('#empty').classList.remove('hidden');
}

function escapeHtml(s) {
  return String(s || '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}

function renderPin(item) {
  if (!item.image_url) return;
  const div = document.createElement('div');
  div.className = 'pin' + (state.selectMode ? ' selectable' : '');
  div.dataset.id = item.id || item.image_url;

  let aspect = '';
  if (item.width && item.height) aspect = `aspect-ratio:${item.width}/${item.height};`;

  const tagsHtml = (item.tags || []).slice(0, 3).map(t =>
    `<span class="text-xs text-white/80">${(t.split(' ')[1] || t.split(' ')[0])}</span>`
  ).join(' · ');

  div.innerHTML = `
    <div style="${aspect}background:#f3f3f3;">
      <img loading="lazy" src="${item.thumbnail || item.image_url}" alt="${escapeHtml(item.title)}" referrerpolicy="no-referrer" onerror="this.parentElement.style.minHeight='200px';this.style.display='none';this.parentElement.innerHTML='<div class=\\'flex items-center justify-center h-full text-neutral-400 text-sm\\'>加载失败</div>'" />
    </div>
    <div class="overlay">
      <span class="source-badge src-${item.source}">${sourceLabel(item.source)}</span>
      <div>
        ${item.title ? `<div class="pin-title">${escapeHtml(item.title)}</div>` : ''}
        ${tagsHtml ? `<div class="mt-1 truncate">${tagsHtml}</div>` : ''}
      </div>
    </div>`;

  div.onclick = (e) => {
    if (state.selectMode) {
      e.preventDefault();
      togglePinSelection(div, item);
    } else {
      openDetail(item);
    }
  };
  $('#grid').appendChild(div);

  if (state.selectedIds.has(item.id || item.image_url)) {
    div.classList.add('selected');
  }

  fetch('/api/track', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({image_id: item.id || item.image_url, action: 'view', tags: item.tags || []})
  }).catch(() => {});
}

function sourceLabel(s) {
  const labels = {pinterest:'Pinterest', behance:'Behance', dribbble:'Dribbble',
                  unsplash:'Unsplash', pexels:'Pexels', pixabay:'Pixabay',
                  zcool:'站酷', uicn:'UI中国'};
  return labels[s] || s;
}

function openDetail(item) {
  state.currentItem = item;
  $('#detailImg').src = item.image_url;
  $('#detailTitle').textContent = item.title || '无标题';
  $('#detailDesc').textContent = item.description || '';
  $('#detailAuthor').textContent = item.author ? `By ${item.author}` : '';
  $('#detailSource').textContent = sourceLabel(item.source);
  $('#detailSource').className = `source-badge src-${item.source}`;
  $('#origLink').href = item.link || '#';
  const tagsEl = $('#detailTags');
  tagsEl.innerHTML = '';
  (item.tags || []).forEach(t => {
    const c = document.createElement('span');
    c.className = 'tag-chip';
    c.textContent = t;
    c.onclick = () => { closeDetail(); $('#q').value = t.split(' ')[0]; search($('#q').value); };
    tagsEl.appendChild(c);
  });
  const isFav = state.favorites.has(item.id || item.image_url);
  $('#favBtn').textContent = isFav ? '✓ 已收藏' : '❤️ 收藏';
  $('#detailModal').classList.remove('hidden');
  fetch('/api/track', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({image_id: item.id || item.image_url, action: 'click', tags: item.tags || []})
  }).catch(() => {});
}

function closeDetail(e) {
  if (e && e.target.id !== 'detailModal') return;
  $('#detailModal').classList.add('hidden');
  state.currentItem = null;
}

async function toggleFav() {
  if (!state.currentItem) return;
  const item = state.currentItem;
  const id = item.id || item.image_url;
  if (state.favorites.has(id)) {
    await fetch(`/api/favorite/${encodeURIComponent(id)}`, {method: 'DELETE'});
    state.favorites.delete(id);
    $('#favBtn').textContent = '❤️ 收藏';
  } else {
    await fetch('/api/favorite', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({image_id: id, data: item})
    });
    state.favorites.add(id);
    $('#favBtn').textContent = '✓ 已收藏';
    fetch('/api/track', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({image_id: id, action: 'save', tags: item.tags || []})
    }).catch(() => {});
  }
}

async function downloadImage() {
  if (!state.currentItem) return;
  try {
    const res = await fetch(state.currentItem.image_url, {referrerPolicy: 'no-referrer'});
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `designhub_${Date.now()}.jpg`;
    a.click();
    URL.revokeObjectURL(a.href);
  } catch (e) {
    window.open(state.currentItem.image_url, '_blank');
  }
}

// ============ 收藏夹相关 ============
async function showFavorites() {
  state.viewMode = 'favorites';
  state.selectMode = false;
  state.selectedIds.clear();
  $('#grid').innerHTML = '';
  $('#empty').classList.add('hidden');
  $('#filters').classList.add('hidden');
  $('#favToolbar').classList.remove('hidden');
  $('#loading').classList.remove('hidden');

  const res = await fetch('/api/favorites');
  const data = await res.json();
  $('#loading').classList.add('hidden');

  const items = data.items || [];
  $('#favCount').textContent = `共 ${items.length} 张`;

  if (!items.length) {
    $('#favToolbar').classList.add('hidden');
    $('#empty').classList.remove('hidden');
    $('#empty').innerHTML = `<div class="text-6xl mb-4">💔</div><h2 class="text-2xl font-bold mb-2">收藏夹是空的</h2><p class="text-neutral-500">看到喜欢的图点击 ❤️</p>`;
    return;
  }
  items.forEach(it => {
    state.favorites.add(it.id || it.image_url);
    renderPin(it);
  });
}

function toggleSelectMode() {
  state.selectMode = !state.selectMode;
  state.selectedIds.clear();

  $$('#grid .pin').forEach(p => {
    p.classList.toggle('selectable', state.selectMode);
    p.classList.remove('selected');
  });
  $('#selectBtn').textContent = state.selectMode ? '✕ 退出多选' : '✓ 多选';
  $('#selectAllBtn').classList.toggle('hidden', !state.selectMode);
  $('#downloadSelectedBtn').classList.toggle('hidden', !state.selectMode);
  updateSelectedCount();
}

function togglePinSelection(pinEl, item) {
  const id = item.id || item.image_url;
  if (state.selectedIds.has(id)) {
    state.selectedIds.delete(id);
    pinEl.classList.remove('selected');
  } else {
    state.selectedIds.add(id);
    pinEl.classList.add('selected');
  }
  updateSelectedCount();
}

function selectAll() {
  const allSelected = state.selectedIds.size === $$('#grid .pin').length;
  if (allSelected) {
    state.selectedIds.clear();
    $$('#grid .pin').forEach(p => p.classList.remove('selected'));
  } else {
    state.selectedIds.clear();
    $$('#grid .pin').forEach(p => {
      state.selectedIds.add(p.dataset.id);
      p.classList.add('selected');
    });
  }
  updateSelectedCount();
}

function updateSelectedCount() {
  const n = state.selectedIds.size;
  const btn = $('#downloadSelectedBtn');
  btn.textContent = `下载选中 (${n})`;
  btn.disabled = n === 0;
}

async function downloadAllFavorites() {
  await doDownload('');
}

async function downloadSelected() {
  if (state.selectedIds.size === 0) return;
  const ids = [...state.selectedIds].join(',');
  await doDownload(ids);
}

async function doDownload(ids) {
  const toast = createToast(`正在打包${ids ? ' ' + state.selectedIds.size + ' 张' : '收藏夹'}...`);
  try {
    const url = `/api/favorites/download${ids ? '?ids=' + encodeURIComponent(ids) : ''}`;
    const res = await fetch(url);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    toast.querySelector('span').textContent = '下载中...';
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `designhub_favorites_${Date.now()}.zip`;
    a.click();
    URL.revokeObjectURL(a.href);
    toast.querySelector('span').textContent = `✓ 已保存 (${(blob.size / 1024 / 1024).toFixed(1)} MB)`;
    toast.querySelector('.spinner-small').remove();
    setTimeout(() => toast.remove(), 3000);
  } catch (e) {
    toast.innerHTML = `<span>❌ 下载失败：${e.message}</span>`;
    setTimeout(() => toast.remove(), 4000);
  }
}

function createToast(msg) {
  const t = document.createElement('div');
  t.className = 'download-toast';
  t.innerHTML = `<div class="spinner-small"></div><span>${msg}</span>`;
  document.body.appendChild(t);
  return t;
}

// ============ 推荐 ============
async function loadRecommend() {
  state.viewMode = 'search';
  $('#favToolbar').classList.add('hidden');
  $('#grid').innerHTML = '';
  $('#empty').classList.add('hidden');
  $('#filters').classList.add('hidden');
  $('#loading').classList.remove('hidden');
  try {
    const res = await fetch('/api/recommend?limit=40');
    const data = await res.json();
    if (data.seeds && data.seeds.length) showStatus(`🎯 基于你的兴趣：${data.seeds.join(' · ')}`);
    (data.items || []).forEach(renderPin);
    if (!data.items || !data.items.length) $('#empty').classList.remove('hidden');
  } finally {
    $('#loading').classList.add('hidden');
  }
}

// ============ 设置 ============
async function showSettings() {
  const res = await fetch('/api/config');
  const cfg = await res.json();
  $('#cfgWorker').value = cfg.worker_base || '';
  $('#cfgUseProxy').checked = cfg.use_proxy || false;
  $('#settingsModal').classList.remove('hidden');
}

function closeSettings(e) {
  if (e && e.target.id !== 'settingsModal') return;
  $('#settingsModal').classList.add('hidden');
}

async function saveSettings() {
  const cfg = {
    worker_base: $('#cfgWorker').value.trim(),
    use_proxy: $('#cfgUseProxy').checked,
  };
  const u = $('#cfgUnsplash').value.trim();
  const p = $('#cfgPexels').value.trim();
  const x = $('#cfgPixabay').value.trim();
  if (u) cfg.unsplash_key = u;
  if (p) cfg.pexels_key = p;
  if (x) cfg.pixabay_key = x;
  await fetch('/api/config', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(cfg)
  });
  closeSettings();
  showStatus('✓ 设置已保存');
}

// ============ 事件绑定 ============
let searchTimer;
$('#q').addEventListener('input', e => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    const v = e.target.value.trim();
    if (v) search(v);
  }, 500);
});
$('#q').addEventListener('keydown', e => {
  if (e.key === 'Enter') {
    clearTimeout(searchTimer);
    const v = e.target.value.trim();
    if (v) search(v);
  }
});

document.addEventListener('click', e => {
  if (e.target.classList && e.target.classList.contains('filter-chip')) {
    $$('.filter-chip').forEach(c => c.classList.remove('active'));
    e.target.classList.add('active');
    state.source = e.target.dataset.src;
    if (state.lastQ) search(state.lastQ);
  }
});

window.addEventListener('scroll', () => {
  if (state.loading || !state.lastQ || state.viewMode !== 'search') return;
  if (window.innerHeight + window.scrollY >= document.body.offsetHeight - 600) {
    state.page++;
    search(state.lastQ, true);
  }
});

fetch('/api/favorites').then(r => r.json()).then(d => {
  (d.items || []).forEach(it => state.favorites.add(it.id || it.image_url));
}).catch(() => {});

console.log('🎨 DesignHub v1.1 Ready');
