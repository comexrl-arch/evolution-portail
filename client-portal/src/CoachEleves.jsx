import React, { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, CalendarClock, CalendarPlus, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, Circle, ClipboardList, Copy, MessageCircle, MessageSquare, NotebookPen, Plus, RefreshCw, Search, Send, Sparkles, Star, Upload, X } from 'lucide-react'
import { FormulaireRdv, appelAgenda, dateLongue, heureFr, nouveauRdv } from './CoachAgenda.jsx'
import { ListePoints, rdvPourPoint } from './PointsRythme.jsx'
import Discussion, { messagesDepuisQuestions } from './Discussion.jsx'
import { CapParcours, DicteeVocale, ScoreCommercial, TuileResultat, kpiRenseignes, lireFiche, lireModule } from './App.jsx'

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

// Section repliee par defaut (« Ses points », « Ses fiches ») : le resume
// reste visible, le detail s'ouvre au clic.
function SectionRepliable({ titre, resume, children }) {
  const [ouvert, setOuvert] = useState(false)
  return (
    <section className="coach-section coach-repliable">
      <button type="button" className="coach-repliable-entete" aria-expanded={ouvert} onClick={() => setOuvert((v) => !v)}>
        <span className="resultats-titre">{titre}</span>
        {resume && <span className="coach-repliable-resume">{resume}</span>}
        <ChevronDown size={18} aria-hidden="true" className={`coach-repliable-chevron${ouvert ? ' resultats-chevron-ouvert' : ''}`} />
      </button>
      {ouvert && <div className="coach-repliable-corps">{children}</div>}
    </section>
  )
}

function resumePoints(points) {
  const liste = points || []
  if (!liste.length) return 'Aucun point prévu'
  const n = (statut) => liste.filter((p) => p.statut === statut).length
  return [
    n('fait') && `${n('fait')} fait${n('fait') > 1 ? 's' : ''}`,
    n('planifie') && `${n('planifie')} planifié${n('planifie') > 1 ? 's' : ''}`,
    n('a_planifier') && `${n('a_planifier')} à planifier`,
  ].filter(Boolean).join(' · ')
}

function resumeFiches(fiches, aRelire) {
  const faites = fiches.filter((f) => f.etat === 'Terminé').length
  const relire = (aRelire || []).length
  return `${faites} sur ${fiches.length} terminées${relire ? ` · ${relire} retour${relire > 1 ? 's' : ''} à relire` : ''}`
}

