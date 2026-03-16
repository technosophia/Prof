import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { auth } from '@/lib/api'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'

function parseStatusCode(errorMessage) {
  const match = (errorMessage || '').match(/status=(\d+)/)
  return match ? Number(match[1]) : null
}

function deriveUserIdFromEmail(email) {
  const [prefix = ''] = (email || '').split('@')
  return prefix.trim().toLowerCase().replace(/\s+/g, '_').replace(/\./g, '_').replace(/_+/g, '_').replace(/^_+|_+$/g, '')
}

export default function Login() {
  const [activeTab, setActiveTab] = useState('login')
  const [loginForm, setLoginForm] = useState({ userId: '', password: '' })
  const [registerForm, setRegisterForm] = useState({ email: '', password: '', confirmPassword: '', userId: '' })
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const [registrationPending, setRegistrationPending] = useState(false)
  const navigate = useNavigate()

  const emailDerivedId = useMemo(() => deriveUserIdFromEmail(registerForm.email), [registerForm.email])

  const setLogin = (k, v) => setLoginForm((s) => ({ ...s, [k]: v }))
  const setRegister = (k, v) => setRegisterForm((s) => ({ ...s, [k]: v }))

  async function submitLogin(e) {
    e.preventDefault()
    setError('')
    setInfo('')
    try {
      const data = await auth.login(loginForm.userId, loginForm.password)
      localStorage.setItem('token', data.access_token)
      navigate('/chat')
    } catch (err) {
      const status = parseStatusCode(err?.message)
      if (status === 403 && err?.message?.includes('pending_approval')) {
        setInfo('Your account is pending approval. You will be able to log in once an admin approves it.')
      } else {
        setError('Authentication failed')
      }
    }
  }

  async function submitRegister(e) {
    e.preventDefault()
    setError('')
    setInfo('')

    const email = registerForm.email.trim()
    const userId = (registerForm.userId || emailDerivedId).trim()

    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setError('Please provide a valid email address.')
      return
    }
    if (registerForm.password.length < 8) {
      setError('Password must contain at least 8 characters.')
      return
    }
    if (registerForm.password !== registerForm.confirmPassword) {
      setError('Passwords do not match.')
      return
    }
    if (!userId) {
      setError('Please provide a username (ID).')
      return
    }

    try {
      const data = await auth.register(email, registerForm.password, registerForm.confirmPassword, userId)
      if (data?.status === 'pending') {
        setRegistrationPending(true)
        return
      }
      localStorage.setItem('token', data.access_token)
      navigate('/chat')
    } catch (err) {
      const status = parseStatusCode(err?.message)
      if (status === 409 && err?.message?.includes('user_id_conflict')) {
        setError('This username is already taken. Please choose another.')
        return
      }
      setError('Registration failed')
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md space-y-4">
        <h1 className="text-xl font-semibold">Student Access</h1>

        <div className="flex gap-2">
          <Button type="button" variant={activeTab === 'login' ? 'default' : 'secondary'} className="flex-1" onClick={() => setActiveTab('login')}>
            Login
          </Button>
          <Button type="button" variant={activeTab === 'register' ? 'default' : 'secondary'} className="flex-1" onClick={() => setActiveTab('register')}>
            Register
          </Button>
        </div>

        {activeTab === 'login' ? (
          <form className="space-y-3" onSubmit={submitLogin}>
            <div><Label>User ID or Email</Label><Input value={loginForm.userId} onChange={(e) => setLogin('userId', e.target.value)} /></div>
            <div><Label>Password</Label><Input type="password" value={loginForm.password} onChange={(e) => setLogin('password', e.target.value)} /></div>
            {info ? <p className="text-sm text-blue-400">{info}</p> : null}
            {error ? <p className="text-sm text-red-400">{error}</p> : null}
            <Button className="w-full" type="submit">Login</Button>
          </form>
        ) : registrationPending ? (
          <p className="text-sm text-emerald-400">Registration submitted! Your account is pending approval by an administrator.</p>
        ) : (
          <form className="space-y-3" onSubmit={submitRegister}>
            <div><Label>Email</Label><Input type="email" value={registerForm.email} onChange={(e) => setRegister('email', e.target.value)} /></div>
            <div>
              <Label>Username (ID)</Label>
              <Input
                value={registerForm.userId || emailDerivedId}
                onChange={(e) => setRegister('userId', e.target.value)}
                placeholder={emailDerivedId || 'john_doe'}
                autoFocus={Boolean(error && error.includes('username'))}
              />
              <p className="text-xs text-slate-400 mt-1">This will be your login ID.</p>
            </div>
            <div><Label>Password</Label><Input type="password" value={registerForm.password} onChange={(e) => setRegister('password', e.target.value)} /></div>
            <div><Label>Confirm password</Label><Input type="password" value={registerForm.confirmPassword} onChange={(e) => setRegister('confirmPassword', e.target.value)} /></div>
            {error ? <p className="text-sm text-red-400">{error}</p> : null}
            <Button className="w-full" type="submit">Create account</Button>
          </form>
        )}
      </Card>
    </div>
  )
}
