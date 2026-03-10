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
  messages: (id) => get(`/api/conversations/${id}/messages`),
}

export function streamChat(conversationId, message, onChunk, onDone, onError) {
  const token = localStorage.getItem('token')
  fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ conversation_id: conversationId, message }),
  })
    .then((res) => {
      if (!res.ok || !res.body) throw new Error(`Stream failed: ${res.status}`)
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      function pump() {
        reader.read().then(({ done, value }) => {
          if (done) {
            onDone()
            return
          }
          buffer += decoder.decode(value, { stream: true })
          const parts = buffer.split('\n')
          buffer = parts.pop() || ''
          parts.forEach((line) => {
            if (line.startsWith('data: ')) {
              const data = JSON.parse(line.slice(6))
              if (data.type === 'chunk') onChunk(data.content)
              if (data.type === 'done') onDone()
              if (data.type === 'error') onError(data.content)
            }
          })
          pump()
        })
      }
      pump()
    })
    .catch((err) => onError(err?.message || 'stream error'))
}
