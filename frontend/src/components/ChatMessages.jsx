import { Fragment, useEffect, useRef, useState } from 'react'
import { ThumbsDown, ThumbsUp } from 'lucide-react'

import { feedback, messageContext } from '@/lib/api'

function renderInlineMarkdown(text) {
  const parts = []
  const pattern = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\([^\)]+\))/g
  let last = 0
  let key = 0
  let match = pattern.exec(text)

  while (match) {
    if (match.index > last) {
      parts.push(<Fragment key={`text-${key += 1}`}>{text.slice(last, match.index)}</Fragment>)
    }

    const token = match[0]
    if (token.startsWith('**') && token.endsWith('**')) {
      parts.push(<strong key={`strong-${key += 1}`}>{token.slice(2, -2)}</strong>)
    } else if (token.startsWith('*') && token.endsWith('*')) {
      parts.push(<em key={`em-${key += 1}`}>{token.slice(1, -1)}</em>)
    } else if (token.startsWith('`') && token.endsWith('`')) {
      parts.push(
        <code key={`code-${key += 1}`} className="bg-slate-900/70 px-1 py-0.5 rounded text-xs">
          {token.slice(1, -1)}
        </code>,
      )
    } else if (token.startsWith('[')) {
      const bracketEnd = token.indexOf(']')
      const label = token.slice(1, bracketEnd)
      const href = token.slice(bracketEnd + 2, -1)
      parts.push(
        <a key={`link-${key += 1}`} href={href} className="underline text-blue-300" target="_blank" rel="noreferrer">
          {label}
        </a>,
      )
    }

    last = pattern.lastIndex
    match = pattern.exec(text)
  }

  if (last < text.length) {
    parts.push(<Fragment key={`tail-${key += 1}`}>{text.slice(last)}</Fragment>)
  }

  return parts.length ? parts : text
}

