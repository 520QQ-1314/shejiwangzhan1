'use strict';

const state = {
  page: 1, lastQ: '', loading: false, source: 'all',
  currentItem: null, favorites: new Set(), mode: 'search'  // search | favorites | recommend
};
const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);

// ============ 搜索 ============
async function search(q, append = false) {
  if (!q || state.loading) return;
  state.lastQ = q; state.loading = true; state.mode = 'search';
  if (!append) {
    state.page = 1;
    $('#grid').innerHTML = '';
    $('#empty').classList.add('hidden');
    $('#filters').classList.remove('hidden');
    $('#favToolbar').classList.add('hidden');
  }
  $('#loading').classList.remove('hidden');
  try {
    const res = await fetch(`/api/search?q=${encodeURIComponent(q)}&sources=${state.source}&page=${state.page}`);
    const data = await res.json();
    if (data.message) showToast(data.message);
    if (data.results && data.results.length) {
      data.results.forEach(renderPin);
    } else if (!append) {
      $('#empty').classList.remove('hidden');
      $('#empty').innerHTML = `<div class="text-6xl mb-4">😅</div><h2 class="text-2xl font-bold mb-2">未找到内容</h2><p class="text-neutral-500">试试别的关键词，或检查是否启用了相应源</p>`;
    }
  } catch (e) {
    showToast('搜索失败：' + e.message);
  } finally {
    $('#loading').classList.add('hidden');
    state.loading = false;
  }
}

function quickSearch(q) { $('#q').value = q; search(q); }

function goHome() {
  state.lastQ = ''; state.page = 1; state.mode = 'search';
  $('#q').value = '';
  $('#grid').innerHTML = '';
  $('#filters').classList.add('hidden');
  $('#favToolbar').classList.add('hidden');
  $('#empty').classList.remove('hidden');
  $('#empty').innerHTML = `
    <div class="text-6xl mb-4">🎨</div>
    <h2 class="text-2xl font-bold mb-2">欢迎使用 DesignHub v1.1</h2>
    <p class="text-neutral-500 mb-2">国内外 9 个设计源一站搜索</p>
    <p class="text-xs text-neutral-400 mb-6">Pinterest · Behance · Dribbble · Unsplash · Pexels · Pixabay · 站酷 · UI中国 · 花瓣</p>`;
}

function escapeHtml(s) {
  return String(s || '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}

// ============ 渲染图块 ============
function renderPin(item) {
  if (!item.image_url) return;
  const div = document.createElement('div');
  div.className = 'pin';
  let aspect = '';
  if (item.width && item.height) aspect = `aspect-ratio:${item.width}/${item.height};`;
  const tagsHtml = (item.tags || []).slice(0, 3).map(t =>
    `<span class="text-xs text-white/80">${escapeHtml(t.split(' ')[1] || t.split(' ')[0])}</span>`
  ).join(' · ');
  div.innerHTML = `
    <div style="${aspect}background:#f3f3f3;">
      <img loading="lazy" src="${item.thumbnail || item.image_url}" alt="${escapeHtml(item.title)}" referrerpolicy="no-referrer" onerror="this.parentElement.style.minHeight='200px';this.style.display='none';this.parentElement.innerHTML='<div class=\\'flex items-center justify-center h-full text-neutral-400 text-sm\\'>加载失败</div>'" />
    </div>
    <div class="overlay">
      <span class="source-badge src-${item.source}">${item.source}</span>
      <div>
        ${item.title ? `<div class="pin-title">${escapeHtml(item.title)}</div>` : ''}
        ${tagsHtml ? `<div class="mt-1 truncate">${tagsHtml}</div>` : ''}
      </div>
    </div>`;
  div.onclick = () => openDetail(item);
  $('#grid').appendChild(div);
  fetch('/api/track', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({image_id: item.id || item.image_url, action: 'view', tags: item.tags || []})
  }).catch(() => {});
}

// ============ 详情 ============
function openDetail(item) {
  state.currentItem = item;
  $('#detailImg').src = item.image_url;
  $('#detailTitle').textContent = item.title || '无标题';
  $('#detailDesc').textContent = item.description || '';
  $('#detailAuthor').textContent = item.author ? `By ${item.author}` : '';
  $('#detailSource').textContent = item.source;
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

// ============ 收藏 ============
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
  if (state.mode === 'favorites') showFavorites();
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

// ============ 收藏夹 ============
async function showFavorites() {
  state.mode = 'favorites';
  $('#grid').innerHTML = '';
  $('#empty').classList.add('hidden');
  $('#filters').classList.add('hidden');
  $('#loading').classList.remove('hidden');
  const res = await fetch('/api/favorites');
  const data = await res.json();
  $('#loading').classList.add('hidden');
  if (!data.items || !data.items.length) {
    $('#favToolbar').classList.add('hidden');
    $('#empty').classList.remove('hidden');
    $('#empty').innerHTML = `<div class="text-6xl mb-4">💔</div><h2 class="text-2xl font-bold mb-2">收藏夹是空的</h2><p class="text-neutral-500">看到喜欢的图点击 ❤️</p>`;
    return;
  }
  $('#favCount').textContent = data.items.length;
  $('#favToolbar').classList.remove('hidden');
  data.items.forEach(it => { state.favorites.add(it.id || it.image_url); renderPin(it); });
}

// ============ 批量下载 ZIP（核心新功能）============
async function downloadAllFavorites() {
  $('#downloadBtn').disabled = true;
  $('#dlStatus').textContent = '启动打包任务...';
  $('#dlText').textContent = '0 / 0';
  $('#dlFill').style.width = '0%';
  $('#dlHint').classList.add('hidden');
  $('#downloadModal').classList.remove('hidden');

  try {
    // 1. 启动任务
    const startRes = await fetch('/api/download/start', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({})
    });
    if (!startRes.ok) {
      const err = await startRes.json().catch(() => ({}));
      throw new Error(err.detail || '启动任务失败');
    }
    const { task_id, total } = await startRes.json();
    $('#dlStatus').textContent = `正在下载图片...`;
    $('#dlText').textContent = `0 / ${total}`;
    if (total > 20) $('#dlHint').classList.remove('hidden');

    // 2. 轮询进度
    const pollResult = await pollDownloadStatus(task_id, total);
    if (pollResult.status === 'error') {
      throw new Error(pollResult.error || '打包失败');
    }

    // 3. 触发下载
    $('#dlStatus').textContent = '打包完成，正在下载...';
    const a = document.createElement('a');
    a.href = `/api/download/file/${task_id}`;
    a.download = `designhub_favorites_${Date.now()}.zip`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);

    setTimeout(() => {
      $('#downloadModal').classList.add('hidden');
      $('#downloadBtn').disabled = false;
      showToast(`✓ 已打包 ${pollResult.done - pollResult.failed} 张图（失败 ${pollResult.failed} 张）`);
    }, 1500);
  } catch (e) {
    $('#downloadModal').classList.add('hidden');
    $('#downloadBtn').disabled = false;
    showToast('✗ 下载失败：' + e.message);
  }
}

