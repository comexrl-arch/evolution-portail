import React, { useEffect, useMemo, useState } from 'react'
import { ChevronDown, ChevronLeft, RefreshCw, Search } from 'lucide-react'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8013'

// Messages fixes : aucun detail technique n'est affiche.
const MESSAGE_SERVICE_INDISPONIBLE = 'Activité des élèves momentanément indisponible. Réessayez dans quelques minutes.'
const MESSAGE_CONNEXION = 'Connexion impossible. Vérifiez le réseau et réessayez.'

// Au-dela, l'eleve est signale comme decroche (meme seuil que les relances).
const JOURS_INACTIF = 7

const KPI_COLONNES = [
  ['valeur_j0', 'J0'],
  ['valeur_j30', 'J30'],
  ['valeur_j60', 'J60'],
  ['valeur_j90', 'J90'],
  ['objectif_j90', 'Obj. J90'],
]

const STATUT_COULEURS = {
  'Terminé': 'var(--success)',
  'En cours': 'var(--accent)',
}

// Date ISO -> jj/mm/aaaa, sans passer par Date pour les dates seules (pas de decalage de fuseau).
function dateFr(iso) {
  if (!iso) return null
  const [a, m, j] = String(iso).slice(0, 10).split('-')
  return `${j}/${m}/${a}`
}

function depuis(jours) {
  if (jours === null || jours === undefined) return 'aucune saisie'
  if (jours === 0) return "aujourd'hui"
  if (jours === 1) return 'hier'
  return `il y a ${jours} jours`
}

function nombre(valeur) {
  if (valeur === null || valeur === undefined || valeur === '') return '—'
  return typeof valeur === 'number' ? valeur.toLocaleString('fr-FR') : String(valeur)
}

function valeurLisible(valeur) {
  if (valeur === true) return 'Oui'
  if (valeur === false) return 'Non'
  if (Array.isArray(valeur)) return valeur.join(', ')
  if (valeur && typeof valeur === 'object') return JSON.stringify(valeur)
  return String(valeur ?? '').replace(/^##(TABLE|CHECK)## /gm, '')
}

async function lireCoach(chemin, coachKey, onAuthFailure) {
  let res
  try {
    res = await fetch(`${API_BASE}${chemin}`, { headers: { 'X-Coach-Key': coachKey } })
  } catch {
    return { erreur: MESSAGE_CONNEXION }
  }
  if (res.status === 401) {
    onAuthFailure()
    return { erreur: '' }
  }
  if (!res.ok) return { erreur: MESSAGE_SERVICE_INDISPONIBLE }
  try {
    return { data: await res.json() }
  } catch {
    return { erreur: MESSAGE_SERVICE_INDISPONIBLE }
  }
}

function Titre({ children }) {
  return (
    <p className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: 'var(--text-secondary)' }}>
      {children}
    </p>
  )
}

function Bloc({ titre, children }) {
  return (
    <div className="card-glass p-4" style={{ borderRadius: 'var(--radius-md)' }}>
      <Titre>{titre}</Titre>
      {children}
    </div>
  )
}

function Vide({ children }) {
  return <p className="text-sm" style={{ color: 'var(--text-tertiary)' }}>{children}</p>
}

function Pastilles({ eleve }) {
  const pastilles = []
  if (eleve.jours_sans_saisie === null || eleve.jours_sans_saisie >= JOURS_INACTIF) {
    pastilles.push(['Sans activité ' + (eleve.jours_sans_saisie === null ? '' : `depuis ${eleve.jours_sans_saisie} j`), 'var(--danger)'])
  }
  if (eleve.retours_ia_a_relire > 0) {
    pastilles.push([`${eleve.retours_ia_a_relire} retour${eleve.retours_ia_a_relire > 1 ? 's' : ''} d'Idris à relire`, 'var(--warning)'])
  }
  if (!pastilles.length) return null
  return (
    <div className="flex flex-wrap gap-1.5 mt-1">
      {pastilles.map(([texte, couleur]) => (
        <span key={texte} className="text-xs font-semibold" style={{ color: couleur }}>{texte.trim()}</span>
      ))}
    </div>
  )
}

