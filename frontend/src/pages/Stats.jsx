import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { auth, conversations } from '@/lib/api'

function formatElapsed(lastMessageAt) {
  if (!lastMessageAt) return '—'

  const then = new Date(lastMessageAt)
  if (Number.isNaN(then.getTime())) return lastMessageAt

  let deltaSeconds = Math.max(0, Math.floor((Date.now() - then.getTime()) / 1000))
  const days = Math.floor(deltaSeconds / 86400)
  deltaSeconds -= days * 86400
  const hours = Math.floor(deltaSeconds / 3600)
  deltaSeconds -= hours * 3600
  const minutes = Math.floor(deltaSeconds / 60)

  const parts = []
  if (days > 0) parts.push(`${days}d`)
  if (hours > 0 || days > 0) parts.push(`${hours}h`)
  parts.push(`${minutes}m`)

  return `${parts.join(' ')} ago`
}

export default function Stats() {
  const [user, setUser] = useState(null)
  const [stats, setStats] = useState([])
  const navigate = useNavigate()

  useEffect(() => {
    auth
      .me()
      .then(async (me) => {
        const canAccess = me.role === 'admin' || me.role === 'master' || !!me.masquerader_id
        if (!canAccess) {
          navigate('/chat')
          return
        }

        setUser(me)
        const data = await conversations.usersStats()
        setStats(data)
      })
      .catch(() => {
        localStorage.removeItem('token')
        navigate('/login')
      })
  }, [])

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-6">
      <div className="max-w-5xl mx-auto space-y-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold">User conversation stats</h1>
            <p className="text-sm text-slate-400">
              {user ? `Connected as ${user.name} (${user.role})` : 'Loading profile...'}
            </p>
          </div>
          <button
            onClick={() => navigate('/chat')}
            className="text-xs px-3 py-2 rounded bg-slate-700 hover:bg-slate-600"
          >
            Back to chat
          </button>
        </div>

        <div className="overflow-x-auto rounded border border-slate-800">
          <table className="w-full text-sm">
            <thead className="bg-slate-900 text-slate-300">
              <tr>
                <th className="text-left px-3 py-2">User</th>
                <th className="text-left px-3 py-2">Role</th>
                <th className="text-right px-3 py-2">Conversations</th>
                <th className="text-right px-3 py-2">Messages</th>
                <th className="text-left px-3 py-2">Last message</th>
              </tr>
            </thead>
            <tbody>
              {stats.map((row) => (
                <tr key={row.user_id} className="border-t border-slate-800">
                  <td className="px-3 py-2">{row.name}</td>
                  <td className="px-3 py-2 text-slate-400">{row.role}</td>
                  <td className="px-3 py-2 text-right">{row.conversation_count}</td>
                  <td className="px-3 py-2 text-right">{row.total_messages}</td>
                  <td className="px-3 py-2 text-slate-400" title={row.last_message_at || ''}>
                    {formatElapsed(row.last_message_at)}
                  </td>
                </tr>
              ))}
              {stats.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-3 py-6 text-center text-slate-500">
                    No user stats available.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
