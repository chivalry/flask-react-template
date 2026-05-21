import { Link, Navigate, Route, Routes, useNavigate } from 'react-router-dom'

import { logout } from './api/auth'
import ProtectedRoute from './components/ProtectedRoute'
import Home from './pages/Home'
import Login from './pages/Login'
import Register from './pages/Register'
import { useAuthStore } from './store/auth'

export default function App() {
  const user = useAuthStore((s) => s.user)
  const clearUser = useAuthStore((s) => s.clearUser)
  const navigate = useNavigate()

  const handleLogout = async () => {
    try {
      await logout()
    } finally {
      clearUser()
      navigate('/login')
    }
  }

  return (
    <>
      <nav
        style={{
          padding: '0.75rem 1.5rem',
          borderBottom: '1px solid #e0e0e0',
          display: 'flex',
          gap: '1rem',
          alignItems: 'center',
        }}
      >
        <Link to="/" style={{ fontWeight: 600, textDecoration: 'none' }}>
          Flask React Template
        </Link>
        <span style={{ flex: 1 }} />
        {user ? (
          <>
            <span style={{ fontSize: '0.875rem', color: '#555' }}>{user.email}</span>
            <button onClick={handleLogout} style={{ cursor: 'pointer' }}>
              Logout
            </button>
          </>
        ) : (
          <Link to="/login">Sign in</Link>
        )}
      </nav>

      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <Home />
            </ProtectedRoute>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  )
}
