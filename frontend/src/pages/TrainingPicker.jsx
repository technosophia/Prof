import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { auth } from '@/lib/api'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'

export default function TrainingPicker() {
  const [enrollments, setEnrollments] = useState([])
  const [loading, setLoading] = useState(true)
  const [selecting, setSelecting] = useState(null)
  const [error, setError] = useState('')
  const navigate = useNavigate()

  useEffect(() => {
    auth
      .enrollments()
      .then((data) => {
        const list = data?.enrollments ?? []
        if (list.length === 0) {
          navigate('/chat', { replace: true })
          return
        }
        if (list.length === 1) {
          auth.selectTraining(list[0].master_id).then(() => navigate('/chat', { replace: true }))
          return
        }
        setEnrollments(list)
      })
      .catch(() => {
        localStorage.removeItem('token')
        navigate('/login', { replace: true })
      })
      .finally(() => setLoading(false))
  }, [])

  async function pick(masterId) {
    setSelecting(masterId)
    setError('')
    try {
      await auth.selectTraining(masterId)
      navigate('/chat', { replace: true })
    } catch {
      setError('Could not select training. Please try again.')
      setSelecting(null)
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-slate-400">Loading trainings…</p>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-lg space-y-4 p-6">
        <h1 className="text-xl font-semibold">Select a Training</h1>
        <p className="text-sm text-slate-400">You are enrolled in multiple workshops. Choose which one to access.</p>

        <div className="flex flex-col gap-3">
          {enrollments.map((e) => (
            <Button
              key={e.master_id}
              variant="secondary"
              className="w-full justify-start text-left h-auto py-3 px-4"
              disabled={selecting !== null}
              onClick={() => pick(e.master_id)}
            >
              <div>
                <div className="font-medium">{e.master_name}</div>
                {e.enrolled_at && (
                  <div className="text-xs text-slate-400 mt-0.5">
                    Enrolled {new Date(e.enrolled_at).toLocaleDateString()}
                  </div>
                )}
              </div>
            </Button>
          ))}
        </div>

        {error ? <p className="text-sm text-red-400">{error}</p> : null}
      </Card>
    </div>
  )
}