function LigneEleve({ eleve, onOuvrir }) {
  if (eleve.illisible) {
    return (
      <div className="card-glass p-4" style={{ borderRadius: 'var(--radius-md)' }}>
        <p className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>{eleve.nom}</p>
        <p className="text-xs" style={{ color: 'var(--text-tertiary)' }}>Données momentanément illisibles.</p>
      </div>
    )
  }
  const pourcent = eleve.fiches_total ? Math.round((eleve.fiches_terminees / eleve.fiches_total) * 100) : 0
  return (
    <button
      onClick={() => onOuvrir(eleve)}
      className="card-glass p-4 w-full text-left"
      style={{ borderRadius: 'var(--radius-md)' }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>{eleve.nom}</p>
          <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
            {[eleve.parcours, eleve.jour !== null && eleve.jour !== undefined ? `J${eleve.jour}/${eleve.duree}` : null, eleve.etat !== 'En cours' ? eleve.etat : null]
              .filter(Boolean).join(' · ')}
          </p>
          <Pastilles eleve={eleve} />
        </div>
        <ChevronDown size={18} color="var(--text-secondary)" style={{ transform: 'rotate(-90deg)' }} />
      </div>
      <div className="mt-2 h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--accent-soft)' }}>
        <div className="h-full rounded-full" style={{ width: `${pourcent}%`, background: 'var(--accent)' }} />
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-3 gap-y-1 mt-2 text-xs" style={{ color: 'var(--text-tertiary)' }}>
        <span>Fiches : <strong style={{ color: 'var(--text-primary)' }}>{eleve.fiches_terminees}/{eleve.fiches_total}</strong></span>
        <span>Dernière saisie : <strong style={{ color: 'var(--text-primary)' }}>{depuis(eleve.jours_sans_saisie)}</strong></span>
        <span>Connexion : <strong style={{ color: 'var(--text-primary)' }}>{dateFr(eleve.derniere_connexion) || '—'}</strong></span>
        <span>Prospects : <strong style={{ color: 'var(--text-primary)' }}>{eleve.nb_prospects}</strong>
          {eleve.prospects_par_statut?.Client ? ` · ${eleve.prospects_par_statut.Client} client(s)` : ''}</span>
      </div>
    </button>
  )
}

function ReponsesFiche({ fiche, clientPageId, coachKey, onAuthFailure }) {
  const [etat, setEtat] = useState({ chargement: true })

  useEffect(() => {
    let actif = true
    lireCoach(`/coach/fiches/${fiche.id}?client_page_id=${encodeURIComponent(clientPageId)}`, coachKey, onAuthFailure)
      .then((r) => { if (actif) setEtat({ ...r, chargement: false }) })
    return () => { actif = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fiche.id, clientPageId])

  if (etat.chargement) return <Vide>Chargement des réponses...</Vide>
  if (etat.erreur) return <p className="text-sm" style={{ color: 'var(--danger)' }}>{etat.erreur}</p>

  const champs = etat.data?.champs || []
  // Une entree sans id = pre-remplissage propose au client, jamais enregistre.
  const entrees = (etat.data?.entrees || []).filter((e) => e.id).slice().reverse()
  if (!entrees.length) return <Vide>Rien d'enregistré pour l'instant.</Vide>

  return (
    <div className="space-y-3">
      {entrees.map((entree) => {
        const lignes = champs
          .map((c) => [c.libelle, entree.donnees?.[c.cle]])
          .filter(([, v]) => v !== undefined && v !== null && v !== '')
        return (
          <div key={entree.id} className="p-3 rounded-xl" style={{ border: 'var(--border-subtle)' }}>
            {entree.date && <p className="text-xs mb-1" style={{ color: 'var(--text-tertiary)' }}>Enregistré le {dateFr(entree.date)}</p>}
            {lignes.length === 0 && <Vide>Entrée vide.</Vide>}
            <dl className="space-y-1.5">
              {lignes.map(([libelle, valeur], i) => (
                <div key={i}>
                  <dt className="text-xs" style={{ color: 'var(--text-tertiary)' }}>{libelle}</dt>
                  <dd className="text-sm whitespace-pre-wrap" style={{ color: 'var(--text-primary)' }}>{valeurLisible(valeur)}</dd>
                </div>
              ))}
            </dl>
            {entree.retour_ia?.texte && (
              <div className="mt-2 p-2 rounded-lg" style={{ background: 'var(--accent-soft)' }}>
                <p className="text-xs font-semibold" style={{ color: 'var(--text-secondary)' }}>Retour d'Idris</p>
                <p className="text-sm whitespace-pre-wrap" style={{ color: 'var(--text-primary)' }}>{entree.retour_ia.texte}</p>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function DetailEleve({ eleve, coachKey, onAuthFailure, onRetour }) {
  const [etat, setEtat] = useState({ chargement: true })
  const [ficheOuverte, setFicheOuverte] = useState(null)

  async function charger(frais = false) {
    setEtat((e) => ({ ...e, chargement: true, erreur: '' }))
    const r = await lireCoach(`/coach/eleves/${eleve.client_page_id}${frais ? '?frais=true' : ''}`, coachKey, onAuthFailure)
    setEtat({ ...r, chargement: false })
  }

  useEffect(() => {
    charger()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eleve.client_page_id])

  const d = etat.data?.dashboard
  const carnet = etat.data?.carnet
  const bilans = (etat.data?.bilans || []).slice(-8).reverse()

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <button onClick={onRetour} className="flex items-center gap-1 text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>
          <ChevronLeft size={16} /> Tous les élèves
        </button>
        <button
          onClick={() => charger(true)}
          disabled={etat.chargement}
          className="px-3 py-1.5 rounded-xl flex items-center gap-1.5 text-sm disabled:opacity-50"
          style={{ color: 'var(--text-secondary)', border: 'var(--border-subtle)' }}
          aria-label="Actualiser"
        >
          <RefreshCw size={14} />
        </button>
      </div>

      <div>
        <h2 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>{d?.nom || eleve.nom}</h2>
        <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
          {[eleve.parcours, d?.rythme ? `J${d.rythme.jour}/${d.rythme.duree}` : null, d?.date_demarrage ? `démarré le ${dateFr(d.date_demarrage)}` : null]
            .filter(Boolean).join(' · ')}
        </p>
        <p className="text-xs mt-1" style={{ color: 'var(--text-tertiary)' }}>Ce que l'élève voit dans son espace, lu à la même source.</p>
      </div>

      {etat.chargement && !d && <Vide>Chargement...</Vide>}
      {etat.erreur && <p className="text-sm" style={{ color: 'var(--danger)' }}>{etat.erreur}</p>}

      {d && (
        <>
          <Bloc titre="En bref">
            <div className="grid grid-cols-2 gap-2 text-sm">
              <p style={{ color: 'var(--text-secondary)' }}>Fiches en retard : <strong style={{ color: d.rythme?.en_retard ? 'var(--danger)' : 'var(--text-primary)' }}>{d.rythme?.en_retard ?? '—'}</strong></p>
              <p style={{ color: 'var(--text-secondary)' }}>Bilans d'affilée : <strong style={{ color: 'var(--text-primary)' }}>{d.regularite?.serie ?? '—'}</strong></p>
              <p style={{ color: 'var(--text-secondary)' }}>Dernière relance : <strong style={{ color: 'var(--text-primary)' }}>{dateFr(eleve.derniere_relance) || '—'}</strong></p>
              <p style={{ color: 'var(--text-secondary)' }}>Relances envoyées : <strong style={{ color: 'var(--text-primary)' }}>{eleve.nb_relances}</strong></p>
            </div>
            {d.objectif_90j && (
              <p className="text-sm mt-2" style={{ color: 'var(--text-primary)' }}>
                <span style={{ color: 'var(--text-tertiary)' }}>Objectif 90 jours : </span>{d.objectif_90j}
              </p>
            )}
            {d.personnalisation?.zones_prioritaires?.length > 0 && (
              <p className="text-sm mt-1" style={{ color: 'var(--text-primary)' }}>
                <span style={{ color: 'var(--text-tertiary)' }}>Zones prioritaires : </span>
                {d.personnalisation.zones_prioritaires.map((z) => z.zone).join(', ')}
              </p>
            )}
          </Bloc>

          <Bloc titre="Fiches">
            <ul className="space-y-1">
              {d.fiches.map((fiche) => {
                const ouverte = ficheOuverte === fiche.id
                const bloquee = String(fiche.acces || '').includes('Bloqué')
                return (
                  <li key={fiche.id}>
                    <button
                      onClick={() => setFicheOuverte(ouverte ? null : fiche.id)}
                      disabled={bloquee}
                      className="w-full flex items-center justify-between gap-3 text-sm text-left py-1 disabled:opacity-60"
                      aria-expanded={ouverte}
                    >
                      <span style={{ color: 'var(--text-primary)' }}>
                        {String(fiche.nom || '').split(' - ').slice(-1)[0]}
                        {fiche.priorite?.type === 'prioritaire' && (
                          <span className="text-xs" style={{ color: 'var(--warning)' }}> · prioritaire</span>
                        )}
                      </span>
                      <span className="text-xs font-semibold shrink-0" style={{ color: STATUT_COULEURS[fiche.etat] || 'var(--text-tertiary)' }}>
                        {bloquee ? 'Pas encore ouverte' : fiche.etat || 'Pas commencé'}
                      </span>
                    </button>
                    {ouverte && (
                      <div className="pb-2">
                        <ReponsesFiche fiche={fiche} clientPageId={eleve.client_page_id} coachKey={coachKey} onAuthFailure={onAuthFailure} />
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          </Bloc>

          <Bloc titre="Indicateurs (KPI)">
            {d.kpi?.length ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr style={{ color: 'var(--text-tertiary)' }}>
                      <th className="text-left font-medium py-1 pr-2">KPI</th>
                      {KPI_COLONNES.map(([cle, libelle]) => <th key={cle} className="text-right font-medium py-1 px-1">{libelle}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {d.kpi.map((kpi) => (
                      <tr key={kpi.id} style={{ borderTop: 'var(--border-subtle)' }}>
                        <td className="py-1 pr-2" style={{ color: 'var(--text-primary)' }}>{kpi.nom}</td>
                        {KPI_COLONNES.map(([cle]) => (
                          <td key={cle} className="text-right py-1 px-1" style={{ color: 'var(--text-primary)' }}>{nombre(kpi[cle])}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <Vide>Aucun indicateur saisi.</Vide>}
          </Bloc>

          <Bloc titre="Bilans hebdomadaires">
            {bilans.length ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr style={{ color: 'var(--text-tertiary)' }}>
                      <th className="text-left font-medium py-1 pr-2">Semaine du</th>
                      <th className="text-right font-medium py-1 px-1">Contacts</th>
                      <th className="text-right font-medium py-1 px-1">RDV</th>
                      <th className="text-right font-medium py-1 px-1">Propos.</th>
                      <th className="text-right font-medium py-1 px-1">Ventes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bilans.map((b) => (
                      <tr key={b.semaine_du} style={{ borderTop: 'var(--border-subtle)', color: 'var(--text-primary)' }}>
                        <td className="py-1 pr-2">{dateFr(b.semaine_du)}</td>
                        <td className="text-right py-1 px-1">{nombre(b.contacts)}</td>
                        <td className="text-right py-1 px-1">{nombre(b.rdv)}</td>
                        <td className="text-right py-1 px-1">{nombre(b.propositions)}</td>
                        <td className="text-right py-1 px-1">{nombre(b.ventes)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <Vide>Aucun bilan enregistré.</Vide>}
          </Bloc>

          <Bloc titre="Carnet de prospects">
            {carnet?.prospects?.length ? (
              <>
                <p className="text-sm mb-2" style={{ color: 'var(--text-secondary)' }}>
                  {carnet.statuts.map((s) => `${s} : ${carnet.par_statut[s] || 0}`).join(' · ')}
                  {carnet.a_relancer?.length ? ` · ${carnet.a_relancer.length} à relancer` : ''}
                </p>
                <ul className="space-y-1">
                  {carnet.prospects.slice(0, 30).map((p) => (
                    <li key={p.id} className="flex justify-between gap-3 text-sm">
                      <span style={{ color: 'var(--text-primary)' }}>{p.nom}</span>
                      <span className="text-xs shrink-0" style={{ color: 'var(--text-tertiary)' }}>
                        {p.statut}{p.relance ? ` · relance ${dateFr(p.relance)}` : ''}
                      </span>
                    </li>
                  ))}
                </ul>
              </>
            ) : <Vide>Carnet vide.</Vide>}
          </Bloc>

          {d.syntheses?.length > 0 && (
            <Bloc titre="Synthèses mensuelles envoyées">
              <div className="space-y-2">
                {d.syntheses.map((s) => (
                  <div key={s.mois}>
                    <p className="text-xs" style={{ color: 'var(--text-tertiary)' }}>Mois {s.mois}{s.date ? ` · ${dateFr(s.date)}` : ''}</p>
                    <p className="text-sm whitespace-pre-wrap" style={{ color: 'var(--text-primary)' }}>{s.texte}</p>
                  </div>
                ))}
              </div>
            </Bloc>
          )}
        </>
      )}
    </div>
  )
}

export default function CoachEleves({ coachKey, onAuthFailure }) {
  const [eleves, setEleves] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [ouvert, setOuvert] = useState(null)

  async function charger() {
    setLoading(true)
    setError('')
    const r = await lireCoach('/coach/eleves', coachKey, onAuthFailure)
    setLoading(false)
    if (r.erreur !== undefined) return setError(r.erreur)
    if (!Array.isArray(r.data?.eleves)) return setError(MESSAGE_SERVICE_INDISPONIBLE)
    setEleves(r.data.eleves)
  }

  useEffect(() => {
    charger()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const filtres = useMemo(() => {
    const q = query.trim().toLocaleLowerCase('fr-FR')
    return eleves.filter((e) => !q || (e.nom || '').toLocaleLowerCase('fr-FR').includes(q))
  }, [eleves, query])

  if (ouvert) {
    return <DetailEleve eleve={ouvert} coachKey={coachKey} onAuthFailure={onAuthFailure} onRetour={() => setOuvert(null)} />
  }

  return (
    <div>
      <p className="text-sm mb-4" style={{ color: 'var(--text-secondary)' }}>
        Ce que chaque élève fait dans son espace client : fiches, indicateurs, bilans, carnet de prospects. Lecture seule.
      </p>

      <div className="card-glass p-4 mb-4 flex gap-2" style={{ borderRadius: 'var(--radius-lg)' }}>
        <div className="flex-1 flex items-center gap-2 field-input px-3 py-2">
          <Search size={14} color="var(--text-tertiary)" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Rechercher un élève..."
            className="flex-1 bg-transparent outline-none text-sm"
          />
        </div>
        <button
          onClick={charger}
          disabled={loading}
          className="px-3 rounded-xl flex items-center gap-1.5 text-sm font-medium disabled:opacity-50"
          style={{ color: 'var(--text-secondary)', border: 'var(--border-subtle)' }}
          aria-label="Actualiser"
        >
          <RefreshCw size={14} />
        </button>
      </div>

      {loading && <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>Chargement...</p>}
      {error && <p className="text-sm" style={{ color: 'var(--danger)' }}>{error}</p>}
      {!loading && !error && eleves.length === 0 && <Vide>Aucun élève en cours.</Vide>}

      <div className="space-y-3">
        {filtres.map((eleve) => <LigneEleve key={eleve.client_page_id} eleve={eleve} onOuvrir={setOuvert} />)}
      </div>
    </div>
  )
}
