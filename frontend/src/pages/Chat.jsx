import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { auth, conversations, regenerateLastResponse, streamChat } from '@/lib/api'
import { Button } from '@/components/ui/button'
import ConversationList from '@/components/ConversationList'
import ChatMessages from '@/components/ChatMessages'
import ChatInput from '@/components/ChatInput'

export default function Chat() {
  const [user, setUser] = useState(null)
  const [list, setList] = useState([])
  const [currentId, setCurrentId] = useState(null)
  const [messages, setMessages] = useState([])
  const [streaming, setStreaming] = useState(false)
  const navigate = useNavigate()

  async function loadConversations(selectFirst = true) {
    const items = await conversations.list()
    if (!items.length) {
      const created = await conversations.create('New conversation')
      setList([created])
      setCurrentId(created.id)
      setMessages([])
      return
    }
    setList(items)
    if (selectFirst && !currentId) setCurrentId(items[0].id)
  }

  useEffect(() => {
    auth
      .me()
      .then(setUser)
      .then(() => loadConversations())
      .catch(() => {
        localStorage.removeItem('token')
        navigate('/login')
      })
  }, [])

  useEffect(() => {
    if (!currentId) return
    conversations.messages(currentId).then(setMessages)
  }, [currentId])

  async function onCreate() {
    const created = await conversations.create('New conversation')
    setList((prev) => [created, ...prev])
    setCurrentId(created.id)
    setMessages([])
  }

  async function onRename(id, currentTitle) {
    const title = window.prompt('New conversation title', currentTitle)
    if (!title || !title.trim() || title.trim() === currentTitle) return
    await conversations.rename(id, title.trim())
    await loadConversations(false)
  }

  async function onDelete(id, title) {
    const ok = window.confirm(`Delete conversation \"${title}\"?`)
    if (!ok) return
    await conversations.delete(id)
    const items = await conversations.list()
    if (!items.length) {
      const created = await conversations.create('New conversation')
      setList([created])
      setCurrentId(created.id)
      setMessages([])
      return
    }
    setList(items)
    setCurrentId(items[0].id)
  }

  function onLogout() {
    localStorage.removeItem('token')
    navigate('/login')
  }

  function onSend(text) {
    if (!currentId || streaming) return
    setStreaming(true)
    setMessages((prev) => [...prev, { role: 'user', content: text }, { role: 'assistant', content: '' }])

    streamChat(
      currentId,
      text,
      (chunk) => {
        setMessages((prev) => {
          const next = [...prev]
          next[next.length - 1] = { ...next[next.length - 1], content: next[next.length - 1].content + chunk }
          return next
        })
      },
      () => {
        setStreaming(false)
        loadConversations(false)
        conversations.messages(currentId).then(setMessages)
      },
      () => {
        setStreaming(false)
      },
    )
  }

  function onRegenerate() {
    if (!currentId || streaming || messages.length < 1) return

    let lastUserIdx = -1
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      if (messages[i].role === 'user') {
        lastUserIdx = i
        break
      }
    }
    if (lastUserIdx < 0) return

    const base = messages.slice(0, lastUserIdx + 1)
    setStreaming(true)
    setMessages([...base, { role: 'assistant', content: '' }])

    regenerateLastResponse(
      currentId,
      (chunk) => {
        setMessages((prev) => {
          const next = [...prev]
          next[next.length - 1] = { ...next[next.length - 1], content: next[next.length - 1].content + chunk }
          return next
        })
      },
      () => {
        setStreaming(false)
        loadConversations(false)
        conversations.messages(currentId).then(setMessages)
      },
      () => {
        setStreaming(false)
      },
    )
  }

  return (
    <div className="flex h-screen">
      <ConversationList
        conversations={list}
        currentId={currentId}
        onSelect={setCurrentId}
        onCreate={onCreate}
        onRename={onRename}
        onDelete={onDelete}
        onLogout={onLogout}
      />
      <section className="flex flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-slate-800 px-4 py-3 text-sm text-slate-300">
          <span>{user ? `${user.name} (${user.role})` : 'Loading...'}</span>
          <Button className="bg-slate-700 hover:bg-slate-600" onClick={onRegenerate} disabled={streaming || messages.length === 0}>
            Regenerate last response
          </Button>
        </header>
        <ChatMessages messages={messages} streaming={streaming} />
        <ChatInput onSend={onSend} disabled={streaming || !currentId} />
      </section>
    </div>
  )
}
