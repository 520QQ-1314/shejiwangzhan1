/**
 * DesignHub Cloudflare Worker v1.1
 * 新增 Dribbble 支持
 */
const ALLOWED_HOSTS = new Set([
  // Pinterest
  'www.pinterest.com', 'pinterest.com',
  'i.pinimg.com', 's.pinimg.com',
  // Behance
  'www.behance.net', 'behance.net',
  'mir-s3-cdn-cf.behance.net', 'a5.behance.net',
  // Dribbble (v1.1 新增)
  'dribbble.com', 'www.dribbble.com',
  'cdn.dribbble.com',
]);

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': '*',
};

addEventListener('fetch', e => e.respondWith(handle(e.request)));

async function handle(req) {
  if (req.method === 'OPTIONS') return new Response(null, { headers: CORS });
  const url = new URL(req.url);

  if (url.pathname === '/' || url.pathname === '/health') {
    return json({ ok: true, name: 'DesignHub Proxy', version: '1.1', allowed: [...ALLOWED_HOSTS] });
  }
  if (url.pathname !== '/proxy') return json({ error: 'not found' }, 404);

  const target = url.searchParams.get('url');
  if (!target) return json({ error: 'missing url' }, 400);

  let t;
  try { t = new URL(target); }
  catch { return json({ error: 'invalid url' }, 400); }

  if (!ALLOWED_HOSTS.has(t.hostname))
    return json({ error: 'host not allowed', hostname: t.hostname, allowed: [...ALLOWED_HOSTS] }, 403);

  const headers = new Headers();
  const BLOCKED_REQ_HEADERS = [
    'host', 'origin', 'referer', 'cf-connecting-ip', 'cf-ipcountry',
    'cf-ray', 'cf-visitor', 'x-forwarded-for', 'x-forwarded-proto', 'x-real-ip',
  ];
  for (const [k, v] of req.headers) {
    if (!BLOCKED_REQ_HEADERS.includes(k.toLowerCase())) {
      headers.set(k, v);
    }
  }
  headers.set('Host', t.hostname);
  headers.set('Referer', `https://${t.hostname}/`);

  // Dribbble 需要更完整的浏览器伪装
  if (t.hostname.includes('dribbble.com')) {
    headers.set('Accept', 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8');
    headers.set('Accept-Language', 'en-US,en;q=0.9');
    headers.set('Sec-Fetch-Dest', 'document');
    headers.set('Sec-Fetch-Mode', 'navigate');
    headers.set('Sec-Fetch-Site', 'none');
  }

  try {
    const init = { method: req.method, headers, redirect: 'follow' };
    if (!['GET', 'HEAD'].includes(req.method)) init.body = await req.arrayBuffer();
    const r = await fetch(t.toString(), init);

    const h = new Headers(r.headers);
    Object.entries(CORS).forEach(([k, v]) => h.set(k, v));
    h.delete('content-security-policy');
    h.delete('content-security-policy-report-only');
    h.delete('x-frame-options');

    return new Response(r.body, { status: r.status, statusText: r.statusText, headers: h });
  } catch (e) {
    return json({ error: 'fetch failed', message: e.message }, 502);
  }
}

function json(d, s = 200) {
  return new Response(JSON.stringify(d, null, 2), {
    status: s, headers: { 'Content-Type': 'application/json', ...CORS }
  });
}
