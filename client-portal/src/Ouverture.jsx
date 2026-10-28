import React, { useEffect, useState } from 'react'

// Animation d'ouverture (28/10/2026), d'apres le croquis du logo de Rony : la
// courbe de croissance se dessine au crayon, le « e » dore apparait, puis
// « eVolution 2.0 » et la devise. Une fois par lancement de l'application
// (sessionStorage), un toucher la passe. Version Espace Coach : mention dediee.

const CLE = 'ouverture_vue'
const DUREE = 3900

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

export default function Ouverture({ coach = false }) {
  const [etat, setEtat] = useState(() => (dejaVue() ? 'fini' : 'joue'))

  useEffect(() => {
    if (etat !== 'joue') return undefined
    marquerVue()
    const calme = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    const sortie = setTimeout(() => setEtat('sort'), calme ? 900 : DUREE)
    return () => clearTimeout(sortie)
  }, [etat])

  useEffect(() => {
    if (etat !== 'sort') return undefined
    const fin = setTimeout(() => setEtat('fini'), 450)
    return () => clearTimeout(fin)
  }, [etat])

  if (etat === 'fini') return null

  return (
    <div
      className={`ouverture${etat === 'sort' ? ' ouverture-sort' : ''}`}
      onClick={() => setEtat('sort')}
      role="presentation"
    >
      <div className="ouverture-scene">
        <svg className="ouverture-courbe" viewBox="0 0 600 230" aria-hidden="true">
          <defs>
            <linearGradient id="ouverture-graphite" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#6B6760" />
              <stop offset="1" stopColor="#2E2C29" />
            </linearGradient>
          </defs>
          <path className="ouverture-trait ouverture-trait-1" d="M40 205 C 52 130, 128 120, 150 168" />
          <path className="ouverture-trait ouverture-trait-2" d="M170 205 C 190 95, 290 92, 330 150 C 368 206, 438 214, 478 150 C 500 116, 520 92, 548 66" />
          <path className="ouverture-trait ouverture-trait-3" d="M318 132 C 330 60, 420 40, 452 90" />
          <polygon className="ouverture-fleche" points="578,37 531,53 559,83" />
        </svg>

        <p className="ouverture-nom" aria-label="eVolution 2.0">
          <span className="ouverture-e">e</span>
          <span className="ouverture-suite">Volution</span>
          <span className="ouverture-version">2.0</span>
        </p>
        <span className="ouverture-souligne" aria-hidden="true" />
        <p className="ouverture-devise">
          Structure <i>|</i> Stratégie <i>|</i> Croissance
        </p>
        {coach && <p className="ouverture-coach">Espace Coach</p>}
      </div>
    </div>
  )
}
