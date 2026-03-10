import { useEffect, useRef } from 'react'

export default function ChatMessages({ messages, streaming }) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages])

  return (
    <div className="flex-1 overflow-y-auto p-4 min-h-0">
      <div className="space-y-4 max-w-3xl mx-auto">
        {messages.map((m, idx) => (
          <div key={idx} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[85%] sm:max-w-[75%] rounded-xl px-4 py-2 text-sm leading-relaxed whitespace-pre-wrap break-words ${
                m.role === 'user' ? 'bg-blue-600 text-white' : 'bg-slate-800 text-slate-100'
              }`}
            >
              {m.content}
              {streaming && idx === messages.length - 1 && m.role === 'assistant' ? (
                <span className="ml-1 animate-pulse">▌</span>
              ) : null}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
