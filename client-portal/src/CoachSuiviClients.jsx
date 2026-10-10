import React, { useEffect, useMemo, useState } from 'react'
import { ChevronDown, RefreshCw, Search } from 'lucide-react'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8013'

// Messages fixes : aucun detail technique n'est affiche.
const MESSAGE_SERVICE_INDISPONIBLE = 'Cockpit momentanément indisponible. Réessayez dans quelques minutes.'
const MESSAGE_CONNEXION = 'Connexion impossible. Vérifiez le réseau et réessayez.'

// Colonne « n » du cockpit : 1 à 7 = étape en cours, 8 = terminé.
const ETAPE_TERMINEE = 8

const ALERTE_COULEURS = {
  'En retard': 'var(--danger)',
  "Aujourd'hui": 'var(--warning)',
  'Sous 48 h': 'var(--warning)',
}

const INDICATEURS = [
  ['leads', 'Leads'],
  ['rdv', 'RDV'],
  ['ventes', 'Ventes'],
  ['conversion', 'Conversion'],
  ['panier_moyen', 'Panier moyen'],
  ['reachat', 'Réachat'],
]

// Date ISO (AAAA-MM-JJ) -> jj/mm/aaaa, sans passer par Date (pas de décalage de fuseau).
function dateFr(iso) {
  if (!iso) return null
  const [a, m, j] = iso.split('-')
  return `${j}/${m}/${a}`
}

function formatIndicateur(cle, valeur) {
  if (typeof valeur !== 'number') return String(valeur)
  if (cle === 'conversion') return `${Math.round(valeur * 100)} %`
  if (cle === 'panier_moyen') return `${valeur.toLocaleString('fr-FR', { maximumFractionDigits: 0 })} €`
  return valeur.toLocaleString('fr-FR')
}

function Progression({ numero }) {
  if (!numero) return null
  const faites = Math.min(numero - 1, ETAPE_TERMINEE - 1)
  const total = ETAPE_TERMINEE - 1
  return (
    <div className="mt-2" aria-label={`Progression : ${faites} étape(s) sur ${total}`}>
      <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--accent-soft)' }}>
        <div
          className="h-full rounded-full"
          style={{
            width: `${(faites / total) * 100}%`,
            background: numero === ETAPE_TERMINEE ? 'var(--success)' : 'var(--accent)',
          }}
        />
      </div>
      <p className="text-xs mt-1" style={{ color: 'var(--text-tertiary)' }}>
        {faites}/{total} étapes du process
      </p>
    </div>
  )
}

