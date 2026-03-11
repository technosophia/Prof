const BASE = ''

function getHeaders() {
  const token = localStorage.getItem('token')
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
}

function formatHttpError(detail, method, path, status) {
  const cleanDetail = (detail || '').trim() || 'no response body'
  return `[API ${method} ${path}] status=${status} detail=${cleanDetail}`
}

async function request(path, options = {}) {
  const method = options.method || 'GET'
  let res
  try {
    res = await fetch(`${BASE}${path}`, { ...options, headers: { ...getHeaders(), ...(options.headers || {}) } })
  } catch (error) {
    throw new Error(`[API ${method} ${path}] network error: ${error?.message || String(error)}`)
  }

  if (!res.ok) {
    let detail = ''
    try {
      detail = await res.text()
    } catch (error) {
      detail = `unable to read error body: ${error?.message || String(error)}`
    }
    throw new Error(formatHttpError(detail, method, path, res.status))
  }

  if (res.status === 204) return null

  try {
    return await res.json()
  } catch (error) {
    throw new Error(`[API ${method} ${path}] invalid JSON response: ${error?.message || String(error)}`)
  }
}

const post = (path, body) => request(path, { method: 'POST', body: JSON.stringify(body) })
const get = (path) => request(path)
const del = (path) => request(path, { method: 'DELETE' })
const patch = (path, body) => request(path, { method: 'PATCH', body: JSON.stringify(body) })

export const auth = {
  login: (userId, password) => post('/api/auth/login', { user_id: userId, password }),
  initPassword: (userId, resetCode, newPassword) =>
    post('/api/auth/init-password', { user_id: userId, reset_code: resetCode, new_password: newPassword }),
  me: () => get('/api/auth/me'),
}

export const conversations = {
  list: () => get('/api/conversations'),
  create: (title) => post('/api/conversations', { title }),
  delete: (id) => del(`/api/conversations/${id}`),
  rename: (id, title) => patch(`/api/conversations/${id}`, { title }),
  messages: (id) => get(`/api/conversations/${id}/messages`),
  usersStats: () => get('/api/conversations/stats/users'),
}

export const masquerade = {
  targets: () => get('/api/auth/masquerade-targets'),
  as: (targetUserId) => post('/api/auth/masquerade', { target_user_id: targetUserId }),
}

export const messageContext = {
  get: (conversationId, messageIndex, timestamp) =>
    get(
      `/api/conversations/${conversationId}/messages/${messageIndex}/context?timestamp=${encodeURIComponent(timestamp ?? '')}`,
    ),
}

function streamSsePost(path, body, onChunk, onDone, onError) {
  const token = localStorage.getItem('token')
  fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  })
    .then((res) => {
      if (!res.ok || !res.body) {
        onError(`[SSE POST ${path}] request failed with status=${res.status}`)
        return
      }
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      function pump() {
        reader
          .read()
          .then(({ done, value }) => {
            if (done) return

            buffer += decoder.decode(value, { stream: true })
            const events = buffer.split('\n\n')
            buffer = events.pop() || ''

            events.forEach((eventBlock) => {
              eventBlock.split('\n').forEach((line) => {
                if (line.startsWith('data: ')) {
                  const data = JSON.parse(line.slice(6))
                  if (data.type === 'chunk') onChunk(data.content)
                  if (data.type === 'done') onDone()
                  if (data.type === 'error') onError(`[SSE POST ${path}] server error: ${data.content}`)
                }
              })
            })

            pump()
          })
          .catch((err) => onError(`[SSE POST ${path}] stream read error: ${err?.message || 'unknown'}`))
      }

      pump()
    })
    .catch((err) => onError(`[SSE POST ${path}] fetch failed: ${err?.message || 'unknown'}`))
}

export function streamChat(conversationId, message, onChunk, onDone, onError) {
  streamSsePost('/api/chat/stream', { conversation_id: conversationId, message }, onChunk, onDone, onError)
}

export function regenerateLastResponse(conversationId, onChunk, onDone, onError) {
  streamSsePost('/api/chat/regenerate-stream', { conversation_id: conversationId }, onChunk, onDone, onError)
}
