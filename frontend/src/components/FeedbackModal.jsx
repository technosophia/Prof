import { useEffect, useRef, useState } from 'react'
import { Star, X } from 'lucide-react'

import { feedback } from '@/lib/api'

const TAB_LAST = 'last'
const TAB_CONVERSATION = 'conversation'
const TAB_APP = 'app'

export default function FeedbackModal({
  open,
  onClose,
  conversationId = null,
  lastAssistantIndex = -1,
}) {
  const modalRef = useRef(null)
  const [tab, setTab] = useState(TAB_LAST)

  const [lastSentiment, setLastSentiment] = useState('')
  const [lastComment, setLastComment] = useState('')
  const [lastLoading, setLastLoading] = useState(false)
  const [lastError, setLastError] = useState('')
  const [lastOk, setLastOk] = useState(false)

  const [conversationComment, setConversationComment] = useState('')
  const [conversationLoading, setConversationLoading] = useState(false)
  const [conversationError, setConversationError] = useState('')
  const [conversationOk, setConversationOk] = useState(false)

  const [appComment, setAppComment] = useState('')
  const [appRating, setAppRating] = useState(null)
  const [appLoading, setAppLoading] = useState(false)
  const [appError, setAppError] = useState('')
  const [appOk, setAppOk] = useState(false)

  useEffect(() => {
    if (!open) return

    function onKeyDown(event) {
      if (event.key === 'Escape') {
        onClose()
        return
      }

      if (event.key !== 'Tab' || !modalRef.current) return
      const focusables = modalRef.current.querySelectorAll(
        'button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )
      if (!focusables.length) return
      const first = focusables[0]
      const last = focusables[focusables.length - 1]

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown)
    const firstFocusable = modalRef.current?.querySelector('button, textarea, input')
    firstFocusable?.focus()

    return () => {
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open, onClose])

  if (!open) return null

  function resetLast() {
    setLastSentiment('')
    setLastComment('')
    setLastError('')
    setLastOk(false)
  }

  function resetConversation() {
    setConversationComment('')
    setConversationError('')
    setConversationOk(false)
  }

  function resetApp() {
    setAppComment('')
    setAppRating(null)
    setAppError('')
    setAppOk(false)
  }

  async function submitLastFeedback() {
    if (!conversationId || lastAssistantIndex < 0 || !lastSentiment || lastLoading) return
    setLastLoading(true)
    setLastError('')

    try {
      await feedback.message(conversationId, lastAssistantIndex, lastSentiment, lastComment)
      setLastOk(true)
      window.setTimeout(resetLast, 2000)
    } catch (error) {
      setLastError(error?.message || 'Feedback request failed')
    } finally {
      setLastLoading(false)
    }
  }

  async function submitConversationFeedback() {
    if (!conversationId || !conversationComment.trim() || conversationLoading) return
    setConversationLoading(true)
    setConversationError('')

    try {
      await feedback.conversation(conversationId, conversationComment.trim())
      setConversationOk(true)
      window.setTimeout(resetConversation, 2000)
    } catch (error) {
      setConversationError(error?.message || 'Feedback request failed')
    } finally {
      setConversationLoading(false)
    }
  }

  async function submitAppFeedback() {
    if (!appComment.trim() || appLoading) return
    setAppLoading(true)
    setAppError('')

    try {
      await feedback.app(appComment.trim(), appRating)
      setAppOk(true)
      window.setTimeout(resetApp, 2000)
    } catch (error) {
      setAppError(error?.message || 'Feedback request failed')
    } finally {
      setAppLoading(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-label="Feedback"
        className="w-full max-w-xl rounded-lg border border-slate-700 bg-slate-900 p-4 text-slate-100 shadow-xl"
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Feedback</h2>
          <button className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-slate-100" onClick={onClose} aria-label="Close feedback modal">
            <X size={18} />
          </button>
        </div>

        <div className="mb-4 flex gap-2 text-xs">
          <button
            type="button"
            className={`rounded px-3 py-1.5 ${tab === TAB_LAST ? 'bg-slate-700 text-white' : 'bg-slate-800 text-slate-400 hover:text-slate-200'}`}
            onClick={() => setTab(TAB_LAST)}
            disabled={lastAssistantIndex < 0}
          >
            Last message
          </button>
          <button
            type="button"
            className={`rounded px-3 py-1.5 ${tab === TAB_CONVERSATION ? 'bg-slate-700 text-white' : 'bg-slate-800 text-slate-400 hover:text-slate-200'}`}
            onClick={() => setTab(TAB_CONVERSATION)}
            disabled={!conversationId}
          >
            Conversation
          </button>
          <button
            type="button"
            className={`rounded px-3 py-1.5 ${tab === TAB_APP ? 'bg-slate-700 text-white' : 'bg-slate-800 text-slate-400 hover:text-slate-200'}`}
            onClick={() => setTab(TAB_APP)}
          >
            App
          </button>
        </div>

        {tab === TAB_LAST && (
          <div className="space-y-3">
            {lastAssistantIndex < 0 ? (
              <p className="text-sm text-slate-400">No assistant message yet.</p>
            ) : (
              <>
                <div className="flex gap-2">
                  <button
                    type="button"
                    className={`rounded px-3 py-1.5 text-sm ${lastSentiment === 'positive' ? 'bg-green-700 text-white' : 'bg-slate-800 text-slate-300 hover:text-white'}`}
                    onClick={() => setLastSentiment('positive')}
                  >
                    👍 Helpful
                  </button>
                  <button
                    type="button"
                    className={`rounded px-3 py-1.5 text-sm ${lastSentiment === 'negative' ? 'bg-red-700 text-white' : 'bg-slate-800 text-slate-300 hover:text-white'}`}
                    onClick={() => setLastSentiment('negative')}
                  >
                    👎 Not helpful
                  </button>
                </div>
                <textarea
                  className="h-24 w-full rounded border border-slate-700 bg-slate-950 p-2 text-sm outline-none focus:border-slate-500"
                  maxLength={500}
                  value={lastComment}
                  onChange={(event) => setLastComment(event.target.value)}
                  placeholder="Optional comment"
                />
                <div className="text-right text-xs text-slate-500">{lastComment.length}/500</div>
                {lastError && <p className="text-xs text-red-400">{lastError}</p>}
                {lastOk && <p className="text-xs text-emerald-400">✅ Feedback sent.</p>}
                <button
                  type="button"
                  className="rounded bg-slate-700 px-3 py-1.5 text-sm hover:bg-slate-600 disabled:cursor-not-allowed disabled:opacity-50"
                  onClick={submitLastFeedback}
                  disabled={lastLoading || !lastSentiment || lastAssistantIndex < 0}
                >
                  {lastLoading ? 'Submitting…' : 'Submit'}
                </button>
              </>
            )}
          </div>
        )}

        {tab === TAB_CONVERSATION && (
          <div className="space-y-3">
            <textarea
              className="h-28 w-full rounded border border-slate-700 bg-slate-950 p-2 text-sm outline-none focus:border-slate-500"
              maxLength={1000}
              value={conversationComment}
              onChange={(event) => setConversationComment(event.target.value)}
              placeholder="Tell us about this conversation"
            />
            <div className="text-right text-xs text-slate-500">{conversationComment.length}/1000</div>
            {conversationError && <p className="text-xs text-red-400">{conversationError}</p>}
            {conversationOk && <p className="text-xs text-emerald-400">✅ Feedback sent.</p>}
            <button
              type="button"
              className="rounded bg-slate-700 px-3 py-1.5 text-sm hover:bg-slate-600 disabled:cursor-not-allowed disabled:opacity-50"
              onClick={submitConversationFeedback}
              disabled={conversationLoading || !conversationComment.trim() || !conversationId}
            >
              {conversationLoading ? 'Submitting…' : 'Submit'}
            </button>
          </div>
        )}

        {tab === TAB_APP && (
          <div className="space-y-3">
            <div className="flex gap-1">
              {[1, 2, 3, 4, 5].map((value) => (
                <button
                  key={`star-${value}`}
                  type="button"
                  className={`rounded p-1 ${appRating && appRating >= value ? 'text-amber-400' : 'text-slate-500 hover:text-slate-200'}`}
                  onClick={() => setAppRating(value)}
                  aria-label={`Set rating ${value}`}
                >
                  <Star size={18} fill={appRating && appRating >= value ? 'currentColor' : 'none'} />
                </button>
              ))}
            </div>
            <textarea
              className="h-28 w-full rounded border border-slate-700 bg-slate-950 p-2 text-sm outline-none focus:border-slate-500"
              maxLength={1000}
              value={appComment}
              onChange={(event) => setAppComment(event.target.value)}
              placeholder="Tell us about the app"
            />
            <div className="text-right text-xs text-slate-500">{appComment.length}/1000</div>
            {appError && <p className="text-xs text-red-400">{appError}</p>}
            {appOk && <p className="text-xs text-emerald-400">✅ Feedback sent.</p>}
            <button
              type="button"
              className="rounded bg-slate-700 px-3 py-1.5 text-sm hover:bg-slate-600 disabled:cursor-not-allowed disabled:opacity-50"
              onClick={submitAppFeedback}
              disabled={appLoading || !appComment.trim()}
            >
              {appLoading ? 'Submitting…' : 'Submit'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
