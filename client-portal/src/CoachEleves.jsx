import React, { useEffect, useMemo, useState } from 'react'
import { CalendarClock, CalendarPlus, ChevronDown, ChevronLeft, ChevronRight, RefreshCw, Search } from 'lucide-react'
import { FormulaireRdv, appelAgenda, dateLongue, heureFr, nouveauRdv } from './CoachAgenda.jsx'
import { ListePoints, rdvPourPoint } from './PointsRythme.jsx'
import { CapParcours, ScoreCommercial, TuileResultat, kpiRenseignes, lireFiche, lireModule } from './App.jsx'

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
  // Espace insecable classique : l'espace fine du format francais disparait en petit corps.
  return typeof valeur === 'number' ? valeur.toLocaleString('fr-FR').replace(/\u202f/g, '\u00a0') : String(valeur)
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

function Section({ titre, action, children }) {
  return (
    <section className="coach-section">
      <div className="resultats-entete">
        <h3 className="resultats-titre">{titre}</h3>
        {action}
      </div>
      {children}
    </section>
  )
}

function Vide({ children }) {
  return <p className="espace-vide">{children}</p>
}

function maintenantLocal() {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`
}

function ProchainRdv({ rdv }) {
  if (!rdv) return null
  return (
    <p className="eleve-prochain-rdv">
      <CalendarClock size={14} aria-hidden="true" />
      {rdv.type === 'suivi' ? 'Suivi' : 'RDV'} {dateLongue(rdv.debut)}, {heureFr(rdv.debut)}
    </p>
  )
}

function inactif(eleve) {
  return eleve.jours_sans_saisie === null || eleve.jours_sans_saisie >= JOURS_INACTIF
}

// Eleve a regarder en premier : decroche ou retours d'Idris en attente.
function aSurveiller(eleve) {
  return !eleve.illisible && (inactif(eleve) || eleve.retours_ia_a_relire > 0)
}

function EtatEleve({ eleve }) {
  if (!inactif(eleve)) return <span className="coach-puce coach-puce-ok">Actif</span>
  return (
    <span className="coach-puce coach-puce-alerte">
      {eleve.jours_sans_saisie === null ? 'Aucune saisie' : `Sans activité depuis ${eleve.jours_sans_saisie} j`}
    </span>
  )
}

// Bandeau du haut, meme style que « Ton cap 90 jours » cote client.
function BandeauEleves({ eleves }) {
  const lisibles = eleves.filter((e) => !e.illisible)
  const decroches = lisibles.filter(inactif).length
  const retours = lisibles.reduce((n, e) => n + (e.retours_ia_a_relire || 0), 0)
  const fiches = lisibles.reduce((n, e) => n + (e.fiches_total || 0), 0)
  const faites = lisibles.reduce((n, e) => n + (e.fiches_terminees || 0), 0)
  const prospects = lisibles.reduce((n, e) => n + (e.nb_prospects || 0), 0)
  const signes = lisibles.reduce((n, e) => n + (e.prospects_par_statut?.Client || 0), 0)

  return (
    <section className="cap coach-bandeau">
      <div className="cap-temps">
        <p className="cap-surtitre">Tes élèves</p>
        <p className="cap-jour">{eleves.length}<small> en cours</small></p>
        <p className="cap-statut">
          {decroches > 0
            ? <span className="cap-statut-puce cap-statut-retard">{decroches} sans activité depuis {JOURS_INACTIF} jours</span>
            : <span className="cap-statut-puce cap-statut-ok">Tous actifs cette semaine</span>}
          {retours > 0 && <span>{retours} retour{retours > 1 ? 's' : ''} d'Idris à relire</span>}
        </p>
      </div>
      <div className="cap-objectif">
        <p className="cap-surtitre">En chiffres</p>
        <div className="cap-chiffres">
          <div><strong>{fiches ? Math.round((faites / fiches) * 100) : 0} %</strong><span>des fiches terminées</span></div>
          <div><strong>{prospects}</strong><span>prospects dans les carnets</span></div>
          <div><strong>{signes}</strong><span>client{signes > 1 ? 's' : ''} signé{signes > 1 ? 's' : ''}</span></div>
        </div>
      </div>
    </section>
  )
}

function CarteEleve({ eleve, rdv, onOuvrir }) {
  if (eleve.illisible) {
    return (
      <div className="eleve-carte eleve-carte-illisible">
        <p className="coach-carte-nom">{eleve.nom}</p>
        <p className="espace-vide">Données momentanément illisibles.</p>
      </div>
    )
  }
  const pourcent = eleve.fiches_total ? Math.round((eleve.fiches_terminees / eleve.fiches_total) * 100) : 0
  const clients = eleve.prospects_par_statut?.Client || 0
  return (
    <button type="button" onClick={() => onOuvrir(eleve)} className={`eleve-carte${aSurveiller(eleve) ? ' eleve-carte-alerte' : ''}`}>
      <div className="eleve-carte-haut">
        <div className="min-w-0">
          <p className="coach-carte-nom">{eleve.nom}</p>
          <p className="eleve-carte-meta">
            {[eleve.parcours, eleve.jour !== null && eleve.jour !== undefined ? `Jour ${eleve.jour} sur ${eleve.duree}` : null, eleve.etat !== 'En cours' ? eleve.etat : null]
              .filter(Boolean).join(' · ')}
          </p>
        </div>
        <EtatEleve eleve={eleve} />
      </div>

      {eleve.retours_ia_a_relire > 0 && (
        <p className="eleve-carte-retours">
          {eleve.retours_ia_a_relire} retour{eleve.retours_ia_a_relire > 1 ? 's' : ''} d'Idris à relire
        </p>
      )}

      <ProchainRdv rdv={rdv} />

      <div className="eleve-carte-progres">
        <div className="resultat-jauge"><span style={{ width: `${pourcent}%` }} /></div>
        <span><strong>{eleve.fiches_terminees}/{eleve.fiches_total}</strong> fiches</span>
      </div>

      <dl className="eleve-carte-chiffres">
        <div><dt>Dernière saisie</dt><dd>{depuis(eleve.jours_sans_saisie)}</dd></div>
        <div><dt>Connexion</dt><dd>{dateFr(eleve.derniere_connexion) || '—'}</dd></div>
        <div><dt>Prospects</dt><dd>{eleve.nb_prospects}{clients ? ` · ${clients} client${clients > 1 ? 's' : ''}` : ''}</dd></div>
      </dl>

      <span className="eleve-carte-lien">Voir son espace <ChevronRight size={15} aria-hidden="true" /></span>
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
          <div key={entree.id} className="coach-reponse">
            {entree.date && <p className="coach-reponse-date">Enregistré le {dateFr(entree.date)}</p>}
            {lignes.length === 0 && <Vide>Entrée vide.</Vide>}
            <dl className="space-y-2">
              {lignes.map(([libelle, valeur], i) => (
                <div key={i}>
                  <dt className="text-xs" style={{ color: 'var(--text-tertiary)' }}>{libelle}</dt>
                  <dd className="text-sm whitespace-pre-wrap" style={{ color: 'var(--text-primary)' }}>{valeurLisible(valeur)}</dd>
                </div>
              ))}
            </dl>
            {entree.retour_ia?.texte && (
              <div className="coach-retour-idris">
                <p className="energie-surtitre">Retour d'Idris</p>
                <p className="text-sm whitespace-pre-wrap" style={{ color: 'var(--text-primary)' }}>{entree.retour_ia.texte}</p>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// Fiches regroupees par module, comme « Mon parcours » cote client.
function FichesParModule({ fiches, clientPageId, coachKey, onAuthFailure }) {
  const [ouverte, setOuverte] = useState(null)
  const modules = []
  for (const fiche of fiches) {
    const label = fiche.module || 'Autres'
    let groupe = modules.find((m) => m.label === label)
    if (!groupe) {
      groupe = { label, fiches: [] }
      modules.push(groupe)
    }
    groupe.fiches.push(fiche)
  }

  return (
    <div className="coach-modules">
      {modules.map((module) => {
        const { surtitre, titre } = lireModule(module.label)
        const faites = module.fiches.filter((f) => f.etat === 'Terminé').length
        return (
          <div key={module.label} className="energie-carte">
            <div className="coach-module-entete">
              <div className="min-w-0">
                <p className="energie-surtitre">{surtitre}</p>
                <p className="coach-module-titre">{titre}</p>
              </div>
              <span className={`coach-puce ${faites === module.fiches.length ? 'coach-puce-ok' : 'coach-puce-neutre'}`}>
                {faites}/{module.fiches.length}
              </span>
            </div>
            <ul className="module-carte-fiches">
              {module.fiches.map((fiche) => {
                const estOuverte = ouverte === fiche.id
                const bloquee = String(fiche.acces || '').includes('Bloqué')
                const finie = fiche.etat === 'Terminé'
                const { numero, titre: titreFiche } = lireFiche(fiche.nom)
                return (
                  <li key={fiche.id}>
                    <button
                      type="button"
                      onClick={() => setOuverte(estOuverte ? null : fiche.id)}
                      disabled={bloquee}
                      className={`module-fiche${finie ? ' module-fiche-fini' : fiche.etat === 'En cours' ? ' module-fiche-actif' : ''}`}
                      aria-expanded={estOuverte}
                    >
                      <span className="module-fiche-numero">{numero ?? '•'}</span>
                      <span className="module-fiche-titre">
                        {titreFiche}
                        {fiche.priorite?.type === 'prioritaire' && <span className="coach-prioritaire"> · prioritaire</span>}
                      </span>
                      <span className="coach-fiche-etat" style={{ color: STATUT_COULEURS[fiche.etat] || 'var(--text-tertiary)' }}>
                        {bloquee ? 'Pas encore ouverte' : fiche.etat || 'Pas commencé'}
                      </span>
                    </button>
                    {estOuverte && (
                      <div className="coach-fiche-reponses">
                        <ReponsesFiche fiche={fiche} clientPageId={clientPageId} coachKey={coachKey} onAuthFailure={onAuthFailure} />
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          </div>
        )
      })}
    </div>
  )
}

function TableauKpi({ kpis }) {
  return (
    <div className="coach-tableau">
      <table>
        <thead>
          <tr>
            <th>Indicateur</th>
            {KPI_COLONNES.map(([cle, libelle]) => <th key={cle}>{libelle}</th>)}
          </tr>
        </thead>
        <tbody>
          {kpis.map((kpi) => (
            <tr key={kpi.id}>
              <td>{kpi.nom}</td>
              {KPI_COLONNES.map(([cle]) => <td key={cle}>{nombre(kpi[cle])}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function DetailEleve({ eleve, rdv, points, eleves, coachKey, onAuthFailure, onRetour, onRdv }) {
  const [etat, setEtat] = useState({ chargement: true })
  const [detailKpi, setDetailKpi] = useState(false)
  const [planifier, setPlanifier] = useState(false)
  const [message, setMessage] = useState('')

  async function charger(frais = false) {
    setEtat((e) => ({ ...e, chargement: true, erreur: '' }))
    const r = await lireCoach(`/coach/eleves/${eleve.client_page_id}${frais ? '?frais=true' : ''}`, coachKey, onAuthFailure)
    setEtat({ ...r, chargement: false })
  }

  useEffect(() => {
    charger()
    window.scrollTo(0, 0)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eleve.client_page_id])

  const d = etat.data?.dashboard
  const carnet = etat.data?.carnet
  const bilans = (etat.data?.bilans || []).slice(-8).reverse()
  const kpis = Array.isArray(d?.kpi) ? d.kpi : []
  const jour = d?.rythme ? d.rythme.jour : null
  const fichesFaites = d ? d.fiches.filter((f) => f.etat === 'Terminé').length : 0

  return (
    <div>
      <div className="coach-detail-barre">
        <button type="button" onClick={onRetour} className="coach-retour">
          <ChevronLeft size={16} aria-hidden="true" /> Tous les élèves
        </button>
        <button
          type="button"
          onClick={() => charger(true)}
          disabled={etat.chargement}
          className="coach-bouton-icone"
          aria-label="Actualiser"
          title="Actualiser"
        >
          <RefreshCw size={15} className={etat.chargement ? 'coach-tourne' : undefined} />
        </button>
      </div>

      <div className="coach-detail-entete">
        <h2 className="coach-detail-nom">{d?.nom || eleve.nom}</h2>
        <p className="eleve-carte-meta">
          {[eleve.parcours, d?.date_demarrage ? `démarré le ${dateFr(d.date_demarrage)}` : null, `connexion ${dateFr(eleve.derniere_connexion) || 'jamais'}`]
            .filter(Boolean).join(' · ')}
        </p>
        <p className="coach-intro">Ce que l'élève voit dans son espace, lu à la même source.</p>
        <div className="coach-detail-actions">
          <ProchainRdv rdv={rdv} />
          {onRdv && (
            <button type="button" className="resultats-bouton" onClick={() => setPlanifier(nouveauRdv({ eleve }))}>
              <CalendarPlus size={15} aria-hidden="true" /> Planifier un RDV
            </button>
          )}
        </div>
        {message && <p className="agenda-message" role="status">{message}</p>}
      </div>

      {planifier && (
        <FormulaireRdv
          initial={planifier}
          eleves={eleves}
          coachKey={coachKey}
          onAuthFailure={onAuthFailure}
          onFerme={() => setPlanifier(false)}
          onEnregistre={(evt) => {
            setPlanifier(false)
            if (evt) {
              setMessage('Ajouté à votre Google Agenda.')
              onRdv(evt)
            }
          }}
        />
      )}

      {points && (
        <Section titre="Ses points">
          <ListePoints
            coach
            points={points.points}
            onPlanifier={onRdv ? (p) => setPlanifier(rdvPourPoint(p, { ...eleve, parcours: points.parcours })) : null}
          />
        </Section>
      )}

      {etat.chargement && !d && <Vide>Chargement...</Vide>}
      {etat.erreur && <p className="text-sm" style={{ color: 'var(--danger)' }}>{etat.erreur}</p>}

      {d && (
        <>
          <CapParcours
            coach
            rythme={d.rythme}
            objectif={d.objectif_90j}
            fichesFaites={fichesFaites}
            fichesTotal={d.fiches.length}
            regularite={d.regularite}
          />

          <Section titre="Son suivi">
            <div className="energie-grille">
              <div className="energie-carte">
                <p className="energie-surtitre">Activité et relances</p>
                <dl className="coach-stats">
                  <div><dt>Dernière saisie</dt><dd className={inactif(eleve) ? 'coach-stat-alerte' : undefined}>{depuis(eleve.jours_sans_saisie)}</dd></div>
                  <div><dt>Fiches en retard</dt><dd className={d.rythme?.en_retard ? 'coach-stat-alerte' : undefined}>{d.rythme?.en_retard ?? '—'}</dd></div>
                  <div><dt>Bilans d'affilée</dt><dd>{d.regularite?.serie ?? '—'}</dd></div>
                  <div><dt>Relances envoyées</dt><dd>{eleve.nb_relances ?? 0}</dd></div>
                  <div><dt>Dernière relance</dt><dd>{dateFr(eleve.derniere_relance) || '—'}</dd></div>
                  <div><dt>Retours d'Idris à relire</dt><dd className={eleve.retours_ia_a_relire ? 'coach-stat-attente' : undefined}>{eleve.retours_ia_a_relire ?? 0}</dd></div>
                </dl>
              </div>
              <div className="energie-carte">
                <p className="energie-surtitre">Priorités du diagnostic</p>
                {d.personnalisation?.zones_prioritaires?.length > 0 ? (
                  <ul className="coach-zones">
                    {d.personnalisation.zones_prioritaires.map((z, i) => (
                      <li key={z.zone}>
                        <span className="coach-zone-rang">{i + 1}</span>
                        <span>
                          <strong>{z.zone}</strong>
                          {z.score !== undefined && z.score !== null && <small> · {z.score}/3</small>}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : <Vide>Pas encore de diagnostic validé.</Vide>}
              </div>
            </div>
          </Section>

          <Section
            titre="Ses résultats"
            action={kpis.length > 0 && kpiRenseignes(kpis) && (
              <button type="button" className="resultats-bouton" aria-expanded={detailKpi} onClick={() => setDetailKpi((v) => !v)}>
                {detailKpi ? 'Masquer le détail' : 'Détail J0 à J90'}
                <ChevronDown size={15} aria-hidden="true" className={detailKpi ? 'resultats-chevron-ouvert' : undefined} />
              </button>
            )}
          >
            {kpis.length > 0 && kpiRenseignes(kpis) ? (
              <div className="resultats-grille">
                {kpis.map((kpi) => <TuileResultat key={kpi.id} kpi={kpi} jour={jour} />)}
              </div>
            ) : <Vide>Aucun indicateur saisi.</Vide>}
            {detailKpi && <TableauKpi kpis={kpis} />}
            <ScoreCommercial coach personnalisation={d.personnalisation} />
          </Section>

          <Section titre="Ses fiches">
            <FichesParModule fiches={d.fiches} clientPageId={eleve.client_page_id} coachKey={coachKey} onAuthFailure={onAuthFailure} />
          </Section>

          <div className="energie-grille coach-section">
            <div className="energie-carte">
              <p className="energie-surtitre">Bilans de la semaine</p>
              {bilans.length ? (
                <div className="coach-tableau">
                  <table>
                    <thead>
                      <tr>
                        <th>Semaine du</th>
                        <th>Contacts</th>
                        <th>RDV</th>
                        <th>Propos.</th>
                        <th>Ventes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {bilans.map((b) => (
                        <tr key={b.semaine_du}>
                          <td>{dateFr(b.semaine_du)}</td>
                          <td>{nombre(b.contacts)}</td>
                          <td>{nombre(b.rdv)}</td>
                          <td>{nombre(b.propositions)}</td>
                          <td>{nombre(b.ventes)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <Vide>Aucun bilan enregistré.</Vide>}
            </div>

            <div className="energie-carte">
              <p className="energie-surtitre">Carnet de prospects</p>
              {carnet?.prospects?.length ? (
                <>
                  <div className="coach-statuts">
                    {carnet.statuts.map((s) => (
                      <span key={s} className="coach-puce coach-puce-neutre">{s} <strong>{carnet.par_statut[s] || 0}</strong></span>
                    ))}
                    {carnet.a_relancer?.length > 0 && (
                      <span className="coach-puce coach-puce-attente">À relancer <strong>{carnet.a_relancer.length}</strong></span>
                    )}
                  </div>
                  <ul className="coach-prospects">
                    {carnet.prospects.slice(0, 30).map((p) => (
                      <li key={p.id}>
                        <span>{p.nom}</span>
                        <small>{p.statut}{p.relance ? ` · relance ${dateFr(p.relance)}` : ''}</small>
                      </li>
                    ))}
                  </ul>
                </>
              ) : <Vide>Carnet vide.</Vide>}
            </div>
          </div>

          {d.syntheses?.length > 0 && (
            <Section titre="Synthèses mensuelles envoyées">
              <div className="space-y-3">
                {d.syntheses.map((s) => (
                  <div key={s.mois} className="energie-carte">
                    <p className="energie-surtitre">Mois {s.mois}{s.date ? ` · ${dateFr(s.date)}` : ''}</p>
                    <p className="text-sm whitespace-pre-wrap" style={{ color: 'var(--text-primary)' }}>{s.texte}</p>
                  </div>
                ))}
              </div>
            </Section>
          )}
        </>
      )}
    </div>
  )
}

export default function CoachEleves({ coachKey, onAuthFailure, onDetail }) {
  const [eleves, setEleves] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [ouvert, setOuvert] = useState(null)
  // Prochain RDV de chaque eleve, lu dans l'agenda (absent si non branche).
  const [prochains, setProchains] = useState({})
  const [agendaBranche, setAgendaBranche] = useState(false)
  // Points suggeres par eleve (rythme des points), lus avec l'agenda.
  const [points, setPoints] = useState({})

  async function chargerPoints() {
    const r = await appelAgenda('/coach/points', coachKey, () => {})
    if (Array.isArray(r.data?.eleves)) setPoints(Object.fromEntries(r.data.eleves.map((e) => [e.client_page_id, e])))
  }

  async function chargerProchains() {
    const r = await appelAgenda(`/coach/agenda/prochains?depuis=${encodeURIComponent(maintenantLocal())}`, coachKey, () => {})
    if (r.data) {
      setAgendaBranche(Boolean(r.data.configure))
      setProchains(r.data.prochains || {})
      if (r.data.configure) chargerPoints()
    }
  }

  async function charger() {
    chargerProchains()
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

  // Les eleves a surveiller passent en tete, l'ordre du serveur est garde sinon.
  const filtres = useMemo(() => {
    const q = query.trim().toLocaleLowerCase('fr-FR')
    const liste = eleves.filter((e) => !q || (e.nom || '').toLocaleLowerCase('fr-FR').includes(q))
    return [...liste.filter(aSurveiller), ...liste.filter((e) => !aSurveiller(e))]
  }, [eleves, query])

  useEffect(() => {
    onDetail?.(Boolean(ouvert))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ouvert])

  if (ouvert) {
    return (
      <DetailEleve
        eleve={ouvert}
        rdv={prochains[ouvert.client_page_id]}
        points={points[ouvert.client_page_id]}
        eleves={eleves}
        coachKey={coachKey}
        onAuthFailure={onAuthFailure}
        onRetour={() => setOuvert(null)}
        onRdv={agendaBranche ? () => chargerProchains() : null}
      />
    )
  }

  return (
    <div>
      {eleves.length > 0 && <BandeauEleves eleves={eleves} />}

      <div className="coach-recherche">
        <div className="field-input coach-recherche-champ">
          <Search size={15} color="var(--text-tertiary)" aria-hidden="true" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Rechercher un élève..."
            className="flex-1 bg-transparent outline-none text-sm"
          />
        </div>
        <button
          type="button"
          onClick={charger}
          disabled={loading}
          className="coach-bouton-icone"
          aria-label="Actualiser"
          title="Actualiser"
        >
          <RefreshCw size={15} className={loading ? 'coach-tourne' : undefined} />
        </button>
      </div>

      {loading && <Vide>Chargement...</Vide>}
      {error && <p className="text-sm" style={{ color: 'var(--danger)' }}>{error}</p>}
      {!loading && !error && eleves.length === 0 && <Vide>Aucun élève en cours.</Vide>}

      <div className="eleves-grille">
        {filtres.map((eleve) => <CarteEleve key={eleve.client_page_id} eleve={eleve} rdv={prochains[eleve.client_page_id]} onOuvrir={setOuvert} />)}
      </div>
    </div>
  )
}
