import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { auth } from '@/lib/api'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'

export default function Login() {
  const [firstTime, setFirstTime] = useState(false)
  const [form, setForm] = useState({ userId: '', password: '', resetCode: '', newPassword: '' })
  const [error, setError] = useState('')
  const navigate = useNavigate()

  const set = (k, v) => setForm((s) => ({ ...s, [k]: v }))

  async function submit(e) {
    e.preventDefault()
    setError('')
    try {
      const data = firstTime
        ? await auth.initPassword(form.userId, form.resetCode, form.newPassword)
        : await auth.login(form.userId, form.password)
      localStorage.setItem('token', data.access_token)
      navigate('/chat')
    } catch (err) {
      setError('Authentication failed')
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md space-y-4">
        <h1 className="text-xl font-semibold">Student Login</h1>
        <form className="space-y-3" onSubmit={submit}>
          <div><Label>User ID</Label><Input value={form.userId} onChange={(e) => set('userId', e.target.value)} /></div>
          {!firstTime ? (
            <div><Label>Password</Label><Input type="password" value={form.password} onChange={(e) => set('password', e.target.value)} /></div>
          ) : (
            <>
              <div><Label>Reset code</Label><Input value={form.resetCode} onChange={(e) => set('resetCode', e.target.value)} /></div>
              <div><Label>New password</Label><Input type="password" value={form.newPassword} onChange={(e) => set('newPassword', e.target.value)} /></div>
            </>
          )}
          {error ? <p className="text-sm text-red-400">{error}</p> : null}
          <Button className="w-full" type="submit">{firstTime ? 'Initialize password' : 'Login'}</Button>
        </form>
        <button onClick={() => setFirstTime((s) => !s)} className="text-sm text-slate-400 hover:text-slate-200">
          {firstTime ? 'Back to normal login' : 'First time? Use reset code'}
        </button>
      </Card>
    </div>
  )
}