function FicheDetail({ client }) {
  const indicateurs = INDICATEURS.filter(([cle]) => client.indicateurs?.[cle] !== undefined)
  return (
    <div className="mt-4 pt-4 space-y-4" style={{ borderTop: 'var(--border-subtle)' }}>
      {client.date_premiere_session && (
        <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
          1re session : <strong>{dateFr(client.date_premiere_session)}</strong>
        </p>
      )}

      {client.prochaine_action && (
        <div className="p-3 rounded-xl" style={{ background: 'var(--accent-soft)' }}>
          <p className="text-xs font-semibold uppercase tracking-wider mb-1" style={{ color: 'var(--text-secondary)' }}>
            Prochaine action
          </p>
          <p className="text-sm" style={{ color: 'var(--text-primary)' }}>{client.prochaine_action}</p>
          {(client.echeance || client.alerte) && (
            <p className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>
              {client.echeance && <>Échéance : <strong>{dateFr(client.echeance)}</strong></>}
              {client.alerte && (
                <span className="font-semibold" style={{ color: ALERTE_COULEURS[client.alerte] || 'var(--text-secondary)' }}>
                  {client.echeance ? ' · ' : ''}{client.alerte}
                </span>
              )}
            </p>
          )}
        </div>
      )}

      <ul className="space-y-1.5">
        {client.etapes.map((etape) => (
          <li key={etape.cle} className="flex items-center justify-between gap-3 text-sm">
            <span style={{ color: 'var(--text-primary)' }}>
              {etape.libelle}
              {etape.date && (
                <span className="text-xs" style={{ color: 'var(--text-tertiary)' }}> · {dateFr(etape.date)}</span>
              )}
              {etape.valeur && (
                <span className="text-xs" style={{ color: 'var(--text-tertiary)' }}> · {etape.valeur}</span>
              )}
            </span>
            <span
              className="text-xs font-semibold shrink-0"
              style={{ color: etape.fait ? 'var(--success)' : 'var(--text-tertiary)' }}
            >
              {etape.fait ? 'Fait' : 'À faire'}
            </span>
          </li>
        ))}
      </ul>

      {indicateurs.length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: 'var(--text-secondary)' }}>
            Indicateurs d'activité
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {indicateurs.map(([cle, libelle]) => (
              <div key={cle} className="p-2 rounded-xl" style={{ border: 'var(--border-subtle)' }}>
                <p className="text-xs" style={{ color: 'var(--text-tertiary)' }}>{libelle}</p>
                <p className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
                  {formatIndicateur(cle, client.indicateurs[cle])}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default function CoachSuiviClients({ coachKey, onAuthFailure }) {
  const [clients, setClients] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [etapeFiltre, setEtapeFiltre] = useState('')
  const [expandedLigne, setExpandedLigne] = useState(null)

  async function loadSuivi() {
    setLoading(true)
    setError('')
    try {
      let res
      try {
        res = await fetch(`${API_BASE}/coach/suivi-clients`, { headers: { 'X-Coach-Key': coachKey } })
      } catch {
        setError(MESSAGE_CONNEXION)
        return
      }
      if (res.status === 401) return onAuthFailure()
      if (!res.ok) {
        setError(MESSAGE_SERVICE_INDISPONIBLE)
        return
      }
      let data = null
      try {
        data = await res.json()
      } catch {
        data = null
      }
      if (!Array.isArray(data?.clients)) {
        setError(MESSAGE_SERVICE_INDISPONIBLE)
        return
      }
      setClients(data.clients)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadSuivi()
    // Chargement unique a l'ouverture de l'onglet ; « Actualiser » pour relire.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Étapes réellement présentes dans le cockpit, dans l'ordre du process.
  const etapes = useMemo(() => {
    const vues = new Map()
    for (const c of clients) {
      if (c.etape && !vues.has(c.etape)) vues.set(c.etape, c.etape_numero ?? 99)
    }
    return [...vues.entries()].sort((a, b) => a[1] - b[1]).map(([libelle]) => libelle)
  }, [clients])

  const filtres = useMemo(() => {
    const q = query.trim().toLocaleLowerCase('fr-FR')
    return clients.filter((c) =>
      (!q || c.nom.toLocaleLowerCase('fr-FR').includes(q)) && (!etapeFiltre || c.etape === etapeFiltre)
    )
  }, [clients, query, etapeFiltre])

  return (
    <div>
      <p className="text-sm mb-4" style={{ color: 'var(--text-secondary)' }}>
        Avancement du process client, lu dans le cockpit Google Sheets (lecture seule).
      </p>

      <div className="card-glass p-4 mb-4 space-y-2" style={{ borderRadius: 'var(--radius-lg)' }}>
        <div className="flex items-center gap-2 field-input px-3 py-2">
          <Search size={14} color="var(--text-tertiary)" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Rechercher un client..."
            className="flex-1 bg-transparent outline-none text-sm"
          />
        </div>
        <div className="flex gap-2">
          <select
            value={etapeFiltre}
            onChange={(e) => setEtapeFiltre(e.target.value)}
            className="flex-1 min-w-0 field-input bg-transparent outline-none px-3 py-2 text-sm"
          >
            <option value="">Toutes les étapes</option>
            {etapes.map((e) => <option key={e} value={e}>{e}</option>)}
          </select>
          <button
            onClick={loadSuivi}
            disabled={loading}
            className="px-3 rounded-xl flex items-center gap-1.5 text-sm font-medium disabled:opacity-50"
            style={{ color: 'var(--text-secondary)', border: 'var(--border-subtle)' }}
            aria-label="Actualiser"
          >
            <RefreshCw size={14} />
          </button>
        </div>
      </div>

      {loading && <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>Chargement...</p>}
      {error && <p className="text-sm" style={{ color: 'var(--danger)' }}>{error}</p>}
      {!loading && !error && clients.length === 0 && (
        <p className="text-sm" style={{ color: 'var(--text-tertiary)' }}>Aucun client dans le cockpit.</p>
      )}
      {!loading && !error && clients.length > 0 && filtres.length === 0 && (
        <p className="text-sm" style={{ color: 'var(--text-tertiary)' }}>Aucun client ne correspond à ces critères.</p>
      )}

      <div className="space-y-3">
        {filtres.map((client) => {
          const ouvert = expandedLigne === client.ligne
          return (
            <div key={client.ligne} className="card-glass p-4" style={{ borderRadius: 'var(--radius-md)' }}>
              <button
                onClick={() => setExpandedLigne(ouvert ? null : client.ligne)}
                className="w-full flex items-start justify-between gap-3 text-left"
                aria-expanded={ouvert}
              >
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>{client.nom}</p>
                  <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                    {[client.offre, client.etape].filter(Boolean).join(' · ') || 'Étape non renseignée'}
                  </p>
                  {client.alerte && (
                    <p className="text-xs font-semibold mt-0.5" style={{ color: ALERTE_COULEURS[client.alerte] || 'var(--text-secondary)' }}>
                      {client.alerte}
                    </p>
                  )}
                  <Progression numero={client.etape_numero} />
                </div>
                <ChevronDown
                  size={18}
                  color="var(--text-secondary)"
                  style={{ transform: ouvert ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s' }}
                />
              </button>
              {ouvert && <FicheDetail client={client} />}
            </div>
          )
        })}
      </div>
    </div>
  )
}
