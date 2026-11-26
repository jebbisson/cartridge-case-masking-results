export async function request(path, { signal, body } = {}) {
  const multipart = body instanceof FormData;
  let response;
  try {
    response = await fetch(path, {
      signal,
      mode: 'same-origin',
      cache: 'no-store',
      ...(body === undefined ? {} : {
        method: 'POST',
        ...(multipart ? { body } : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
      }),
    });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new Error('Cannot reach the local review server. Check that Go is running, then retry.');
  }
  const json = (response.headers.get('content-type') || '').includes('application/json');
  const data = json ? await response.json().catch(() => null) : await response.text();
  if (!response.ok) {
    const message = json ? data?.error || data?.message : !/^\s*</.test(data) && data.trim();
    throw Object.assign(new Error(message || `Request failed (HTTP ${response.status}).`), { status: response.status });
  }
  if (!json || data === null) throw new Error('The review server did not return JSON.');
  return data;
}

export const casePath = id => `/api/cases/${encodeURIComponent(id)}`;
