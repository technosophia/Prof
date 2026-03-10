import { useMemo } from 'react'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'

function relTime(iso) {
  if (!iso) return ''
  const diff = Math.max(0, Date.now() - new Date(iso).getTime())
  const h = Math.floor(diff / 3600000)
  if (h > 0) return `${h}h ago`
  const m = Math.floor(diff / 60000)
  return `${Math.max(1, m)}m ago`
}

export default function ConversationList({ conversations, currentId, onSelect, onCreate, onRename, onDelete, onLogout }) {
  const items = useMemo(() => conversations || [], [conversations])

  return (
    <aside className="flex h-full w-80 flex-col border-r border-slate-800 bg-slate-950">
      <div className="p-3">
        <div className="flex gap-2">
          <Button className="flex-1" onClick={onCreate}>+ New conversation</Button>
          <Button className="bg-slate-700 hover:bg-slate-600" onClick={onLogout}>Logout</Button>
        </div>
      </div>
      <Separator />
      <div className="flex-1 overflow-y-auto p-2">
        {items.map((c) => (
          <div key={c.id} className={`mb-2 rounded-md p-3 text-left ${currentId === c.id ? 'bg-slate-800' : 'bg-slate-900 hover:bg-slate-800'}`}>
            <button onClick={() => onSelect(c.id)} className="w-full text-left">
              <div className="text-sm font-medium">{c.title}</div>
              <div className="mt-1 text-xs text-slate-400">{c.message_count} msg • {relTime(c.updated_at)}</div>
            </button>
            <div className="mt-2 flex gap-3">
              <button
                className="text-xs text-slate-400 hover:text-slate-200"
                onClick={() => onRename(c.id, c.title)}
                type="button"
              >
                Rename
              </button>
              <button
                className="text-xs text-red-400 hover:text-red-300"
                onClick={() => onDelete(c.id, c.title)}
                type="button"
              >
                Delete
              </button>
            </div>
          </div>
        ))}
      </div>
    </aside>
  )
}
