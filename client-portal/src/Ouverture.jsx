import React, { useEffect, useRef, useState } from 'react'

// Animation d'ouverture (28/10/2026), dans l'esprit de l'animation de Rony :
// 1. croquis au crayon sur papier quadrille (courbe + « eVolution 2.0 ») ;
// 2. une lumiere doree parcourt la courbe, la feuille bascule ;
// 3. le logo se detache en relief or, poussiere doree et halo sur fond noir ;
// 4. eclat de lumiere : logo final, « e » dore et le reste en noir.
// Une fois par lancement (sessionStorage), un toucher la passe.

const CLE = 'ouverture_vue'
const ETAPES = [
  ['lumiere', 1300],
  ['envol', 2400],
  ['revele', 3500],
  ['sort', 5700],
  ['fini', 6200],
]
const COURBE = 'M40 205 C 52 130, 128 120, 150 168 M170 205 C 190 95, 290 92, 330 150 C 368 206, 438 214, 478 150 C 500 116, 520 92, 548 66'
const BOUCLE = 'M318 132 C 330 60, 420 40, 452 90'
const ELAN = 'M170 205 C 190 95, 290 92, 330 150 C 368 206, 438 214, 478 150 C 500 116, 520 92, 548 66'

function dejaVue() {
  try {
    return sessionStorage.getItem(CLE) === '1'
  } catch {
    return false
  }
}

function marquerVue() {
  try {
    sessionStorage.setItem(CLE, '1')
  } catch {
    // Navigation privee : l'animation reviendra, sans gravite.
  }
}

// Poussiere doree : particules qui tourbillonnent autour du logo (etape 3).
function Poussiere({ actif }) {
  const toile = useRef(null)

  useEffect(() => {
    if (!actif) return undefined
    const canvas = toile.current
    const ctx = canvas?.getContext('2d')
    if (!ctx) return undefined
    const ratio = Math.min(window.devicePixelRatio || 1, 2)
    const l = canvas.clientWidth
    const h = canvas.clientHeight
    canvas.width = l * ratio
    canvas.height = h * ratio
    ctx.scale(ratio, ratio)
    const cx = l / 2
    const cy = h / 2
    const grains = Array.from({ length: 170 }, () => ({
      angle: Math.random() * Math.PI * 2,
      rayon: 0.25 + Math.random() * 0.55,
      vitesse: 0.6 + Math.random() * 1.6,
      taille: 0.6 + Math.random() * 2.2,
      haut: (Math.random() - 0.5) * 0.5,
      vie: Math.random(),
    }))
    const debut = performance.now()
    let image

    const dessiner = (t) => {
      const ecoule = (t - debut) / 1000
      ctx.clearRect(0, 0, l, h)
      ctx.globalCompositeOperation = 'source-over'
      for (const g of grains) {
        const a = g.angle + ecoule * g.vitesse
        const x = cx + Math.cos(a) * g.rayon * l * 0.5
        const y = cy + Math.sin(a) * g.rayon * h * 0.16 + g.haut * h * 0.3 - ecoule * 12 * g.vitesse
        const eclat = Math.max(0, Math.sin((g.vie + ecoule * 0.9) * Math.PI)) * Math.max(0, 1 - ecoule / 2.6)
        const grad = ctx.createRadialGradient(x, y, 0, x, y, g.taille * 3)
        grad.addColorStop(0, `rgba(255, 236, 180, ${eclat})`)
        grad.addColorStop(0.4, `rgba(232, 180, 90, ${eclat * 0.6})`)
        grad.addColorStop(1, 'rgba(200, 140, 50, 0)')
        ctx.fillStyle = grad
        ctx.beginPath()
        ctx.arc(x, y, g.taille * 3, 0, Math.PI * 2)
        ctx.fill()
      }
      if (ecoule < 2.8) image = requestAnimationFrame(dessiner)
    }
    image = requestAnimationFrame(dessiner)
    return () => cancelAnimationFrame(image)
  }, [actif])

  return <canvas ref={toile} className="ouverture-poussiere" aria-hidden="true" />
}

