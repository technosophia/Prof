const BASE = ''

function getHeaders() {
  const token = localStorage.getItem('token')
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
}

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, { ...options, headers: { ...getHeaders(), ...(options.headers || {}) } })
  if (!res.ok) {
    const detail = await res.text()
    throw new Error(detail || `Request failed: ${res.status}`)
  }
  if (res.status === 204) return null
  return res.json()
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
}

function streamSsePost(path, body, onChunk, onDone, onError) {
  const token = localStorage.getItem('token')
  fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  })
    .then((res) => {
      if (!res.ok || !res.body) throw new Error(`Stream failed: ${res.status}`)
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
                  if (data.type === 'error') onError(data.content)
                }
              })
            })

            pump()
          })
          .catch((err) => onError(err?.message || 'stream read error'))
      }

      pump()
    })
    .catch((err) => onError(err?.message || 'stream error'))
}

export function streamChat(conversationId, message, onChunk, onDone, onError) {
  streamSsePost('/api/chat/stream', { conversation_id: conversationId, message }, onChunk, onDone, onError)
}

export function regenerateLastResponse(conversationId, onChunk, onDone, onError) {
  streamSsePost('/api/chat/regenerate-stream', { conversation_id: conversationId }, onChunk, onDone, onError)
}
