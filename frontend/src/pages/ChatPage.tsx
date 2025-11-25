import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthToken } from '../stores/authStore'

export function ChatPage({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate()
  const token = useAuthToken()

  useEffect(() => {
    const t = token ?? localStorage.getItem('token')
    // Redirect to login if not authenticated
    if (!t) {
      navigate('/login')
    }
  }, [token, navigate])

  return <>{children}</>
}
