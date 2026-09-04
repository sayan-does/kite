import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  server: {
    proxy: {
      '/interest-tags': 'http://localhost:8000',
      '/me': 'http://localhost:8000',
      '/stack': 'http://localhost:8000',
      '/feed': 'http://localhost:8000',
      '/quiz': 'http://localhost:8000',
      '/auth': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
    allowedHosts: true,
  },
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg', 'eagle-logo.png'],
      manifest: {
        name: 'Kite',
        short_name: 'Kite',
        description: 'Personal discovery and dependency tracking for developers',
        theme_color: '#fcf9f3',
        background_color: '#fcf9f3',
        display: 'standalone',
        orientation: 'any',
        start_url: '/',
        scope: '/',
        icons: [
          { src: 'icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: 'icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: 'icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        runtimeCaching: [
          {
            urlPattern: /\/feed(\?|$)/,
            handler: 'NetworkFirst',
            options: {
              cacheName: 'api-feed-cache',
              expiration: {
                maxEntries: 50,
                maxAgeSeconds: 60 * 60 * 24,
              },
            },
          },
          {
            urlPattern: /\/stack\/projects(\?|$)/,
            handler: 'NetworkFirst',
            options: {
              cacheName: 'api-stack-projects-cache',
              expiration: {
                maxEntries: 50,
                maxAgeSeconds: 60 * 60 * 24,
              },
            },
          },
          {
            urlPattern: /\/stack\/digest(\?|$)/,
            handler: 'NetworkFirst',
            options: {
              cacheName: 'api-digest-cache',
              expiration: {
                maxEntries: 50,
                maxAgeSeconds: 60 * 60 * 24,
              },
            },
          },
        ],
      },
    }),
  ],
})
