import { Link } from 'react-router-dom'
import KiteLogo from './KiteLogo'

interface KiteBrandProps {
  to?: string
  size?: 'sm' | 'md' | 'lg'
  showWordmark?: boolean
}

const sizes = { sm: 22, md: 28, lg: 36 } as const
const textSizes = { sm: 'text-lg', md: 'text-xl', lg: 'text-2xl' } as const

export default function KiteBrand({ to, size = 'md', showWordmark = true }: KiteBrandProps) {
  const content = (
    <span className="kite-brand-lockup">
      <KiteLogo size={sizes[size]} title={showWordmark ? undefined : 'Kite'} />
      {showWordmark && (
        <span className={`kite-brand-wordmark ${textSizes[size]}`}>Kite</span>
      )}
    </span>
  )

  if (to) {
    return (
      <Link to={to} className="kite-brand-link" aria-label="Kite home">
        {content}
      </Link>
    )
  }

  return content
}
