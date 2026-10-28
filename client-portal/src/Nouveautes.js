import { useCallback, useEffect, useRef, useState } from 'react'

// Badges « nouveau » (28/10/2026) : RDV poses ou deplaces par Rony, retours
// d'Idris, activite des eleves cote coach. Ce qui est « deja vu » reste dans
// ce navigateur (localStorage) : rien a regler dans Notion.

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8013'
const SESSION_KEY = 'portal_session_token'
const VU_RDV = 'portail_vu_rdv'
const VU_IDRIS = 'portail_vu_idris'
const VU_ELEVES = 'coach_vu_activite'

function lire(cle) {
  try {
    const valeur = localStorage.getItem(cle)
    return valeur === null ? null : JSON.parse(valeur)
  } catch {
    return null
  }
}

function ecrire(cle, valeur) {
  try {
    localStorage.setItem(cle, JSON.stringify(valeur))
  } catch {
    // Navigation privee : les badges reviennent a chaque visite, sans gravite.
  }
}

// Pastille sur l'icone de l'application installee (Chrome, Edge, Safari iOS).
export function badgeApplication(nombre) {
  try {
    if (nombre > 0) navigator.setAppBadge?.(nombre)?.catch?.(() => {})
    else navigator.clearAppBadge?.()?.catch?.(() => {})
  } catch {
    // Non pris en charge : rien a faire.
  }
}

// Relit quand l'application revient au premier plan ou qu'une notification
// arrive (message du service worker).
function useRelecture(relire, actif) {
  useEffect(() => {
    if (!actif) return undefined
    const auPremierPlan = () => { if (document.visibilityState === 'visible') relire() }
    const auMessage = (e) => { if (e.data?.type === 'push') relire() }
    document.addEventListener('visibilitychange', auPremierPlan)
    navigator.serviceWorker?.addEventListener?.('message', auMessage)
    return () => {
      document.removeEventListener('visibilitychange', auPremierPlan)
      navigator.serviceWorker?.removeEventListener?.('message', auMessage)
    }
  }, [relire, actif])
}

export function cleRdv(p) {
  return `${p.type}|${p.evenement?.debut}`
}

// Espace eleve : points (RDV) et retours d'Idris, avec ce qui n'a pas ete vu.
export function useNouveautesEleve(actif) {
  const [points, setPoints] = useState(null)
  const [retours, setRetours] = useState([])
  const [vusRdv, setVusRdv] = useState(() => lire(VU_RDV) || [])
  const [vusIdris, setVusIdris] = useState(() => lire(VU_IDRIS))
  const enCours = useRef(false)

  const relire = useCallback(async () => {
    if (enCours.current) return
    enCours.current = true
    const entetes = { headers: { Authorization: `Bearer ${localStorage.getItem(SESSION_KEY)}` } }
    const json = (url, defaut) => fetch(url, entetes).then((r) => (r.ok ? r.json() : defaut)).catch(() => defaut)
    const [p, n] = await Promise.all([
      json(`${API_BASE}/portal/points`, { points: [] }),
      json(`${API_BASE}/portal/nouveautes`, { retours_idris: [] }),
    ])
    enCours.current = false
    setPoints(Array.isArray(p.points) ? p.points : [])
    const liste = Array.isArray(n.retours_idris) ? n.retours_idris : []
    setRetours(liste)
    // Premiere visite : les anciens retours ne sont pas « nouveaux ».
    setVusIdris((vus) => {
      if (vus !== null) return vus
      const tous = liste.map((r) => r.id)
      ecrire(VU_IDRIS, tous)
      return tous
    })
  }, [])

  useEffect(() => { if (actif) relire() }, [actif, relire])
  useRelecture(relire, actif)

  const rdvAVenir = (points || []).filter((p) => p.statut === 'planifie' && p.evenement)
  const rdvNouveaux = rdvAVenir.filter((p) => !vusRdv.includes(cleRdv(p)))
  const idrisNouveaux = retours.filter((r) => !(vusIdris || []).includes(r.id))

  useEffect(() => {
    if (actif && points) badgeApplication(rdvNouveaux.length + idrisNouveaux.length)
  }, [actif, points, rdvNouveaux.length, idrisNouveaux.length])

  const marquerRdvVus = useCallback(() => {
    const cles = (points || []).filter((p) => p.statut === 'planifie' && p.evenement).map(cleRdv)
    setVusRdv((vus) => {
      if (cles.every((c) => vus.includes(c))) return vus
      // On ne garde que les RDV encore a venir.
      ecrire(VU_RDV, cles)
      return cles
    })
  }, [points])

  const marquerFicheVue = useCallback((ficheId) => {
    const ids = retours.filter((r) => r.fiche_id === ficheId).map((r) => r.id)
    if (!ids.length) return
    setVusIdris((vus) => {
      const suite = [...new Set([...(vus || []), ...ids])]
      ecrire(VU_IDRIS, suite)
      return suite
    })
  }, [retours])

  return { points, rdvNouveaux, idrisNouveaux, marquerRdvVus, marquerFicheVue }
}

// Espace Coach : eleves qui ont saisi quelque chose depuis la derniere fois
// que Rony a ouvert leur fiche eleve.
export function useActiviteEleves(coachKey, actif) {
  const [activite, setActivite] = useState({})
  const [vus, setVus] = useState(() => lire(VU_ELEVES))

  const relire = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/coach/eleves/activite`, { headers: { 'X-Coach-Key': coachKey } })
      if (!r.ok) return
      const data = await r.json()
      const liste = data.activite || {}
      setActivite(liste)
      // Premiere visite : rien n'est « nouveau ».
      setVus((v) => {
        if (v !== null) return v
        ecrire(VU_ELEVES, liste)
        return liste
      })
    } catch {
      // Badge absent, sans gravite.
    }
  }, [coachKey])

  useEffect(() => { if (actif) relire() }, [actif, relire])
  useRelecture(relire, actif)

  const nouveaux = Object.keys(activite).filter((id) => activite[id] > ((vus || {})[id] || ''))

  useEffect(() => {
    if (actif) badgeApplication(nouveaux.length)
  }, [actif, nouveaux.length])

  const marquerVu = useCallback((id) => {
    setVus((v) => {
      const suite = { ...(v || {}), [id]: activite[id] || new Date().toISOString() }
      ecrire(VU_ELEVES, suite)
      return suite
    })
  }, [activite])

  return { nouveaux, marquerVu, relire }
}
