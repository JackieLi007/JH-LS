export const API_BASE = window.__API_BASE__ || '';

export async function requestJson(path, options = {}) {
  const isFormData = options.body instanceof FormData;
  const headers = isFormData ? (options.headers || {}) : {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let message = `Request failed: ${response.status}`;
    try {
      const data = await response.json();
      if (data?.error) message = data.error;
    } catch {
      message = `请求失败（HTTP ${response.status}），服务未返回可识别的错误信息。`;
    }
    throw new Error(message);
  }

  return response.json();
}
