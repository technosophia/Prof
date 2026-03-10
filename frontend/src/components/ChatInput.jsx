import { useState, useRef } from 'react'
import { Button } from '@/components/ui/button'

export default function ChatInput({ onSend, disabled }) {
  const [value, setValue] = useState('')
  const textareaRef = useRef(null)

  function submit() {
    const msg = value.trim()
    if (!msg || disabled) return
    onSend(msg)
    setValue('')
    // Reset textarea height
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }

  function onKeyDown(e) {
    // Send on Enter (not Shift+Enter)
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  function onInput(e) {
    setValue(e.target.value)
    // Auto-grow up to ~5 lines
    const el = e.target
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 140) + 'px'
  }

  return (
    <div className="shrink-0 border-t border-slate-800 px-3 py-2 flex items-end gap-2">
      <textarea
        ref={textareaRef}
        rows={1}
        value={value}
        onChange={onInput}
        onKeyDown={onKeyDown}
        placeholder="Ask your coach… (Enter to send, Shift+Enter for newline)"
        disabled={disabled}
        className="flex-1 resize-none rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50 min-h-[40px] max-h-[140px] overflow-y-auto"
      />
      <Button onClick={submit} disabled={disabled || !value.trim()} className="shrink-0 self-end">
        Send
      </Button>
    </div>
  )
}
