// Service worker du portail eVolution 2.0 : uniquement les notifications
// (27/10/2026). Pas de cache hors ligne : chaque ouverture charge la derniere
// version du portail, comme avant.

self.addEventListener('install', () => self.skipWaiting())

self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()))

self.addEventListener('push', (event) => {
  let donnees = {}
  try {
    donnees = event.data ? event.data.json() : {}
  } catch {
    donnees = { texte: event.data ? event.data.text() : '' }
  }

  event.waitUntil((async () => {
    await self.registration.showNotification(donnees.titre || 'eVolution 2.0', {
      body: donnees.texte || '',
      icon: '/icone-192.png',
      badge: '/icone-192.png',
      data: { url: donnees.url || '/' },
    })
    // Badges (28/10/2026) : pastille sur l'icone de l'application, et l'espace
    // deja ouvert relit ses nouveautes tout de suite.
    try {
      await self.navigator.setAppBadge?.()
    } catch {
      // Non pris en charge.
    }
    const fenetres = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    fenetres.forEach((f) => f.postMessage({ type: 'push' }))
  })())
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const url = new URL(event.notification.data?.url || '/', self.location.origin).href

  event.waitUntil((async () => {
    const fenetres = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    for (const fenetre of fenetres) {
      if (new URL(fenetre.url).origin !== self.location.origin) continue
      try {
        await fenetre.navigate(url)
        return fenetre.focus()
      } catch {
        // Fenetre non controlee : on en ouvre une nouvelle.
      }
    }
    return self.clients.openWindow(url)
  })())
})
