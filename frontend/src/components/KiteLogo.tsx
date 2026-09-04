interface KiteLogoProps {
  size?: number
  className?: string
  title?: string
}

const ASPECT = 1024 / 932

/** User-provided perched eagle silhouette (eagle-logo.png). */
export default function KiteLogo({ size = 28, className = '', title }: KiteLogoProps) {
  const height = size
  const width = Math.round(size * ASPECT)

  return (
    <img
      src="/eagle-logo.png"
      alt={title ?? ''}
      width={width}
      height={height}
      className={`kite-logo-mark${className ? ` ${className}` : ''}`}
      aria-hidden={title ? undefined : true}
    />
  )
}
