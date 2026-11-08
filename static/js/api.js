/** API 请求封装：自动带会话 Cookie 与 CSRF 头，统一错误处理。 */

async function request(method, url, body, opts = {}) {
  const headers = { "X-Requested-With": "XMLHttpRequest" };
  let payload;
  if (body instanceof FormData) {
    payload = body;
  } else if (body != null) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const resp = await fetch(url, {
    method, headers, body: payload, credentials: "same-origin",
  });
  if (opts.raw) return resp;
  let data = null;
  try { data = await resp.json(); } catch { /* 非JSON */ }
  if (!resp.ok) {
    const msg = (data && (data.detail || data.message)) || `请求失败（${resp.status}）`;
    const err = new Error(msg);
    err.status = resp.status;
    throw err;
  }
  return data;
}

export const api = {
  get: (url) => request("GET", url),
  post: (url, body) => request("POST", url, body),
  put: (url, body) => request("PUT", url, body),
  del: (url) => request("DELETE", url),
  upload: (url, formData) => request("POST", url, formData),
  raw: (url, opts) => request("GET", url, null, opts),
};

export function download(url) {
  // 带 Cookie 的附件下载（管理员导出等）
  const a = document.createElement("a");
  a.href = url;
  a.click();
}
