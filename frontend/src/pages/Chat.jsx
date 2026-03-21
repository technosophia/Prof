import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Menu } from 'lucide-react'
import { auth, conversations, masquerade, regenerateLastResponse, streamChat, admin } from '@/lib/api'
import { Button } from '@/components/ui/button'
import ConversationList from '@/components/ConversationList'
import ChatMessages from '@/components/ChatMessages'
import ChatInput from '@/components/ChatInput'
import FeedbackModal from '@/components/FeedbackModal'
import RegenerateButtons from '@/components/RegenerateButtons'

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
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  const [llmStatus, setLlmStatus] = useState(null)
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

        // Load LLM status for everyone
        const status = await admin.llm.get()
        setLlmStatus(status)

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

  async function handleLlmChange(llmId) {
    try {
      await admin.llm.set(llmId)
      const status = await admin.llm.get()
      setLlmStatus(status)
    } catch (err) {
      console.error('Failed to change LLM:', err)
    }
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

  // NEW: Regenerate with specific result limit
  function onRegenerateWithLimit(limit) {
    if (!currentId || streaming || messages.length < 1) return

    let lastUserIdx = -1
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      if (messages[i].role === 'user') {
        lastUserIdx = i
        break
      }
    }
    if (lastUserIdx < 0) return

    // Keep messages up to and including the last user message
    const base = messages.slice(0, lastUserIdx + 1)

    setStreaming(true)
    // Set messages to base + a new empty assistant message
    setMessages([...base, { role: 'assistant', content: '' }])

    regenerateLastResponse(
      currentId,
      (chunk) => {
        setMessages((prev) => {
          const next = [...prev]
          // Update the last message (which is the assistant message)
          next[next.length - 1] = {
            ...next[next.length - 1],
            content: next[next.length - 1].content + chunk
          }
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
      limit // NEW: Pass the result limit
    )
  }

  // Keep original for backward compatibility
  function onRegenerate() {
    onRegenerateWithLimit(3) // Default limit = 3
  }

  const currentTitle = list.find((c) => c.id === currentId)?.title ?? ''
  const lastAssistantIndex = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      if (messages[i].role === 'assistant') return i
    }
    return -1
  }, [messages])

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
        onFeedback={() => setFeedbackOpen(true)}
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

          {/* LLM Selector - visible to all, editable by admin only */}
          {llmStatus && (
            <div className="flex items-center gap-1 shrink-0">
              <span className="text-xs text-slate-400 hidden sm:inline">LLM:</span>
              {llmStatus.can_change ? (
                <select
                  className="text-xs bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-300 max-w-[150px]"
                  value={llmStatus.current_llm?.id ?? ''}
                  onChange={(e) => e.target.value && handleLlmChange(e.target.value)}
                >
                  {llmStatus.available_llms
                    .filter((llm) => llm.available)
                    .map((llm) => (
                      <option key={llm.id} value={llm.id}>
                        {llm.name}
                      </option>
                    ))}
                </select>
              ) : (
                <span className="text-xs text-slate-400 bg-slate-800 rounded px-2 py-1">
                  {llmStatus.current_llm?.name ?? 'Unknown'}
                </span>
              )}
            </div>
          )}
        </header>

        <ChatMessages
          messages={messages}
          streaming={streaming}
          canInspect={isPowerUser}
          conversationId={currentId}
        />

        {/* NEW: Regenerate buttons section - only show if there are messages and not streaming */}
        {messages.length > 0 && !streaming && (
          <RegenerateButtons
            onRegenerate={onRegenerate}
            onRegenerateWithMore={() => onRegenerateWithLimit(5)}  // More context = 5
            onRegenerateWithLess={() => onRegenerateWithLimit(1)}  // Less context = 1
            disabled={streaming}
          />
        )}

        <ChatInput onSend={onSend} disabled={streaming || !currentId} />
        <FeedbackModal
          open={feedbackOpen}
          onClose={() => setFeedbackOpen(false)}
          conversationId={currentId}
          lastAssistantIndex={lastAssistantIndex}
        />
      </section>
    </div>
  )
}
