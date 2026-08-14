/**
 * OpenAI 兼容接口客户端，默认指向 DeepSeek。
 *
 * 坑记录：DeepSeek 开 response_format: json_object 时，
 * 如果 messages 里一个 "json" 字样都没有，接口会直接 400。
 * 所以这里发之前先自检，缺了就自己补一句，而不是等它报错。
 */

const TIMEOUT_MS = 45000;

export class LlmError extends Error {
  constructor(message, kind) {
    super(message);
    this.name = 'LlmError';
    this.kind = kind; // 'config' | 'network' | 'http' | 'timeout' | 'empty'
  }
}

/**
 * @returns {Promise<string>} 模型返回的文本内容
 */
export async function chatJson({ baseUrl, apiKey, model, system, user, temperature = 0 }) {
  if (!apiKey) throw new LlmError('没有配置模型 API Key', 'config');
  if (!baseUrl) throw new LlmError('没有配置模型接口地址', 'config');

  const messages = [
    { role: 'system', content: system },
    { role: 'user', content: user }
  ];

  // json_object 模式的硬性要求
  const mentionsJson = messages.some((m) => /json/i.test(m.content));
  if (!mentionsJson) {
    messages[0].content += '\n\n请用 JSON 格式回答。';
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  let res;
  try {
    res = await fetch(`${baseUrl.replace(/\/$/, '')}/v1/chat/completions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${apiKey}`
      },
      body: JSON.stringify({
        model,
        messages,
        temperature,
        response_format: { type: 'json_object' },
        max_tokens: 1600
      }),
      signal: controller.signal
    });
  } catch (e) {
    clearTimeout(timer);
    if (e.name === 'AbortError') throw new LlmError('模型调用超时', 'timeout');
    throw new LlmError(`模型调用失败：${e.message}`, 'network');
  }
  clearTimeout(timer);

  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new LlmError(`模型返回 ${res.status}：${body.slice(0, 200)}`, 'http');
  }

  const data = await res.json().catch(() => null);
  const content = data?.choices?.[0]?.message?.content;
  if (!content) throw new LlmError('模型返回内容为空', 'empty');
  return content;
}
