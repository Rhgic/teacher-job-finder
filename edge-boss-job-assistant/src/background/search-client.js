/**
 * 公开信息检索客户端。支持 Tavily 和 Serper，都是「给关键词返链接和摘要」。
 *
 * 这里只读检索 API 返回的公开摘要，不去抓任何需要登录的页面。
 * 返回的 URL 会原样带到侧边栏，你能自己点开核对 —— 这是整个背调能不能信的关键。
 */

const TIMEOUT_MS = 20000;

export class SearchError extends Error {
  constructor(message, kind) {
    super(message);
    this.name = 'SearchError';
    this.kind = kind;
  }
}

/**
 * @returns {Promise<Array<{url:string,title:string,content:string}>>}
 */
export async function search({ provider, apiKey, query, maxResults = 5 }) {
  if (provider === 'none') return [];
  if (!apiKey) throw new SearchError('没有配置检索 API Key', 'config');

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    if (provider === 'tavily') return await tavily({ apiKey, query, maxResults, signal: controller.signal });
    if (provider === 'serper') return await serper({ apiKey, query, maxResults, signal: controller.signal });
    throw new SearchError(`不认识的检索服务：${provider}`, 'config');
  } catch (e) {
    if (e.name === 'AbortError') throw new SearchError('检索超时', 'timeout');
    if (e instanceof SearchError) throw e;
    throw new SearchError(`检索失败：${e.message}`, 'network');
  } finally {
    clearTimeout(timer);
  }
}

async function tavily({ apiKey, query, maxResults, signal }) {
  const res = await fetch('https://api.tavily.com/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      api_key: apiKey,
      query,
      max_results: maxResults,
      search_depth: 'basic',
      include_answer: false
    }),
    signal
  });
  if (!res.ok) throw new SearchError(`Tavily 返回 ${res.status}`, 'http');
  const data = await res.json();
  return (data.results || []).map((r) => ({
    url: r.url,
    title: r.title || '',
    content: r.content || ''
  }));
}

async function serper({ apiKey, query, maxResults, signal }) {
  const res = await fetch('https://google.serper.dev/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-API-KEY': apiKey },
    body: JSON.stringify({ q: query, num: maxResults, gl: 'cn', hl: 'zh-cn' }),
    signal
  });
  if (!res.ok) throw new SearchError(`Serper 返回 ${res.status}`, 'http');
  const data = await res.json();
  return (data.organic || []).slice(0, maxResults).map((r) => ({
    url: r.link,
    title: r.title || '',
    content: r.snippet || ''
  }));
}

/** 多个查询并发跑，按 URL 去重。某个查询挂了不影响其他的。 */
export async function searchMany({ provider, apiKey, queries, maxResults = 4 }) {
  const settled = await Promise.allSettled(
    queries.map((query) => search({ provider, apiKey, query, maxResults }))
  );
  const seen = new Set();
  const out = [];
  const errors = [];
  for (const s of settled) {
    if (s.status === 'rejected') {
      errors.push(s.reason?.message || String(s.reason));
      continue;
    }
    for (const r of s.value) {
      if (!r.url || seen.has(r.url)) continue;
      seen.add(r.url);
      out.push(r);
    }
  }
  return { results: out, errors };
}
