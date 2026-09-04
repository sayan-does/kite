import { useLocation } from 'react-router-dom'

export default function PageTransition({ children }: { children: React.ReactNode }) {
  const location = useLocation()
  return (
    <div key={location.pathname} className="kite-page-enter">
      {children}
    </div>
  )
}
