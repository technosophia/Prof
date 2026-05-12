import { useState, useEffect, useCallback } from 'react'
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

function extractDeadlineMessage(errorMessage) {
  const marker = 'deadline_expired::'
  const idx = (errorMessage || '').indexOf(marker)
  if (idx < 0) return 'Your access period has ended.'
  return errorMessage.slice(idx + marker.length).replace(/\]$/, '').trim() || 'Your access period has ended.'
}

export default function Login() {
  const [activeTab, setActiveTab] = useState('login')

  // Login tab — multi-step
  const [loginStep, setLoginStep] = useState(1)       // 1=email, 2=credentials
  const [loginMode, setLoginMode] = useState(null)    // 'normal' | 'first_time'
  const [emailInput, setEmailInput] = useState('')
  const [password, setPassword] = useState('')
  const [authFailed, setAuthFailed] = useState(false)
  const [activationSent, setActivationSent] = useState(false)
  const [firstTimeUserId, setFirstTimeUserId] = useState('')
  const [firstTimeForm, setFirstTimeForm] = useState({ resetCode: '', newPassword: '', confirmPassword: '', displayName: '' })

  // Waitlist
  const [waitlistEmail, setWaitlistEmail] = useState('')
  const [selectedList, setSelectedList] = useState('')
  const [availableLists, setAvailableLists] = useState([])

  // Forgot password
  const [resetForm, setResetForm] = useState({ userId: '', resetCode: '', newPassword: '', confirmPassword: '' })
  const [resetStep, setResetStep] = useState(1)
  const [resetPending, setResetPending] = useState(false)

  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
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
      if (lists.length > 0) setSelectedList(lists[0].id)
    }).catch(() => setAvailableLists([]))
  }, [])

  const setReset = (k, v) => setResetForm(s => ({ ...s, [k]: v }))
  const setFirstTime = (k, v) => setFirstTimeForm(s => ({ ...s, [k]: v }))

  function resetLoginFlow() {
    setLoginStep(1)
    setLoginMode(null)
    setPassword('')
    setAuthFailed(false)
    setActivationSent(false)
    setFirstTimeUserId('')
    setFirstTimeForm({ resetCode: '', newPassword: '', confirmPassword: '', displayName: '' })
    setError('')
    setInfo('')
  }

  function cancelReset() {
    setResetForm({ userId: '', resetCode: '', newPassword: '', confirmPassword: '' })
    setResetStep(1)
    setError('')
    setInfo('')
  }

  async function submitEmailCheck(e) {
    e.preventDefault()
    setError('')
    const input = emailInput.trim()
    if (!input) {
      setError('Please enter your email or username.')
      return
    }
    const isEmail = input.includes('@')
    if (!isEmail) {
      // Username path — skip check, always goes to normal login
      setLoginMode('normal')
      setLoginStep(2)
      return
    }
    const email = input.toLowerCase()
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setError('Please enter a valid email address.')
      return
    }
    try {
      const data = await auth.checkEmail(email)
      if (data.status === 'not_found') {
        setError('No account found for this email. Please check or contact support.')
        return
      }
      if (data.status === 'activation_expired') {
        setLoginMode('activation_expired')
        setLoginStep(2)
        return
      }
      if (data.status === 'first_time') {
        setFirstTimeUserId(data.user_id)
        setFirstTimeForm(f => ({ ...f, displayName: data.suggested_name || '' }))
        setLoginMode('first_time')
      } else {
        setLoginMode('normal')
      }
      setLoginStep(2)
    } catch {
      setError('Unable to verify. Please try again.')
    }
  }

  async function submitRequestActivation(e) {
    e.preventDefault()
    setError('')
    try {
      await auth.requestActivation(emailInput.trim().toLowerCase())
      setActivationSent(true)
    } catch {
      setError('Failed to send email. Please try again.')
    }
  }

  async function submitNormalLogin(e) {
    e.preventDefault()
    setError('')
    setInfo('')
    setAuthFailed(false)
    try {
      const data = await auth.login(emailInput, password)
      localStorage.setItem('token', data.access_token)
      await redirectAfterLogin()
    } catch (err) {
      const statusCode = parseStatusCode(err?.message)
      if (statusCode === 403 && err?.message?.includes('pending_approval')) {
        setInfo('Your account is pending approval.')
      } else if (statusCode === 403 && err?.message?.includes('deadline_expired::')) {
        setError(extractDeadlineMessage(err.message))
      } else {
        setError('Wrong password.')
        setAuthFailed(true)
      }
    }
  }

  async function submitFirstTimeSetup(e) {
    e.preventDefault()
    setError('')
    if (!firstTimeForm.resetCode.trim()) {
      setError('Please enter the reset code from your welcome email.')
      return
    }
    if (firstTimeForm.newPassword.length < 8) {
      setError('Password must be at least 8 characters.')
      return
    }
    if (firstTimeForm.newPassword !== firstTimeForm.confirmPassword) {
      setError('Passwords do not match.')
      return
    }
    try {
      const data = await auth.initPassword(
        firstTimeUserId,
        firstTimeForm.resetCode.trim(),
        firstTimeForm.newPassword,
        firstTimeForm.displayName.trim() || null,
      )
      localStorage.setItem('token', data.access_token)
      await redirectAfterLogin()
    } catch (err) {
      const statusCode = parseStatusCode(err?.message)
      if (statusCode === 400) {
        setError('Invalid reset code. Please check your welcome email.')
      } else if (statusCode === 409) {
        setError('This display name is already taken. Please choose another.')
      } else {
        setError('Setup failed. Please try again.')
      }
    }
  }

  async function requestResetCode(e) {
    e.preventDefault()
    setError('')
    setInfo('')
    if (!resetForm.userId.trim()) {
      setError('Please enter your username or email.')
      return
    }
    setResetPending(true)
    try {
      const data = await auth.requestPasswordReset(resetForm.userId.trim())
      if (data?.reset_code) {
        setInfo(`Reset code: ${data.reset_code}`)
      } else {
        setInfo('If the account exists, a reset code has been sent.')
      }
      setResetStep(2)
    } catch {
      setError('Failed to request reset code.')
    } finally {
      setResetPending(false)
    }
  }

  async function submitResetPassword(e) {
    e.preventDefault()
    setError('')
    setInfo('')
    if (!resetForm.resetCode.trim()) { setError('Please enter the reset code.'); return }
    if (resetForm.newPassword.length < 8) { setError('Password must be at least 8 characters.'); return }
    if (resetForm.newPassword !== resetForm.confirmPassword) { setError('Passwords do not match.'); return }
    setResetPending(true)
    try {
      const data = await auth.initPassword(resetForm.userId.trim(), resetForm.resetCode.trim(), resetForm.newPassword)
      localStorage.setItem('token', data.access_token)
      await redirectAfterLogin()
    } catch (err) {
      const statusCode = parseStatusCode(err?.message)
      setError(statusCode === 400 ? 'Invalid reset code.' : 'Password reset failed.')
    } finally {
      setResetPending(false)
    }
  }

  async function submitWaitlist(e) {
    e.preventDefault()
    setError('')
    setInfo('')
    const email = waitlistEmail.trim()
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { setError('Please provide a valid email address.'); return }
    if (!selectedList) { setError('Please select a waitlist.'); return }
    try {
      const data = await auth.waitlist(email, selectedList)
      if (data?.status === 'pending') {
        setInfo('You have been added to the waitlist. You will be notified after approval.')
        setWaitlistEmail('')
      }
    } catch (err) {
      const statusCode = parseStatusCode(err?.message)
      if (statusCode === 409 && err?.message?.includes('email_already_registered')) {
        setError('This email is already registered. Please login instead.')
        return
      }
      setError('Waitlist registration failed.')
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md space-y-4">
        <h1 className="text-xl font-semibold">Student Access</h1>

        <div className="flex gap-2">
          <Button type="button" variant={activeTab === 'login' ? 'default' : 'secondary'} className="flex-1"
            onClick={() => { setActiveTab('login'); resetLoginFlow(); cancelReset() }}>
            Login
          </Button>
          <Button type="button" variant={activeTab === 'forgot' ? 'default' : 'secondary'} className="flex-1"
            onClick={() => { setActiveTab('forgot'); setError(''); setInfo('') }}>
            Forgot
          </Button>
          {availableLists.length > 0 && (
            <Button type="button" variant={activeTab === 'waitlist' ? 'default' : 'secondary'} className="flex-1"
              onClick={() => { setActiveTab('waitlist'); setError(''); setInfo('') }}>
              Waitlist
            </Button>
          )}
        </div>

        {activeTab === 'login' ? (
          loginStep === 1 ? (
            <form className="space-y-3" onSubmit={submitEmailCheck}>
              <div>
                <Label>Email or Username</Label>
                <Input value={emailInput} onChange={e => setEmailInput(e.target.value)} placeholder="you@example.com or john_doe" autoFocus />
              </div>
              {error ? <p className="text-sm text-red-400">{error}</p> : null}
              <Button className="w-full" type="submit">Continue</Button>
            </form>
          ) : loginMode === 'activation_expired' ? (
            <div className="space-y-3">
              <p className="text-sm text-amber-400 font-medium">Activation code expired</p>
              <div>
                <Label>{emailInput.includes('@') ? 'Email' : 'Username'}</Label>
                <Input value={emailInput} disabled className="opacity-60" />
              </div>
              <p className="text-sm text-slate-400">
                Your activation code is no longer valid. Click below to receive a new one.
              </p>
              {!activationSent ? (
                <>
                  {error ? <p className="text-sm text-red-400">{error}</p> : null}
                  <Button className="w-full" onClick={submitRequestActivation}>
                    Send new activation email
                  </Button>
                </>
              ) : (
                <p className="text-sm text-emerald-400">
                  Email sent! Check your inbox, then come back and log in.
                </p>
              )}
              <Button type="button" variant="secondary" className="w-full" onClick={resetLoginFlow}>Back</Button>
            </div>
          ) : loginMode === 'first_time' ? (
            <form className="space-y-3" onSubmit={submitFirstTimeSetup}>
              <p className="text-sm text-emerald-400 font-medium">First login — set up your account</p>
              <div>
                <Label>Email</Label>
                <Input value={emailInput} disabled className="opacity-60" />
              </div>
              <div>
                <Label>Display name</Label>
                <Input value={firstTimeForm.displayName} onChange={e => setFirstTime('displayName', e.target.value)} placeholder="Your name" />
                <p className="text-xs text-slate-400 mt-1">Pre-filled from your email. You can change it.</p>
              </div>
              <div>
                <Label>Reset code</Label>
                <Input value={firstTimeForm.resetCode} onChange={e => setFirstTime('resetCode', e.target.value)} placeholder="From your welcome email" />
              </div>
              <div><Label>New password</Label><Input type="password" value={firstTimeForm.newPassword} onChange={e => setFirstTime('newPassword', e.target.value)} /></div>
              <div><Label>Confirm password</Label><Input type="password" value={firstTimeForm.confirmPassword} onChange={e => setFirstTime('confirmPassword', e.target.value)} /></div>
              {error ? <p className="text-sm text-red-400">{error}</p> : null}
              <Button className="w-full" type="submit">Set up my account</Button>
              <Button type="button" variant="secondary" className="w-full" onClick={resetLoginFlow}>Back</Button>
            </form>
          ) : (
            <form className="space-y-3" onSubmit={submitNormalLogin}>
              <div>
                <Label>{emailInput.includes('@') ? 'Email' : 'Username'}</Label>
                <Input value={emailInput} disabled className="opacity-60" />
              </div>
              <div>
                <Label>Password</Label>
                <Input type="password" value={password} onChange={e => setPassword(e.target.value)} autoFocus />
              </div>
              {info ? <p className="text-sm text-blue-400">{info}</p> : null}
              {error ? (
                <p className="text-sm text-red-400">
                  {error}
                  {authFailed && (
                    <button type="button" className="text-blue-400 underline ml-2"
                      onClick={() => { setActiveTab('forgot'); setError(''); setInfo(''); setAuthFailed(false) }}>
                      Forgot password?
                    </button>
                  )}
                </p>
              ) : null}
              <Button className="w-full" type="submit">Login</Button>
              <Button type="button" variant="secondary" className="w-full" onClick={resetLoginFlow}>Back</Button>
            </form>
          )
        ) : activeTab === 'forgot' ? (
          resetStep === 1 ? (
            <form className="space-y-3" onSubmit={requestResetCode}>
              <p className="text-sm text-slate-400">Enter your username or email to request a reset code.</p>
              <div>
                <Label>Username or Email</Label>
                <Input value={resetForm.userId} onChange={e => setReset('userId', e.target.value)} placeholder="john_doe or you@example.com" />
              </div>
              {info ? <p className="text-sm text-blue-400">{info}</p> : null}
              {error ? <p className="text-sm text-red-400">{error}</p> : null}
              <Button className="w-full" type="submit" disabled={resetPending}>{resetPending ? 'Sending...' : 'Request Reset Code'}</Button>
              <Button type="button" variant="secondary" className="w-full" onClick={() => { setActiveTab('login'); cancelReset() }}>Back to Login</Button>
            </form>
          ) : (
            <form className="space-y-3" onSubmit={submitResetPassword}>
              <p className="text-sm text-slate-400">Enter the reset code and your new password.</p>
              <div><Label>Reset Code</Label><Input value={resetForm.resetCode} onChange={e => setReset('resetCode', e.target.value)} placeholder="ABC123" /></div>
              <div><Label>New Password</Label><Input type="password" value={resetForm.newPassword} onChange={e => setReset('newPassword', e.target.value)} /></div>
              <div><Label>Confirm Password</Label><Input type="password" value={resetForm.confirmPassword} onChange={e => setReset('confirmPassword', e.target.value)} /></div>
              {error ? <p className="text-sm text-red-400">{error}</p> : null}
              <Button className="w-full" type="submit" disabled={resetPending}>{resetPending ? 'Resetting...' : 'Reset Password'}</Button>
              <Button type="button" variant="secondary" className="w-full" onClick={cancelReset}>Back</Button>
            </form>
          )
        ) : (
          <form className="space-y-3" onSubmit={submitWaitlist}>
            <p className="text-sm text-slate-400">No account yet? Join the waitlist and get notified after approval.</p>
            <div>
              <Label>Select Waitlist</Label>
              <select value={selectedList} onChange={e => setSelectedList(e.target.value)}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                style={{ backgroundColor: 'white', color: 'black', border: '1px solid #ccc' }}>
                {availableLists.map(list => (
                  <option key={list.id} value={list.id} style={{ color: 'black' }}>{list.name}</option>
                ))}
              </select>
            </div>
            <div><Label>Email</Label><Input type="email" value={waitlistEmail} onChange={e => setWaitlistEmail(e.target.value)} /></div>
            {info ? <p className="text-sm text-blue-400">{info}</p> : null}
            {error ? <p className="text-sm text-red-400">{error}</p> : null}
            <Button className="w-full" type="submit">Join waitlist</Button>
          </form>
        )}
      </Card>
    </div>
  )
}
