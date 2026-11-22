import { config } from 'dotenv'
import { resolve } from 'node:path'

config({ path: resolve(import.meta.dirname, '../../backend/.env') })
config({ path: resolve(import.meta.dirname, '../../frontend/.env') })

export const env = {
  supabaseUrl: process.env.SUPABASE_URL ?? process.env.VITE_SUPABASE_URL ?? '',
  supabaseAnonKey: process.env.SUPABASE_ANON_KEY ?? process.env.VITE_SUPABASE_ANON_KEY ?? '',
  serviceRoleKey: process.env.SUPABASE_SERVICE_ROLE_KEY ?? '',
  apiBase: process.env.PLAYWRIGHT_API_BASE ?? 'http://127.0.0.1:8000',
}

export function requireEnv() {
  const missing = [
    !env.supabaseUrl && 'SUPABASE_URL',
    !env.supabaseAnonKey && 'SUPABASE_ANON_KEY',
    !env.serviceRoleKey && 'SUPABASE_SERVICE_ROLE_KEY',
  ].filter(Boolean)
  if (missing.length) {
    throw new Error(`Missing env for e2e: ${missing.join(', ')}`)
  }
}