function AvisJ90({ avis }) {
  return (
    <Section titre="Son avis sur les 90 jours">
      <div className="energie-carte">
        <p className="energie-surtitre coach-avis-note">
          <Star size={14} aria-hidden="true" /> {avis.note ?? '—'}/10{avis.le ? ` · ${dateFr(avis.le)}` : ''}
        </p>
        <p className="text-sm whitespace-pre-wrap" style={{ color: 'var(--text-primary)' }}>{avis.avis}</p>
        <p className="eleve-carte-meta">
          {avis.accord_publication
            ? `Accord pour le citer${avis.signature ? `, signé « ${avis.signature} »` : ''}.`
            : 'Pas d\'accord pour le citer publiquement.'}
        </p>
      </div>
    </Section>
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
  return !eleve.illisible && (inactif(eleve) || eleve.retours_ia_a_relire > 0 || eleve.questions_en_attente > 0)
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

function CarteEleve({ eleve, rdv, onOuvrir, nouveau = false }) {
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
          <p className="coach-carte-nom">{eleve.nom}{nouveau && <span className="badge-nouveau">Nouveau</span>}</p>
          <p className="eleve-carte-meta">
            {[eleve.parcours, eleve.jour !== null && eleve.jour !== undefined ? `Jour ${eleve.jour} sur ${eleve.duree}` : null, eleve.etat !== 'En cours' ? eleve.etat : null]
              .filter(Boolean).join(' · ')}
          </p>
        </div>
        <EtatEleve eleve={eleve} />
      </div>

      {eleve.questions_en_attente > 0 && (
        <p className="eleve-carte-retours eleve-carte-question">
          <MessageSquare size={13} aria-hidden="true" /> {eleve.questions_en_attente} question{eleve.questions_en_attente > 1 ? 's' : ''} pour vous
        </p>
      )}

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

// --- Retours signes (29/10/2026) : « Idris prepare, Rony signe » ------------------
// Rony relit le retour d'Idris, le corrige si besoin, le publie ou le bloque,
// et peut y ajouter son mot. En Autonome, Idris publie seul.

function libelleRetour(retour) {
  if (retour.statut === 'bloque') return { classe: 'coach-puce-alerte', texte: retour.mot_coach ? 'Idris bloqué · votre mot publié' : "Bloqué, l'élève ne le voit pas" }
  if (retour.valide_le) return { classe: 'coach-puce-ok', texte: `Validé par vous le ${dateFr(retour.valide_le)}` }
  if (retour.statut === 'a_relire') return { classe: 'coach-puce-attente', texte: retour.visible_eleve ? 'À relire · déjà visible (12 h passées)' : "À relire · l'élève attend" }
  return { classe: 'coach-puce-neutre', texte: 'Publié sans relecture' }
}

function RetourASigner({ entree, clientPageId, autonome, coachKey, onAuthFailure, onSigne }) {
  const [retour, setRetour] = useState(entree.retour_ia)
  const [edition, setEdition] = useState(() => entree.retour_ia?.statut === 'a_relire')
  const [texte, setTexte] = useState(entree.retour_ia?.texte || '')
  const [mot, setMot] = useState(entree.retour_ia?.mot_coach || '')
  const [envoi, setEnvoi] = useState('')
  const [message, setMessage] = useState('')

  if (!retour) return null
  if (retour.statut === 'en_cours') return <p className="coach-signature-attente">Idris rédige son retour…</p>

  if (autonome) {
    return retour.texte ? (
      <div className="coach-retour-idris">
        <p className="energie-surtitre">Retour d'Idris · publié seul (formule Autonome)</p>
        <p className="text-sm whitespace-pre-wrap" style={{ color: 'var(--text-primary)' }}>{retour.texte}</p>
      </div>
    ) : null
  }

  async function signer(action) {
    setEnvoi(action)
    setMessage('')
    const r = await appelAgenda(`/coach/entrees/${entree.id}/signature`, coachKey, onAuthFailure, {
      method: 'POST',
      body: JSON.stringify({ client_page_id: clientPageId, action, texte, mot }),
    })
    setEnvoi('')
    if (r.erreur !== undefined) return setMessage(r.erreur)
    const maintenant = new Date().toISOString()
    const suivant = r.data?.retour_ia || {
      ...retour,
      statut: action === 'publier' ? 'publie' : 'bloque',
      texte,
      mot_coach: mot.trim() || null,
      valide_le: action === 'publier' || mot.trim() ? maintenant : null,
      visible_eleve: action === 'publier' || Boolean(mot.trim()),
    }
    setRetour(suivant)
    setEdition(false)
    setMessage(action === 'publier' ? "Publié. L'élève est prévenu sur son téléphone." : mot.trim() ? "Retour d'Idris bloqué, votre mot est publié." : "Retour d'Idris bloqué.")
    onSigne?.()
  }

  const puce = libelleRetour(retour)

  return (
    <div className="coach-signature">
      <div className="coach-signature-entete">
        <p className="energie-surtitre">Retour d'Idris</p>
        <span className={`coach-puce ${puce.classe}`}>{puce.texte}</span>
      </div>

      {edition ? (
        <>
          <label className="coach-signature-label" htmlFor={`retour-${entree.id}`}>Texte d'Idris (vous pouvez le corriger)</label>
          <textarea id={`retour-${entree.id}`} className="field-input coach-signature-texte" rows={7} value={texte} onChange={(e) => setTexte(e.target.value)} />
          <label className="coach-signature-label" htmlFor={`mot-${entree.id}`}>Votre mot à l'élève (facultatif)</label>
          <textarea
            id={`mot-${entree.id}`}
            className="field-input"
            rows={3}
            value={mot}
            onChange={(e) => setMot(e.target.value)}
            placeholder="Ex. : Très bon travail sur ta cible, on creuse ton prix au prochain point."
          />
          <DicteeVocale value={mot} onChange={setMot} libelle="Dicter votre mot" />
          <div className="coach-signature-actions">
            <button type="button" className="fiche-bouton" disabled={Boolean(envoi) || (!texte.trim() && !mot.trim())} onClick={() => signer('publier')}>
              {envoi === 'publier' ? 'Publication…' : 'Valider et publier'}
            </button>
            <button type="button" className="resultats-bouton" disabled={Boolean(envoi)} onClick={() => signer('bloquer')}>
              {envoi === 'bloquer' ? 'Envoi…' : mot.trim() ? "Bloquer Idris, garder mon mot" : "Bloquer le retour d'Idris"}
            </button>
          </div>
        </>
      ) : (
        <>
          {retour.texte && retour.statut !== 'bloque' && <p className="text-sm whitespace-pre-wrap" style={{ color: 'var(--text-primary)' }}>{retour.texte}</p>}
          {retour.mot_coach && (
            <div className="coach-mot">
              <p className="coach-signature-label">Votre mot</p>
              <p className="text-sm whitespace-pre-wrap">{retour.mot_coach}</p>
            </div>
          )}
          <button type="button" className="resultats-bouton coach-signature-modifier" onClick={() => setEdition(true)}>
            {retour.valide_le ? 'Modifier' : retour.statut === 'a_relire' ? 'Relire et valider' : 'Valider ou ajouter mon mot'}
          </button>
        </>
      )}
      {message && <p className="agenda-message" role="status">{message}</p>}
    </div>
  )
}

function ReponsesFiche({ fiche, clientPageId, autonome, coachKey, onAuthFailure, onSigne }) {
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
            <RetourASigner
              entree={entree}
              clientPageId={clientPageId}
              autonome={autonome}
              coachKey={coachKey}
              onAuthFailure={onAuthFailure}
              onSigne={onSigne}
            />
          </div>
        )
      })}
    </div>
  )
}

