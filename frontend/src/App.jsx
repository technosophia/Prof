import { Navigate, Route, Routes } from 'react-router-dom'
import Login from './pages/Login'
import Chat from './pages/Chat'
import Stats from './pages/Stats'

const authed = () => Boolean(localStorage.getItem('token'))

function ProtectedRoute({ children }) {
  if (!authed()) return <Navigate to="/login" replace />
  return children
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/chat"
        element={
          <ProtectedRoute>
            <Chat />
          </ProtectedRoute>
        }
      />
      <Route
        path="/stats"
        element={
          <ProtectedRoute>
            <Stats />
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to={authed() ? '/chat' : '/login'} replace />} />
    </Routes>
  )
}
