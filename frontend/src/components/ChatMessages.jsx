import { ScrollArea } from '@/components/ui/scroll-area'

export default function ChatMessages({ messages, streaming }) {
  return (
    <ScrollArea className="h-[calc(100vh-110px)] p-4">
      <div className="space-y-4">
        {messages.map((m, idx) => (
          <div key={idx} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[75%] rounded-xl px-4 py-2 text-sm ${m.role === 'user' ? 'bg-blue-600 text-white' : 'bg-slate-800 text-slate-100'}`}>
              {m.content}
              {streaming && idx === messages.length - 1 && m.role === 'assistant' ? <span className="ml-1 animate-pulse">▌</span> : null}
            </div>
          </div>
        ))}
      </div>
    </ScrollArea>
  )
}