function MarkdownBlock({ content, className = '' }) {
  const lines = (content || '').split('\n')
  const blocks = []
  let idx = 0
  let key = 0

  while (idx < lines.length) {
    const line = lines[idx]

    if (line.startsWith('```')) {
      const codeLines = []
      idx += 1
      while (idx < lines.length && !lines[idx].startsWith('```')) {
        codeLines.push(lines[idx])
        idx += 1
      }
      blocks.push(
        <pre key={`pre-${key += 1}`} className="bg-slate-900/70 rounded p-2 overflow-x-auto text-xs mb-2 last:mb-0">
          <code>{codeLines.join('\n')}</code>
        </pre>,
      )
      idx += 1
      continue
    }

    if (line.startsWith('- ')) {
      const items = []
      while (idx < lines.length && lines[idx].startsWith('- ')) {
        items.push(lines[idx].slice(2))
        idx += 1
      }
      blocks.push(
        <ul key={`ul-${key += 1}`} className="list-disc pl-5 mb-2 last:mb-0">
          {items.map((item, itemIdx) => (
            <li key={`li-${itemIdx}`}>{renderInlineMarkdown(item)}</li>
          ))}
        </ul>,
      )
      continue
    }

    if (!line.trim()) {
      idx += 1
      continue
    }

    const headingMatch = line.match(/^(#{1,3})\s+(.*)$/)
    if (headingMatch) {
      const level = headingMatch[1].length
      const headingClass = level === 1 ? 'text-base font-semibold' : level === 2 ? 'text-sm font-semibold' : 'text-sm font-medium'
      blocks.push(
        <div key={`h-${key += 1}`} className={`${headingClass} mb-2 last:mb-0`}>
          {renderInlineMarkdown(headingMatch[2])}
        </div>,
      )
      idx += 1
      continue
    }

    blocks.push(
      <p key={`p-${key += 1}`} className="mb-2 last:mb-0">
        {renderInlineMarkdown(line)}
      </p>,
    )
    idx += 1
  }

  return <div className={className}>{blocks.length ? blocks : content}</div>
}

export default function ChatMessages({ messages, streaming, canInspect = false, conversationId = null }) {
  const bottomRef = useRef(null)
  const [expandedIdx, setExpandedIdx] = useState(null)
  const [contextData, setContextData] = useState({})
  const [messageVotes, setMessageVotes] = useState({})
  const [voteLoading, setVoteLoading] = useState({})
  const [voteError, setVoteError] = useState({})

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages])

  // NEW: Track message versions to detect regeneration
  const [messageVersions, setMessageVersions] = useState({})

  // NEW: When messages change, check if assistant messages have been updated
  useEffect(() => {
    messages.forEach((message, idx) => {
      if (message.role === 'assistant') {
        const versionKey = `${idx}-${message.content.length}`
        if (messageVersions[idx] !== versionKey) {
          // This message has changed - clear its context data
          setContextData(prev => {
            const newData = { ...prev }
            delete newData[idx]
            return newData
          })
          setMessageVersions(prev => ({ ...prev, [idx]: versionKey }))

          // If this message was expanded, refresh its context
          if (expandedIdx === idx) {
            loadContextData(message, idx)
          }
        }
      }
    })
  }, [messages])

  async function loadContextData(message, idx) {
    if (!canInspect || message.role !== 'assistant' || !conversationId) return

    try {
      const data = await messageContext.get(conversationId, idx, message.timestamp)
      setContextData((prev) => ({ ...prev, [idx]: data }))
    } catch (error) {
      setContextData((prev) => ({
        ...prev,
        [idx]: { found: false, debug: error?.message || 'request failed' }
      }))
    }
  }

  async function onInspect(message, idx) {
    if (!canInspect || message.role !== 'assistant' || !conversationId) return

    if (expandedIdx === idx) {
      setExpandedIdx(null)
      return
    }

    // Always refresh context data when expanding, even if we have cached data
    await loadContextData(message, idx)
    setExpandedIdx(idx)
  }

  async function onVoteMessage(idx, sentiment) {
    if (!conversationId || voteLoading[idx] || messageVotes[idx]) return
    setVoteLoading((prev) => ({ ...prev, [idx]: true }))
    setVoteError((prev) => ({ ...prev, [idx]: false }))

    try {
      await feedback.message(conversationId, idx, sentiment)
      setMessageVotes((prev) => ({ ...prev, [idx]: sentiment }))
    } catch (error) {
      setVoteError((prev) => ({ ...prev, [idx]: true }))
      window.setTimeout(() => {
        setVoteError((prev) => ({ ...prev, [idx]: false }))
      }, 2000)
    } finally {
      setVoteLoading((prev) => ({ ...prev, [idx]: false }))
    }
  }

  return (
    <div className="flex-1 overflow-y-auto p-4 min-h-0">
      <div className="space-y-4 max-w-3xl mx-auto">
        {messages.map((m, idx) => {
          const inspectable = canInspect && m.role === 'assistant'
          const currentContext = contextData[idx]
          const showThumbs = m.role === 'assistant' && !streaming
          const disabledVote = voteLoading[idx] || !!messageVotes[idx]

          return (
            <div key={`msg-${idx}-${m.role}-${m.content.length}`} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div>
                <div
                  role={inspectable ? 'button' : undefined}
                  tabIndex={inspectable ? 0 : undefined}
                  onClick={() => onInspect(m, idx)}
                  onKeyDown={(e) => {
                    if (!inspectable) return
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      onInspect(m, idx)
                    }
                  }}
                  className={`max-w-[85%] sm:max-w-[75%] rounded-xl px-4 py-2 text-sm leading-relaxed break-words transition ${
                    m.role === 'user' ? 'bg-blue-600 text-white' : 'bg-slate-800 text-slate-100'
                  } ${inspectable ? 'cursor-pointer hover:ring-1 hover:ring-slate-600' : ''}`}
                >
                  <MarkdownBlock content={m.content} />
                  {streaming && idx === messages.length - 1 && m.role === 'assistant' ? (
                    <span className="ml-1 animate-pulse">▌</span>
                  ) : null}
                </div>

                {showThumbs && (
                  <div className="mt-1 ml-2 flex items-center gap-2 text-slate-500">
                    <button
                      type="button"
                      className={`rounded p-1 transition hover:text-green-400 ${messageVotes[idx] === 'positive' ? 'text-green-400 bg-slate-800' : ''}`}
                      onClick={() => onVoteMessage(idx, 'positive')}
                      disabled={disabledVote}
                      aria-label="Helpful"
                    >
                      <ThumbsUp size={14} />
                    </button>
                    <button
                      type="button"
                      className={`rounded p-1 transition hover:text-red-400 ${messageVotes[idx] === 'negative' ? 'text-red-400 bg-slate-800' : ''}`}
                      onClick={() => onVoteMessage(idx, 'negative')}
                      disabled={disabledVote}
                      aria-label="Not helpful"
                    >
                      <ThumbsDown size={14} />
                    </button>
                    {voteError[idx] && <span className="inline-block h-2 w-2 rounded-full bg-red-500" aria-hidden="true" />}
                  </div>
                )}

                {canInspect && expandedIdx === idx && currentContext && (
                  <div className="mt-1 ml-2 text-xs bg-slate-900 border border-slate-700 rounded p-2 max-w-[85%]">
                    {!currentContext.found ? (
                      <div className="space-y-1">
                        <span className="text-slate-500 italic">No monitor data found for this message.</span>
                        {currentContext.debug && <div className="text-slate-500">debug: {currentContext.debug}</div>}
                      </div>
                    ) : (
                      <>
                        <div className="flex gap-3 text-slate-400 mb-1">
                          <span>🔡 {currentContext.total_tokens} tokens</span>
                          {currentContext.total_cost > 0 && <span>💰 ${currentContext.total_cost.toFixed(6)}</span>}
                          <span>
                            🤖 {currentContext.llm_type}/{currentContext.model}
                          </span>
                        </div>

                        {currentContext.context_messages?.length > 0 && (
                          <details className="mb-1">
                            <summary className="cursor-pointer text-slate-400 hover:text-slate-200">
                              🔧 Context ({currentContext.context_messages.length})
                            </summary>
                            <div className="mt-1 space-y-1">
                              {currentContext.context_messages.map((cm, cmIdx) => (
                                <div key={`ctx-${idx}-${cmIdx}`} className="bg-slate-800 rounded px-2 py-1">
                                  <span className="text-slate-500 uppercase text-[10px]">{cm.role}</span>
                                  <MarkdownBlock content={cm.content} className="text-slate-300 text-[11px] mt-0.5" />
                                </div>
                              ))}
                            </div>
                          </details>
                        )}

                        <details>
                          <summary className="cursor-pointer text-slate-400 hover:text-slate-200">
                            💬 Messages sent ({currentContext.messages?.length ?? 0})
                          </summary>
                          <div className="mt-1 space-y-1">
                            {(currentContext.messages ?? []).map((msg, msgIdx) => (
                              <div key={`llm-msg-${idx}-${msgIdx}`} className="bg-slate-800 rounded px-2 py-1">
                                <span className="text-slate-500 uppercase text-[10px]">{msg.role}</span>
                                <MarkdownBlock content={msg.content} className="text-slate-300 text-[11px] mt-0.5" />
                              </div>
                            ))}
                          </div>
                        </details>
                      </>
                    )}
                  </div>
                )}
              </div>
            </div>
          )
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