export default function Ouverture({ coach = false }) {
  const [etape, setEtape] = useState(() => (dejaVue() ? 'fini' : 'croquis'))

  useEffect(() => {
    if (etape === 'fini') return undefined
    marquerVue()
    const calme = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    const minuteurs = calme
      ? [setTimeout(() => setEtape('revele'), 50), setTimeout(() => setEtape('sort'), 1200), setTimeout(() => setEtape('fini'), 1700)]
      : ETAPES.map(([nom, quand]) => setTimeout(() => setEtape((e) => (e === 'sort' && nom !== 'fini' ? e : nom)), quand))
    return () => minuteurs.forEach(clearTimeout)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (etape !== 'sort') return undefined
    const fin = setTimeout(() => setEtape('fini'), 500)
    return () => clearTimeout(fin)
  }, [etape])

  if (etape === 'fini') return null

  return (
    <div className={`ouverture ouverture-${etape}`} onClick={() => setEtape('sort')} role="presentation">
      <div className="ouverture-halo" aria-hidden="true" />
      <div className="ouverture-papier" aria-hidden="true">
        <span className="ouverture-cote">ÉCHELLE 1:1</span>
        <span className="ouverture-cote ouverture-cote-droite">MATIÈRE : OR / GRAPHITE</span>
      </div>
      <Poussiere actif={etape === 'envol' || etape === 'revele'} />

      <div className="ouverture-logo">
        <svg className="ouverture-courbe" viewBox="0 0 600 230" aria-hidden="true">
          <defs>
            <pattern id="ouv-hachures" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(35)">
              <rect width="5" height="5" fill="#EDE6D8" />
              <line x1="0" y1="0" x2="0" y2="5" stroke="#6E6A62" strokeWidth="1.4" />
            </pattern>
            <linearGradient id="ouv-or" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="#FFF4CF" />
              <stop offset="0.35" stopColor="#F0C96F" />
              <stop offset="0.7" stopColor="#C08A36" />
              <stop offset="1" stopColor="#7A5420" />
            </linearGradient>
            <linearGradient id="ouv-or-tranche" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="#8A5F22" />
              <stop offset="1" stopColor="#4A3210" />
            </linearGradient>
            <filter id="ouv-lueur" x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur stdDeviation="6" result="flou" />
              <feMerge><feMergeNode in="flou" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
          </defs>

          {/* 1. Croquis : contour au crayon et hachures */}
          <g className="ouverture-croquis-trait">
            <path className="ouverture-trace ouverture-trace-1" d={COURBE} stroke="#3A3732" strokeWidth="15" />
            <path className="ouverture-trace ouverture-trace-1" d={COURBE} stroke="url(#ouv-hachures)" strokeWidth="12" />
            <path className="ouverture-trace ouverture-trace-2" d={BOUCLE} stroke="#3A3732" strokeWidth="15" />
            <path className="ouverture-trace ouverture-trace-2" d={BOUCLE} stroke="url(#ouv-hachures)" strokeWidth="12" />
            <polygon className="ouverture-pointe-croquis" points="580,35 529,51 561,85" />
          </g>

          {/* 3. Relief or : tranche sombre, face doree, reflet */}
          <g className="ouverture-or">
            <g transform="translate(0 5)">
              <path d={COURBE} stroke="url(#ouv-or-tranche)" strokeWidth="14" fill="none" strokeLinecap="round" />
              <path d={BOUCLE} stroke="url(#ouv-or-tranche)" strokeWidth="14" fill="none" strokeLinecap="round" />
              <polygon points="580,35 529,51 561,85" fill="#4A3210" />
            </g>
            <path d={COURBE} stroke="url(#ouv-or)" strokeWidth="14" fill="none" strokeLinecap="round" />
            <path d={BOUCLE} stroke="url(#ouv-or)" strokeWidth="14" fill="none" strokeLinecap="round" />
            <polygon points="580,35 529,51 561,85" fill="url(#ouv-or)" />
            <path className="ouverture-reflet" d={ELAN} stroke="#FFFBEA" strokeWidth="3" fill="none" strokeLinecap="round" />
          </g>

          {/* 2. Lumiere doree qui parcourt la courbe */}
          <path className="ouverture-sillage" d={ELAN} stroke="#FFD98A" strokeWidth="6" fill="none" strokeLinecap="round" filter="url(#ouv-lueur)" />
          <circle className="ouverture-etincelle" r="7" fill="#FFF6D8" filter="url(#ouv-lueur)">
            <animateMotion dur="1s" begin="1.35s" fill="freeze" path={ELAN} />
          </circle>
        </svg>

        <p className="ouverture-nom" aria-label="eVolution 2.0">
          <span className="ouverture-e">e</span>Volution<span className="ouverture-version">2.0</span>
        </p>
        <p className="ouverture-devise">
          Structure <i>|</i> Stratégie <i>|</i> Croissance
        </p>
        {coach && <p className="ouverture-coach">Espace Coach</p>}
      </div>
    </div>
  )
}
