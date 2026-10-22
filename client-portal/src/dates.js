export function formaterMaj(iso) {
  // Heure de Guadeloupe, ou se trouvent les clients.
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  const options = { timeZone: 'America/Guadeloupe' }
  const jour = date.toLocaleDateString('fr-FR', { ...options, day: '2-digit', month: '2-digit', year: 'numeric' })
  const heure = date.toLocaleTimeString('fr-FR', { ...options, hour: '2-digit', minute: '2-digit' })
  return `${jour} à ${heure}`
}
