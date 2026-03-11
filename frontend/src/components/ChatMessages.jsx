import { useEffect, useRef, useState } from 'react'

import { messageContext } from '@/lib/api'

export default function ChatMessages({ messages, streaming, canInspect = false, conversationId = null }) {
  const bottomRef = useRef(null)
  const [expandedIdx, setExpandedIdx] = useState(null)
  const [contextData, setContextData] = useState({})

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages])

  async function onInspect(message, idx) {
    if (!canInspect || message.role !== 'assistant' || !conversationId) return

    if (expandedIdx === idx) {
      setExpandedIdx(null)
      return
    }

    if (!contextData[idx]) {
      const data = await messageContext.get(conversationId, idx, message.timestamp)
      setContextData((prev) => ({ ...prev, [idx]: data }))
    }

    setExpandedIdx(idx)
  }

  return (
    <div className="flex-1 overflow-y-auto p-4 min-h-0">
      <div className="space-y-4 max-w-3xl mx-auto">
        {messages.map((m, idx) => {
          const inspectable = canInspect && m.role === 'assistant'
          const currentContext = contextData[idx]

          return (
            <div key={`msg-${idx}-${m.role}`} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
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
                  className={`max-w-[85%] sm:max-w-[75%] rounded-xl px-4 py-2 text-sm leading-relaxed whitespace-pre-wrap break-words transition ${
                    m.role === 'user' ? 'bg-blue-600 text-white' : 'bg-slate-800 text-slate-100'
                  } ${inspectable ? 'cursor-pointer hover:ring-1 hover:ring-slate-600' : ''}`}
                >
                  {m.content}
                  {streaming && idx === messages.length - 1 && m.role === 'assistant' ? (
                    <span className="ml-1 animate-pulse">▌</span>
                  ) : null}
                </div>

                {canInspect && expandedIdx === idx && currentContext && (
                  <div className="mt-1 ml-2 text-xs bg-slate-900 border border-slate-700 rounded p-2 max-w-[85%]">
                    {!currentContext.found ? (
                      <span className="text-slate-500 italic">No monitor data found for this message.</span>
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
                                  <pre className="whitespace-pre-wrap text-slate-300 text-[11px] mt-0.5">{cm.content}</pre>
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
                                <pre className="whitespace-pre-wrap text-slate-300 text-[11px] mt-0.5">{msg.content}</pre>
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
