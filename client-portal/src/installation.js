import { useEffect, useState } from 'react'

// Installation du portail comme application (client et coach).
// Le navigateur envoie « beforeinstallprompt » une seule fois, souvent avant
// que le bouton « Installer » soit affiche : on le garde ici des le
// chargement, et les composants s'abonnent.

let invite = null
const abonnes = new Set()

function prevenir() {
  for (const f of abonnes) f(invite)
}

export function demarrerInstallation() {
  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault()
    invite = event
    prevenir()
  })
  window.addEventListener('appinstalled', () => {
    invite = null
    prevenir()
  })
  // Service worker existant (notifications, aucun cache) : l'enregistrer des
  // l'ouverture rend l'application installable partout.
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js').catch(() => {})
    })
  }
}

export function inviteInstallation() {
  return invite
}

export function suivreInstallation(f) {
  abonnes.add(f)
  return () => abonnes.delete(f)
}

export function estInstallee() {
  return window.matchMedia?.('(display-mode: standalone)').matches || window.navigator.standalone === true
}

export async function installer() {
  if (!invite) return false
  const evenement = invite
  evenement.prompt()
  const { outcome } = await evenement.userChoice
  invite = null
  prevenir()
  return outcome === 'accepted'
}

// L'Espace Coach est une application a part : son manifeste, ses icones,
// son titre. Appele avant le premier rendu.
export function identiteCoach() {
  const remplacer = (selecteur, attribut, valeur) => {
    for (const el of document.querySelectorAll(selecteur)) el.setAttribute(attribut, valeur)
  }
  document.title = 'RL-eVolution Coach'
  remplacer('link[rel="manifest"]', 'href', '/coach.webmanifest')
  remplacer('link[rel="icon"][href="/favicon.ico"]', 'href', '/coach-favicon.ico')
  remplacer('link[rel="icon"][href="/favicon-32.png"]', 'href', '/coach-favicon-32.png')
  remplacer('link[rel="icon"][href="/icone-192.png"]', 'href', '/coach-192.png')
  remplacer('link[rel="apple-touch-icon"]', 'href', '/coach-180.png')
  remplacer('meta[name="apple-mobile-web-app-title"]', 'content', 'RL-eVolution Coach')
  remplacer('meta[name="theme-color"]', 'content', '#8E6C38')
}

// { invite, installee } a jour pour un composant React.
export function useInstallation() {
  const [etat, setEtat] = useState(() => ({ invite: inviteInstallation(), installee: estInstallee() }))
  useEffect(() => {
    const installee = () => setEtat({ invite: null, installee: true })
    window.addEventListener('appinstalled', installee)
    const arreter = suivreInstallation((i) => setEtat((e) => ({ ...e, invite: i })))
    return () => {
      arreter()
      window.removeEventListener('appinstalled', installee)
    }
  }, [])
  return etat
}