function pollDownloadStatus(taskId, total) {
  return new Promise((resolve) => {
    let consecutiveErrors = 0;
    const timer = setInterval(async () => {
      try {
        const res = await fetch(`/api/download/status/${taskId}`);
        if (!res.ok) {
          consecutiveErrors++;
          if (consecutiveErrors > 5) {
            clearInterval(timer);
            resolve({status: 'error', error: '任务状态查询失败'});
          }
          return;
        }
        consecutiveErrors = 0;
        const st = await res.json();
        $('#dlFill').style.width = `${st.progress}%`;<think> 用户想要扩展之前的代码，接入 Dribbble、站酷、UI中国 等设计平台，并添加批量下载收藏夹为 ZIP 的功能。我先来分析这些平台的特点——Dribbble 是国际设计平台，但已经关闭了公开 API，需要通过 HTML 爬取；其他平台也需要类似的方案。

现在我在研究各个平台的具体数据获取方式，包括它们的搜索 URL、API 端点和 HTML 结构。

站酷需要处理反爬虫机制，而 UI 中国则需要 HTML 解析。对于 ZIP 下载，我打算用内存中的 zipfile 模块配合异步并发下载来实现流式返回。

Writing scraper classes... I'm finishing up the HTML parsing logic for Dribbble shots, extracting IDs, images, titles and links from the page structure, then falling back to parsing embedded JSON data if the HTML approach doesn't yield results. The Dribbble structure seems fragile though, so I should make this more robust to handle variations in their markup. Now I'm moving on to implement the scraper for Zcool's search API.

Writing the ZCool scraper class... I'm realizing that Zcool's search results are structured with image URLs in `data-original` attributes within card elements, and the page uses Vue with initial state data embedded in the HTML. Rather than parsing the complex page structure, I could hit their search API directly or use a more robust approach that tries multiple URL patterns and extraction methods. For UI China, the domain is ui.cn and the scraping will be similarly challenging due to how Chinese design platforms handle dynamic content.

Building the ZIP download endpoint... Writing the download handler... Writing the parser logic... Writing the ZCool scraper... Writing the UI China scraper... I'm working through the regex pattern to extract work items from the HTML, deduplicating by image URL, and building standardized objects with IDs, titles, and links. Now I'm reconsidering which design platforms to support—Dribbble, ZCOOL, and UI China are the priority, though I'm also thinking about whether to add Huaban or other Chinese design communities. The key challenge is implementing efficient ZIP downloads for large collections with proper concurrency limits and correct headers to avoid IP blocking.

Defining utility functions for sanitizing filenames and guessing image extensions...

Now I'm setting up the download endpoint that accepts optional image IDs to batch download favorites as a ZIP file. I'm retrieving all favorites from cache, filtering by the provided IDs if specified, then creating a temporary ZIP file. I'm using a semaphore to limit concurrent downloads to 5 and setting up an async function to download each image with appropriate headers and referer information based on the source.

Downloading images and writing to ZIP... I'm thinking through the best structure for presenting this response — I should provide complete code for the new crawler files, then use a mix of full file replacements for heavily modified files like main.py and incremental patches for lighter changes. I'll organize it as: overview of new features, complete new crawler implementations, then modified files with either full code or key sections depending on the scope of changes, followed by testing and deployment steps.</think>

# DesignHub v1.1 增量升级：三大设计站 + ZIP 批量下载

## 一、本次升级地图
