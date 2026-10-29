import { readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Appli Coach sur iPhone (29/10/2026) : Safari lit le manifeste et l'icone
// dans le HTML recu, pas ceux que src/main.jsx remplace ensuite. dist/coach.html
// (servi a /coach par Cloudflare Pages) porte donc directement l'identite Coach,
// et « Sur l'ecran d'accueil » installe l'Espace Coach, pas l'espace client.
function pageCoach() {
  const remplacements = [
    ['<title>Espace Client · eVolution 2.0</title>', '<title>RL-eVolution Coach</title>'],
    ['href="/manifest.webmanifest"', 'href="/coach.webmanifest"'],
    ['href="/favicon.ico"', 'href="/coach-favicon.ico"'],
    ['href="/favicon-32.png"', 'href="/coach-favicon-32.png"'],
    ['href="/icone-192.png"', 'href="/coach-192.png"'],
    ['href="/icone-180.png"', 'href="/coach-180.png"'],
    ['content="eVolution 2.0"', 'content="RL-eVolution Coach"'],
    ['content="#F1F0EC"', 'content="#8E6C38"'],
  ]
  let dossier = 'dist'
  return {
    name: 'page-coach',
    apply: 'build',
    configResolved(config) {
      dossier = resolve(config.root, config.build.outDir)
    },
    closeBundle() {
      let html = readFileSync(resolve(dossier, 'index.html'), 'utf8')
      for (const [avant, apres] of remplacements) {
        if (!html.includes(avant)) throw new Error(`page-coach : « ${avant} » introuvable dans index.html`)
        html = html.replace(avant, apres)
      }
      writeFileSync(resolve(dossier, 'coach.html'), html)
    },
  }
}

export default defineConfig({
  plugins: [react(), tailwindcss(), pageCoach()],
  server: {
    port: 5174,
    strictPort: true,
  },
})
