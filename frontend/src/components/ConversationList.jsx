import { useMemo } from 'react'
import { MessageSquarePlus, X } from 'lucide-react'

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

export default function ConversationList({
  conversations,
  currentId,
  onSelect,
  onCreate,
  onRename,
  onDelete,
  onLogout,
  open,
  onClose,
  onFeedback,
}) {
  const items = useMemo(() => conversations || [], [conversations])

  return (
    <>
      {open && (
        <div
          className="fixed inset-0 z-20 bg-black/60 backdrop-blur-sm md:hidden"
          onClick={onClose}
        />
      )}

      <aside
        className={[
          'flex flex-col border-r border-slate-800 bg-slate-950',
          'fixed inset-y-0 left-0 z-30 w-72 transition-transform duration-300 ease-in-out',
          open ? 'translate-x-0' : '-translate-x-full',
          'md:static md:w-80 md:translate-x-0 md:transition-none md:z-auto',
        ].join(' ')}
      >
        <div className="flex items-center gap-2 p-3">
          <Button className="flex-1" onClick={onCreate}>+ New conversation</Button>
          <Button className="bg-slate-700 hover:bg-slate-600 shrink-0" onClick={onLogout}>Logout</Button>
          <button
            className="ml-1 rounded-md p-1.5 text-slate-400 hover:bg-slate-800 hover:text-slate-100 md:hidden"
            onClick={onClose}
            aria-label="Close sidebar"
          >
            <X size={18} />
          </button>
        </div>

        <Separator />

        <div className="flex-1 overflow-y-auto p-2">
          {items.map((c) => (
            <div
              key={c.id}
              className={`mb-2 rounded-md p-3 text-left ${currentId === c.id ? 'bg-slate-800' : 'bg-slate-900 hover:bg-slate-800'}`}
            >
              <button
                onClick={() => { onSelect(c.id); onClose?.() }}
                className="w-full text-left"
              >
                <div className="text-sm font-medium truncate">{c.title}</div>
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

        {currentId && typeof onFeedback === 'function' && (
          <div className="p-3 pt-2">
            <button
              type="button"
              className="flex w-full items-center justify-center gap-2 rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-slate-300 transition hover:bg-slate-800 hover:text-slate-100"
              onClick={onFeedback}
            >
              <MessageSquarePlus size={14} />
              Give feedback
            </button>
          </div>
        )}
      </aside>
    </>
  )
}
