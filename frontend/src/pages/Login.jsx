import { useMemo, useState, useEffect, useCallback } from 'react'
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

function extractDeadlineMessage(errorMessage) {
  const marker = 'deadline_expired::'
  const idx = (errorMessage || '').indexOf(marker)
  if (idx < 0) return 'Your access period has ended.'
  return errorMessage.slice(idx + marker.length).replace(/\]$/, '').trim() || 'Your access period has ended.'
}

export default function Login() {
  const [activeTab, setActiveTab] = useState('login')
  const [loginForm, setLoginForm] = useState({ userId: '', password: '' })
  const [registerForm, setRegisterForm] = useState({ email: '', password: '', confirmPassword: '', userId: '' })
  const [waitlistEmail, setWaitlistEmail] = useState('')
  const [selectedList, setSelectedList] = useState('')
  const [availableLists, setAvailableLists] = useState([])
  const [resetForm, setResetForm] = useState({ userId: '', resetCode: '', newPassword: '', confirmPassword: '' })
  const [resetStep, setResetStep] = useState(1)
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const [registrationPending, setRegistrationPending] = useState(false)
  const [resetPending, setResetPending] = useState(false)
  const navigate = useNavigate()

  const redirectAfterLogin = useCallback(async () => {
    try {
      const data = await auth.enrollments()
      const count = (data?.enrollments ?? []).length
      navigate(count > 1 ? '/select-training' : '/chat', { replace: true })
    } catch {
      navigate('/chat', { replace: true })
    }
  }, [navigate])

  useEffect(() => {
    auth.getWaitlistLists().then(lists => {
      setAvailableLists(lists)
      if (lists.length > 0) {
        setSelectedList(lists[0].id)
      }
    }).catch(() => {
      setAvailableLists([])
    })
  }, [])

  const emailDerivedId = useMemo(() => deriveUserIdFromEmail(registerForm.email), [registerForm.email])

  const setLogin = (k, v) => setLoginForm((s) => ({ ...s, [k]: v }))
  const setRegister = (k, v) => setRegisterForm((s) => ({ ...s, [k]: v }))
  const setReset = (k, v) => setResetForm((s) => ({ ...s, [k]: v }))

  async function submitLogin(e) {
    e.preventDefault()
    setError('')
    setInfo('')
    try {
      const data = await auth.login(loginForm.userId, loginForm.password)
      localStorage.setItem('token', data.access_token)
      await redirectAfterLogin()
    } catch (err) {
      const status = parseStatusCode(err?.message)
      if (status === 403 && err?.message?.includes('pending_approval')) {
        setInfo('Your account is pending approval. You will be able to log in once an admin approves it.')
      } else if (status === 403 && err?.message?.includes('deadline_expired::')) {
        setError(extractDeadlineMessage(err.message))
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
      await redirectAfterLogin()
    } catch (err) {
      const status = parseStatusCode(err?.message)
      if (status === 409 && err?.message?.includes('user_id_conflict')) {
        setError('This username is already taken. Please choose another.')
        return
      }
      if (status === 409 && err?.message?.includes('email_already_registered')) {
        setError('This email is already registered. Please login instead.')
        return
      }
      setError('Registration failed')
    }
  }

  async function requestResetCode(e) {
    e.preventDefault()
    setError('')
    setInfo('')
    if (!resetForm.userId.trim()) {
      setError('Please enter your username.')
      return
    }
    setResetPending(true)
    try {
      const data = await auth.requestPasswordReset(resetForm.userId.trim())
      if (data?.reset_code) {
        setInfo(`Reset code: ${data.reset_code}`)
        setResetStep(2)
      } else {
        setInfo('If the user exists, a reset code has been sent.')
        setResetStep(2)
      }
    } catch (err) {
      setError('Failed to request reset code')
    } finally {
      setResetPending(false)
    }
  }

  async function submitResetPassword(e) {
    e.preventDefault()
    setError('')
    setInfo('')
    if (!resetForm.resetCode.trim()) {
      setError('Please enter the reset code.')
      return
    }
    if (resetForm.newPassword.length < 8) {
      setError('Password must contain at least 8 characters.')
      return
    }
    if (resetForm.newPassword !== resetForm.confirmPassword) {
      setError('Passwords do not match.')
      return
    }
    setResetPending(true)
    try {
      const data = await auth.initPassword(resetForm.userId.trim(), resetForm.resetCode.trim(), resetForm.newPassword)
      localStorage.setItem('token', data.access_token)
      await redirectAfterLogin()
    } catch (err) {
      const status = parseStatusCode(err?.message)
      if (status === 400) {
        setError('Invalid reset code')
      } else {
        setError('Password reset failed')
      }
    } finally {
      setResetPending(false)
    }
  }

  async function submitWaitlist(e) {
    e.preventDefault()
    setError('')
    setInfo('')
    const email = waitlistEmail.trim()
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setError('Please provide a valid email address.')
      return
    }
    if (!selectedList) {
      setError('Please select a waitlist.')
      return
    }

    try {
      const data = await auth.waitlist(email, selectedList)
      if (data?.status === 'pending') {
        setInfo('You have been added to the waitlist. You will receive an email when your account is approved.')
        setWaitlistEmail('')
      }
    } catch (err) {
      const status = parseStatusCode(err?.message)
      if (status === 409 && err?.message?.includes('email_already_registered')) {
        setError('This email is already registered. Please login instead.')
        return
      }
      setError('Waitlist registration failed')
    }
  }

  function cancelReset() {
    setResetForm({ userId: '', resetCode: '', newPassword: '', confirmPassword: '' })
    setResetStep(1)
    setError('')
    setInfo('')
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md space-y-4">
        <h1 className="text-xl font-semibold">Student Access</h1>

        <div className="flex gap-2">
          <Button type="button" variant={activeTab === 'login' ? 'default' : 'secondary'} className="flex-1" onClick={() => { setActiveTab('login'); cancelReset() }}>
            Login
          </Button>
          <Button type="button" variant={activeTab === 'register' ? 'default' : 'secondary'} className="flex-1" onClick={() => { setActiveTab('register'); cancelReset() }}>
            Register
          </Button>
          <Button type="button" variant={activeTab === 'forgot' ? 'default' : 'secondary'} className="flex-1" onClick={() => setActiveTab('forgot')}>
            Forgot
          </Button>
          <Button type="button" variant={activeTab === 'waitlist' ? 'default' : 'secondary'} className="flex-1" onClick={() => setActiveTab('waitlist')}>
            Waitlist
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
        ) : activeTab === 'forgot' ? (
          resetStep === 1 ? (
            <form className="space-y-3" onSubmit={requestResetCode}>
              <p className="text-sm text-slate-400">Enter your username to request a reset code.</p>
              <div><Label>Username</Label><Input value={resetForm.userId} onChange={(e) => setReset('userId', e.target.value)} placeholder="john_doe" /></div>
              {info ? <p className="text-sm text-blue-400">{info}</p> : null}
              {error ? <p className="text-sm text-red-400">{error}</p> : null}
              <Button className="w-full" type="submit" disabled={resetPending}>{resetPending ? 'Sending...' : 'Request Reset Code'}</Button>
              <Button type="button" variant="secondary" className="w-full" onClick={() => { setActiveTab('login'); cancelReset() }}>Back to Login</Button>
            </form>
          ) : (
            <form className="space-y-3" onSubmit={submitResetPassword}>
              <p className="text-sm text-slate-400">Enter the reset code and your new password.</p>
              <div><Label>Reset Code</Label><Input value={resetForm.resetCode} onChange={(e) => setReset('resetCode', e.target.value)} placeholder="ABC123" /></div>
              <div><Label>New Password</Label><Input type="password" value={resetForm.newPassword} onChange={(e) => setReset('newPassword', e.target.value)} /></div>
              <div><Label>Confirm Password</Label><Input type="password" value={resetForm.confirmPassword} onChange={(e) => setReset('confirmPassword', e.target.value)} /></div>
              {error ? <p className="text-sm text-red-400">{error}</p> : null}
              <Button className="w-full" type="submit" disabled={resetPending}>{resetPending ? 'Resetting...' : 'Reset Password'}</Button>
              <Button type="button" variant="secondary" className="w-full" onClick={cancelReset}>Back</Button>
            </form>
          )
        ) : activeTab === 'waitlist' ? (
          <form className="space-y-3" onSubmit={submitWaitlist}>
            <p className="text-sm text-slate-400">No account yet? Join the waitlist and get notified after approval.</p>
            <div>
              <Label>Select Waitlist</Label>
              <select
                value={selectedList}
                onChange={(e) => setSelectedList(e.target.value)}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-black"
                style={{ backgroundColor: 'white', color: 'black', border: '1px solid #ccc' }}
              >
                {availableLists.length === 0 ? (
                  <option value="">No lists available</option>
                ) : (
                  availableLists.map(list => (
                    <option key={list.id} value={list.id} style={{color: 'black'}}>{list.name}</option>
                  ))
                )}
              </select>
            </div>
            <div><Label>Email</Label><Input type="email" value={waitlistEmail} onChange={(e) => setWaitlistEmail(e.target.value)} /></div>
            {info ? <p className="text-sm text-blue-400">{info}</p> : null}
            {error ? <p className="text-sm text-red-400">{error}</p> : null}
            <Button className="w-full" type="submit" disabled={availableLists.length === 0}>Join waitlist</Button>
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
