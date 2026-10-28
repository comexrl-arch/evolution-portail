import React, { useEffect, useMemo, useState } from 'react'
import { CalendarPlus, ChevronLeft, ChevronRight, ExternalLink, RefreshCw, Trash2, X } from 'lucide-react'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8013'

// Messages fixes : aucun detail technique n'est affiche.
const MESSAGE_SERVICE_INDISPONIBLE = 'Agenda momentanément indisponible. Réessayez dans quelques minutes.'
const MESSAGE_CONNEXION = 'Connexion impossible. Vérifiez le réseau et réessayez.'

// Grille de la semaine : de 7 h à 21 h, une ligne par demi-heure.
const HEURE_DEBUT = 7
const HEURE_FIN = 21
const HAUTEUR_HEURE = 52

const JOURS_COURTS = ['lun.', 'mar.', 'mer.', 'jeu.', 'ven.', 'sam.', 'dim.']
const MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre']

export const TYPES_RDV = [
  ['rdv', 'RDV coaching'],
  ['suivi', 'Étape de suivi'],
  ['autre', 'Autre'],
]

const DUREES = [15, 30, 45, 60, 90, 120]

// --- Dates locales en texte ("2026-10-30", "2026-10-30T10:00") : les heures
// viennent du serveur deja dans le fuseau de l'agenda, on ne les convertit pas.

function pad(n) {
  return String(n).padStart(2, '0')
}

function jourIso(d) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

// Midi : aucun changement d'heure ne fait sauter de jour.
function versDate(iso) {
  const [a, m, j] = iso.slice(0, 10).split('-').map(Number)
  return new Date(a, m - 1, j, 12)
}

function ajouterJours(iso, n) {
  const d = versDate(iso)
  d.setDate(d.getDate() + n)
  return jourIso(d)
}

function lundi(iso) {
  const d = versDate(iso)
  return ajouterJours(iso, -((d.getDay() + 6) % 7))
}

export function aujourdhui() {
  return jourIso(new Date())
}