// Fiches regroupees par module, comme « Mon parcours » cote client.
function FichesParModule({ fiches, clientPageId, autonome, aRelire = [], coachKey, onAuthFailure, onSigne }) {
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
                        {!autonome && aRelire.includes(fiche.id) && <span className="coach-puce coach-puce-attente coach-fiche-relire">À relire</span>}
                      </span>
                      <span className="coach-fiche-etat" style={{ color: STATUT_COULEURS[fiche.etat] || 'var(--text-tertiary)' }}>
                        {bloquee ? 'Pas encore ouverte' : fiche.etat || 'Pas commencé'}
                      </span>
                    </button>
                    {estOuverte && (
                      <div className="coach-fiche-reponses">
                        <ReponsesFiche fiche={fiche} clientPageId={clientPageId} autonome={autonome} coachKey={coachKey} onAuthFailure={onAuthFailure} onSigne={onSigne} />
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

// --- Alertes d'intervention (29/10/2026) : eleves qui ont besoin de Rony, avec
// un message WhatsApp pret a envoyer. -----------------------------------------------

function MessagePret({ alerte }) {
  const [copie, setCopie] = useState(false)
  if (!alerte.message) return null
  const copier = async () => {
    try {
      await navigator.clipboard.writeText(alerte.message)
      setCopie(true)
      setTimeout(() => setCopie(false), 2000)
    } catch {
      setCopie(false)
    }
  }
  return (
    <div className="alerte-message">
      <p className="alerte-message-texte">{alerte.message}</p>
      <div className="alerte-message-actions">
        <a className="alerte-whatsapp" href={alerte.whatsapp} target="_blank" rel="noopener noreferrer">
          <MessageCircle size={14} aria-hidden="true" /> Envoyer sur WhatsApp
        </a>
        <button type="button" className="resultats-bouton" onClick={copier}>
          <Copy size={14} aria-hidden="true" /> {copie ? 'Copié' : 'Copier'}
        </button>
      </div>
    </div>
  )
}

function AlertesEleves({ coachKey, onOuvrir, eleves }) {
  const [etat, setEtat] = useState({ chargement: true, liste: [] })
  const [deplie, setDeplie] = useState(null)

  async function charger(frais = false) {
    setEtat((e) => ({ ...e, chargement: true }))
    const r = await appelAgenda(`/coach/alertes${frais ? '?frais=true' : ''}`, coachKey, () => {})
    setEtat({ chargement: false, liste: Array.isArray(r.data?.eleves) ? r.data.eleves : [], erreur: r.erreur })
  }

  useEffect(() => {
    charger()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (etat.chargement && !etat.liste.length) return null
  if (!etat.liste.length) {
    return etat.erreur === undefined ? <p className="alertes-calme"><CheckCircle2 size={15} aria-hidden="true" /> Aucun élève à relancer aujourd'hui.</p> : null
  }

  return (
    <section className="alertes">
      <div className="alertes-entete">
        <p className="alertes-titre"><AlertTriangle size={16} aria-hidden="true" /> À surveiller aujourd'hui · {etat.liste.length}</p>
        <button type="button" className="coach-bouton-icone" onClick={() => charger(true)} disabled={etat.chargement} aria-label="Recalculer" title="Recalculer">
          <RefreshCw size={14} className={etat.chargement ? 'coach-tourne' : undefined} />
        </button>
      </div>
      <ul className="alertes-liste">
        {etat.liste.map((e) => {
          const premiere = e.alertes.find((a) => a.message) || e.alertes[0]
          const ouvert = deplie === e.client_page_id
          const eleve = eleves.find((x) => x.client_page_id === e.client_page_id)
          return (
            <li key={e.client_page_id} className="alerte">
              <div className="alerte-haut">
                <div className="min-w-0">
                  <p className="alerte-nom">{e.nom}</p>
                  <p className="alerte-signaux">{e.alertes.map((a) => a.titre).join(' · ')}</p>
                </div>
                <div className="alerte-boutons">
                  {premiere.message && (
                    <button type="button" className="resultats-bouton" aria-expanded={ouvert} onClick={() => setDeplie(ouvert ? null : e.client_page_id)}>
                      {ouvert ? 'Masquer' : 'Message prêt'}
                    </button>
                  )}
                  {eleve && (
                    <button type="button" className="coach-bouton-icone" onClick={() => onOuvrir(eleve)} aria-label={`Ouvrir la fiche de ${e.nom}`} title="Ouvrir sa fiche">
                      <ChevronRight size={16} />
                    </button>
                  )}
                </div>
              </div>
              {ouvert && (
                <>
                  {premiere.detail && <p className="alerte-detail">{premiere.detail}</p>}
                  <MessagePret alerte={premiere} />
                </>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

// --- Preparation d'un point (29/10/2026) ------------------------------------------------

function PreparationPoint({ eleve, coachKey, onAuthFailure, onFerme }) {
  const [etat, setEtat] = useState({ chargement: true })
  const [idris, setIdris] = useState({})

  useEffect(() => {
    let actif = true
    appelAgenda(`/coach/eleves/${eleve.client_page_id}/preparation`, coachKey, onAuthFailure)
      .then((r) => { if (actif) setEtat({ ...r, chargement: false }) })
    return () => { actif = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eleve.client_page_id])

  async function demanderIdris() {
    setIdris({ chargement: true })
    const r = await appelAgenda(`/coach/eleves/${eleve.client_page_id}/preparation/idris`, coachKey, onAuthFailure, { method: 'POST' })
    setIdris(r.erreur !== undefined ? { erreur: r.erreur || "Idris n'a pas pu préparer le point. Réessayez." } : r.data)
  }

  const p = etat.data

  return (
    <div className="energie-carte preparation">
      <div className="coach-signature-entete">
        <p className="energie-surtitre"><ClipboardList size={14} aria-hidden="true" /> Préparer le point avec {(eleve.nom || '').split(' ')[0]}</p>
        <button type="button" className="coach-bouton-icone" onClick={onFerme} aria-label="Fermer" title="Fermer"><X size={15} /></button>
      </div>

      {etat.chargement && <Vide>Je rassemble ce qu'il a fait…</Vide>}
      {etat.erreur && <p className="text-sm" style={{ color: 'var(--danger)' }}>{etat.erreur}</p>}

      {p && (
        <>
          <p className="preparation-periode">
            {p.depuis_dernier_point ? `Depuis le dernier point (${dateFr(p.depuis)})` : `Ces 14 derniers jours (depuis le ${dateFr(p.depuis)})`}
            {p.jour !== null && p.jour !== undefined ? ` · jour ${p.jour}` : ''}
          </p>

          {p.alertes.length > 0 && (
            <ul className="preparation-alertes">
              {p.alertes.map((a) => <li key={a.type}><AlertTriangle size={13} aria-hidden="true" /> <strong>{a.titre}</strong>{a.detail ? ` · ${a.detail}` : ''}</li>)}
            </ul>
          )}

          <div className="preparation-grille">
            <div>
              <p className="coach-signature-label">Fiches travaillées</p>
              {p.fiches_travaillees.length
                ? <ul className="preparation-liste">{p.fiches_travaillees.map((f) => <li key={f.fiche}>{f.fiche} <small>{dateFr(f.date)}</small></li>)}</ul>
                : <p className="preparation-vide">Aucune.</p>}
              {p.fiches_en_retard > 0 && <p className="preparation-vide">{p.fiches_en_retard} fiche{p.fiches_en_retard > 1 ? 's' : ''} en retard.</p>}
            </div>
            <div>
              <p className="coach-signature-label">Ses chiffres (bilans)</p>
              {p.bilans.length
                ? <ul className="preparation-liste">{p.bilans.map((b) => <li key={b.semaine_du}>Sem. du {dateFr(b.semaine_du)} <small>{b.contacts} contacts · {b.rdv} RDV · {b.ventes} vente{b.ventes > 1 ? 's' : ''}</small></li>)}</ul>
                : <p className="preparation-vide">Aucun bilan.</p>}
            </div>
            <div>
              <p className="coach-signature-label">Engagements du dernier point</p>
              {p.engagements.length
                ? <ul className="compte-rendu-suivi">{p.engagements.map((e) => (
                  <li key={e.id} className={e.fait ? 'compte-rendu-tenu' : undefined}>
                    {e.fait ? <CheckCircle2 size={15} aria-hidden="true" /> : <Circle size={15} aria-hidden="true" />}<span>{e.texte}</span>
                  </li>
                ))}</ul>
                : <p className="preparation-vide">Pas encore de compte rendu.</p>}
            </div>
            <div>
              <p className="coach-signature-label">Ce qu'il a demandé</p>
              {p.questions_rony.length + p.questions_idris.length
                ? <ul className="preparation-liste">
                  {p.questions_rony.map((q) => <li key={q.id}><strong>À vous :</strong> {q.question}</li>)}
                  {p.questions_idris.map((q, i) => <li key={i}><strong>À Idris :</strong> {q.question}</li>)}
                </ul>
                : <p className="preparation-vide">Aucune question.</p>}
              <p className="preparation-vide">
                Carnet : {Object.entries(p.carnet.par_statut).map(([s, n]) => `${s} ${n}`).join(', ') || 'vide'}
                {p.carnet.a_relancer ? ` · ${p.carnet.a_relancer} à relancer` : ''}
              </p>
            </div>
          </div>

          <div className="preparation-idris">
            {!idris.synthese && (
              <button type="button" className="resultats-bouton" onClick={demanderIdris} disabled={idris.chargement}>
                <Sparkles size={14} aria-hidden="true" /> {idris.chargement ? 'Idris prépare…' : 'Synthèse et 3 questions par Idris'}
              </button>
            )}
            {idris.erreur && <p className="agenda-message" role="status">{idris.erreur}</p>}
            {idris.synthese && (
              <div className="coach-retour-idris">
                <p className="energie-surtitre">Idris · pour vous</p>
                <p className="text-sm">{idris.synthese}</p>
                {idris.questions?.length > 0 && (
                  <ol className="preparation-questions">{idris.questions.map((q, i) => <li key={i}>{q}</li>)}</ol>
                )}
                {idris.vigilance && <p className="text-sm"><strong>À ne pas laisser passer :</strong> {idris.vigilance}</p>}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

// --- Questions pour Rony (29/10/2026) ---------------------------------------------------

function QuestionsRony({ eleve, questions, coachKey, onAuthFailure }) {
  const [liste, setListe] = useState(questions)
  const [reponse, setReponse] = useState('')
  const [cible, setCible] = useState(null)
  const [envoi, setEnvoi] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => { setListe(questions) }, [questions])

  // Plus ancienne question sans reponse d'abord, comme on lit un fil.
  const attente = [...liste].filter((q) => !q.reponse).sort((a, b) => String(a.posee_le).localeCompare(String(b.posee_le)))
  const visee = attente.find((q) => q.id === cible) || attente[0]
  const prenom = (eleve.nom || '').split(' ')[0] || "L'élève"

  async function repondre(event) {
    event.preventDefault()
    if (!visee) return
    setEnvoi(true)
    setMessage('')
    const r = await appelAgenda(`/coach/eleves/${eleve.client_page_id}/questions/${visee.id}/reponse`, coachKey, onAuthFailure, {
      method: 'POST',
      body: JSON.stringify({ reponse }),
    })
    setEnvoi(false)
    if (r.erreur !== undefined) return setMessage(r.erreur)
    setListe((l) => l.map((x) => (x.id === visee.id ? r.data : x)))
    setReponse('')
    setCible(null)
    setMessage("Réponse envoyée. L'élève est prévenu sur son téléphone.")
  }

  return (
    <section className="coach-section discussion-section">
      <div className="resultats-entete">
        <h3 className="resultats-titre">Discussion avec {prenom}</h3>
        {attente.length > 0 && <span className="coach-puce coach-puce-attente">{attente.length} en attente</span>}
      </div>
      <div className="discussion-cadre">
        <Discussion
          messages={messagesDepuisQuestions(liste)}
          moi="coach"
          noms={{ eleve: prenom }}
          enAttente={attente.length}
          cible={visee?.id}
          onCibler={setCible}
          vide="Aucune question pour l'instant. L'élève peut vous écrire depuis son tableau de bord."
        />
        {visee && (
          <form className="discussion-saisie" onSubmit={repondre}>
            {attente.length > 1 && <p className="discussion-citation">Réponse à : « {visee.question.slice(0, 90)}{visee.question.length > 90 ? '…' : ''} »</p>}
            <div className="discussion-saisie-ligne">
              <textarea
                className="field-input"
                rows={2}
                value={reponse}
                onChange={(e) => setReponse(e.target.value)}
                placeholder="Votre réponse…"
                aria-label="Votre réponse"
              />
              <DicteeVocale value={reponse} onChange={setReponse} libelle="Dicter votre réponse" compact />
              <button type="submit" className="discussion-envoyer" disabled={envoi || !reponse.trim()} aria-label="Envoyer la réponse">
                <Send size={18} aria-hidden="true" />
              </button>
            </div>
          </form>
        )}
      </div>
      {message && <p className="agenda-message" role="status">{message}</p>}
    </section>
  )
}

// --- Compte rendu apres chaque point (29/10/2026) ----------------------------------
// Rony dicte ou tape ses notes, Idris peut les mettre en forme, l'eleve
// retrouve le resume et ses engagements sur son tableau de bord.

function aujourdhuiIso() {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

function FormulaireCompteRendu({ eleve, coachKey, onAuthFailure, onFerme, onEnvoye }) {
  const [datePoint, setDatePoint] = useState(aujourdhuiIso())
  const [notes, setNotes] = useState('')
  const [resume, setResume] = useState('')
  const [engagements, setEngagements] = useState([''])
  const [envoi, setEnvoi] = useState('')
  const [message, setMessage] = useState('')
  const prenom = (eleve.nom || '').split(' ')[0]

  async function mettreEnForme() {
    setEnvoi('forme')
    setMessage('')
    const r = await appelAgenda('/coach/comptes-rendus/mise-en-forme', coachKey, onAuthFailure, {
      method: 'POST',
      body: JSON.stringify({ notes, prenom }),
    })
    setEnvoi('')
    if (r.erreur !== undefined) return setMessage(r.erreur || "Idris n'a pas pu mettre vos notes en forme. Écrivez le résumé vous-même.")
    setResume(r.data.resume || '')
    setEngagements(r.data.engagements?.length ? r.data.engagements : [''])
  }

  async function envoyer() {
    setEnvoi('envoi')
    setMessage('')
    const r = await appelAgenda(`/coach/eleves/${eleve.client_page_id}/comptes-rendus`, coachKey, onAuthFailure, {
      method: 'POST',
      body: JSON.stringify({ resume: resume || notes, engagements: engagements.filter((e) => e.trim()), date_point: datePoint }),
    })
    setEnvoi('')
    if (r.erreur !== undefined) return setMessage(r.erreur)
    onEnvoye(r.data)
  }

  const changerEngagement = (i, valeur) => setEngagements((liste) => liste.map((e, j) => (j === i ? valeur : e)))

  return (
    <div className="energie-carte compte-rendu-formulaire">
      <div className="coach-signature-entete">
        <p className="energie-surtitre">Compte rendu du point avec {prenom || "l'élève"}</p>
        <button type="button" className="coach-bouton-icone" onClick={onFerme} aria-label="Fermer" title="Fermer"><X size={15} /></button>
      </div>

      <label className="coach-signature-label" htmlFor="cr-date">Date du point</label>
      <input id="cr-date" type="date" className="field-input compte-rendu-date" value={datePoint} onChange={(e) => setDatePoint(e.target.value)} />

      <label className="coach-signature-label" htmlFor="cr-notes">Vos notes (dictées ou tapées, en vrac)</label>
      <textarea
        id="cr-notes"
        className="field-input"
        rows={5}
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        placeholder="Ce qu'on a vu, ce qui bloque, ce qu'il s'engage à faire d'ici le prochain point…"
      />
      <div className="compte-rendu-outils">
        <DicteeVocale value={notes} onChange={setNotes} libelle="Dicter vos notes" />
        <button type="button" className="resultats-bouton" disabled={!notes.trim() || Boolean(envoi)} onClick={mettreEnForme}>
          <Sparkles size={14} aria-hidden="true" /> {envoi === 'forme' ? 'Idris met en forme…' : 'Mettre en forme avec Idris'}
        </button>
      </div>

      <label className="coach-signature-label" htmlFor="cr-resume">Résumé pour l'élève</label>
      <textarea
        id="cr-resume"
        className="field-input"
        rows={4}
        value={resume}
        onChange={(e) => setResume(e.target.value)}
        placeholder="Laissé vide, vos notes sont envoyées telles quelles."
      />

      <p className="coach-signature-label">Ses engagements d'ici le prochain point</p>
      <ul className="compte-rendu-engagements">
        {engagements.map((e, i) => (
          <li key={i}>
            <input
              type="text"
              className="field-input"
              value={e}
              maxLength={200}
              onChange={(ev) => changerEngagement(i, ev.target.value)}
              placeholder={i === 0 ? 'Ex. : Appeler 5 prospects d’ici mercredi' : 'Autre engagement'}
              aria-label={`Engagement ${i + 1}`}
            />
            {engagements.length > 1 && (
              <button type="button" className="coach-bouton-icone" onClick={() => setEngagements((l) => l.filter((_, j) => j !== i))} aria-label="Retirer" title="Retirer"><X size={14} /></button>
            )}
          </li>
        ))}
      </ul>
      {engagements.length < 5 && (
        <button type="button" className="coach-lien-ajout" onClick={() => setEngagements((l) => [...l, ''])}>
          <Plus size={14} aria-hidden="true" /> Ajouter un engagement
        </button>
      )}

      <div className="coach-signature-actions">
        <button
          type="button"
          className="fiche-bouton"
          disabled={Boolean(envoi) || (!resume.trim() && !notes.trim() && !engagements.some((e) => e.trim()))}
          onClick={envoyer}
        >
          {envoi === 'envoi' ? 'Envoi…' : "Envoyer à l'élève"}
        </button>
      </div>
      {message && <p className="agenda-message" role="status">{message}</p>}
    </div>
  )
}

function ComptesRendus({ eleve, comptesRendus, coachKey, onAuthFailure, onAjoute }) {
  const [ouvert, setOuvert] = useState(false)
  const [message, setMessage] = useState('')

  return (
    <Section
      titre="Comptes rendus de points"
      action={!ouvert && (
        <button type="button" className="resultats-bouton" onClick={() => { setOuvert(true); setMessage('') }}>
          <NotebookPen size={15} aria-hidden="true" /> Écrire le compte rendu
        </button>
      )}
    >
      {ouvert && (
        <FormulaireCompteRendu
          eleve={eleve}
          coachKey={coachKey}
          onAuthFailure={onAuthFailure}
          onFerme={() => setOuvert(false)}
          onEnvoye={(cr) => {
            setOuvert(false)
            setMessage("Envoyé. L'élève le retrouve sur son tableau de bord.")
            onAjoute(cr)
          }}
        />
      )}
      {message && <p className="agenda-message" role="status">{message}</p>}
      {comptesRendus.length ? (
        <div className="space-y-3">
          {comptesRendus.slice(0, 6).map((cr) => {
            const tenus = cr.engagements.filter((e) => e.fait).length
            return (
              <div key={cr.id} className="energie-carte compte-rendu">
                <div className="coach-signature-entete">
                  <p className="energie-surtitre">Point du {dateFr(cr.date_point)}</p>
                  {cr.engagements.length > 0 && (
                    <span className={`coach-puce ${tenus === cr.engagements.length ? 'coach-puce-ok' : 'coach-puce-neutre'}`}>
                      {tenus}/{cr.engagements.length} tenus
                    </span>
                  )}
                </div>
                {cr.resume && <p className="text-sm whitespace-pre-wrap" style={{ color: 'var(--text-primary)' }}>{cr.resume}</p>}
                {cr.engagements.length > 0 && (
                  <ul className="compte-rendu-suivi">
                    {cr.engagements.map((e) => (
                      <li key={e.id} className={e.fait ? 'compte-rendu-tenu' : undefined}>
                        {e.fait ? <CheckCircle2 size={15} aria-hidden="true" /> : <Circle size={15} aria-hidden="true" />}
                        <span>{e.texte}</span>
                        <small>{e.fait ? 'tenu' : 'pas encore'}</small>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )
          })}
        </div>
      ) : !ouvert && <Vide>Aucun compte rendu pour l'instant. Après chaque point, écrivez-en un : l'élève retrouve ses engagements sur son tableau de bord.</Vide>}
    </Section>
  )
}

// Carnet de l'eleve vu par Rony (29/10/2026) : entonnoir, coordonnees, dernier
// echange, et export du carnet en Excel ou CSV.
function CarnetEleve({ carnet, eleve, coachKey, onAuthFailure }) {
  const [tout, setTout] = useState(false)
  const [erreur, setErreur] = useState('')
  const e = carnet.entonnoir
  const liste = tout ? carnet.prospects : carnet.prospects.slice(0, 15)

  async function exporter(format) {
    setErreur('')
    try {
      const res = await fetch(`${API_BASE}/coach/eleves/${eleve.client_page_id}/prospects/export?format=${format}`, { headers: { 'X-Coach-Key': coachKey } })
      if (res.status === 401) return onAuthFailure()
      if (!res.ok) throw new Error('export')
      const url = URL.createObjectURL(await res.blob())
      const lien = document.createElement('a')
      lien.href = url
      lien.download = `carnet-${(eleve.nom || 'eleve').toLowerCase().replace(/[^a-z0-9]+/g, '-')}.${format}`
      document.body.appendChild(lien)
      lien.click()
      lien.remove()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch {
      setErreur(MESSAGE_SERVICE_INDISPONIBLE)
    }
  }

  return (
    <>
      {e && (
        <p className="coach-entonnoir">
          {e.prospects} prospect{e.prospects > 1 ? 's' : ''} → {e.contactes} contacté{e.contactes > 1 ? 's' : ''}{e.taux_contact !== null ? ` (${e.taux_contact} %)` : ''} → {e.rdv} RDV{e.taux_rdv !== null ? ` (${e.taux_rdv} %)` : ''} → {e.clients} client{e.clients > 1 ? 's' : ''}{e.taux_signature !== null ? ` (${e.taux_signature} %)` : ''}
          {carnet.ventes?.ca > 0 ? ` · ${carnet.ventes.ca.toLocaleString('fr-FR')} € signés` : ''}
        </p>
      )}
      <div className="coach-statuts">
        {carnet.statuts.map((s) => (
          <span key={s} className="coach-puce coach-puce-neutre">{s} <strong>{carnet.par_statut[s] || 0}</strong></span>
        ))}
        {carnet.a_relancer?.length > 0 && (
          <span className="coach-puce coach-puce-attente">À relancer <strong>{carnet.a_relancer.length}</strong></span>
        )}
      </div>
      <ul className="coach-prospects">
        {liste.map((p) => {
          const dernier = (p.journal || []).at(-1)
          return (
            <li key={p.id}>
              <span>
                {p.nom}
                {(p.telephone || p.email) && <small className="coach-prospect-contact">{[p.telephone, p.email].filter(Boolean).join(' · ')}</small>}
                {dernier && <small className="coach-prospect-contact">Dernier échange ({dateFr(dernier.date)}) : {dernier.texte}</small>}
              </span>
              <small>{p.statut}{p.relance ? ` · relance ${dateFr(p.relance)}` : ''}{p.montant ? ` · ${p.montant.toLocaleString('fr-FR')} €` : ''}</small>
            </li>
          )
        })}
      </ul>
      <div className="coach-carnet-actions">
        {carnet.prospects.length > 15 && (
          <button type="button" className="coach-lien-ajout" onClick={() => setTout((v) => !v)}>
            {tout ? 'Voir moins' : `Voir les ${carnet.prospects.length} prospects`}
          </button>
        )}
        <button type="button" className="coach-lien-ajout" onClick={() => exporter('xlsx')}><Upload size={13} /> Excel</button>
        <button type="button" className="coach-lien-ajout" onClick={() => exporter('csv')}><Upload size={13} /> CSV</button>
      </div>
      {erreur && <p className="text-sm" style={{ color: 'var(--danger)' }}>{erreur}</p>}
    </>
  )
}

function DetailEleve({ eleve, rdv, points, eleves, coachKey, onAuthFailure, onRetour, onRdv }) {
  const [etat, setEtat] = useState({ chargement: true })
  const [detailKpi, setDetailKpi] = useState(false)
  const [planifier, setPlanifier] = useState(false)
  const [preparer, setPreparer] = useState(false)
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
  const autonome = eleve.parcours === 'Autonome'
  const [comptesRendusAjoutes, setComptesRendusAjoutes] = useState([])
  const comptesRendus = [...comptesRendusAjoutes, ...(etat.data?.comptes_rendus || []).filter((c) => !comptesRendusAjoutes.some((a) => a.id === c.id))]

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
          {eleve.parcours !== 'Autonome' && (
            <button type="button" className="resultats-bouton" onClick={() => setPreparer((v) => !v)} aria-expanded={preparer}>
              <ClipboardList size={15} aria-hidden="true" /> Préparer le point
            </button>
          )}
          {onRdv && (
            <button type="button" className="resultats-bouton" onClick={() => setPlanifier(nouveauRdv({ eleve }))}>
              <CalendarPlus size={15} aria-hidden="true" /> Planifier un RDV
            </button>
          )}
        </div>
        {message && <p className="agenda-message" role="status">{message}</p>}
      </div>

      {preparer && <PreparationPoint eleve={eleve} coachKey={coachKey} onAuthFailure={onAuthFailure} onFerme={() => setPreparer(false)} />}

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
        <SectionRepliable titre="Ses points" resume={resumePoints(points.points)}>
          <ListePoints
            coach
            points={points.points}
            onPlanifier={onRdv ? (p) => setPlanifier(rdvPourPoint(p, { ...eleve, parcours: points.parcours })) : null}
          />
        </SectionRepliable>
      )}

      {d && !autonome && eleve.parcours !== 'Atelier' && (
        <QuestionsRony eleve={eleve} questions={etat.data?.questions_rony || []} coachKey={coachKey} onAuthFailure={onAuthFailure} />
      )}

      {d && !autonome && (
        <ComptesRendus
          eleve={eleve}
          comptesRendus={comptesRendus}
          coachKey={coachKey}
          onAuthFailure={onAuthFailure}
          onAjoute={(cr) => setComptesRendusAjoutes((l) => [cr, ...l])}
        />
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

          <SectionRepliable titre="Ses fiches" resume={resumeFiches(d.fiches, eleve.fiches_a_relire)}>
            <FichesParModule
              fiches={d.fiches}
              clientPageId={eleve.client_page_id}
              autonome={autonome}
              aRelire={eleve.fiches_a_relire || []}
              coachKey={coachKey}
              onAuthFailure={onAuthFailure}
            />
          </SectionRepliable>

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
                <CarnetEleve carnet={carnet} eleve={eleve} coachKey={coachKey} onAuthFailure={onAuthFailure} />
              ) : <Vide>Carnet vide.</Vide>}
            </div>
          </div>

          {etat.data?.avis_j90 && <AvisJ90 avis={etat.data.avis_j90} />}

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

export default function CoachEleves({ coachKey, onAuthFailure, onDetail, nouveaux = [], onVu, onActualiser }) {
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
    onActualiser?.()
    chargerProchains()
    setLoading(true)
    setError('')
    const r = await lireCoach('/coach/eleves', coachKey, onAuthFailure)
    setLoading(false)
    if (r.erreur !== undefined) return setError(r.erreur)
    if (!Array.isArray(r.data?.eleves)) return setError(MESSAGE_SERVICE_INDISPONIBLE)
    setEleves(r.data.eleves)
    // ?eleve=<id> : ouverture depuis une notification (question d'un eleve).
    const demande = new URLSearchParams(window.location.search).get('eleve')
    const cible = demande && r.data.eleves.find((e) => e.client_page_id === demande)
    if (cible) {
      setOuvert(cible)
      window.history.replaceState({}, '', window.location.pathname)
    }
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
    if (ouvert) onVu?.(ouvert.client_page_id)
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
      {eleves.length > 0 && <AlertesEleves coachKey={coachKey} eleves={eleves} onOuvrir={setOuvert} />}

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
        {filtres.map((eleve) => <CarteEleve key={eleve.client_page_id} eleve={eleve} rdv={prochains[eleve.client_page_id]} onOuvrir={setOuvert} nouveau={nouveaux.includes(eleve.client_page_id)} />)}
      </div>
    </div>
  )
}
