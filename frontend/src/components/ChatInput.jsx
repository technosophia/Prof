import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

export default function ChatInput({ onSend, disabled }) {
  const [value, setValue] = useState('')

  const submit = (e) => {
    e.preventDefault()
    const msg = value.trim()
    if (!msg) return
    onSend(msg)
    setValue('')
  }

  return (
    <form onSubmit={submit} className="flex gap-2 border-t border-slate-800 p-3">
      <Input value={value} onChange={(e) => setValue(e.target.value)} placeholder="Ask your coach..." disabled={disabled} />
      <Button type="submit" disabled={disabled}>Send</Button>
    </form>
  )
}