function maintenantLocal() {
  const d = new Date()
  return `${jourIso(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function minutes(dateHeure) {
  const [h, m] = dateHeure.slice(11, 16).split(':').map(Number)
  return h * 60 + m
}

function heureDe(min) {
  return `${pad(Math.floor(min / 60))}:${pad(min % 60)}`
}

function decaler(dateHeure, deltaMin) {
  const [jour, heure] = dateHeure.split('T')
  let total = minutes(`${jour}T${heure}`) + deltaMin
  let j = jour
  while (total >= 1440) { total -= 1440; j = ajouterJours(j, 1) }
  while (total < 0) { total += 1440; j = ajouterJours(j, -1) }
  return `${j}T${heureDe(total)}`
}

function duree(evt) {
  if (evt.journee) return 0
  const jours = Math.round((versDate(evt.fin) - versDate(evt.debut)) / 86400000)
  return jours * 1440 + minutes(evt.fin) - minutes(evt.debut)
}

// "09:30" -> "9 h 30", "14:00" -> "14 h".
export function heureFr(dateHeure) {
  const [h, m] = dateHeure.slice(11, 16).split(':')
  return `${Number(h)} h${m === '00' ? '' : ` ${m}`}`
}

export function dateLongue(iso) {
  const d = versDate(iso)
  return `${['dimanche', 'lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi'][d.getDay()]} ${d.getDate()} ${MOIS[d.getMonth()]}`
}

export function libelleCreneau(evt) {
  if (evt.journee) return `${dateLongue(evt.debut)}, toute la journée`
  return `${dateLongue(evt.debut)}, ${heureFr(evt.debut)} à ${heureFr(evt.fin)}`
}

function periode(vue, ancre) {
  if (vue === 'mois') {
    const premier = `${ancre.slice(0, 8)}01`
    const debut = lundi(premier)
    return { debut, fin: ajouterJours(debut, 42) }
  }
  const debut = lundi(ancre)
  return { debut, fin: ajouterJours(debut, 7) }
}

function titrePeriode(vue, ancre, debut) {
  if (vue === 'mois') {
    const d = versDate(ancre)
    return `${MOIS[d.getMonth()]} ${d.getFullYear()}`
  }
  const a = versDate(debut)
  const b = versDate(ajouterJours(debut, 6))
  return a.getMonth() === b.getMonth()
    ? `${a.getDate()} au ${b.getDate()} ${MOIS[b.getMonth()]} ${b.getFullYear()}`
    : `${a.getDate()} ${MOIS[a.getMonth()]} au ${b.getDate()} ${MOIS[b.getMonth()]} ${b.getFullYear()}`
}

// --- API -------------------------------------------------------------------

export async function appelAgenda(chemin, coachKey, onAuthFailure, options = {}) {
  let res
  try {
    res = await fetch(`${API_BASE}${chemin}`, {
      ...options,
      headers: { 'X-Coach-Key': coachKey, ...(options.body ? { 'Content-Type': 'application/json' } : {}) },
    })
  } catch {
    return { erreur: MESSAGE_CONNEXION }
  }
  if (res.status === 401) {
    onAuthFailure()
    return { erreur: '' }
  }
  let data = null
  try {
    data = await res.json()
  } catch {
    data = null
  }
  // 403 et 422 portent une phrase fixe du serveur, sure a afficher.
  if (res.status === 403 || res.status === 422 || res.status === 404) {
    return { erreur: typeof data?.detail === 'string' ? data.detail : MESSAGE_SERVICE_INDISPONIBLE }
  }
  if (!res.ok || !data) return { erreur: MESSAGE_SERVICE_INDISPONIBLE }
  return { data }
}

// --- Formulaire de RDV (aussi ouvert depuis la fiche d'un eleve) -------------

export function nouveauRdv({ jour, heure = '10:00', eleve = null, type = 'rdv' } = {}) {
  return {
    mode: 'creer',
    type,
    eleve_id: eleve?.client_page_id || '',
    eleve_nom: eleve?.nom || '',
    titre: '',
    date: jour || aujourdhui(),
    heure,
    duree: type === 'suivi' ? 30 : 60,
    lieu: '',
    description: '',
  }
}

// Meme regle que agenda_service.titre_evenement cote serveur.
function titreAutomatique(type, eleveNom) {
  const libelle = { rdv: 'RDV coaching', suivi: 'Suivi' }[type] || 'Rendez-vous'
  return eleveNom ? `${libelle} · ${eleveNom}` : libelle
}

function depuisEvenement(evt) {
  return {
    mode: evt.portail ? 'modifier' : 'lire',
    id: evt.id,
    evt,
    type: evt.type || 'rdv',
    eleve_id: evt.eleve_id || '',
    eleve_nom: evt.eleve_nom || '',
    titre: evt.titre,
    titreAuto: evt.titre === titreAutomatique(evt.type, evt.eleve_nom),
    date: evt.debut.slice(0, 10),
    heure: evt.journee ? '10:00' : evt.debut.slice(11, 16),
    duree: duree(evt) || 60,
    lieu: evt.lieu || '',
    description: evt.description || '',
  }
}

export function FormulaireRdv({ initial, eleves, coachKey, onAuthFailure, onFerme, onEnregistre }) {
  const [f, setF] = useState(initial)
  const [attente, setAttente] = useState(false)
  const [erreur, setErreur] = useState('')
  const lecture = f.mode === 'lire'

  const changer = (cle, valeur) => setF((x) => ({ ...x, [cle]: valeur }))

  async function enregistrer(e) {
    e.preventDefault()
    setAttente(true)
    setErreur('')
    const debut = `${f.date}T${f.heure}`
    const corps = {
      type: f.type,
      eleve_id: f.eleve_id || null,
      eleve_nom: f.eleve_nom || null,
      // Titre laisse vide (ou titre automatique d'origine) : le serveur le refait.
      titre: f.titre && !(f.mode === 'modifier' && f.titreAuto && f.titre === initial.titre) ? f.titre : null,
      description: f.description,
      lieu: f.lieu,
      debut,
      fin: decaler(debut, Number(f.duree)),
    }
    const r = f.mode === 'creer'
      ? await appelAgenda('/coach/agenda', coachKey, onAuthFailure, { method: 'POST', body: JSON.stringify(corps) })
      : await appelAgenda(`/coach/agenda/${encodeURIComponent(f.id)}`, coachKey, onAuthFailure, { method: 'PATCH', body: JSON.stringify(corps) })
    setAttente(false)
    if (r.erreur !== undefined) return setErreur(r.erreur)
    onEnregistre(r.data)
  }

  async function supprimer() {
    setAttente(true)
    setErreur('')
    const r = await appelAgenda(`/coach/agenda/${encodeURIComponent(f.id)}`, coachKey, onAuthFailure, { method: 'DELETE' })
    setAttente(false)
    if (r.erreur !== undefined) return setErreur(r.erreur)
    onEnregistre(null)
  }

  return (
    <div className="agenda-voile" onClick={onFerme}>
      <form className="agenda-panneau" onClick={(e) => e.stopPropagation()} onSubmit={enregistrer}>
        <div className="agenda-panneau-entete">
          <div>
            <p className="energie-surtitre">{f.mode === 'creer' ? 'Nouveau rendez-vous' : lecture ? 'Dans votre agenda' : 'Rendez-vous'}</p>
            <h3 className="coach-module-titre">{lecture ? f.titre : f.eleve_nom || (f.mode === 'creer' ? 'Planifier' : f.titre)}</h3>
          </div>
          <button type="button" className="coach-bouton-icone" onClick={onFerme} aria-label="Fermer"><X size={16} /></button>
        </div>

        {lecture ? (
          <>
            <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>{libelleCreneau(f.evt)}</p>
            {f.lieu && <p className="text-sm mt-1" style={{ color: 'var(--text-secondary)' }}>{f.lieu}</p>}
            <p className="coach-intro" style={{ margin: '0.9rem 0 0' }}>
              Événement personnel ou créé hors de l'Espace Coach : il se modifie dans Google Agenda.
            </p>
          </>
        ) : (
          <div className="agenda-champs">
            <div className="agenda-types" role="radiogroup" aria-label="Type">
              {TYPES_RDV.map(([cle, libelle]) => (
                <button
                  key={cle}
                  type="button"
                  role="radio"
                  aria-checked={f.type === cle}
                  className={`agenda-type${f.type === cle ? ' agenda-type-actif' : ''} agenda-type-${cle}`}
                  onClick={() => changer('type', cle)}
                >
                  {libelle}
                </button>
              ))}
            </div>

            <label className="agenda-champ">
              <span>Élève</span>
              <select
                className="field-input"
                value={f.eleve_id}
                onChange={(e) => {
                  const eleve = eleves.find((x) => x.client_page_id === e.target.value)
                  setF((x) => ({ ...x, eleve_id: eleve?.client_page_id || '', eleve_nom: eleve?.nom || '' }))
                }}
              >
                <option value="">Aucun élève</option>
                {f.eleve_id && !eleves.some((x) => x.client_page_id === f.eleve_id) && <option value={f.eleve_id}>{f.eleve_nom}</option>}
                {eleves.filter((x) => !x.illisible).map((x) => <option key={x.client_page_id} value={x.client_page_id}>{x.nom}</option>)}
              </select>
            </label>

            <label className="agenda-champ">
              <span>Titre</span>
              <input
                className="field-input"
                value={f.titre}
                onChange={(e) => changer('titre', e.target.value)}
                placeholder={titreAutomatique(f.type, f.eleve_nom)}
              />
            </label>

            <div className="agenda-ligne">
              <label className="agenda-champ">
                <span>Date</span>
                <input type="date" required className="field-input" value={f.date} onChange={(e) => changer('date', e.target.value)} />
              </label>
              <label className="agenda-champ">
                <span>Heure</span>
                <input type="time" required step="900" className="field-input" value={f.heure} onChange={(e) => changer('heure', e.target.value)} />
              </label>
              <label className="agenda-champ">
                <span>Durée</span>
                <select className="field-input" value={f.duree} onChange={(e) => changer('duree', Number(e.target.value))}>
                  {[...new Set([...DUREES, Number(f.duree)])].sort((a, b) => a - b).map((d) => (
                    <option key={d} value={d}>{d < 60 ? `${d} min` : `${Math.floor(d / 60)} h${d % 60 ? ` ${d % 60}` : ''}`}</option>
                  ))}
                </select>
              </label>
            </div>

            <label className="agenda-champ">
              <span>Lieu ou lien visio</span>
              <input className="field-input" value={f.lieu} onChange={(e) => changer('lieu', e.target.value)} placeholder="Téléphone, Google Meet, bureau..." />
            </label>

            <label className="agenda-champ">
              <span>Notes</span>
              <textarea className="field-input" rows={3} value={f.description} onChange={(e) => changer('description', e.target.value)} placeholder="Ce qu'on prépare, la fiche à revoir..." />
            </label>
          </div>
        )}

        {erreur && <p className="text-sm mt-3" style={{ color: 'var(--danger)' }}>{erreur}</p>}

        <div className="agenda-actions">
          {!lecture && (
            <button type="submit" className="fiche-bouton" disabled={attente}>
              {attente ? 'Enregistrement...' : f.mode === 'creer' ? 'Ajouter à mon agenda' : 'Enregistrer'}
            </button>
          )}
          {f.mode === 'modifier' && (
            <button type="button" className="agenda-supprimer" onClick={supprimer} disabled={attente}>
              <Trash2 size={15} aria-hidden="true" /> Supprimer
            </button>
          )}
          {f.evt?.lien && (
            <a className="agenda-lien" href={f.evt.lien} target="_blank" rel="noreferrer">
              Ouvrir dans Google Agenda <ExternalLink size={14} aria-hidden="true" />
            </a>
          )}
        </div>
      </form>
    </div>
  )
}

// --- Vues ---------------------------------------------------------------------

function classeEvenement(evt) {
  if (!evt.portail) return 'agenda-evt agenda-evt-perso'
  return `agenda-evt agenda-evt-${evt.type || 'autre'}`
}

// Evenements qui se chevauchent : places cote a cote dans la colonne du jour.
function placer(evenements) {
  const tries = [...evenements].sort((a, b) => a.debut.localeCompare(b.debut) || duree(b) - duree(a))
  const colonnes = []
  const groupes = []
  let groupe = []
  let finGroupe = ''
  for (const evt of tries) {
    if (groupe.length && evt.debut >= finGroupe) {
      groupes.push(groupe)
      groupe = []
      colonnes.length = 0
    }
    let col = colonnes.findIndex((fin) => fin <= evt.debut)
    if (col === -1) {
      col = colonnes.length
      colonnes.push(evt.fin)
    } else {
      colonnes[col] = evt.fin
    }
    groupe.push({ evt, col })
    finGroupe = groupe.length === 1 ? evt.fin : (evt.fin > finGroupe ? evt.fin : finGroupe)
  }
  if (groupe.length) groupes.push(groupe)
  return groupes.flatMap((g) => {
    const largeur = Math.max(...g.map((x) => x.col)) + 1
    return g.map((x) => ({ ...x, largeur }))
  })
}

function VueSemaine({ debut, evenements, onCreneau, onOuvrir, onDeposer }) {
  const jours = Array.from({ length: 7 }, (_, i) => ajouterJours(debut, i))
  const today = aujourdhui()
  const heures = Array.from({ length: HEURE_FIN - HEURE_DEBUT }, (_, i) => HEURE_DEBUT + i)
  const journee = evenements.filter((e) => e.journee)
  const now = maintenantLocal()

  return (
    <div className="agenda-semaine">
      <div className="agenda-semaine-entete">
        <span />
        {jours.map((j, i) => (
          <div key={j} className={`agenda-jour-titre${j === today ? ' agenda-aujourdhui' : ''}`}>
            <span>{JOURS_COURTS[i]}</span>
            <strong>{versDate(j).getDate()}</strong>
          </div>
        ))}
      </div>
      {journee.length > 0 && (
        <div className="agenda-journee">
          <span className="agenda-heure">journée</span>
          {jours.map((j) => (
            <div key={j}>
              {journee.filter((e) => e.debut <= j && (e.fin > j || e.fin === e.debut)).map((e) => (
                <button key={e.id} type="button" className={classeEvenement(e)} onClick={() => onOuvrir(e)}>{e.titre}</button>
              ))}
            </div>
          ))}
        </div>
      )}
      <div className="agenda-grille" style={{ height: heures.length * HAUTEUR_HEURE }}>
        <div className="agenda-heures">
          {heures.map((h) => <span key={h} className="agenda-heure" style={{ top: (h - HEURE_DEBUT) * HAUTEUR_HEURE }}>{h} h</span>)}
        </div>
        {jours.map((j) => {
          const duJour = evenements.filter((e) => !e.journee && e.debut.slice(0, 10) === j)
          return (
            <div key={j} className={`agenda-colonne${j === today ? ' agenda-colonne-aujourdhui' : ''}`}>
              {heures.flatMap((h) => [0, 30].map((m) => {
                const heure = `${pad(h)}:${pad(m)}`
                return (
                  <div
                    key={heure}
                    className="agenda-creneau"
                    onClick={() => onCreneau(j, heure)}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={(e) => { e.preventDefault(); onDeposer(e.dataTransfer.getData('text/plain'), j, heure) }}
                    title={`${dateLongue(j)}, ${heure.replace(':', ' h ')}`}
                  />
                )
              }))}
              {j === today && now.slice(0, 10) === j && minutes(now) >= HEURE_DEBUT * 60 && minutes(now) < HEURE_FIN * 60 && (
                <span className="agenda-maintenant" style={{ top: ((minutes(now) - HEURE_DEBUT * 60) / 60) * HAUTEUR_HEURE }} />
              )}
              {placer(duJour).map(({ evt, col, largeur }) => {
                const haut = Math.max(0, minutes(evt.debut) - HEURE_DEBUT * 60)
                const bas = Math.min((HEURE_FIN - HEURE_DEBUT) * 60, evt.fin.slice(0, 10) > j ? 1440 : minutes(evt.fin) - HEURE_DEBUT * 60)
                if (bas <= 0 || haut >= (HEURE_FIN - HEURE_DEBUT) * 60) return null
                const court = bas - haut < 45
                return (
                  <button
                    key={evt.id}
                    type="button"
                    className={`${classeEvenement(evt)}${court ? ' agenda-evt-court' : ''}`}
                    draggable={evt.portail}
                    onDragStart={(e) => e.dataTransfer.setData('text/plain', evt.id)}
                    onClick={(e) => { e.stopPropagation(); onOuvrir(evt) }}
                    style={{
                      top: (haut / 60) * HAUTEUR_HEURE,
                      height: Math.max(((bas - haut) / 60) * HAUTEUR_HEURE - 2, 20),
                      left: `calc(${(col / largeur) * 100}% + 2px)`,
                      width: `calc(${100 / largeur}% - 4px)`,
                    }}
                  >
                    <strong>{heureFr(evt.debut)}</strong> {evt.titre}
                  </button>
                )
              })}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function VueMois({ debut, ancre, evenements, onJour, onOuvrir, onDeposer }) {
  const jours = Array.from({ length: 42 }, (_, i) => ajouterJours(debut, i))
  const mois = ancre.slice(0, 7)
  const today = aujourdhui()
  return (
    <div className="agenda-mois">
      {JOURS_COURTS.map((j) => <span key={j} className="agenda-mois-jour">{j}</span>)}
      {jours.map((j) => {
        const duJour = evenements.filter((e) => (e.journee ? e.debut <= j && e.fin > j : e.debut.slice(0, 10) === j))
        return (
          <div
            key={j}
            className={`agenda-case${j.slice(0, 7) !== mois ? ' agenda-case-hors' : ''}${j === today ? ' agenda-aujourdhui' : ''}`}
            onClick={() => onJour(j)}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); onDeposer(e.dataTransfer.getData('text/plain'), j, null) }}
          >
            <strong>{versDate(j).getDate()}</strong>
            {duJour.slice(0, 3).map((evt) => (
              <button
                key={evt.id}
                type="button"
                className={classeEvenement(evt)}
                draggable={evt.portail}
                onDragStart={(e) => e.dataTransfer.setData('text/plain', evt.id)}
                onClick={(e) => { e.stopPropagation(); onOuvrir(evt) }}
              >
                {!evt.journee && <b>{evt.debut.slice(11, 16)}</b>} {evt.titre}
              </button>
            ))}
            {duJour.length > 3 && <span className="agenda-plus">+{duJour.length - 3}</span>}
          </div>
        )
      })}
    </div>
  )
}

// Telephone : la semaine en liste, jour par jour.
function VueListe({ debut, evenements, onJour, onOuvrir }) {
  const jours = Array.from({ length: 7 }, (_, i) => ajouterJours(debut, i))
  const today = aujourdhui()
  return (
    <div className="agenda-liste">
      {jours.map((j) => {
        const duJour = evenements.filter((e) => (e.journee ? e.debut <= j && e.fin > j : e.debut.slice(0, 10) === j))
        return (
          <section key={j} className={`agenda-liste-jour${j === today ? ' agenda-aujourdhui' : ''}`}>
            <header>
              <strong>{dateLongue(j)}</strong>
              <button type="button" className="agenda-ajout-jour" onClick={() => onJour(j)} aria-label={`Ajouter un rendez-vous le ${dateLongue(j)}`}>
                <CalendarPlus size={16} />
              </button>
            </header>
            {duJour.length === 0 ? <p className="espace-vide">Rien de prévu.</p> : duJour.map((evt) => (
              <button key={evt.id} type="button" className={`${classeEvenement(evt)} agenda-liste-evt`} onClick={() => onOuvrir(evt)}>
                <span className="agenda-liste-heure">{evt.journee ? 'Journée' : `${evt.debut.slice(11, 16)} à ${evt.fin.slice(11, 16)}`}</span>
                <span>{evt.titre}</span>
              </button>
            ))}
          </section>
        )
      })}
    </div>
  )
}

function useEstMobile() {
  const requete = '(max-width: 640px)'
  const [mobile, setMobile] = useState(() => window.matchMedia?.(requete).matches || false)
  useEffect(() => {
    const mq = window.matchMedia?.(requete)
    if (!mq) return undefined
    const suivre = () => setMobile(mq.matches)
    mq.addEventListener('change', suivre)
    return () => mq.removeEventListener('change', suivre)
  }, [])
  return mobile
}

function AgendaNonBranche({ compte }) {
  return (
    <div className="energie-carte coach-colonne">
      <p className="energie-surtitre">Agenda à brancher</p>
      <p className="coach-module-titre" style={{ marginBottom: '0.6rem' }}>Un réglage et votre Google Agenda s'affiche ici.</p>
      <ol className="agenda-etapes">
        {compte ? (
          <li>
            Dans Google Agenda, ouvrez <strong>Paramètres de mon agenda</strong>, puis <strong>Partager avec des personnes</strong>.
            Ajoutez <code>{compte}</code> avec le droit <strong>Apporter des modifications aux événements</strong>.
          </li>
        ) : (
          <li>Donnez au portail l'accès à votre Google Agenda (même accès Google que le cockpit).</li>
        )}
        <li>Sur Render, ajoutez la variable <code>GOOGLE_CALENDAR_ID</code> avec l'adresse Gmail de votre agenda.</li>
        <li>Rechargez cette page.</li>
      </ol>
    </div>
  )
}

export default function CoachAgenda({ coachKey, onAuthFailure }) {
  const mobile = useEstMobile()
  const [vue, setVue] = useState('semaine')
  const [ancre, setAncre] = useState(aujourdhui)
  const [etat, setEtat] = useState({ chargement: true, evenements: [] })
  const [eleves, setEleves] = useState([])
  const [formulaire, setFormulaire] = useState(null)
  const [message, setMessage] = useState('')

  const { debut, fin } = periode(vue, ancre)

  async function charger() {
    setEtat((e) => ({ ...e, chargement: true, erreur: '' }))
    const r = await appelAgenda(`/coach/agenda?debut=${debut}&fin=${fin}`, coachKey, onAuthFailure)
    if (r.erreur !== undefined) return setEtat((e) => ({ ...e, chargement: false, erreur: r.erreur }))
    setEtat({ chargement: false, configure: r.data.configure, compte: r.data.compte_de_service, evenements: r.data.evenements || [] })
  }

  useEffect(() => {
    charger()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debut, fin])

  useEffect(() => {
    appelAgenda('/coach/eleves', coachKey, onAuthFailure).then((r) => {
      if (Array.isArray(r.data?.eleves)) setEleves(r.data.eleves)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const evenements = useMemo(() => [...etat.evenements].sort((a, b) => a.debut.localeCompare(b.debut)), [etat.evenements])
  const parId = useMemo(() => new Map(evenements.map((e) => [e.id, e])), [evenements])

  function naviguer(sens) {
    if (sens === 0) return setAncre(aujourdhui())
    if (vue === 'mois') {
      const d = versDate(ancre)
      d.setDate(1)
      d.setMonth(d.getMonth() + sens)
      return setAncre(jourIso(d))
    }
    setAncre(ajouterJours(ancre, 7 * sens))
  }

  // Glisser-deposer : on garde la duree, on change le jour (et l'heure en semaine).
  async function deposer(id, jour, heure) {
    const evt = parId.get(id)
    if (!evt || !evt.portail) return
    const nouveauDebut = `${jour}T${heure || evt.debut.slice(11, 16)}`
    if (nouveauDebut === evt.debut) return
    const nouvelleFin = decaler(nouveauDebut, duree(evt))
    // Affichage immediat, puis confirmation par Google.
    setEtat((e) => ({ ...e, evenements: e.evenements.map((x) => (x.id === id ? { ...x, debut: nouveauDebut, fin: nouvelleFin } : x)) }))
    const r = await appelAgenda(`/coach/agenda/${encodeURIComponent(id)}`, coachKey, onAuthFailure, {
      method: 'PATCH',
      body: JSON.stringify({ debut: nouveauDebut, fin: nouvelleFin }),
    })
    if (r.erreur !== undefined) {
      setMessage(r.erreur || MESSAGE_SERVICE_INDISPONIBLE)
      return charger()
    }
    setMessage(`Déplacé au ${libelleCreneau(r.data)}.`)
  }

  const prochains = evenements
    .filter((e) => e.portail && !e.journee && e.debut >= maintenantLocal())
    .slice(0, 4)

  return (
    <div>
      <div className="agenda-barre">
        <div className="agenda-nav">
          <button type="button" className="coach-bouton-icone" onClick={() => naviguer(-1)} aria-label="Période précédente"><ChevronLeft size={16} /></button>
          <button type="button" className="agenda-aujourdhui-bouton" onClick={() => naviguer(0)}>Aujourd'hui</button>
          <button type="button" className="coach-bouton-icone" onClick={() => naviguer(1)} aria-label="Période suivante"><ChevronRight size={16} /></button>
          <h3 className="agenda-periode">{titrePeriode(vue, ancre, debut)}</h3>
        </div>
        <div className="agenda-nav">
          <div className="agenda-vues" role="tablist">
            {[['semaine', 'Semaine'], ['mois', 'Mois']].map(([cle, libelle]) => (
              <button key={cle} type="button" role="tab" aria-selected={vue === cle} className={vue === cle ? 'agenda-vue-active' : undefined} onClick={() => setVue(cle)}>
                {libelle}
              </button>
            ))}
          </div>
          <button type="button" className="coach-bouton-icone" onClick={charger} disabled={etat.chargement} aria-label="Actualiser" title="Actualiser">
            <RefreshCw size={15} className={etat.chargement ? 'coach-tourne' : undefined} />
          </button>
          {etat.configure && (
            <button type="button" className="fiche-bouton agenda-nouveau" onClick={() => setFormulaire(nouveauRdv({ jour: ancre >= debut && ancre < fin ? ancre : debut }))}>
              <CalendarPlus size={16} aria-hidden="true" /> Nouveau RDV
            </button>
          )}
        </div>
      </div>

      {etat.erreur && <p className="text-sm mb-3" style={{ color: 'var(--danger)' }}>{etat.erreur}</p>}
      {message && <p className="agenda-message" role="status">{message}</p>}

      {etat.configure === false && <AgendaNonBranche compte={etat.compte} />}

      {etat.configure && (
        <>
          {prochains.length > 0 && (
            <div className="agenda-prochains">
              <p className="energie-surtitre">À venir avec vos élèves</p>
              <div>
                {prochains.map((e) => (
                  <button key={e.id} type="button" className={`agenda-prochain agenda-prochain-${e.type || 'autre'}`} onClick={() => setFormulaire(depuisEvenement(e))}>
                    <strong>{e.eleve_nom || e.titre}</strong>
                    <span>{TYPES_RDV.find(([c]) => c === e.type)?.[1] || 'Rendez-vous'} · {dateLongue(e.debut)}, {heureFr(e.debut)}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {vue === 'mois' ? (
            <VueMois
              debut={debut}
              ancre={ancre}
              evenements={evenements}
              onJour={(j) => { setAncre(j); setVue('semaine') }}
              onOuvrir={(e) => setFormulaire(depuisEvenement(e))}
              onDeposer={deposer}
            />
          ) : mobile ? (
            <VueListe
              debut={debut}
              evenements={evenements}
              onJour={(j) => setFormulaire(nouveauRdv({ jour: j }))}
              onOuvrir={(e) => setFormulaire(depuisEvenement(e))}
            />
          ) : (
            <VueSemaine
              debut={debut}
              evenements={evenements}
              onCreneau={(j, h) => setFormulaire(nouveauRdv({ jour: j, heure: h }))}
              onOuvrir={(e) => setFormulaire(depuisEvenement(e))}
              onDeposer={deposer}
            />
          )}

          <p className="agenda-legende">
            <span className="agenda-pastille agenda-evt-rdv" /> RDV coaching
            <span className="agenda-pastille agenda-evt-suivi" /> Étape de suivi
            <span className="agenda-pastille agenda-evt-perso" /> Vos autres rendez-vous (lecture seule)
            {!mobile && <em> · Glissez un rendez-vous pour le déplacer, cliquez sur un créneau libre pour en ajouter un.</em>}
          </p>
        </>
      )}

      {formulaire && (
        <FormulaireRdv
          initial={formulaire}
          eleves={eleves}
          coachKey={coachKey}
          onAuthFailure={onAuthFailure}
          onFerme={() => setFormulaire(null)}
          onEnregistre={(evt) => {
            setFormulaire(null)
            setMessage(evt ? `Enregistré dans votre Google Agenda : ${libelleCreneau(evt)}.` : 'Rendez-vous supprimé de votre Google Agenda.')
            charger()
          }}
        />
      )}
    </div>
  )
}
