import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Menu } from 'lucide-react'
import { auth, conversations, masquerade, regenerateLastResponse, streamChat } from '@/lib/api'
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
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [masqueradeTargets, setMasqueradeTargets] = useState([])
  const [isMasquerading, setIsMasquerading] = useState(false)
  const [masqueraderId, setMasqueraderId] = useState(null)
  const navigate = useNavigate()
  const isPowerUser = user?.role === 'admin' || user?.role === 'master' || !!user?.masquerader_id

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
      .then(async (me) => {
        setUser(me)
        setIsMasquerading(!!me.masquerader_id)
        setMasqueraderId(me.masquerader_id ?? null)

        if (me.role !== 'normal' || me.masquerader_id) {
          const targets = await masquerade.targets()
          setMasqueradeTargets(targets)
        }

        await loadConversations()
      })
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
    const ok = window.confirm(`Delete conversation "${title}"?`)
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

  async function handleMasquerade(targetId) {
    const data = await masquerade.as(targetId)
    localStorage.setItem('token', data.access_token)
    window.location.reload()
  }

  async function handleUnmasquerade() {
    if (!masqueraderId) return
    const data = await masquerade.as(masqueraderId)
    localStorage.setItem('token', data.access_token)
    window.location.reload()
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

  const currentTitle = list.find((c) => c.id === currentId)?.title ?? ''

  return (
    <div className="flex h-screen overflow-hidden">
      <ConversationList
        conversations={list}
        currentId={currentId}
        onSelect={setCurrentId}
        onCreate={onCreate}
        onRename={onRename}
        onDelete={onDelete}
        onLogout={onLogout}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />

      <section className="flex flex-1 flex-col min-w-0">
        <header className="flex items-center gap-2 border-b border-slate-800 px-3 py-3 text-sm text-slate-300 shrink-0">
          <button
            className="rounded-md p-1.5 text-slate-400 hover:bg-slate-800 hover:text-slate-100 md:hidden shrink-0"
            onClick={() => setSidebarOpen(true)}
            aria-label="Open sidebar"
          >
            <Menu size={20} />
          </button>

          <span className="flex-1 truncate font-medium text-slate-200">{currentTitle}</span>

          {isPowerUser && masqueradeTargets.length > 0 && (
            <select
              className="text-xs bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-300"
              value={isMasquerading ? user?.id ?? '' : ''}
              onChange={(e) => e.target.value && handleMasquerade(e.target.value)}
            >
              <option value="">View as…</option>
              {masqueradeTargets.map((target) => (
                <option key={target.id} value={target.id}>
                  {target.name} ({target.role})
                </option>
              ))}
            </select>
          )}

          {isMasquerading && (
            <button
              onClick={handleUnmasquerade}
              className="text-xs px-2 py-1 rounded bg-amber-700 hover:bg-amber-600 text-white shrink-0"
            >
              ↩ Exit masquerade
            </button>
          )}

          {isMasquerading && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-amber-800 text-amber-200 shrink-0">
              Viewing as {user?.name} ({user?.role})
            </span>
          )}

          {!isMasquerading && (
            <span className="hidden sm:block shrink-0 text-slate-400">
              {user ? `${user.name} (${user.role})` : ''}
            </span>
          )}

          {isPowerUser && (
            <Link
              to="/stats"
              className="text-xs px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-white shrink-0"
            >
              Stats
            </Link>
          )}
          <Button
            className="bg-slate-700 hover:bg-slate-600 shrink-0 text-xs px-2 py-1.5"
            onClick={onRegenerate}
            disabled={streaming || messages.length === 0}
          >
            <span className="hidden sm:inline">Regenerate</span>
            <span className="sm:hidden">↺</span>
          </Button>
        </header>

        <ChatMessages
          messages={messages}
          streaming={streaming}
          canInspect={isPowerUser}
          conversationId={currentId}
        />
        <ChatInput onSend={onSend} disabled={streaming || !currentId} />
      </section>
    </div>
  )
}
