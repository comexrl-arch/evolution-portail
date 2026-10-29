import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { formaterMaj } from './dates'
import { ArrowLeft, Award, BookOpen, CalendarDays, CheckCircle2, ChevronDown, ChevronRight, Compass, Copy, Library, Link2, ListChecks, LayoutDashboard, Loader2, Lock, Mail, Map as IconeCarte, MapPin, Menu, MessageCircle, Mic, Phone, PlayCircle, Printer, Quote, Share2, Smartphone, Rocket, Sparkles, Star, Target, UserRound, Users, X } from 'lucide-react'
import logo from './assets/logo.svg'
import { installer, useInstallation } from './installation.js'
import BoutonInstaller from './BoutonInstaller.jsx'
import { ListePoints, libellePoint } from './PointsRythme.jsx'
import { cleRdv, useNouveautesEleve } from './Nouveautes.js'
import monogramme from './assets/monogramme.svg'
import illustrationModule0 from './assets/modules/module-0.jpg'
import illustrationModule1 from './assets/modules/module-1.jpg'
import illustrationModule2 from './assets/modules/module-2.jpg'
import illustrationModule3 from './assets/modules/module-3.jpg'
import illustrationModule4 from './assets/modules/module-4.jpg'
import illustrationModule5 from './assets/modules/module-5.jpg'
import illustrationCible from './assets/modules/module-cible.jpg'
import illustrationPitch from './assets/modules/module-pitch.jpg'
import illustrationPrix from './assets/modules/module-prix.jpg'
import illustrationAides from './assets/modules/module-aides.jpg'
import illustrationSemaine from './assets/modules/module-semaine.jpg'

// Le portail parle a portal_main.py, un process separe de main.py (agents
// IA, port 8010) - voir portal_main.py. Port 8013, pas 8011 : verifie en
// direct qu'un process invisible de tasklist/Get-Process/taskkill restait
// bloque sur 8011 et repondait avec du code perime (silencieusement, sans
// erreur - exactement le piege que ce commentaire visait a eviter). 8013
// verifie propre (bind natif reussi, aucune entree fantome) au moment du
// changement. /health expose "started_at" pour reperer un futur fantome.
const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8013'
const SESSION_KEY = 'portal_session_token'
const OUVRIR_KEY = 'portail_ouvrir'

// Les titres de fiche stockes en base suivent "{Client} - {Titre master}"
// (voir onboard_client cote backend) : le client le sait deja qu'il s'agit
// de son propre parcours, pas besoin de le repeter sur chaque encart.
function sansNomClient(nom) {
  const index = nom.indexOf(' - ')
  return index === -1 ? nom : nom.slice(index + 3)
}

// Dictee vocale : reconnaissance de la parole integree au navigateur
// (gratuite, Chrome, Edge, Safari ; absente de Firefox, le bouton est alors
// simplement masque). Proposee sur les reponses qu'on dit a l'oral : pitch,
// presentation, script, phrase de positionnement.
const SpeechRecognitionNavigateur =
  typeof window !== 'undefined' ? window.SpeechRecognition || window.webkitSpeechRecognition : undefined
const CHAMP_ORAL = /pitch|oral|pr[ée]sentation|pr[ée]sente|script|positionnement|elevator|accroche|discours/i

function DicteeVocale({ value, onChange }) {
  const [ecoute, setEcoute] = useState(false)
  const [erreur, setErreur] = useState('')
  const reconnaissance = useRef(null)
  const valeurCourante = useRef(value)
  valeurCourante.current = value

  useEffect(() => () => reconnaissance.current?.abort(), [])

  if (!SpeechRecognitionNavigateur) return null

  const demarrer = () => {
    const rec = new SpeechRecognitionNavigateur()
    rec.lang = 'fr-FR'
    rec.continuous = true
    rec.interimResults = false
    rec.onresult = (event) => {
      let texte = ''
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        if (event.results[i].isFinal) texte += event.results[i][0].transcript
      }
      texte = texte.trim()
      if (!texte) return
      const avant = (valeurCourante.current || '').trimEnd()
      const suivant = avant ? `${avant} ${texte}` : texte.charAt(0).toUpperCase() + texte.slice(1)
      valeurCourante.current = suivant
      onChange(suivant)
    }
    rec.onerror = (event) => {
      setErreur(event.error === 'not-allowed' || event.error === 'service-not-allowed'
        ? "Autorise l'accès au micro dans ton navigateur pour dicter."
        : "La dictée s'est interrompue. Réessaie.")
    }
    rec.onend = () => setEcoute(false)
    reconnaissance.current = rec
    setErreur('')
    setEcoute(true)
    try {
      rec.start()
    } catch {
      setEcoute(false)
    }
  }

  const arreter = () => reconnaissance.current?.stop()

  return (
    <div className="dictee">
      <button
        type="button"
        className={`dictee-bouton${ecoute ? ' dictee-active' : ''}`}
        onClick={ecoute ? arreter : demarrer}
        aria-pressed={ecoute}
      >
        <Mic size={14} aria-hidden="true" />
        {ecoute ? 'J’écoute… touche pour arrêter' : 'Dicter à voix haute'}
      </button>
      {erreur && <p className="dictee-erreur">{erreur}</p>}
    </div>
  )
}

function FieldInput({ champ, value, onChange }) {
  if (champ.type === 'choix') {
    return (
      <select
        className="field-input"
        value={value ?? ''}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="" disabled>
          Choisir…
        </option>
        {(champ.options || []).map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    )
  }

  if (champ.type === 'nombre') {
    return (
      <input
        className="field-input"
        type="number"
        value={value ?? ''}
        onChange={(event) => onChange(event.target.value === '' ? '' : Number(event.target.value))}
      />
    )
  }

  if (champ.type === 'date') {
    return (
      <input
        className="field-input"
        type="date"
        value={value ?? ''}
        onChange={(event) => onChange(event.target.value)}
      />
    )
  }

  return (
    <textarea
      className="field-input"
      rows={3}
      placeholder="Écris ici…"
      value={value ?? ''}
      onChange={(event) => onChange(event.target.value)}
    />
  )
}

// Libelle de la question, avec le bouton de dictee juste a cote (demande de
// Rony du 26/10/2026) pour les champs a dire a l'oral.
function EnteteChamp({ champ, value, onChange, children, Balise = 'label' }) {
  const dictee = !['choix', 'nombre', 'date'].includes(champ.type) && CHAMP_ORAL.test(champ.libelle || '')

  if (!dictee) return <Balise className="fiche-champ-libelle">{children}</Balise>

  return (
    <div className="fiche-champ-entete">
      <Balise className="fiche-champ-libelle">{children}</Balise>
      <DicteeVocale value={value ?? ''} onChange={onChange} />
    </div>
  )
}

function ProgressStat({ pct, children }) {
  const clamped = Math.max(0, Math.min(100, Math.round(pct || 0)))

  return (
    <div className="progress-stat">
      <p className="progress-stat-value">{clamped}%</p>
      <p className="progress-stat-label">{children}</p>
      <div className="progress-stat-track">
        <div style={{ width: `${clamped}%` }} />
      </div>
    </div>
  )
}

const TABLE_LINE_PREFIX = '##TABLE## '

const IMAGE_LINE_PREFIX = '##IMAGE## '

const CHECK_LINE_PREFIX = '##CHECK## '

const normaliserLibelle = (texte) =>
  String(texte || '')
    .split('(')[0]
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9 ]/gi, ' ')
    .trim()
    .toLowerCase()

const memeLibelle = (a, b) => {
  const x = normaliserLibelle(a)
  const y = normaliserLibelle(b)
  return Boolean(x && y) && (x === y || x.startsWith(y) || y.startsWith(x))
}

function lireTable(ligne) {
  try {
    return JSON.parse(ligne.slice(TABLE_LINE_PREFIX.length))
  } catch {
    return null
  }
}

function indexTableModele(lignes, champs) {
  // Fiche recurrente (ex. tableau de prospection) : le modele Notion contient
  // un tableau vide dont les colonnes reprennent les champs de saisie. On le
  // repere pour y afficher les saisies du client a la place.
  return lignes.findIndex((ligne) => {
    if (!ligne.startsWith(TABLE_LINE_PREFIX)) return false
    const table = lireTable(ligne)
    const entete = table?.hasHeader ? table.rows?.[0] || [] : []
    return entete.filter((cellule) => champs.some((champ) => memeLibelle(cellule, champ.libelle))).length >= 2
  })
}

function tableSaisies(champs, entrees, entete) {
  // Colonnes : celles du tableau modele (s'il existe), puis les champs qui n'y
  // figurent pas. La date d'enregistrement n'est ajoutee que si aucun champ
  // "Date" n'est saisi par le client (evite la colonne Date en double).
  const champDate = champs.some((champ) => memeLibelle(champ.libelle, 'Date'))
  const colonnes = []

  for (const cellule of entete || []) {
    const champ = champs.find((c) => memeLibelle(cellule, c.libelle))
    if (champ) colonnes.push({ titre: cellule, champ })
    else if (memeLibelle(cellule, 'Date') && !champDate) colonnes.push({ titre: cellule, date: true })
  }

  if (!entete && !champDate) colonnes.push({ titre: 'Date', date: true })

  for (const champ of champs) {
    if (!colonnes.some((col) => col.champ === champ)) colonnes.push({ titre: champ.libelle, champ })
  }

  const lignes = entrees.map((entree) =>
    colonnes.map((col) => String((col.date ? entree.date : entree.donnees?.[col.champ.cle]) ?? '')),
  )

  return TABLE_LINE_PREFIX + JSON.stringify({ hasHeader: true, rows: [colonnes.map((col) => col.titre), ...lignes] })
}

function renderInline(texte) {
  if (typeof texte !== 'string') return texte
  if (!texte.includes('**') && !texte.includes('](')) return texte
  return texte
    .split(/(\*\*.+?\*\*|\[[^\]]*\]\((?:https?:|mailto:|tel:)[^)\s]+\))/g)
    .map((part, i) => {
      const bold = part.match(/^\*\*(.+)\*\*$/)
      if (bold) return <strong key={i}>{bold[1]}</strong>
      const link = part.match(/^\[([^\]]*)\]\(([^)\s]+)\)$/)
      if (link) {
        return (
          <a key={i} href={link[2]} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--gold)', textDecoration: 'underline' }}>
            {link[1] || 'Ouvrir'}
          </a>
        )
      }
      return part
    })
}

function renderTextLine(ligne, key) {
  if (ligne.startsWith(IMAGE_LINE_PREFIX)) {
    const [src, ...rest] = ligne.slice(IMAGE_LINE_PREFIX.length).split('|')
    const legende = rest.join('|').trim()

    return (
      <figure key={key} className="fiche-figure">
        <img src={src} alt={legende || 'Illustration'} loading="lazy" />
        {legende && <figcaption>{legende}</figcaption>}
      </figure>
    )
  }
  if (ligne.startsWith(TABLE_LINE_PREFIX)) {
    let table = null

    try {
      table = JSON.parse(ligne.slice(TABLE_LINE_PREFIX.length))
    } catch {
      return null
    }

    const { hasHeader, rows } = table
    const headerRow = hasHeader ? rows[0] : null
    const bodyRows = hasHeader ? rows.slice(1) : rows

    return (
      <div key={key} className="fiche-table">
        <table>
          {headerRow && (
            <thead>
              <tr>
                {headerRow.map((cell, i) => <th key={i}>{renderInline(cell)}</th>)}
              </tr>
            </thead>
          )}
          <tbody>
            {bodyRows.map((row, ri) => (
              <tr key={ri}>
                {row.map((cell, ci) => <td key={ci}>{renderInline(cell)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  const niveau = niveauTitre(ligne)

  if (niveau) {
    return <h3 key={key} className="fiche-soustitre">{renderInline(sansEmoji(ligne.slice(niveau + 1)))}</h3>
  }
  if (ligne.startsWith('- ')) {
    return <p key={key} className="fiche-puce">{renderInline(ligne.slice(2))}</p>
  }
  if (ligne.startsWith('> ')) {
    return <p key={key} className="fiche-encadre">{renderInline(ligne.slice(2))}</p>
  }
  if (!ligne.trim()) return null
  return <p key={key} className="fiche-texte">{renderInline(ligne)}</p>
}

// Les titres des fiches Notion commencent par un emoji ("# 📅 MON PLAN...",
// "### 🎯 1. MES OBJECTIFS") : retire pour une presentation sobre, le numero
// de section prend le relais.
const EMOJI_DEBUT = /^[\p{Extended_Pictographic}\p{Emoji_Modifier}\uFE0F\u200D\s]+/u

const sansEmoji = (texte) => texte.replace(EMOJI_DEBUT, '')

function niveauTitre(ligne) {
  const titre = (ligne || '').match(/^(#{1,3}) /)
  return titre ? titre[1].length : 0
}

const estParagraphe = (ligne) => Boolean(ligne) && !niveauTitre(ligne) && !/^(- |> |##)/.test(ligne)

function decouperFiche(items, texteDe) {
  // Meme lecture que la synthese : un titre "# ", une introduction, puis des
  // sections ouvertes par le premier niveau de titre rencontre ("## " ou
  // "### "). Les titres plus fins restent des sous-titres dans leur section.
  const niveaux = items.map((item) => niveauTitre(texteDe(item)))
  const premier = niveaux.findIndex((n) => n > 0)
  const aTitre = premier >= 0 && niveaux[premier] === 1
  const niveauSection = Math.min(4, ...niveaux.filter((n, i) => n > 0 && !(aTitre && i === premier)))

  let titre = null
  const intro = []
  const sections = []

  items.forEach((item, i) => {
    if (aTitre && i === premier) {
      titre = sansEmoji(texteDe(item).slice(2))
      return
    }

    if (niveaux[i] && niveaux[i] <= niveauSection) {
      const libelle = sansEmoji(texteDe(item).slice(niveaux[i] + 1))
      const numero = libelle.match(/^(\d+)[.)]\s*(.*)$/)
      sections.push({ numero: numero?.[1], titre: numero ? numero[2] : libelle, items: [] })
      return
    }

    if (sections.length) sections[sections.length - 1].items.push(item)
    else intro.push(item)
  })

  // L'accroche sous le titre (paragraphes simples) va dans l'en-tete, le
  // reste de l'introduction dans un premier bloc sans titre.
  let accroche = 0
  while (accroche < intro.length && estParagraphe(texteDe(intro[accroche]))) accroche += 1

  return { titre, accroche: intro.slice(0, accroche), intro: intro.slice(accroche), sections }
}

function FicheDocument({ items, texteDe, rendre, surtitre, apres }) {
  const { titre, accroche, intro, sections } = decouperFiche(items, texteDe)
  const rendreTous = (liste) => liste.map(rendre)

  return (
    <article className="fiche-document">
      {(titre || surtitre) && (
        <header className="fiche-entete">
          {surtitre && <p className="fiche-surtitre">{surtitre}</p>}
          {titre && <h1 className="fiche-titre">{renderInline(titre)}</h1>}
          {accroche.length > 0 && (
            <div className="fiche-accroche">
              {accroche.map((item, i) => <p key={i}>{renderInline(texteDe(item))}</p>)}
            </div>
          )}
        </header>
      )}

      {!titre && !surtitre && accroche.length > 0 && (
        <section className="fiche-section">{rendreTous(accroche)}</section>
      )}

      {intro.length > 0 && <section className="fiche-section">{rendreTous(intro)}</section>}

      {sections.map((section, index) => (
        <section key={index} className="fiche-section">
          <header className="fiche-section-entete">
            {section.numero && <span className="fiche-section-numero">{section.numero}</span>}
            <h2 className="fiche-section-titre">{renderInline(section.titre)}</h2>
          </header>
          {section.items.length > 0 && <div className="fiche-section-corps">{rendreTous(section.items)}</div>}
        </section>
      ))}

      {apres}
    </article>
  )
}

function surtitreFiche(nom) {
  const numero = (nom || '').match(/^\s*(\d+)\s*[.)]/)
  if (numero) return `Fiche ${numero[1]} · Parcours eVolution 2.0`
  return /^\s*bonus/i.test(nom || '') ? 'Fiche bonus · Parcours eVolution 2.0' : 'Parcours eVolution 2.0'
}

function FicheContent({ texte, checks, onToggleCheck, saisies, surtitre }) {
  if (!texte) return null

  const lignes = texte.split('\n')
  const indexModele = saisies?.entrees?.length ? indexTableModele(lignes, saisies.champs) : -1
  const items = lignes.map((ligne, index) => ({ ligne, index })).filter(({ ligne }) => ligne.trim())

  const rendre = ({ ligne, index }) => {
    if (index === indexModele) {
      const entete = lireTable(ligne).rows[0]
      return renderTextLine(tableSaisies(saisies.champs, saisies.entrees, entete), index)
    }

    if (ligne.startsWith(CHECK_LINE_PREFIX)) {
      const [cle, ...reste] = ligne.slice(CHECK_LINE_PREFIX.length).split('|')

      return (
        <label key={index} className="fiche-case">
          <input
            type="checkbox"
            checked={Boolean(checks?.[cle])}
            disabled={!onToggleCheck}
            onChange={(event) => onToggleCheck?.(cle, event.target.checked)}
          />
          <span>{renderInline(reste.join('|'))}</span>
        </label>
      )
    }

    return renderTextLine(ligne, index)
  }

  return <FicheDocument items={items} texteDe={(item) => item.ligne} rendre={rendre} surtitre={surtitre} />
}

const SYNTHESE_AXES = {
  encouragement: { libelle: 'Bel élan', classe: 'badge-success' },
  a_faire: { libelle: 'Cap à tenir', classe: 'badge-warning' },
  reprise: { libelle: 'On repart', classe: 'badge-accent' },
}

const SYNTHESE_MENTION = 'Synthèse rédigée automatiquement'

function decouperSynthese(texte) {
  // Le texte de l'IA suit un plan en 5 parties numerotees ("1. Ou tu en es"
  // ... "5. Une question..."), suivies d'une mention finale. Renvoie null si
  // le plan n'est pas reconnu : l'affichage retombe alors sur le texte brut.
  const lignes = (texte || '').replace(/<br\s*\/?>/gi, '\n').split('\n').map((l) => l.trim())
  const sections = {}
  const intro = []
  let mention = ''
  let courante = null

  for (const ligne of lignes) {
    if (!ligne) continue

    const nue = ligne.replace(/[*"«»“”]/g, '').trim()

    if (nue.startsWith(SYNTHESE_MENTION)) {
      mention = nue
      courante = null
      continue
    }

    const titre = ligne.match(/^#{0,4}\s*\**\s*([1-5])[.)]\s+(.{0,80}?)\**\s*:?\s*$/)

    if (titre && !sections[titre[1]]) {
      courante = titre[1]
      sections[courante] = []
      continue
    }

    if (courante) sections[courante].push(ligne)
    else intro.push(ligne)
  }

  if (Object.keys(sections).length < 3) return null

  return { intro, sections, mention }
}

const sansPuce = (ligne) => ligne.replace(/^(?:[-•*]|\d+[.)])\s+/, '')

function SyntheseJauge({ synthese }) {
  // Realisation de la periode : fiches terminees au moment de la synthese,
  // comparees aux fiches ouvertes a ce stade (J30, J60, J90).
  const { fiches_terminees: faites, fiches_prevues: prevues, fiches_total: total, fiches_du_mois: duMois } = synthese

  if (faites == null || !prevues) return null

  const taux = Math.min(Math.round((faites / prevues) * 100), 100)
  const niveau = taux >= 100 ? 'succes' : taux >= 60 ? 'accent' : 'alerte'

  return (
    <section className={`synthese-jauge synthese-jauge-${niveau}`}>
      <div className="synthese-jauge-entete">
        <p className="synthese-bloc-titre"><Target size={16} /> Réalisation du mois {synthese.mois}</p>
        <span className="synthese-jauge-taux">{taux}%</span>
      </div>
      <div className="synthese-jauge-barre" role="progressbar" aria-valuenow={taux} aria-valuemin={0} aria-valuemax={100}>
        <span style={{ width: `${taux}%` }} />
      </div>
      <p className="synthese-jauge-detail">
        <strong>{Math.min(faites, prevues)} / {prevues}</strong> fiches prévues à J{30 * synthese.mois}
        {duMois > 0 && <> · <strong>+{duMois}</strong> ce mois</>}
        {total ? <> · {Math.min(faites, total)} / {total} sur tout le parcours</> : null}
      </p>
    </section>
  )
}

function SyntheseResultats({ resultats }) {
  // Ce que le client a pose sur la periode (phrase d'accroche, cible), repris
  // de ses fiches pour qu'il le relise avec sa synthese.
  if (!resultats?.length) return null

  return (
    <section className="synthese-resultats">
      <p className="synthese-bloc-titre"><Rocket size={16} /> Ce que tu as posé</p>
      <div className="synthese-grille">
        {resultats.map((bloc) => (
          <div key={bloc.titre} className="synthese-resultat">
            <p className="synthese-resultat-titre">{bloc.titre}</p>
            {bloc.reponses.map((reponse, index) => (
              <div key={index} className={index === 0 ? 'synthese-resultat-phare' : 'synthese-resultat-ligne'}>
                <span>{reponse.libelle}</span>
                <p>{reponse.valeur}</p>
              </div>
            ))}
          </div>
        ))}
      </div>
    </section>
  )
}

function SyntheseCard({ synthese }) {
  const parties = decouperSynthese(synthese.texte)

  if (!parties) {
    return (
      <div className="synthese">
        <SignatureIdris />
        <SyntheseJauge synthese={synthese} />
        <SyntheseResultats resultats={synthese.resultats} />
        <FicheContent texte={synthese.texte} />
      </div>
    )
  }

  const { intro, sections, mention } = parties
  const axe = SYNTHESE_AXES[synthese.axe]
  const paragraphes = (lignes = []) => lignes.map((l, i) => <p key={i}>{renderInline(sansPuce(l))}</p>)

  return (
    <div className="synthese">
      <SignatureIdris />
      {axe && <span className={`badge ${axe.classe} synthese-axe`}>{axe.libelle}</span>}
      <SyntheseJauge synthese={synthese} />
      {intro.length > 0 && <p className="synthese-intro">{renderInline(intro.join(' '))}</p>}
      <SyntheseResultats resultats={synthese.resultats} />

      <div className="synthese-grille">
        {sections[1] && (
          <section className="synthese-bloc">
            <p className="synthese-bloc-titre"><Compass size={16} /> Où tu en es</p>
            <div className="synthese-bloc-texte">{paragraphes(sections[1])}</div>
          </section>
        )}

        {sections[2] && (
          <section className="synthese-bloc synthese-bloc-succes">
            <p className="synthese-bloc-titre"><CheckCircle2 size={16} /> Ce qui avance</p>
            <ul className="synthese-liste">
              {sections[2].map((l, i) => (
                <li key={i}><CheckCircle2 size={15} /> <span>{renderInline(sansPuce(l))}</span></li>
              ))}
            </ul>
          </section>
        )}
      </div>

      {sections[3] && (
        <section className="synthese-mot">
          <Quote size={22} className="synthese-mot-icone" />
          <p className="synthese-bloc-titre"><Sparkles size={16} /> Le mot du mois</p>
          <div className="synthese-mot-texte">{paragraphes(sections[3])}</div>
        </section>
      )}

      {sections[4] && (
        <section className="synthese-actions">
          <p className="synthese-bloc-titre"><ListChecks size={16} /> Tes actions des 30 prochains jours</p>
          <ol>
            {sections[4].map((l, i) => {
              const fiche = l.match(/fiche\s+(\d+)/i)

              return (
                <li key={i} className="synthese-action">
                  <span className="synthese-action-numero">{i + 1}</span>
                  <span className="synthese-action-texte">{renderInline(sansPuce(l))}</span>
                  {fiche && <span className="badge badge-accent">Fiche {fiche[1]}</span>}
                </li>
              )
            })}
          </ol>
        </section>
      )}

      {sections[5] && (
        <section className="synthese-question">
          <MessageCircle size={18} />
          <div>
            <p className="synthese-bloc-titre">À poser au prochain point collectif</p>
            <div className="synthese-question-texte">{paragraphes(sections[5])}</div>
          </div>
        </section>
      )}

      {mention && <p className="synthese-mention">{mention}</p>}
    </div>
  )
}

function SynthesesSection({ syntheses }) {
  // Parcours Autonome : une synthese redigee tous les 30 jours. La plus
  // recente est depliee, les precedentes repliees.
  if (!syntheses?.length) return null

  const dateFr = (iso) => (iso ? new Date(iso).toLocaleDateString('fr-FR') : '')

  return (
    <>
      <h2 className="accueil-section-titre">Mes synthèses mensuelles</h2>
      {syntheses.map((synthese, index) => (
        <details key={`${synthese.mois}-${synthese.date}`} className="module-accordion" open={index === 0}>
          <summary className="module-heading">
            <ChevronDown size={16} className="module-heading-chevron" />
            <span className="module-heading-label">
              Mois {synthese.mois}{synthese.date ? ` · ${dateFr(synthese.date)}` : ''}
            </span>
          </summary>
          <SyntheseCard synthese={synthese} />
        </details>
      ))}
    </>
  )
}

// Synthese du mois en version courte sur le tableau de bord (lot D) : la
// realisation et les actions des 30 prochains jours. Le texte complet reste
// a un clic, avec les syntheses precedentes.
function SyntheseCourte({ syntheses }) {
  const [complete, setComplete] = useState(false)
  if (!syntheses?.length) return null

  const derniere = syntheses[0]
  const parties = decouperSynthese(derniere.texte)
  const intro = parties ? parties.intro.join(' ') : ''
  const actions = parties?.sections[4] || []
  const { fiches_terminees: faites, fiches_prevues: prevues } = derniere

  return (
    <>
      <section className="synthese-courte">
        <div className="synthese-courte-chiffre">
          <p className="cap-surtitre">Synthèse du mois {derniere.mois}</p>
          {faites != null && prevues > 0 && (
            <>
              <p className="synthese-courte-taux">{Math.min(faites, prevues)} / {prevues}</p>
              <p className="synthese-courte-legende">fiches prévues faites à J{30 * derniere.mois}</p>
            </>
          )}
        </div>
        <div>
          {intro && <p className="synthese-courte-intro">{renderInline(intro)}</p>}
          {actions.length > 0 && (
            <>
              <p className="synthese-courte-sous-titre">Tes actions des 30 prochains jours</p>
              <ol className="synthese-courte-actions">
                {actions.slice(0, 3).map((ligne, i) => <li key={i}>{renderInline(sansPuce(ligne))}</li>)}
              </ol>
            </>
          )}
          <button type="button" className="synthese-courte-lien" aria-expanded={complete} onClick={() => setComplete((v) => !v)}>
            {complete ? 'Masquer la synthèse complète' : 'Lire la synthèse complète'}
            <ChevronDown size={15} aria-hidden="true" className={complete ? 'resultats-chevron-ouvert' : undefined} />
          </button>
        </div>
      </section>
      {complete && <SynthesesSection syntheses={syntheses} />}
    </>
  )
}

function FicheSegments({ segments, formValues, onChange, surtitre }) {
  const rendre = (segment, index) => {
    if (segment.type === 'texte') {
      return renderTextLine(segment.texte, index)
    }

    const champ = segment.champ

    if (champ.type === 'case') {
      return (
        <label key={champ.cle} className="fiche-case">
          <input
            type="checkbox"
            checked={Boolean(formValues[champ.cle])}
            onChange={(event) => onChange(champ.cle, event.target.checked)}
          />
          <span>{champ.libelle}</span>
        </label>
      )
    }

    return (
      <div key={champ.cle} className="fiche-champ">
        <EnteteChamp Balise="p" champ={champ} value={formValues[champ.cle]} onChange={(value) => onChange(champ.cle, value)}>
          {renderInline(champ.libelle_affiche || champ.libelle)}
        </EnteteChamp>
        <FieldInput
          champ={champ}
          value={formValues[champ.cle]}
          onChange={(value) => onChange(champ.cle, value)}
        />
      </div>
    )
  }

  return (
    <FicheDocument
      items={segments}
      texteDe={(segment) => (segment.type === 'texte' ? segment.texte : '')}
      rendre={rendre}
      surtitre={surtitre}
    />
  )
}

function FicheSuivi({ ficheData, formValues, onChange, onSubmit, saving, error, estBilan }) {
  // Fiche de suivi (plan de la semaine, bilan hebdo) : les reponses se
  // saisissent sous chaque question ; le bloc du bas date l'entree et
  // l'ajoute a l'historique. Chaque enregistrement cree une nouvelle ligne.
  const places = new Set(
    ficheData.segments.filter((s) => s.type === 'champ').map((s) => s.champ.cle),
  )
  const restants = ficheData.champs.filter((champ) => !places.has(champ.cle))
  // "Semaine du (identifiant de l'entrée)" : libelle technique du schema.
  const lisible = (libelle) => libelle.replace(/\s*\(identifiant de l'entrée\)/i, '')
  const affiches = Object.fromEntries(
    ficheData.segments.filter((s) => s.type === 'champ').map((s) => [s.champ.cle, s.champ.libelle_affiche]),
  )
  const champsTableau = ficheData.champs.map((champ) => ({
    ...champ,
    libelle: champ.court || lisible(affiches[champ.cle] || champ.libelle).replace(/\s*:\s*$/, ''),
  }))

  // "Semaine du" propose d'office le lundi de la semaine en cours.
  const champSemaine = restants.find((champ) => champ.type === 'date')
  useEffect(() => {
    if (!champSemaine || formValues[champSemaine.cle]) return
    const lundi = new Date()
    lundi.setDate(lundi.getDate() - ((lundi.getDay() + 6) % 7))
    const iso = `${lundi.getFullYear()}-${String(lundi.getMonth() + 1).padStart(2, '0')}-${String(lundi.getDate()).padStart(2, '0')}`
    onChange(champSemaine.cle, iso)
  }, [champSemaine, formValues, onChange])

  return (
    <>
      {estBilan && champSemaine && (
        <SuggestionCarnet
          semaineDu={formValues[champSemaine.cle]}
          onReprendre={(totaux) => {
            onChange('nb_contacts_tentes', totaux.contacts)
            onChange('nb_rdv_obtenus', totaux.rdv)
            onChange('nb_ventes_conclues', totaux.ventes)
          }}
        />
      )}

      <FicheSegments
        surtitre={surtitreFiche(ficheData.nom)}
        segments={ficheData.segments}
        formValues={formValues}
        onChange={onChange}
      />

      <form onSubmit={onSubmit} className="fiche-section fiche-formulaire">
        <header className="fiche-section-entete">
          <Rocket size={18} className="fiche-section-icone" />
          <h2 className="fiche-section-titre">Enregistrer cette semaine</h2>
        </header>

        <p className="fiche-champ-aide">
          Réponds aux questions ci-dessus, puis enregistre. Chaque semaine ajoute une ligne
          à ton historique : tu peux revenir sur cette fiche toutes les semaines.
        </p>

        {restants.map((champ) => (
          <div key={champ.cle} className="fiche-champ">
            <EnteteChamp champ={champ} value={formValues[champ.cle]} onChange={(value) => onChange(champ.cle, value)}>
              {lisible(champ.libelle)}
            </EnteteChamp>
            <FieldInput champ={champ} value={formValues[champ.cle]} onChange={(value) => onChange(champ.cle, value)} />
          </div>
        ))}

        {error && <p className="text-sm" style={{ color: 'var(--red)' }}>{error}</p>}

        <button type="submit" disabled={saving} className="fiche-bouton disabled:opacity-60">
          {saving ? 'Enregistrement…' : 'Enregistrer ma semaine'}
        </button>
      </form>

      {ficheData.entrees.length > 0 && (
        <section className="fiche-section fiche-section-isolee">
          <header className="fiche-section-entete">
            <ListChecks size={18} className="fiche-section-icone" />
            <h2 className="fiche-section-titre">Mes semaines précédentes</h2>
          </header>
          {renderTextLine(tableSaisies(champsTableau, ficheData.entrees, null), 'saisies')}
        </section>
      )}
    </>
  )
}

const FORMULES = [
  { motif: /atelier/i, libelle: 'Formule Atelier' },
  { motif: /autonome/i, libelle: 'Formule Autonome' },
]

export function libelleFormule(parcours) {
  // Parcours vide = coaching (valeur historique des premiers clients).
  const formule = FORMULES.find((f) => f.motif.test(parcours || ''))
  return formule ? formule.libelle : 'Formule Coaching 90 jours'
}

const ILLUSTRATIONS_MODULES = [
  illustrationModule0, illustrationModule1, illustrationModule2,
  illustrationModule3, illustrationModule4, illustrationModule5,
]

// Sigles gardes en capitales quand un titre en capitales est remis en casse
// de phrase ("MON PLAN DE PROSPECTION" -> "Mon plan de prospection").
const SIGLES = /^(KPI|RDV|J\d+|CA|IA|TPE|PME|CRM|SMS)$/

function casseDePhrase(texte) {
  if (!texte || texte !== texte.toUpperCase()) return texte
  const mots = texte.toLowerCase().split(' ')
  return mots
    .map((mot, i) => {
      const brut = mot.toUpperCase().replace(/[^A-Z0-9]/g, '')
      if (SIGLES.test(brut)) return mot.toUpperCase()
      if (brut === 'EVOLUTION') return mot.replace('evolution', 'eVolution')
      return i === 0 ? mot.charAt(0).toUpperCase() + mot.slice(1) : mot
    })
    .join(' ')
}

// Libelles reels des modules (notion_service._PARCOURS et _PARCOURS_ATELIER) :
// "Démarrage · J0", "Clarifier · Module 1 · Mon offre (J4)",
// "Session 1 · Clarifier ton offre (J0)", "Bonus · Aides publiques"...
// On en tire un surtitre (etape, jalon) et un titre court.
export function lireModule(label) {
  // "\u2060" (separateur invisible) parasite certains noms Notion.
  const propre = (label || '').replace(/\u2060/g, '').trim()
  const parties = propre.split(' · ').map((p) => p.trim()).filter(Boolean)
  if (parties.length < 2) return { surtitre: 'Étape', titre: propre }

  const dernier = parties[parties.length - 1]
  if (/^J\d/.test(dernier)) {
    return { surtitre: dernier, titre: parties.slice(0, -1).join(' · ') }
  }
  const jalon = dernier.match(/^(.*?)\s*\((J[^)]*)\)$/)
  const titre = jalon ? jalon[1] : dernier
  const surtitre = [...parties.slice(0, -1), ...(jalon ? [jalon[2]] : [])].join(' · ')
  return { surtitre, titre }
}

// Croquis choisi d'apres le theme du module, un par module dans un meme
// parcours. Ordre des tests important : les sujets precis d'abord, et
// "Suivre tes prospects" est du suivi, pas de la prospection.
function illustrationDuModule(label) {
  const texte = (label || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '')
  if (/cible/.test(texte)) return illustrationCible
  if (/pitch/.test(texte)) return illustrationPitch
  if (/prix|proposition/.test(texte)) return illustrationPrix
  if (/aides/.test(texte)) return illustrationAides
  if (/planifier/.test(texte)) return illustrationSemaine
  if (/demarrage|commencer/.test(texte)) return ILLUSTRATIONS_MODULES[0]
  if (/clarifi|offre|cible|pitch|positionnement/.test(texte)) return ILLUSTRATIONS_MODULES[2]
  if (/stabilis|bilan|suivre|suivi|kpi|pilotage|aides/.test(texte)) return ILLUSTRATIONS_MODULES[5]
  if (/convertir|rendez-vous|rdv|prix|proposition/.test(texte)) return ILLUSTRATIONS_MODULES[4]
  if (/prospect|routine|planifier/.test(texte)) return ILLUSTRATIONS_MODULES[3]
  if (/diagnostic/.test(texte)) return ILLUSTRATIONS_MODULES[1]
  return ILLUSTRATIONS_MODULES[0]
}

export function lireFiche(nom) {
  const propre = sansNomClient(nom || '').trim()
  const numero = propre.match(/^(\d+)\s*[.)]\s*(.*)$/)
  return numero ? { numero: numero[1], titre: casseDePhrase(numero[2]) } : { numero: null, titre: casseDePhrase(propre) }
}

const ONGLETS = [
  { cle: 'tableau', libelle: 'Tableau de bord', icone: LayoutDashboard },
  { cle: 'parcours', libelle: 'Mon parcours', icone: IconeCarte },
  { cle: 'prospects', libelle: 'Mes prospects', icone: ListChecks },
  { cle: 'idris', libelle: 'Idris, ton assistant', icone: MessageCircle },
  { cle: 'ressources', libelle: 'Ressources', icone: BookOpen },
  { cle: 'communaute', libelle: 'Communauté', icone: Users },
  { cle: 'profil', libelle: 'Profil', icone: UserRound },
]

// Jauge circulaire du tableau de bord.
function Jauge({ pct, titre, detail }) {
  const valeur = Math.max(0, Math.min(100, Math.round(pct || 0)))
  const rayon = 34
  const circonference = 2 * Math.PI * rayon

  return (
    <div className="jauge">
      <svg viewBox="0 0 80 80" className="jauge-cercle" aria-hidden="true">
        <circle cx="40" cy="40" r={rayon} className="jauge-fond" />
        <circle
          cx="40"
          cy="40"
          r={rayon}
          className="jauge-valeur"
          strokeDasharray={circonference}
          strokeDashoffset={circonference * (1 - valeur / 100)}
        />
      </svg>
      <div>
        <p className="jauge-pct">{valeur}%</p>
        <p className="jauge-titre">{titre}</p>
        <p className="jauge-detail">{detail}</p>
      </div>
    </div>
  )
}

// Bandeau « Ton cap 90 jours » (affichage du 26/10/2026) : ou en est le
// client dans le temps, s'il suit le rythme, et son objectif. Le rythme
// (jour, etapes de la frise, fiches en retard) vient du serveur, voir
// notion_service._rythme_parcours.
// coach : meme bandeau dans l'Espace Coach, a la troisieme personne.
export function CapParcours({ rythme, objectif, fichesFaites, fichesTotal, regularite, coach = false }) {
  const jour = rythme ? rythme.jour : null
  const duree = rythme?.duree || 90
  const etapes = rythme?.etapes || []
  const enCours = jour !== null && jour >= 0 && jour <= duree
  const position = jour === null ? 0 : Math.max(0, Math.min(jour / duree, 1))
  const etapeActuelle = jour === null || jour < 0 ? null : [...etapes].reverse().find((e) => jour >= e.debut)
  const retard = rythme?.en_retard || 0
  const fini = fichesTotal > 0 && fichesFaites === fichesTotal

  const statut = fini
    ? { classe: 'cap-statut-ok', texte: 'Parcours terminé' }
    : retard > 0
      ? { classe: 'cap-statut-retard', texte: `${retard} fiche${retard > 1 ? 's' : ''} en retard` }
      : rythme ? { classe: 'cap-statut-ok', texte: 'Dans les temps' } : null

  return (
    <section className="cap">
      <div className="cap-temps">
        <p className="cap-surtitre">{duree === 90 ? (coach ? 'Son cap 90 jours' : 'Ton cap 90 jours') : (coach ? 'Son atelier' : 'Ton atelier')}</p>
        {jour === null ? (
          <p className="cap-jour">{fichesFaites}<small> / {fichesTotal} fiches</small></p>
        ) : jour < 0 ? (
          <p className="cap-jour">Bientôt<small> {coach ? 'sa' : 'ta'} session 1 dans {-jour} jour{jour < -1 ? 's' : ''}</small></p>
        ) : (
          <p className="cap-jour">Jour {jour}<small>{jour > duree ? ` · parcours de ${duree} jours bouclé` : ` sur ${duree}`}</small></p>
        )}
        <p className="cap-statut">
          {statut && <span className={`cap-statut-puce ${statut.classe}`}>{statut.texte}</span>}
          <span>{fichesFaites} fiche{fichesFaites > 1 ? 's' : ''} terminée{fichesFaites > 1 ? 's' : ''} sur {fichesTotal}</span>
        </p>
        {rythme && etapes.length > 0 && (
          <div className="cap-frise" role="img" aria-label={jour >= 0 ? `Jour ${jour} sur ${duree}, étape ${etapeActuelle?.libelle || ''}` : 'Parcours pas encore commencé'}>
            <div className="cap-frise-barre">
              <span className="cap-frise-fait" style={{ width: `${position * 100}%` }} />
              {etapes.slice(1).map((e) => (
                <span key={e.libelle} className="cap-frise-repere" style={{ left: `${(e.debut / duree) * 100}%` }} />
              ))}
              {jour >= 0 && <span className="cap-frise-moi" style={{ left: `${position * 100}%` }} />}
            </div>
            <div className="cap-frise-etapes" aria-hidden="true">
              {etapes.map((e, i) => {
                const largeur = (((etapes[i + 1]?.debut ?? duree) - e.debut) / duree) * 100
                return (
                  <span key={e.libelle} title={e.libelle} style={{ width: `${largeur}%` }} className={e === etapeActuelle ? 'cap-frise-etape-actuelle' : undefined}>
                    {largeur >= 10 ? e.libelle : ''}
                  </span>
                )
              })}
            </div>
          </div>
        )}
      </div>
      <div className="cap-objectif">
        <div>
          <p className="cap-surtitre">{coach ? 'Son objectif' : 'Ton objectif'}</p>
          {objectif ? (
            <p className="cap-objectif-texte">« {objectif} »</p>
          ) : (
            <p className="cap-objectif-vide">{coach ? "Pas encore d'objectif écrit dans la fiche 1." : "Ton objectif n'est pas encore écrit. C'est la phrase qui donne du sens à tout le reste."}</p>
          )}
        </div>
        <div className="cap-chiffres">
          <div><strong>{fichesFaites}/{fichesTotal}</strong><span>fiches terminées</span></div>
          {enCours && <div><strong>{duree - jour}</strong><span>jour{duree - jour > 1 ? 's' : ''} restant{duree - jour > 1 ? 's' : ''}</span></div>}
          {regularite && <div><strong>{regularite.serie}</strong><span>semaine{regularite.serie > 1 ? 's' : ''} de bilan d'affilée</span></div>}
        </div>
      </div>
    </section>
  )
}

function ProchaineEtape({ module, fiche, onOpen, onParcours }) {
  if (!module) {
    return (
      <section className="prochaine-etape">
        <div className="prochaine-etape-corps">
          <p className="prochaine-etape-surtitre">Parcours terminé</p>
          <h3 className="prochaine-etape-titre">Bravo, tu as terminé toutes tes fiches.</h3>
        </div>
      </section>
    )
  }

  const { surtitre, titre } = lireModule(module.label)
  const { numero, titre: titreFiche } = fiche ? lireFiche(fiche.nom) : {}
  const prioritaire = fiche?.priorite?.type === 'prioritaire'
  const verbe = fiche?.etat === 'En cours' ? 'Reprendre' : 'Commencer'
  // Pas de fiche ouverte : la suite attend son jour d'ouverture ou la fiche precedente.
  const ouverture = fiche ? null : module.fiches.find((f) => f.etat !== 'Terminé')?.acces?.match(/ouvre à (J\d+)/)?.[1]

  return (
    <section className="prochaine-etape">
      <img src={illustrationDuModule(module.label)} alt="" className="prochaine-etape-image" />
      <div className="prochaine-etape-corps">
        <p className="prochaine-etape-surtitre">Ta prochaine action{prioritaire ? ' · prioritaire' : ''}</p>
        <h3 className="prochaine-etape-titre">
          {fiche ? `${verbe} la fiche ${numero ? `${numero} : ` : ''}${titreFiche}` : titre}
        </h3>
        <p className="prochaine-etape-fiche">
          {surtitre} · {titre}.
          {prioritaire && ` C'est une fiche prioritaire pour ta zone ${fiche.priorite.zone}.`}
          {!fiche && (ouverture ? ` La prochaine fiche s'ouvre à ${ouverture}.` : ' La suite s\'ouvre dès que la fiche précédente est validée.')}
        </p>
        <div className="prochaine-etape-actions">
          {fiche && (
            <button type="button" className="fiche-bouton" onClick={() => onOpen(fiche.id)}>
              {verbe} la fiche <ChevronRight size={15} aria-hidden="true" />
            </button>
          )}
          <button type="button" className="prochaine-etape-lien" onClick={onParcours}>
            Voir mon parcours
          </button>
        </div>
      </div>
    </section>
  )
}

// Parcours adapte au diagnostic : la fiche 8 terminee designe les zones a
// travailler en priorite (notion_service._personnaliser_parcours).
function BadgePriorite({ priorite }) {
  if (!priorite) return null

  return priorite.type === 'prioritaire' ? (
    <span className="badge-priorite badge-priorite-forte" title={`Zone à travailler : ${priorite.zone}`}>Prioritaire pour toi</span>
  ) : (
    <span className="badge-priorite badge-priorite-acquis" title={`Ton point fort : ${priorite.zone}`}>Point fort</span>
  )
}

function ParcoursSurMesure({ personnalisation, fiches, onOpen }) {
  if (!personnalisation) return null

  const parId = Object.fromEntries(fiches.map((f) => [f.id, f]))
  const { zones_prioritaires: zones, zones_fortes: fortes, total, chiffres } = personnalisation

  return (
    <section className="panel sur-mesure">
      <p className="panel-eyebrow">Ton parcours sur mesure · diagnostic {total} / 15</p>
      {chiffres && (
        <p className="sur-mesure-chiffres">
          Mis à jour avec tes {chiffres.semaines} derniers bilans : {chiffres.contacts} contacts, {chiffres.rdv} rendez-vous, {chiffres.ventes} vente(s).
        </p>
      )}
      {zones.length ? (
        <>
          <p className="sur-mesure-intro">
            D'après ton diagnostic{chiffres ? ' et tes chiffres' : ''}, voici où mettre ton énergie en premier. Ces fiches portent le badge « Prioritaire pour toi » dans ton parcours.
          </p>
          <ol className="sur-mesure-zones">
            {zones.map((zone) => (
              <li key={zone.zone} className="sur-mesure-zone">
                <div className="sur-mesure-zone-entete">
                  <span className="sur-mesure-zone-nom">{zone.zone}</span>
                  <span className="sur-mesure-zone-score">{zone.score} / 3</span>
                </div>
                {zone.constat && <p className="sur-mesure-constat">D'après tes chiffres : {zone.constat}</p>}
                <p className="sur-mesure-pourquoi">{zone.pourquoi}</p>
                <ul className="sur-mesure-fiches">
                  {zone.fiches.map((id) => {
                    const fiche = parId[id]
                    if (!fiche) return null
                    const bloquee = fiche.acces?.includes('Bloqué')
                    const { numero, titre } = lireFiche(fiche.nom)

                    return (
                      <li key={id}>
                        <button type="button" disabled={bloquee} onClick={() => onOpen(id)} className="sur-mesure-fiche">
                          <span>{numero ? `${numero}. ` : ''}{titre}</span>
                          {fiche.etat === 'Terminé' ? (
                            <CheckCircle2 size={14} className="module-fiche-icone-fini" aria-label="Terminée" />
                          ) : bloquee ? (
                            <Lock size={13} aria-label="Pas encore ouverte" />
                          ) : (
                            <ChevronRight size={14} aria-hidden="true" />
                          )}
                        </button>
                      </li>
                    )
                  })}
                </ul>
              </li>
            ))}
          </ol>
        </>
      ) : (
        <p className="sur-mesure-intro">Ton diagnostic est solide sur les 5 zones : avance à ton rythme sur l'ensemble du parcours.</p>
      )}
      {fortes.length > 0 && (
        <p className="sur-mesure-fortes">Tes points forts : {fortes.join(', ')}. Les fiches liées sont marquées « Point fort » : tu peux les traiter plus vite.</p>
      )}
    </section>
  )
}

// "Avant / Maintenant" (decision de Rony du 25/10/2026) : la preuve de
// progression. Score du diagnostic de depart contre score actuel (diagnostic
// vivant, voir notion_service._scores_reels), et chaque KPI J0 contre sa
// derniere valeur connue. Rien d'affiche tant qu'il n'y a rien a comparer.
const KPI_DERNIERES = [['valeur_j90', 'J90'], ['valeur_j60', 'J60'], ['valeur_j30', 'J30']]

function Evolution({ avant, apres }) {
  const ecart = apres - avant
  if (ecart === 0) return <span className="avant-apres-ecart avant-apres-ecart-egal">=</span>
  return (
    <span className={`avant-apres-ecart ${ecart > 0 ? 'avant-apres-ecart-plus' : 'avant-apres-ecart-moins'}`}>
      {ecart > 0 ? '+' : '−'}{formaterKpi(Math.abs(ecart))}
    </span>
  )
}

function AvantMaintenant({ personnalisation, kpis }) {
  const lignesKpi = (kpis || [])
    .map((kpi) => {
      const depart = nombreOuNull(kpi.valeur_j0)
      const derniere = KPI_DERNIERES.map(([champ, periode]) => ({ periode, valeur: nombreOuNull(kpi[champ]) })).find((p) => p.valeur !== null)
      return depart === null || !derniere ? null : { nom: kpi.nom, depart, ...derniere }
    })
    .filter(Boolean)
  const diagnostic = personnalisation?.scores_diagnostic

  if (!diagnostic && !lignesKpi.length) return null

  const actuel = personnalisation?.total_actuel ?? personnalisation?.total

  return (
    <section className="panel avant-apres">
      <p className="panel-eyebrow">Avant / Maintenant</p>
      {diagnostic && (
        <>
          <div className="avant-apres-scores">
            <div>
              <p className="avant-apres-label">Au départ</p>
              <p className="avant-apres-total">{personnalisation.total}<small> / 15</small></p>
            </div>
            <ChevronRight size={22} className="avant-apres-fleche" aria-hidden="true" />
            <div>
              <p className="avant-apres-label">Aujourd'hui</p>
              <p className="avant-apres-total avant-apres-total-actuel">{actuel}<small> / 15</small></p>
            </div>
            <Evolution avant={personnalisation.total} apres={actuel} />
          </div>
          <ul className="avant-apres-lignes">
            {Object.entries(diagnostic).map(([zone, depart]) => (
              <li key={zone}>
                <span className="avant-apres-nom">{zone}</span>
                <span className="avant-apres-valeurs">{depart} → {personnalisation.scores?.[zone] ?? depart} / 3</span>
                <Evolution avant={depart} apres={personnalisation.scores?.[zone] ?? depart} />
              </li>
            ))}
          </ul>
          {!personnalisation.chiffres && (
            <p className="avant-apres-note">Remplis au moins 2 bilans hebdomadaires : ton score suivra alors tes vrais chiffres de prospection, de conversion et de suivi.</p>
          )}
        </>
      )}
      {lignesKpi.length > 0 && (
        <ul className="avant-apres-lignes">
          {lignesKpi.map((ligne) => (
            <li key={ligne.nom}>
              <span className="avant-apres-nom">{ligne.nom}</span>
              <span className="avant-apres-valeurs">{formaterKpi(ligne.depart)} (J0) → {formaterKpi(ligne.valeur)} ({ligne.periode})</span>
              <Evolution avant={ligne.depart} apres={ligne.valeur} />
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function PourquoiPourToi({ fiche, personnalisation }) {
  if (fiche?.priorite?.type !== 'prioritaire' || !personnalisation) return null

  const zone = personnalisation.zones_prioritaires.find((z) => z.zone === fiche.priorite.zone)
  if (!zone) return null

  return (
    <aside className="pourquoi-pour-toi">
      <p className="pourquoi-pour-toi-titre">Pourquoi cette fiche est prioritaire pour toi</p>
      <p>
        {zone.constat ? `D'après tes chiffres : ${zone.constat}` : `Ton diagnostic : ${zone.zone} à ${zone.score} / 3.`} {zone.pourquoi}
      </p>
    </aside>
  )
}

// Tout ce qu'Idris ecrit (retours, brouillons, entrainement, syntheses) prend
// la meme forme, une bulle sombre signee, pour que le client distingue d'un
// coup d'oeil la formation (papier clair) de l'IA (decision de Rony du
// 25/10/2026). Emblème en attendant le portrait d'Idris (croquis).
function IdrisAvatar({ taille = 44 }) {
  return (
    <span className="idris-avatar" style={{ width: taille, height: taille }} aria-hidden="true">
      <svg viewBox="0 0 34 34" width={taille * 0.66} height={taille * 0.66} fill="none" strokeWidth="1.6" strokeLinecap="round">
        <circle cx="17" cy="12" r="6" stroke="var(--brand-gold-metal)" />
        <path d="M6 31c1.5-6 6-9 11-9s9.5 3 11 9" stroke="var(--brand-gold-metal)" />
        <path d="M25 5.5l1.8-1.8M27 9.5h2.4" stroke="var(--brand-gold-champagne)" />
      </svg>
    </span>
  )
}

function IdrisMessage({ titre, meta, children }) {
  return (
    <div className="idris-message">
      <IdrisAvatar />
      <div className="idris-bulle">
        <header className="idris-bulle-entete">
          <strong>Idris</strong>
          <span className="idris-tag">Assistant IA</span>
          {titre && <span className="idris-bulle-titre">{titre}</span>}
        </header>
        {children}
        {meta && <p className="idris-bulle-meta">{meta}</p>}
      </div>
    </div>
  )
}

function SignatureIdris() {
  return <p className="synthese-signature"><IdrisAvatar taille={30} /> <strong>Idris</strong> <span className="idris-tag">Assistant IA</span></p>
}

function IdrisSeparateur({ children = 'Ton échange avec Idris' }) {
  return <p className="idris-separateur">{children}</p>
}

// Paragraphes d'un texte d'Idris ; le dernier (action de la semaine et
// encouragement, voir les prompts) est mis en avant.
function ParagraphesIdris({ texte }) {
  const paragraphes = (texte || '').split(/\n\s*\n/).filter((p) => p.trim())

  return paragraphes.map((paragraphe, index) => (
    <p key={index} className={paragraphes.length > 1 && index === paragraphes.length - 1 ? 'idris-action' : undefined}>
      {paragraphe}
    </p>
  ))
}

function RetourIA({ retour, actif }) {
  if (!actif || !retour) return null

  return (
    <section className="retour-ia" aria-label="Le retour d'Idris">
      <IdrisSeparateur />
      <IdrisMessage
        titre="Ton retour"
        meta={retour.statut === 'publie' && retour.date ? `Rédigé par Idris le ${formaterMaj(retour.date)}` : null}
      >
        {retour.statut === 'publie' ? (
          <ParagraphesIdris texte={retour.texte} />
        ) : retour.statut === 'relecture' ? (
          <p className="retour-ia-attente">J'ai rédigé ton retour, Rony le relit. Il apparaîtra ici d'ici quelques heures.</p>
        ) : (
          <p className="retour-ia-attente">
            <Loader2 size={14} className="animate-spin" aria-hidden="true" /> Je rédige ton retour personnalisé, il arrive dans un instant.
          </p>
        )}
      </IdrisMessage>
    </section>
  )
}

// Entrainement aux objections : Idris (l'assistant IA) joue un prospect, puis
// fait un retour de coach. Rien n'est enregistre, la conversation vit dans la page.
// Idris, l'assistant IA du parcours, se presente une fois en debut de
// parcours (decision de Rony du 22/10/2026). Masque des que le client l'a lu.
const IDRIS_PRESENTE_KEY = 'idris_presente'

function PresentationIdris({ nom }) {
  const [visible, setVisible] = useState(() => {
    try {
      return localStorage.getItem(IDRIS_PRESENTE_KEY) !== '1'
    } catch {
      return true
    }
  })

  if (!visible) return null

  const prenom = (nom || '').split(' ')[0]

  const fermer = () => {
    try {
      localStorage.setItem(IDRIS_PRESENTE_KEY, '1')
    } catch {
      // Navigation privee : la carte reviendra a la prochaine visite.
    }
    setVisible(false)
  }

  return (
    <section className="idris-presentation">
      <IdrisMessage titre={prenom ? `Bonjour ${prenom}, moi c'est Idris` : "Bonjour, moi c'est Idris"}>
      <p>
        Je suis l'assistant IA de ton parcours eVolution 2.0, aux côtés de Rony. Je m'appuie sur ton diagnostic
        et sur tes vrais chiffres pour t'aider là où ça compte le plus pour toi.
      </p>
      <ul>
        <li>Après chaque fiche, je te fais un retour personnalisé : ce que tu as bien fait, et pourquoi la suite compte pour toi.</li>
        <li>Sur tes fiches de rédaction (phrase de positionnement, script d'approche), je te propose un premier jet que tu corriges avec tes mots.</li>
        <li>Quand tu arrives à la vente, je joue tes prospects pour t'entraîner à répondre aux objections.</li>
      </ul>
      <p>Rony garde l'œil sur ton parcours ; moi, je suis là au quotidien. On y va ?</p>
      <button type="button" className="brouillon-ia-bouton" onClick={fermer}>Enchanté, Idris !</button>
      </IdrisMessage>
    </section>
  )
}

function BrouillonIA({ ficheId, champs, formValues, onRemplir }) {
  const [attente, setAttente] = useState(false)
  const [erreur, setErreur] = useState('')
  const [message, setMessage] = useState('')
  const [propositions, setPropositions] = useState({})

  const proposer = async () => {
    setAttente(true)
    setErreur('')
    setMessage('')

    try {
      const response = await fetch(`${API_BASE}/portal/fiches/${ficheId}/brouillon`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${localStorage.getItem(SESSION_KEY)}` },
      })

      if (response.status === 429) throw new Error("Tu as déjà demandé beaucoup de brouillons aujourd'hui : reviens demain.")
      if (!response.ok) throw new Error("Le brouillon n'est pas disponible pour le moment. Réessaie plus tard.")

      const { valeurs } = await response.json()
      const vides = {}
      const enAttente = {}

      Object.entries(valeurs || {}).forEach(([cle, texte]) => {
        if ((formValues[cle] || '').trim()) enAttente[cle] = texte
        else vides[cle] = texte
      })

      onRemplir(vides)
      setPropositions(enAttente)
      setMessage(
        Object.keys(vides).length
          ? "Brouillon ajouté dans tes champs vides. Relis-le, mets-le à ta façon, puis enregistre."
          : 'Tes champs sont déjà remplis : compare avec la proposition ci-dessous.'
      )
    } catch (err) {
      setErreur(err.message)
    } finally {
      setAttente(false)
    }
  }

  const libelle = (cle) => (champs.find((c) => c.cle === cle)?.libelle || '').replace(/\s*:\s*$/, '')

  return (
    <section className="brouillon-ia">
      <div className="brouillon-ia-entete">
        <IdrisAvatar taille={38} />
        <div>
          <p className="brouillon-ia-titre">Besoin d'un point de départ ? <span className="idris-tag">Idris · IA</span></p>
          <p className="brouillon-ia-texte">
            Idris te propose une première version à partir de ce que tu as écrit dans tes fiches précédentes. Tu la corriges avec tes mots.
          </p>
        </div>
      </div>

      <button type="button" className="brouillon-ia-bouton" onClick={proposer} disabled={attente}>
        {attente ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
        {attente ? 'Idris rédige…' : 'Demander un brouillon à Idris'}
      </button>

      {message && <p className="brouillon-ia-message">{message}</p>}
      {erreur && <p className="brouillon-ia-message" style={{ color: 'var(--red)' }}>{erreur}</p>}

      {Object.entries(propositions).map(([cle, texte]) => (
        <div key={cle} className="brouillon-ia-proposition">
          <p className="brouillon-ia-libelle">Proposition d'Idris · {libelle(cle)}</p>
          <p className="brouillon-ia-texte-propose">{texte}</p>
          <button
            type="button"
            className="brouillon-ia-remplacer"
            onClick={() => {
              onRemplir({ [cle]: texte })
              setPropositions(({ [cle]: _, ...reste }) => reste)
            }}
          >
            Remplacer ma version
          </button>
        </div>
      ))}
    </section>
  )
}

function Entrainement() {
  const [scenarios, setScenarios] = useState([])
  const [scenario, setScenario] = useState(null)
  const [messages, setMessages] = useState([])
  const [saisie, setSaisie] = useState('')
  const [retour, setRetour] = useState(null)
  const [attente, setAttente] = useState(false)
  const [erreur, setErreur] = useState('')

  useEffect(() => {
    fetch(`${API_BASE}/portal/entrainement/scenarios`, {
      headers: { Authorization: `Bearer ${localStorage.getItem(SESSION_KEY)}` },
    })
      .then((r) => (r.ok ? r.json() : { scenarios: [] }))
      .then((data) => setScenarios(data.scenarios || []))
      .catch(() => setScenarios([]))
  }, [])

  const envoyer = async (id, historique, terminer = false) => {
    setAttente(true)
    setErreur('')

    try {
      const response = await fetch(`${API_BASE}/portal/entrainement`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem(SESSION_KEY)}` },
        body: JSON.stringify({ scenario: id, messages: historique, terminer }),
      })

      if (response.status === 429) throw new Error("Tu as beaucoup pratiqué aujourd'hui : reviens demain pour continuer.")
      if (!response.ok) throw new Error("L'entraînement n'est pas disponible pour le moment. Réessaie plus tard.")

      const data = await response.json()
      if (data.role === 'coach') setRetour(data.texte)
      else setMessages([...historique, { role: 'prospect', texte: data.texte }])
    } catch (err) {
      setErreur(err.message)
    } finally {
      setAttente(false)
    }
  }

  const demarrer = (id) => {
    setScenario(id)
    setMessages([])
    setRetour(null)
    envoyer(id, [])
  }

  const repondre = (event) => {
    event.preventDefault()
    const texte = saisie.trim()
    if (!texte || attente) return
    const historique = [...messages, { role: 'client', texte }]
    setMessages(historique)
    setSaisie('')
    envoyer(scenario, historique)
  }

  if (!scenarios.length) return null

  const tours = messages.filter((m) => m.role === 'client').length

  return (
    <section className="entrainement">
      <header className="retour-ia-entete">
        <MessageCircle size={17} aria-hidden="true" />
        <h2>Entraîne-toi face à un prospect</h2>
      </header>
      <p className="entrainement-intro">
        Idris joue un prospect qui te sort une objection. Réponds comme en vrai, puis demande-lui ton retour de coach. Rien n'est enregistré.
      </p>
      <div className="entrainement-scenarios">
        {scenarios.map((s) => (
          <button
            key={s.id}
            type="button"
            className={`entrainement-scenario${scenario === s.id ? ' entrainement-scenario-actif' : ''}`}
            onClick={() => demarrer(s.id)}
            disabled={attente}
          >
            {s.titre}
          </button>
        ))}
      </div>

      {scenario && (
        <div className="entrainement-chat">
          {messages.map((m, index) => (
            <p key={index} className={`entrainement-bulle entrainement-bulle-${m.role}`}>
              <span className="entrainement-auteur">{m.role === 'prospect' ? 'Prospect (joué par Idris)' : 'Toi'}</span>
              {m.texte}
            </p>
          ))}
          {attente && <p className="retour-ia-attente"><Loader2 size={14} className="animate-spin" aria-hidden="true" /> …</p>}

          {retour ? (
            <div className="entrainement-retour">
              <IdrisMessage titre="Ton retour de coach">
                <ParagraphesIdris texte={retour} />
              </IdrisMessage>
              <button type="button" className="prochaine-etape-lien" onClick={() => demarrer(scenario)}>Recommencer</button>
            </div>
          ) : messages.length > 0 && (
            <form onSubmit={repondre} className="entrainement-saisie">
              <textarea
                value={saisie}
                onChange={(e) => setSaisie(e.target.value)}
                placeholder="Ta réponse au prospect…"
                rows={2}
                maxLength={800}
                disabled={attente}
              />
              <div className="entrainement-actions">
                <button type="submit" className="fiche-bouton" disabled={attente || !saisie.trim()}>Répondre</button>
                {tours > 0 && (
                  <button type="button" className="prochaine-etape-lien" disabled={attente} onClick={() => envoyer(scenario, messages, true)}>
                    Terminer et recevoir mon retour
                  </button>
                )}
              </div>
            </form>
          )}
          {erreur && <p className="text-sm" style={{ color: 'var(--red)' }}>{erreur}</p>}
        </div>
      )}
    </section>
  )
}

// --- Espace Idris (lot 2, decision de Rony du 25/10/2026) ---
// Questions libres de strategie commerciale, messages prets a envoyer,
// preparation de rendez-vous (Coaching) et entrainement aux objections.
async function appelIdris(chemin, corps) {
  return appelPortail(`/idris${chemin}`, corps)
}

async function appelPortail(chemin, corps) {
  const response = await fetch(`${API_BASE}/portal${chemin}`, {
    method: corps ? 'POST' : 'GET',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem(SESSION_KEY)}` },
    body: corps ? JSON.stringify(corps) : undefined,
  })
  if (!response.ok) {
    const erreur = new Error('idris')
    erreur.status = response.status
    if (response.status === 422) erreur.detail = (await response.json().catch(() => ({}))).detail
    throw erreur
  }
  return response.json()
}

const QUESTIONS_SUGGEREES = [
  'Comment fixer le prix de mon offre ?',
  'Quel canal de prospection choisir en premier ?',
  "Je n'ai eu aucun RDV cette semaine, je fais quoi ?",
]

function DemandeIdris({ etat }) {
  const [messages, setMessages] = useState([])
  const [saisie, setSaisie] = useState('')
  const [attente, setAttente] = useState(false)
  const [erreur, setErreur] = useState('')
  const [restantes, setRestantes] = useState(etat.questions_restantes)
  const finRef = useRef(null)

  useEffect(() => {
    if (messages.length) finRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [messages, attente])

  const envoyer = async (texte) => {
    const question = texte.trim()
    if (!question || attente) return
    const historique = [...messages, { role: 'client', texte: question }]
    setMessages(historique)
    setSaisie('')
    setAttente(true)
    setErreur('')

    try {
      const data = await appelIdris('/question', { messages: historique })
      setMessages([...historique, { role: 'idris', texte: data.texte }])
      setRestantes(data.questions_restantes)
    } catch (err) {
      setMessages(messages)
      setSaisie(question)
      setErreur(err.status === 429
        ? (restantes === null
          ? "Tu as posé beaucoup de questions aujourd'hui : reprends demain."
          : `Tu as utilisé tes ${etat.questions_par_mois} questions du mois : elles reviennent le 1er du mois prochain. Le Coaching 90 jours inclut des questions illimitées.`)
        : "Idris n'est pas disponible pour le moment. Réessaie dans quelques minutes.")
    } finally {
      setAttente(false)
    }
  }

  return (
    <section className="idris-espace-bloc">
      <h2 className="idris-espace-titre">Demande à Idris</h2>
      <p className="idris-espace-intro">
        Une question sur ton offre, ton prix, ta prospection ou tes rendez-vous ? Idris répond à partir de ta méthode et de tes vrais chiffres.
        {restantes === null ? ' Questions illimitées avec ton Coaching.' : ` Il te reste ${restantes} question${restantes > 1 ? 's' : ''} ce mois-ci.`}
      </p>

      <div className="idris-chat">
        <IdrisMessage>
          <p>Bonjour ! Je connais tes fiches, ton diagnostic et tes bilans. Pose-moi ta question, je te réponds avec une action concrète pour ta semaine.</p>
        </IdrisMessage>
        {messages.map((m, index) => (m.role === 'idris' ? (
          <IdrisMessage key={index}><ParagraphesIdris texte={m.texte} /></IdrisMessage>
        ) : (
          <p key={index} className="idris-question">{m.texte}</p>
        )))}
        {attente && (
          <p className="retour-ia-attente idris-attente"><Loader2 size={14} className="animate-spin" aria-hidden="true" /> Idris réfléchit…</p>
        )}
        <span ref={finRef} />
      </div>

      {messages.length === 0 && (
        <div className="idris-suggestions">
          {QUESTIONS_SUGGEREES.map((q) => (
            <button key={q} type="button" className="idris-suggestion" onClick={() => envoyer(q)} disabled={attente}>{q}</button>
          ))}
        </div>
      )}

      <form className="idris-saisie" onSubmit={(e) => { e.preventDefault(); envoyer(saisie) }}>
        <textarea
          value={saisie}
          onChange={(e) => setSaisie(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); envoyer(saisie) } }}
          placeholder="Pose ta question à Idris…"
          rows={2}
          maxLength={800}
          disabled={attente || restantes === 0}
          aria-label="Ta question à Idris"
        />
        <button type="submit" className="fiche-bouton" disabled={attente || !saisie.trim() || restantes === 0}>Envoyer</button>
      </form>
      {erreur && <p className="idris-erreur">{erreur}</p>}
      <p className="idris-mention">Idris est une IA : il peut se tromper. Pour le juridique, la fiscalité ou une grande décision, parles-en à Rony.</p>
    </section>
  )
}

function BoutonCopier({ texte }) {
  const [copie, setCopie] = useState(false)

  const copier = async () => {
    try {
      await navigator.clipboard.writeText(texte)
      setCopie(true)
      setTimeout(() => setCopie(false), 2000)
    } catch {
      setCopie(false)
    }
  }

  return (
    <button type="button" className="idris-copier" onClick={copier}>
      {copie ? <CheckCircle2 size={14} /> : <Copy size={14} />} {copie ? 'Copié' : 'Copier'}
    </button>
  )
}

function MessagesPrets({ types }) {
  const [type, setType] = useState(types[0]?.id)
  const [precision, setPrecision] = useState('')
  const [variantes, setVariantes] = useState([])
  const [attente, setAttente] = useState(false)
  const [erreur, setErreur] = useState('')

  const rediger = async (event) => {
    event.preventDefault()
    setAttente(true)
    setErreur('')

    try {
      const data = await appelIdris('/message', { type, precision })
      setVariantes(data.variantes)
    } catch (err) {
      setErreur(err.status === 429 ? "Tu as demandé beaucoup de messages aujourd'hui : reprends demain." : "Idris n'a pas pu rédiger ton message. Réessaie dans quelques minutes.")
    } finally {
      setAttente(false)
    }
  }

  return (
    <section className="idris-espace-bloc">
      <h2 className="idris-espace-titre">Messages prêts à envoyer</h2>
      <p className="idris-espace-intro">Idris rédige ton message avec tes mots, ta cible et ton offre. Tu le relis, tu l'ajustes, tu l'envoies.</p>
      <form onSubmit={rediger}>
        <div className="idris-suggestions">
          {types.map((t) => (
            <button
              key={t.id}
              type="button"
              className={`idris-suggestion${type === t.id ? ' idris-suggestion-active' : ''}`}
              aria-pressed={type === t.id}
              onClick={() => setType(t.id)}
            >
              {t.titre}
            </button>
          ))}
        </div>
        <input
          className="field-input idris-champ"
          value={precision}
          onChange={(e) => setPrecision(e.target.value)}
          maxLength={500}
          placeholder="Précision (facultatif) : à qui, dans quelle situation…"
          aria-label="Précision sur le destinataire"
        />
        <button type="submit" className="brouillon-ia-bouton" disabled={attente || !type}>
          {attente ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
          {attente ? 'Idris rédige…' : 'Rédiger mon message'}
        </button>
      </form>
      {erreur && <p className="idris-erreur">{erreur}</p>}
      {variantes.map((texte, index) => (
        <IdrisMessage key={index} titre={`Version ${index + 1}`}>
          <p className="idris-message-texte">{texte}</p>
          <BoutonCopier texte={texte} />
        </IdrisMessage>
      ))}
    </section>
  )
}

function PreparationRdv({ disponible }) {
  const [valeurs, setValeurs] = useState({ prospect: '', besoin: '', objectif: '' })
  const [preparation, setPreparation] = useState(null)
  const [attente, setAttente] = useState(false)
  const [erreur, setErreur] = useState('')

  if (!disponible) {
    return (
      <section className="idris-espace-bloc idris-verrou">
        <h2 className="idris-espace-titre"><Lock size={16} /> Préparer un rendez-vous</h2>
        <p className="idris-espace-intro">
          Avant chaque rendez-vous, Idris te prépare tes questions de découverte, les objections probables avec leurs réponses et la prochaine étape à proposer. Inclus dans le Coaching 90 jours.
        </p>
      </section>
    )
  }

  const preparer = async (event) => {
    event.preventDefault()
    setAttente(true)
    setErreur('')

    try {
      setPreparation(await appelIdris('/rdv', valeurs))
    } catch (err) {
      setErreur(err.status === 429 ? "Tu as préparé beaucoup de rendez-vous aujourd'hui : reprends demain." : "Idris n'a pas pu préparer ton rendez-vous. Réessaie dans quelques minutes.")
    } finally {
      setAttente(false)
    }
  }

  const champ = (cle, libelle, placeholder) => (
    <label className="idris-rdv-champ">
      <span>{libelle}</span>
      <textarea
        className="field-input"
        rows={2}
        maxLength={600}
        value={valeurs[cle]}
        placeholder={placeholder}
        onChange={(e) => setValeurs({ ...valeurs, [cle]: e.target.value })}
      />
    </label>
  )

  return (
    <section className="idris-espace-bloc">
      <h2 className="idris-espace-titre">Préparer un rendez-vous</h2>
      <p className="idris-espace-intro">Décris ton prospect : Idris te prépare la trame de ton rendez-vous découverte.</p>
      <form onSubmit={preparer}>
        {champ('prospect', 'Ton prospect', 'Ex. : gérante d’un salon de coiffure à Baie-Mahault, 2 salariées')}
        {champ('besoin', 'Ce que tu sais de son besoin (facultatif)', 'Ex. : agenda vide en semaine')}
        {champ('objectif', 'Ce que tu veux obtenir de ce rendez-vous (facultatif)', 'Ex. : envoyer une proposition')}
        <button type="submit" className="brouillon-ia-bouton" disabled={attente || !valeurs.prospect.trim()}>
          {attente ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
          {attente ? 'Idris prépare…' : 'Préparer mon rendez-vous'}
        </button>
      </form>
      {erreur && <p className="idris-erreur">{erreur}</p>}
      {preparation && (
        <IdrisMessage titre="Ta préparation">
          {preparation.objectif && <p><strong>Objectif :</strong> {preparation.objectif}</p>}
          <p className="idris-rdv-sous-titre">Tes questions de découverte</p>
          <ol className="idris-rdv-liste">{preparation.questions.map((q, i) => <li key={i}>{q}</li>)}</ol>
          {preparation.objections.length > 0 && (
            <>
              <p className="idris-rdv-sous-titre">Les objections probables</p>
              <ul className="idris-rdv-liste">
                {preparation.objections.map((o, i) => (
                  <li key={i}><strong>« {o.objection} »</strong><br />{o.reponse}</li>
                ))}
              </ul>
            </>
          )}
          {preparation.prochaine_etape && <p className="idris-action">Prochaine étape à proposer : {preparation.prochaine_etape}</p>}
        </IdrisMessage>
      )}
    </section>
  )
}

function EspaceIdris() {
  const [etat, setEtat] = useState(null)
  const [erreur, setErreur] = useState(false)

  useEffect(() => {
    appelIdris('').then(setEtat).catch(() => setErreur(true))
  }, [])

  if (erreur) return <p className="espace-vide">Idris n'est pas disponible pour le moment. Réessaie dans quelques minutes.</p>
  if (!etat) return <Loader2 className="animate-spin" color="var(--gold)" size={24} />
  if (!etat.disponible) return <p className="espace-vide">Idris arrive bientôt dans ton espace.</p>

  return (
    <div className="idris-espace">
      <DemandeIdris etat={etat} />
      <MessagesPrets types={etat.types_messages} />
      <PreparationRdv disponible={etat.rdv_disponible} />
      <Entrainement />
    </div>
  )
}

// --- Lot 3 (decision de Rony du 25/10/2026) : jalons, regularite, bilan J90,
// attestation de parcours et installation sur le telephone. ---
function jourDuParcours(dateDemarrage) {
  // Meme calcul que le serveur (_jour_parcours) : jours ecoules en UTC.
  if (!dateDemarrage) return null
  const debut = Date.parse(String(dateDemarrage).slice(0, 10))
  if (Number.isNaN(debut)) return null
  const maintenant = new Date()
  return Math.floor((Date.UTC(maintenant.getUTCFullYear(), maintenant.getUTCMonth(), maintenant.getUTCDate()) - debut) / 86400000)
}

function kpiAtteint(kpis, nom) {
  const kpi = (kpis || []).find((k) => (k.nom || '').toLowerCase() === nom)
  return Boolean(kpi) && ['valeur_j30', 'valeur_j60', 'valeur_j90'].some((c) => (nombreOuNull(kpi[c]) || 0) > 0)
}

const ETAPES_JALONS = ['Clarifier', 'Prospecter', 'Convertir', 'Stabiliser']

function calculerJalons(dashboard, modules) {
  const jour = jourDuParcours(dashboard.date_demarrage)
  const etapeFinie = (etape) => {
    const concernes = modules.filter((m) => m.label.startsWith(etape))
    return concernes.length > 0 && concernes.every((m) => m.fiches.every((f) => f.etat === 'Terminé'))
  }
  const serie = dashboard.regularite?.serie || 0

  return [
    { id: 'diagnostic', titre: 'Diagnostic posé', fait: Boolean(dashboard.personnalisation), bravo: 'Ton diagnostic est posé : tu sais maintenant où mettre ton énergie en premier.' },
    { id: 'j30', titre: 'Cap des 30 jours', fait: jour !== null && jour >= 30, bravo: "Un mois de parcours ! Tu as posé les bases, c'est le moment de passer à l'action terrain." },
    ...ETAPES_JALONS.map((etape) => ({
      id: `etape-${etape}`, titre: `Étape « ${etape} » terminée`, fait: etapeFinie(etape),
      bravo: `Tu as terminé toute l'étape « ${etape} ». Chaque fiche validée, c'est un outil de plus pour vendre.`,
    })),
    { id: 'rdv', titre: 'Premier rendez-vous', fait: kpiAtteint(dashboard.kpi, 'rdv'), bravo: 'Ton premier rendez-vous est dans tes chiffres. Prépare-le avec moi dans l\'onglet Idris !' },
    { id: 'vente', titre: 'Première vente', fait: kpiAtteint(dashboard.kpi, 'nouveaux clients'), bravo: 'Première vente signée ! Note ce qui a marché : c\'est ta méthode qui se met en place.' },
    { id: 'serie4', titre: "4 semaines de bilan d'affilée", fait: serie >= 4, bravo: "4 semaines de bilan d'affilée : la régularité, c'est ce qui fait la différence sur 90 jours." },
    { id: 'j60', titre: 'Cap des 60 jours', fait: jour !== null && jour >= 60, bravo: 'Deux mois de parcours : place à la conversion. Tes rendez-vous sont ta priorité.' },
    { id: 'j90', titre: 'Cap des 90 jours', fait: jour !== null && jour >= 90, bravo: 'Tu as bouclé tes 90 jours. Demande ton bilan et ton attestation de parcours !' },
  ]
}

const JALONS_VUS_KEY = 'jalons_vus'

// Jalon atteint depuis la derniere visite, fete une fois par Idris.
function useJalonAFeter(jalons) {
  const faits = jalons.filter((j) => j.fait)
  const [aFeter, setAFeter] = useState(() => {
    try {
      const brut = localStorage.getItem(JALONS_VUS_KEY)
      // Premiere visite : rien a feter, on memorise l'existant.
      if (brut === null) {
        localStorage.setItem(JALONS_VUS_KEY, JSON.stringify(faits.map((j) => j.id)))
        return null
      }
      const vus = JSON.parse(brut)
      return [...faits].reverse().find((j) => !vus.includes(j.id)) || null
    } catch {
      return null
    }
  })

  const merci = () => {
    try {
      localStorage.setItem(JALONS_VUS_KEY, JSON.stringify(faits.map((j) => j.id)))
    } catch {
      // Navigation privee : le message reviendra a la prochaine visite.
    }
    setAFeter(null)
  }

  return [aFeter, merci]
}

function Jalons({ jalons, regularite }) {
  if (!jalons.some((j) => j.fait) && !regularite) return null

  return (
    <section className="panel jalons">
      <p className="panel-eyebrow">Mes jalons</p>
      {regularite && (
        <p className="jalons-serie">
          <strong>{regularite.serie}</strong> semaine{regularite.serie > 1 ? 's' : ''} de bilan d'affilée
          <span> · {regularite.semaines} bilan{regularite.semaines > 1 ? 's' : ''} au total</span>
        </p>
      )}
      <ul className="jalons-liste">
        {jalons.map((jalon) => (
          <li key={jalon.id} className={jalon.fait ? 'jalon jalon-fait' : 'jalon'}>
            {jalon.fait ? <Award size={15} aria-hidden="true" /> : <Lock size={13} aria-hidden="true" />}
            <span>{jalon.titre}</span>
            <span className="sr-only">{jalon.fait ? ' (atteint)' : ' (à venir)'}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}

// --- Lot D (affichage du 26/10/2026) : bas du tableau de bord en version
// courte. Le detail (parcours sur mesure, tous les jalons) est dans Mon parcours. ---
function bilanDeCetteSemaine(derniere) {
  // `derniere` : la semaine du dernier bilan hebdomadaire (date ISO).
  if (!derniere) return false
  const lundi = (valeur) => {
    const date = new Date(valeur)
    date.setHours(0, 0, 0, 0)
    date.setDate(date.getDate() - ((date.getDay() + 6) % 7))
    return date.getTime()
  }
  return lundi(`${String(derniere).slice(0, 10)}T12:00:00`) === lundi(Date.now())
}

function PrioritesCourtes({ personnalisation, fiches, onOpen }) {
  const zones = personnalisation?.zones_prioritaires || []
  if (!zones.length) return null

  const parId = Object.fromEntries(fiches.map((f) => [f.id, f]))

  return (
    <div className="energie-carte">
      <p className="energie-surtitre">{zones.length > 1 ? `Tes ${zones.length} priorités` : 'Ta priorité'}, d'après ton diagnostic</p>
      <ul className="priorites">
        {zones.map((zone) => (
          <li key={zone.zone} className="priorite">
            <span className={`priorite-score${zone.score >= 2 ? ' priorite-score-moyen' : ''}`}>{zone.score}/3</span>
            <div className="priorite-texte">
              <p className="priorite-zone">{zone.zone}</p>
              <p className="priorite-constat">{zone.constat ? `D'après tes chiffres : ${zone.constat}` : zone.pourquoi}</p>
              <div className="priorite-fiches">
                {zone.fiches.map((id) => parId[id]).filter(Boolean).map((fiche) => {
                  const { numero, titre } = lireFiche(fiche.nom)
                  const faite = fiche.etat === 'Terminé'
                  const bloquee = fiche.acces?.includes('Bloqué')
                  return (
                    <button
                      key={fiche.id}
                      type="button"
                      title={titre}
                      disabled={bloquee}
                      onClick={() => onOpen(fiche.id)}
                      className={`priorite-fiche${faite ? ' priorite-fiche-faite' : ''}`}
                    >
                      {faite ? <CheckCircle2 size={12} aria-label="Terminée" /> : bloquee ? <Lock size={11} aria-label="Pas encore ouverte" /> : null}
                      {numero ? `Fiche ${numero}` : titre}
                    </button>
                  )
                })}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

function RegulariteJalons({ jalons, regularite, onVoirTout }) {
  const faits = jalons.filter((j) => j.fait)
  const prochain = jalons.find((j) => !j.fait)

  if (!faits.length && !regularite) return null

  const serie = regularite?.serie || 0
  const conseil = bilanDeCetteSemaine(regularite?.derniere)
    ? 'Bilan de cette semaine fait. Le suivant, c\'est la semaine prochaine.'
    : serie > 0
      ? `Fais ton bilan de la semaine avant dimanche pour passer à ${serie + 1}.`
      : 'Fais ton bilan de la semaine pour lancer ta série.'

  return (
    <div className="energie-carte">
      {regularite && (
        <>
          <p className="energie-surtitre">Ta régularité</p>
          <p className="regularite-serie">{serie} semaine{serie > 1 ? 's' : ''} de bilan d'affilée</p>
          <p className="regularite-conseil">{conseil}</p>
        </>
      )}
      <button type="button" className="jalons-resume" onClick={onVoirTout}>
        {faits.length > 0 && (
          <span className="jalons-medailles" aria-hidden="true">
            {faits.slice(-4).map((j) => <span key={j.id}><Award size={12} /></span>)}
          </span>
        )}
        <span className="jalons-resume-texte">
          <strong>{faits.length} jalon{faits.length > 1 ? 's' : ''} sur {jalons.length}</strong>
          {prochain && <> · prochain : {prochain.titre}</>}
        </span>
        <ChevronRight size={15} aria-hidden="true" />
      </button>
    </div>
  )
}

function OuMettreTonEnergie({ personnalisation, fiches, jalons, regularite, onOpen, onVoirJalons }) {
  const [aFeter, merci] = useJalonAFeter(jalons)
  if (!personnalisation?.zones_prioritaires?.length && !regularite && !jalons.some((j) => j.fait)) return null

  return (
    <section className="energie">
      <h2 className="resultats-titre">Où mettre ton énergie</h2>
      {aFeter && (
        <div className="jalons-fete">
          <IdrisMessage titre={`Bravo · ${aFeter.titre}`}>
            <p>{aFeter.bravo}</p>
            <button type="button" className="brouillon-ia-bouton" onClick={merci}>Merci Idris !</button>
          </IdrisMessage>
        </div>
      )}
      <div className="energie-grille">
        <PrioritesCourtes personnalisation={personnalisation} fiches={fiches} onOpen={onOpen} />
        <RegulariteJalons jalons={jalons} regularite={regularite} onVoirTout={onVoirJalons} />
      </div>
    </section>
  )
}

// Idris en une ligne, avec une proposition qui colle a l'etape du calendrier.
// La preparation de rendez-vous est reservee au Coaching : elle n'est pas
// proposee ici.
const SUGGESTIONS_IDRIS = {
  Démarrage: 'Une question sur ton diagnostic ? Je t\'explique ce qu\'il dit de ton activité.',
  Clarifier: 'Une question sur ton offre ou ta cible ? Je t\'aide à la formuler.',
  Prospecter: 'Tu veux que je prépare ton prochain message de premier contact, sur WhatsApp ou LinkedIn ?',
  Convertir: 'Un devis envoyé sans réponse ? Je t\'écris la relance.',
  Stabiliser: 'Un client content ? Je t\'aide à lui demander une recommandation.',
}

function IdrisLigne({ etape, onOuvrir }) {
  return (
    <button type="button" className="idris-ligne" onClick={onOuvrir}>
      <IdrisAvatar taille={34} />
      <span className="idris-ligne-texte">
        <strong>Idris</strong> · {SUGGESTIONS_IDRIS[etape] || 'Une question sur ta stratégie commerciale ? Prépare un message avec moi.'}
      </span>
      <span className="idris-ligne-action">Parler à Idris <ChevronRight size={14} aria-hidden="true" /></span>
    </button>
  )
}

function prochaineSession(sessions) {
  // Un point collectif reste « prochain » jusqu'a 2 h apres son debut.
  const maintenant = Date.now()
  return (sessions || []).find((s) => s.date_heure && Date.parse(s.date_heure) + 2 * 3600000 >= maintenant) || null
}

function ProchaineSession({ sessions, onVoir }) {
  const session = prochaineSession(sessions)
  if (!session) return null

  return (
    <button type="button" className="session-ligne" onClick={onVoir}>
      <CalendarDays size={16} aria-hidden="true" />
      <span className="session-ligne-texte"><strong>Prochain point collectif</strong> · {session.nom} · {dateSession(session.date_heure)}</span>
      <ChevronRight size={15} aria-hidden="true" />
    </button>
  )
}

// « Mes prochains points » (28/10/2026) : les RDV avec Rony poses dans son
// agenda, et le point suivant suggere selon le jour de parcours. Les points
// viennent de useNouveautesEleve ; un RDV nouveau ou deplace porte un badge.
function MesPoints({ points, nouveaux = [], onVu, onChange }) {
  // Ce qui etait nouveau a l'affichage le reste a l'ecran, puis devient « vu ».
  const [marques, setMarques] = useState(() => new Set())
  useEffect(() => {
    if (!points) return
    const cles = nouveaux.map(cleRdv)
    if (cles.length) setMarques((m) => new Set([...m, ...cles]))
    onVu?.()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [points])

  if (!points) return null
  const aujourdhui = maintenantLocal().slice(0, 10)
  // Tous les RDV a venir poses par Rony (dans le rythme ou non), puis le
  // prochain point suggere.
  const avenir = points.filter((p) => p.statut === 'planifie' && p.evenement)
    .sort((a, b) => a.evenement.debut.localeCompare(b.evenement.debut))
  const suivant = points.find((p) => p.statut === 'a_planifier' && p.date >= aujourdhui)
  const affiches = [...avenir.slice(0, 3), ...(suivant ? [suivant] : [])]
  if (!affiches.length) return null

  return (
    <section className="panel mes-points">
      <p className="panel-eyebrow"><CalendarDays size={14} /> Mes prochains points</p>
      <ListePoints points={affiches} nouveaux={marques} />
      {suivant && !avenir.length && <p className="mes-points-note">Rony te confirme la date et l'heure.</p>}
      {avenir.filter((p) => p.evenement.annulable && p.evenement.id).slice(0, 3).map((p) => (
        <AnnulerReservation key={p.evenement.id} evenement={p.evenement} onAnnule={onChange} />
      ))}
    </section>
  )
}

// --- Reservation d'un RDV par l'eleve (29/10/2026) : creneaux libres de Rony,
// calcules par le serveur (reservation_service). ---

const JOURS_SEMAINE = ['dimanche', 'lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi']
const MOIS_ANNEE = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre']

function jourCreneau(dateHeure) {
  const [a, m, j] = dateHeure.slice(0, 10).split('-').map(Number)
  const d = new Date(a, m - 1, j)
  return `${JOURS_SEMAINE[d.getDay()]} ${j} ${MOIS_ANNEE[m - 1]}`
}

function heureCreneau(dateHeure) {
  const [h, m] = dateHeure.slice(11, 16).split(':')
  return `${Number(h)} h${m === '00' ? '' : ` ${m}`}`
}

async function appelReservation(chemin, options = {}) {
  try {
    const res = await fetch(`${API_BASE}${chemin}`, {
      ...options,
      headers: {
        Authorization: `Bearer ${localStorage.getItem(SESSION_KEY)}`,
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      },
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) return { erreur: typeof data.detail === 'string' ? data.detail : 'Réservation momentanément indisponible. Réessaie dans quelques minutes.' }
    return { data }
  } catch {
    return { erreur: 'Connexion impossible. Vérifie le réseau et réessaie.' }
  }
}

function AnnulerReservation({ evenement, onAnnule }) {
  const [confirmer, setConfirmer] = useState(false)
  const [envoi, setEnvoi] = useState(false)
  const [erreur, setErreur] = useState('')

  const annuler = async () => {
    setEnvoi(true)
    setErreur('')
    const r = await appelReservation(`/portal/creneaux/${encodeURIComponent(evenement.id)}`, { method: 'DELETE' })
    setEnvoi(false)
    if (r.erreur) { setErreur(r.erreur); return }
    onAnnule?.()
  }

  return (
    <div className="reserver-annuler">
      {!confirmer ? (
        <button type="button" className="reserver-lien" onClick={() => setConfirmer(true)}>
          Annuler mon RDV du {jourCreneau(evenement.debut)}
        </button>
      ) : (
        <p className="reserver-confirmation">
          Annuler ton RDV du {jourCreneau(evenement.debut)} à {heureCreneau(evenement.debut)} ?
          <button type="button" className="resultats-bouton" onClick={annuler} disabled={envoi}>{envoi ? 'Annulation…' : 'Oui, annuler'}</button>
          <button type="button" className="reserver-lien" onClick={() => setConfirmer(false)} disabled={envoi}>Garder mon RDV</button>
        </p>
      )}
      {erreur && <p className="reserver-erreur">{erreur}</p>}
    </div>
  )
}

function ReserverRdv({ points, onReserve }) {
  const [etat, setEtat] = useState(null)
  const [ouvert, setOuvert] = useState(false)
  const [choix, setChoix] = useState(null)
  const [envoi, setEnvoi] = useState(false)
  const [erreur, setErreur] = useState('')
  const [fait, setFait] = useState(null)

  const relire = useCallback(async () => {
    const r = await appelReservation('/portal/creneaux')
    setEtat(r.data || { possible: false, raison: 'indisponible', creneaux: [] })
  }, [])

  // Relu quand les points changent (RDV pose ou annule, par Rony ou par l'eleve).
  useEffect(() => { if (points) relire() }, [points, relire])

  const parJour = useMemo(() => {
    const groupes = []
    for (const c of etat?.creneaux || []) {
      const jour = c.debut.slice(0, 10)
      const dernier = groupes[groupes.length - 1]
      if (dernier?.jour === jour) dernier.creneaux.push(c)
      else groupes.push({ jour, creneaux: [c] })
    }
    return groupes
  }, [etat])

  const reserver = async () => {
    setEnvoi(true)
    setErreur('')
    const r = await appelReservation('/portal/creneaux', { method: 'POST', body: JSON.stringify({ debut: choix.debut }) })
    setEnvoi(false)
    if (r.erreur) {
      setErreur(r.erreur)
      setChoix(null)
      relire()
      return
    }
    setFait(r.data)
    setChoix(null)
    setOuvert(false)
    onReserve?.()
  }

  if (fait) {
    return (
      <section className="panel reserver-rdv">
        <p className="panel-eyebrow"><CheckCircle2 size={14} /> RDV réservé</p>
        <p className="reserver-texte">C'est noté : {jourCreneau(fait.debut)} à {heureCreneau(fait.debut)}. Rony le retrouve dans son agenda.</p>
        <button type="button" className="reserver-lien" onClick={() => setFait(null)}>OK</button>
      </section>
    )
  }

  // Formule sans RDV individuel ou agenda indisponible : rien a montrer. RDV
  // deja pose ou plus de creneau : le bloc reste, avec la raison (29/10/2026).
  if (!etat || !(etat.possible || ['complet', 'deja'].includes(etat.raison))) return null

  return (
    <section className="panel reserver-rdv">
      <p className="panel-eyebrow"><CalendarDays size={14} /> Réserver un RDV avec Rony</p>
      {etat.raison === 'deja' ? (
        <p className="reserver-texte">Ton prochain RDV avec Rony est déjà posé (voir « Mes prochains points »). Tu pourras réserver le suivant une fois ce RDV passé.</p>
      ) : etat.raison === 'complet' ? (
        <p className="reserver-texte">Pas de créneau libre dans les 3 prochaines semaines. Écris à Rony pour trouver un moment.</p>
      ) : !ouvert ? (
        <>
          <p className="reserver-texte">Choisis toi-même ton prochain RDV ({etat.duree} min) parmi les créneaux libres de Rony.</p>
          <button type="button" className="resultats-bouton" onClick={() => setOuvert(true)}>Voir les créneaux</button>
        </>
      ) : (
        <>
          {parJour.map((g) => (
            <div key={g.jour} className="reserver-jour">
              <p className="reserver-jour-nom">{jourCreneau(g.jour)}</p>
              <div className="agenda-libres-choix">
                {g.creneaux.map((c) => (
                  <button
                    key={c.debut}
                    type="button"
                    className={`agenda-libre-puce${choix?.debut === c.debut ? ' agenda-libre-puce-active' : ''}`}
                    onClick={() => { setChoix(c); setErreur('') }}
                  >
                    {heureCreneau(c.debut)}
                  </button>
                ))}
              </div>
            </div>
          ))}
          {choix ? (
            <p className="reserver-confirmation">
              {jourCreneau(choix.debut)} à {heureCreneau(choix.debut)}, {etat.duree} min.
              <button type="button" className="resultats-bouton" onClick={reserver} disabled={envoi}>{envoi ? 'Réservation…' : 'Confirmer ce RDV'}</button>
            </p>
          ) : (
            <p className="mes-points-note">Touche un horaire pour le choisir. Tu pourras annuler jusqu'à 24 h avant.</p>
          )}
          <button type="button" className="reserver-lien" onClick={() => { setOuvert(false); setChoix(null) }}>Fermer</button>
        </>
      )}
      {erreur && <p className="reserver-erreur">{erreur}</p>}
    </section>
  )
}

// Retours d'Idris pas encore lus, en tete de « Mon parcours ».
function NouveauxRetoursIdris({ retours, fiches, onOpen }) {
  const parFiche = [...new Set(retours.map((r) => r.fiche_id).filter(Boolean))]
    .map((id) => (fiches || []).find((f) => f.id === id))
    .filter(Boolean)
  if (!parFiche.length) return null

  return (
    <section className="panel nouveaux-retours">
      <p className="panel-eyebrow"><MessageCircle size={14} /> Idris t'a répondu</p>
      <ul className="nouveaux-retours-liste">
        {parFiche.map((f) => (
          <li key={f.id}>
            <button type="button" className="session-ligne" onClick={() => onOpen(f.id)}>
              <span className="badge-nouveau">Nouveau</span>
              <span className="session-ligne-texte">{lireFiche(f.nom).titre || 'Ta fiche'}</span>
              <ChevronRight size={15} aria-hidden="true" />
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

function etapeDuCalendrier(rythme) {
  if (!rythme || rythme.jour < 0 || rythme.jour > rythme.duree) return null
  return [...(rythme.etapes || [])].reverse().find((e) => rythme.jour >= e.debut)?.libelle || null
}

function bilanFinalOuvert(dashboard) {
  const jour = jourDuParcours(dashboard.date_demarrage)
  return dashboard.fiches.length > 0 && (dashboard.fiches.every((f) => f.etat === 'Terminé') || (jour !== null && jour >= 80))
}

function BilanFinal({ onAttestation }) {
  const [texte, setTexte] = useState('')
  const [attente, setAttente] = useState(false)
  const [erreur, setErreur] = useState('')

  const demander = async () => {
    setAttente(true)
    setErreur('')

    try {
      const response = await fetch(`${API_BASE}/portal/bilan-j90`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${localStorage.getItem(SESSION_KEY)}` },
      })
      if (!response.ok) throw new Error(response.status === 429 ? "Tu as déjà demandé plusieurs bilans aujourd'hui : reviens demain." : "Ton bilan n'est pas disponible pour le moment. Réessaie dans quelques minutes.")
      setTexte((await response.json()).texte)
    } catch (err) {
      setErreur(err.message)
    } finally {
      setAttente(false)
    }
  }

  return (
    <section className="panel bilan-final">
      <p className="panel-eyebrow">Fin de parcours</p>
      <h3 className="bilan-final-titre">Ton bilan des 90 jours</h3>
      <p className="bilan-final-intro">Idris rédige le bilan de ton parcours à partir de tes vrais chiffres, et tu peux télécharger ton attestation de parcours.</p>
      <div className="bilan-final-actions">
        <button type="button" className="brouillon-ia-bouton" onClick={demander} disabled={attente}>
          {attente ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
          {attente ? 'Idris rédige…' : texte ? 'Rédiger à nouveau' : 'Demander mon bilan à Idris'}
        </button>
        <button type="button" className="fiche-bouton" onClick={onAttestation}>
          <Award size={16} /> Mon attestation de parcours
        </button>
      </div>
      {erreur && <p className="idris-erreur">{erreur}</p>}
      {texte && (
        <IdrisMessage titre="Ton bilan des 90 jours">
          <ParagraphesIdris texte={texte} />
        </IdrisMessage>
      )}
    </section>
  )
}

function dateLongue(valeur) {
  const date = valeur ? new Date(valeur) : new Date()
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' })
}

// Attestation de parcours : imprimable ou enregistrable en PDF depuis le
// navigateur. Elle ne reprend que des donnees du portail, et le dit.
function Attestation({ dashboard, modules, onRetour }) {
  const fichesFaites = dashboard.fiches.filter((f) => f.etat === 'Terminé').length
  const modulesFaits = modules.filter((m) => m.fiches.every((f) => f.etat === 'Terminé')).length
  const perso = dashboard.personnalisation
  const prenom = (dashboard.nom || '').split(' ')[0]
  const lignesKpi = (dashboard.kpi || [])
    .map((kpi) => {
      const depart = nombreOuNull(kpi.valeur_j0)
      const derniere = KPI_DERNIERES.map(([champ, periode]) => ({ periode, valeur: nombreOuNull(kpi[champ]) })).find((p) => p.valeur !== null)
      return depart === null || !derniere ? null : `${kpi.nom} : ${formaterKpi(depart)} à J0, ${formaterKpi(derniere.valeur)} à ${derniere.periode}`
    })
    .filter(Boolean)

  return (
    <div className="attestation-page">
      <div className="attestation-barre no-print">
        <button type="button" className="prochaine-etape-lien" onClick={onRetour}><ArrowLeft size={15} /> Retour</button>
        <button type="button" className="fiche-bouton" onClick={() => window.print()}><Printer size={16} /> Imprimer ou enregistrer en PDF</button>
      </div>
      <article className="attestation">
        <img src={logo} alt="RL-eVolution" className="attestation-logo" />
        <p className="attestation-surtitre">Système eVolution 2.0</p>
        <h1>Attestation de parcours</h1>
        <p className="attestation-texte">
          RL-eVolution atteste que <strong>{dashboard.nom}</strong> a suivi le parcours d'accompagnement commercial
          eVolution 2.0, {libelleFormule(dashboard.parcours)}
          {dashboard.date_demarrage ? `, démarré le ${dateLongue(dashboard.date_demarrage)}` : ''}.
        </p>
        <div className="attestation-chiffres">
          <div><strong>{fichesFaites}</strong><span>fiches validées sur {dashboard.fiches.length}</span></div>
          <div><strong>{modulesFaits}</strong><span>modules terminés sur {modules.length}</span></div>
          {perso?.scores_diagnostic && (
            <div><strong>{perso.total} → {perso.total_actuel ?? perso.total}</strong><span>score de diagnostic sur 15</span></div>
          )}
          {dashboard.regularite?.semaines > 0 && (
            <div><strong>{dashboard.regularite.semaines}</strong><span>bilans hebdomadaires</span></div>
          )}
        </div>
        {lignesKpi.length > 0 && (
          <ul className="attestation-kpi">{lignesKpi.map((ligne) => <li key={ligne}>{ligne}</li>)}</ul>
        )}
        <p className="attestation-note">Chiffres issus de l'espace eVolution 2.0 de {prenom || 'ce participant'}, tels qu'il les a saisis.</p>
        <div className="attestation-pied">
          <p>Délivrée le {dateLongue()}</p>
          <p className="attestation-signature">Rony<br /><span>Coach, RL-eVolution</span></p>
        </div>
      </article>
    </div>
  )
}

// Installation sur le telephone : bouton natif quand le navigateur le
// propose (Android, Chrome), sinon la marche a suivre (iPhone, Safari).
function InstallerAppli() {
  const { invite, installee } = useInstallation()

  if (installee) return null

  return (
    <section className="panel installer-appli">
      <p className="panel-eyebrow"><Smartphone size={14} /> Ton espace sur ton téléphone</p>
      <p className="panel-lead">Ajoute eVolution 2.0 sur ton écran d'accueil : tu l'ouvres en un geste, comme une application.</p>
      {invite ? (
        <button type="button" className="fiche-bouton" onClick={installer}>
          Installer l'application
        </button>
      ) : (
        <ul className="installer-etapes">
          <li><strong>iPhone (Safari) :</strong> touche le bouton Partager, puis « Sur l'écran d'accueil ».</li>
          <li><strong>Android (Chrome) :</strong> touche le menu ⋮, puis « Installer l'application » ou « Ajouter à l'écran d'accueil ».</li>
        </ul>
      )}
    </section>
  )
}

// Bibliotheque de modeles (lot 4) : une base par metier, pre-remplie avec les
// mots du client ; Idris peut reecrire un modele entier avec ses fiches.
function ModeleBibliotheque({ modele, metier, iaDisponible }) {
  const [texte, setTexte] = useState(null)
  const [attente, setAttente] = useState(false)
  const [erreur, setErreur] = useState('')

  const personnaliser = async () => {
    setAttente(true)
    setErreur('')

    try {
      setTexte((await appelPortail('/bibliotheque/personnaliser', { modele: modele.id, metier })).texte)
    } catch (err) {
      setErreur(err.status === 429 ? "Tu as beaucoup demandé à Idris aujourd'hui : reprends demain." : "Idris n'a pas pu adapter ce modèle. Réessaie dans quelques minutes.")
    } finally {
      setAttente(false)
    }
  }

  return (
    <li className="biblio-modele">
      <header className="biblio-modele-entete">
        <strong>{modele.titre}</strong>
        <span className="biblio-canal">{modele.canal}</span>
      </header>
      <p className="biblio-texte">{modele.texte}</p>
      <div className="biblio-actions">
        <BoutonCopier texte={modele.texte} />
        {iaDisponible && (
          <button type="button" className="idris-copier" onClick={personnaliser} disabled={attente}>
            {attente ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />} {attente ? 'Idris adapte…' : 'Adapter avec Idris'}
          </button>
        )}
      </div>
      {erreur && <p className="idris-erreur">{erreur}</p>}
      {texte && (
        <IdrisMessage titre="Ta version">
          <p className="idris-message-texte">{texte}</p>
          <BoutonCopier texte={texte} />
        </IdrisMessage>
      )}
    </li>
  )
}

function Bibliotheque() {
  const [contenu, setContenu] = useState(null)
  const [metier, setMetier] = useState(null)
  const [categorie, setCategorie] = useState(null)
  const [erreur, setErreur] = useState(false)

  useEffect(() => {
    let actif = true
    appelPortail(`/bibliotheque${metier ? `?metier=${metier}` : ''}`)
      .then((data) => {
        if (!actif) return
        setContenu(data)
        setCategorie((c) => c || data.categories[0])
      })
      .catch(() => actif && setErreur(true))
    return () => { actif = false }
  }, [metier])

  if (erreur) return <section className="panel"><p className="espace-vide">Ta bibliothèque n'est pas disponible pour le moment. Réessaie dans quelques minutes.</p></section>
  if (!contenu) return <section className="panel"><Loader2 className="animate-spin" color="var(--gold)" size={22} /></section>

  const modeles = contenu.modeles.filter((m) => m.categorie === categorie)

  return (
    <section className="panel biblio">
      <p className="panel-eyebrow"><Library size={14} /> Ma bibliothèque de modèles</p>
      <p className="panel-lead">
        Scripts, messages et trames prêts à copier, pour ton métier.
        {contenu.personnalise_avec.length > 0
          ? ' Ils sont déjà remplis avec les mots de tes fiches.'
          : ' Remplis ta phrase de positionnement : tes modèles reprendront tes propres mots.'}
      </p>
      <label className="biblio-metier">
        <span>Mon métier</span>
        <select className="field-input" value={contenu.metier} onChange={(e) => setMetier(e.target.value)}>
          {contenu.metiers.map((m) => <option key={m.id} value={m.id}>{m.libelle}</option>)}
        </select>
      </label>
      <div className="idris-suggestions" role="tablist" aria-label="Catégories de modèles">
        {contenu.categories.map((c) => (
          <button key={c} type="button" role="tab" aria-selected={c === categorie} className={`idris-suggestion${c === categorie ? ' idris-suggestion-active' : ''}`} onClick={() => setCategorie(c)}>
            {c}
          </button>
        ))}
      </div>
      <ul className="biblio-liste">
        {modeles.map((m) => <ModeleBibliotheque key={`${contenu.metier}-${m.id}`} modele={m} metier={contenu.metier} iaDisponible={contenu.personnalisation_ia} />)}
      </ul>
    </section>
  )
}

// --- Carnet de prospects vivant (27/10/2026) ---------------------------------
// Un prospect par ligne, 4 statuts, une date de relance. Chaque changement de
// statut est date : le bilan hebdo peut reprendre les chiffres de la semaine.
const BILAN_HEBDO_MASTER_ID = '39ffaffd875880708581d60c234aab45'
const CLASSE_STATUT = { 'À contacter': 'a-contacter', 'Contacté': 'contacte', RDV: 'rdv', Client: 'client' }

function isoDuJour(decalage = 0) {
  const d = new Date()
  d.setDate(d.getDate() + decalage)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function dateRelance(iso) {
  if (!iso) return ''
  if (iso === isoDuJour()) return "aujourd'hui"
  if (iso === isoDuJour(1)) return 'demain'
  const date = new Date(`${iso}T12:00:00`)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleDateString('fr-FR', { weekday: 'short', day: 'numeric', month: 'short' })
}

// Meme regle que le serveur (fidelite_service.numero_whatsapp).
const INDICATIFS = [[['0690', '0691', '0590'], '590'], [['0696', '0697', '0596'], '596'], [['0694', '0594'], '594'], [['0692', '0693', '0262', '0639', '0269'], '262']]

function numeroWhatsApp(contact) {
  const brut = String(contact || '').trim()
  if (!/^[+0-9][0-9 .()-]{7,}$/.test(brut)) return null
  let chiffres = brut.replace(/\D/g, '')
  if (brut.startsWith('00')) chiffres = chiffres.slice(2)
  else if (!brut.startsWith('+')) {
    if (chiffres.length !== 10 || !chiffres.startsWith('0')) return null
    const indicatif = INDICATIFS.find(([prefixes]) => prefixes.some((p) => chiffres.startsWith(p)))?.[1] || '33'
    chiffres = indicatif + chiffres.slice(1)
  }
  return chiffres.length >= 10 && chiffres.length <= 15 ? chiffres : null
}

// Totaux d'une semaine (lundi au dimanche) d'apres les dates du carnet.
function totauxCarnet(prospects, lundiIso) {
  const totaux = { contacts: 0, rdv: 0, ventes: 0 }
  if (!lundiIso) return totaux
  const fin = new Date(`${lundiIso}T12:00:00`)
  fin.setDate(fin.getDate() + 6)
  const finIso = `${fin.getFullYear()}-${String(fin.getMonth() + 1).padStart(2, '0')}-${String(fin.getDate()).padStart(2, '0')}`
  const cle = { 'Contacté': 'contacts', RDV: 'rdv', Client: 'ventes' }
  for (const prospect of prospects || []) {
    for (const ev of prospect.evenements || []) {
      if (ev.date >= lundiIso && ev.date <= finIso && cle[ev.statut]) totaux[cle[ev.statut]] += 1
    }
  }
  return totaux
}

async function actionCarnet(action, id, prospect) {
  return appelPortail('/prospects', { action, id, prospect })
}

function MessagePretProspect({ prospect, categorie, modeles }) {
  const choix = (modeles || []).filter((m) => m.categorie === categorie).slice(0, 2)
  const numero = numeroWhatsApp(prospect.contact)

  if (!modeles) return <p className="carnet-aide"><Loader2 size={14} className="animate-spin" /> Je prépare tes modèles…</p>
  if (!choix.length) return <p className="carnet-aide">Pas encore de modèle pour cette étape dans ta bibliothèque.</p>

  return (
    <ul className="carnet-modeles">
      {choix.map((m) => (
        <li key={m.id}>
          <p className="carnet-modele-titre">{m.titre} <span className="biblio-canal">{m.canal}</span></p>
          <p className="biblio-texte">{m.texte}</p>
          <div className="biblio-actions">
            <BoutonCopier texte={m.texte} />
            {numero && (
              <a className="idris-copier" href={`https://wa.me/${numero}?text=${encodeURIComponent(m.texte)}`} target="_blank" rel="noreferrer">
                <MessageCircle size={14} /> Ouvrir dans WhatsApp
              </a>
            )}
          </div>
        </li>
      ))}
    </ul>
  )
}

function LigneProspect({ prospect, statuts, categories, aRelancer, modeles, onModeles, onAction }) {
  const [edition, setEdition] = useState(false)
  const [message, setMessage] = useState(false)
  const [suppression, setSuppression] = useState(false)
  const [brouillon, setBrouillon] = useState({ nom: prospect.nom, contact: prospect.contact || '', note: prospect.note || '' })

  const enregistrer = async (event) => {
    event.preventDefault()
    if (await onAction('modifier', prospect.id, brouillon)) setEdition(false)
  }

  return (
    <li className={`carnet-ligne${aRelancer ? ' carnet-ligne-relance' : ''}`}>
      {edition ? (
        <form className="carnet-edition" onSubmit={enregistrer}>
          <input className="field-input" value={brouillon.nom} maxLength={80} required aria-label="Nom" onChange={(e) => setBrouillon((b) => ({ ...b, nom: e.target.value }))} />
          <input className="field-input" value={brouillon.contact} maxLength={80} placeholder="Téléphone ou e-mail" aria-label="Contact" onChange={(e) => setBrouillon((b) => ({ ...b, contact: e.target.value }))} />
          <textarea className="field-input" value={brouillon.note} maxLength={300} rows={2} placeholder="Note (ce qu'il t'a dit, ce que tu dois lui envoyer…)" aria-label="Note" onChange={(e) => setBrouillon((b) => ({ ...b, note: e.target.value }))} />
          <div className="biblio-actions">
            <button type="submit" className="fiche-bouton">Enregistrer</button>
            <button type="button" className="idris-copier" onClick={() => setEdition(false)}>Annuler</button>
          </div>
        </form>
      ) : (
        <>
          <header className="carnet-ligne-entete">
            <div>
              <strong className="carnet-nom">{prospect.nom}</strong>
              {prospect.contact && <span className="carnet-contact">{prospect.contact}</span>}
            </div>
            <select
              className={`carnet-statut carnet-statut-${CLASSE_STATUT[prospect.statut] || 'a-contacter'}`}
              value={prospect.statut}
              aria-label={`Statut de ${prospect.nom}`}
              onChange={(e) => onAction('modifier', prospect.id, { statut: e.target.value })}
            >
              {statuts.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </header>
          {prospect.note && <p className="carnet-note">{prospect.note}</p>}
          <div className="carnet-relance">
            <label>
              <CalendarDays size={14} aria-hidden="true" />
              <span>{prospect.statut === 'Client' ? 'Prochain contact' : 'Relance'}</span>
              <input
                type="date"
                className="field-input"
                value={prospect.relance || ''}
                onChange={(e) => onAction('modifier', prospect.id, { relance: e.target.value || null })}
              />
            </label>
            {prospect.relance && <span className={aRelancer ? 'carnet-echeance carnet-echeance-due' : 'carnet-echeance'}>{aRelancer ? `À faire (${dateRelance(prospect.relance)})` : dateRelance(prospect.relance)}</span>}
          </div>
          <div className="biblio-actions">
            {prospect.statut !== 'Client' && (
              <button type="button" className="idris-copier" onClick={() => onAction('relance', prospect.id, { relance: isoDuJour(3) })}>
                <CheckCircle2 size={14} /> J'ai relancé
              </button>
            )}
            <button type="button" className="idris-copier" onClick={() => { setMessage((v) => !v); onModeles() }}>
              <Sparkles size={14} /> Message prêt
            </button>
            <button type="button" className="idris-copier" onClick={() => setEdition(true)}>Modifier</button>
            {suppression ? (
              <button type="button" className="idris-copier carnet-supprimer" onClick={() => onAction('supprimer', prospect.id)}>Confirmer la suppression</button>
            ) : (
              <button type="button" className="idris-copier" onClick={() => setSuppression(true)}>Supprimer</button>
            )}
          </div>
          {message && <MessagePretProspect prospect={prospect} categorie={categories[prospect.statut]} modeles={modeles} />}
        </>
      )}
    </li>
  )
}

function CarnetProspects() {
  const [carnet, setCarnet] = useState(null)
  const [erreur, setErreur] = useState('')
  const [chargement, setChargement] = useState(true)
  const [filtre, setFiltre] = useState('tous')
  const [nouveau, setNouveau] = useState({ nom: '', contact: '', relance: '' })
  const [modeles, setModeles] = useState(null)
  const [enCours, setEnCours] = useState(false)

  useEffect(() => {
    let actif = true
    appelPortail('/prospects')
      .then((data) => {
        if (!actif) return
        setCarnet(data)
        if (data.a_relancer.length) setFiltre('relancer')
      })
      .catch(() => actif && setErreur("Ton carnet n'est pas disponible pour le moment. Réessaie dans quelques minutes."))
      .finally(() => actif && setChargement(false))
    return () => { actif = false }
  }, [])

  const chargerModeles = () => {
    if (modeles) return
    appelPortail('/bibliotheque').then((data) => setModeles(data.modeles)).catch(() => setModeles([]))
  }

  const agir = async (action, id, prospect) => {
    setErreur('')
    setEnCours(true)
    try {
      setCarnet(await actionCarnet(action, id, prospect))
      return true
    } catch (err) {
      setErreur(err.detail || "L'enregistrement n'a pas marché. Réessaie dans un instant.")
      return false
    } finally {
      setEnCours(false)
    }
  }

  const ajouter = async (event) => {
    event.preventDefault()
    if (await agir('ajouter', null, { nom: nouveau.nom, contact: nouveau.contact, relance: nouveau.relance || null, statut: 'À contacter' })) {
      setNouveau({ nom: '', contact: '', relance: '' })
      setFiltre('tous')
    }
  }

  if (chargement) return <section className="panel"><Loader2 className="animate-spin" color="var(--gold)" size={22} /></section>
  if (!carnet) return <section className="panel"><p className="espace-vide">{erreur}</p></section>

  const aRelancer = new Set(carnet.a_relancer)
  const visibles = carnet.prospects.filter((p) => (filtre === 'tous' ? true : filtre === 'relancer' ? aRelancer.has(p.id) : p.statut === filtre))
  const semaine = carnet.semaine

  return (
    <section className="panel carnet">
      <p className="panel-eyebrow"><ListChecks size={14} /> Mon carnet de prospects</p>
      <p className="panel-lead">Un prospect par ligne et une date de relance. Ton espace te rappelle qui relancer, et ton bilan de la semaine reprend tes chiffres.</p>

      {carnet.importe && (
        <p className="carnet-aide">J'ai repris les prospects de ta fiche « Mon tableau de prospection ». Ils seront enregistrés dans ton carnet dès ta première modification.</p>
      )}

      <p className="carnet-semaine">
        Cette semaine : <strong>{semaine.contacts}</strong> contact{semaine.contacts > 1 ? 's' : ''}, <strong>{semaine.rdv}</strong> RDV, <strong>{semaine.ventes}</strong> client{semaine.ventes > 1 ? 's' : ''} gagné{semaine.ventes > 1 ? 's' : ''}.
      </p>

      <form className="carnet-ajout" onSubmit={ajouter}>
        <input className="field-input" placeholder="Nom du prospect" value={nouveau.nom} maxLength={80} required aria-label="Nom du prospect" onChange={(e) => setNouveau((n) => ({ ...n, nom: e.target.value }))} />
        <input className="field-input" placeholder="Téléphone ou e-mail" value={nouveau.contact} maxLength={80} aria-label="Téléphone ou e-mail" onChange={(e) => setNouveau((n) => ({ ...n, contact: e.target.value }))} />
        <label className="carnet-ajout-date">
          <span>À contacter le</span>
          <input type="date" className="field-input" value={nouveau.relance} onChange={(e) => setNouveau((n) => ({ ...n, relance: e.target.value }))} />
        </label>
        <button type="submit" className="fiche-bouton" disabled={enCours}>Ajouter</button>
      </form>

      {erreur && <p className="idris-erreur">{erreur}</p>}

      <div className="idris-suggestions" role="tablist" aria-label="Filtrer mon carnet">
        {[
          ['relancer', `À relancer (${carnet.a_relancer.length})`],
          ...carnet.statuts.map((s) => [s, `${s} (${carnet.par_statut[s] || 0})`]),
          ['tous', `Tous (${carnet.prospects.length})`],
        ].map(([cle, libelle]) => (
          <button key={cle} type="button" role="tab" aria-selected={filtre === cle} className={`idris-suggestion${filtre === cle ? ' idris-suggestion-active' : ''}`} onClick={() => setFiltre(cle)}>
            {libelle}
          </button>
        ))}
      </div>

      {visibles.length ? (
        <ul className="carnet-liste">
          {visibles.map((p) => (
            <LigneProspect
              key={`${p.id}-${p.statut}-${p.relance}-${p.nom}-${p.contact}-${p.note}`}
              prospect={p}
              statuts={carnet.statuts}
              categories={carnet.categories}
              aRelancer={aRelancer.has(p.id)}
              modeles={modeles}
              onModeles={chargerModeles}
              onAction={agir}
            />
          ))}
        </ul>
      ) : (
        <p className="espace-vide">
          {carnet.prospects.length ? 'Personne dans cette liste pour le moment.' : 'Ton carnet est vide. Commence par les 5 personnes de ton réseau que tu veux contacter cette semaine.'}
        </p>
      )}
    </section>
  )
}

// Tableau de bord : les relances du jour, seulement s'il y en a.
function RelancesDuJour({ onOuvrir }) {
  const [carnet, setCarnet] = useState(null)

  useEffect(() => {
    let actif = true
    appelPortail('/prospects').then((data) => actif && setCarnet(data)).catch(() => {})
    return () => { actif = false }
  }, [])

  if (!carnet?.a_relancer?.length) return null

  const noms = carnet.prospects.filter((p) => carnet.a_relancer.includes(p.id)).map((p) => p.nom)
  const n = noms.length

  return (
    <section className="panel carnet-rappel">
      <p className="panel-eyebrow"><Phone size={14} /> Tes relances du jour</p>
      <p className="panel-lead">
        {n === 1 ? `1 relance prévue : ${noms[0]}.` : `${n} relances prévues : ${noms.slice(0, 3).join(', ')}${n > 3 ? '…' : '.'}`}
      </p>
      <button type="button" className="fiche-bouton" onClick={onOuvrir}>Ouvrir mon carnet</button>
    </section>
  )
}

// Bilan hebdo : propose les chiffres du carnet pour la semaine choisie.
function SuggestionCarnet({ semaineDu, onReprendre }) {
  const [prospects, setProspects] = useState(null)

  useEffect(() => {
    let actif = true
    appelPortail('/prospects').then((data) => actif && setProspects(data.prospects)).catch(() => {})
    return () => { actif = false }
  }, [])

  const totaux = totauxCarnet(prospects, semaineDu)
  if (!prospects || !(totaux.contacts || totaux.rdv || totaux.ventes)) return null

  return (
    <div className="carnet-suggestion">
      <p>
        <ListChecks size={15} aria-hidden="true" /> D'après ton carnet, semaine du {dateRelance(semaineDu)} : <strong>{totaux.contacts}</strong> contact{totaux.contacts > 1 ? 's' : ''}, <strong>{totaux.rdv}</strong> RDV, <strong>{totaux.ventes}</strong> vente{totaux.ventes > 1 ? 's' : ''}.
      </p>
      <button type="button" className="idris-copier" onClick={() => onReprendre(totaux)}>Reprendre ces chiffres</button>
    </div>
  )
}

// --- Passerelle Autonome vers Coaching (27/10/2026) ---------------------------
// A partir de J30, quand le membre bloque : une proposition par periode de 30 jours.
const PASSERELLE_VUE_KEY = 'passerelle_coaching_vue'

function PasserelleCoaching({ passerelle }) {
  const [vue, setVue] = useState(() => {
    try {
      return passerelle && localStorage.getItem(PASSERELLE_VUE_KEY) === String(passerelle.periode)
    } catch {
      return false
    }
  })
  const [attente, setAttente] = useState(false)

  if (!passerelle || vue) return null

  const fermer = () => {
    try {
      localStorage.setItem(PASSERELLE_VUE_KEY, String(passerelle.periode))
    } catch {
      // Sans stockage, la carte reviendra a la prochaine visite.
    }
    setVue(true)
  }

  const reserver = async () => {
    setAttente(true)
    // Fenetre ouverte tout de suite (sinon bloquee sur iPhone), adresse ensuite.
    const fenetre = window.open('', '_blank')
    let url = passerelle.url
    try {
      url = (await appelPortail('/passerelle-coaching', {})).url || url
    } catch {
      // Rony n'est pas prevenu, mais le client peut quand meme reserver.
    }
    if (fenetre) fenetre.location.href = url
    else window.location.href = url
    setAttente(false)
    fermer()
  }

  return (
    <section className="panel passerelle">
      <IdrisMessage titre="Et si on en parlait ?">
        <p className="idris-message-texte">
          {passerelle.raison === 'retard'
            ? `Tu as ${passerelle.en_retard} fiches en retard. Ça arrive souvent quand on avance seul, surtout quand l'activité prend toute la place.`
            : "Ce mois-ci, aucune fiche n'a avancé. Ce n'est pas grave, mais c'est le bon moment pour ne pas laisser filer."}
          {' '}Rony peut faire le point avec toi au téléphone : où tu en es, ce qui bloque, et si un accompagnement Coaching t'aiderait à passer le cap.
        </p>
        <div className="biblio-actions">
          <button type="button" className="fiche-bouton" onClick={reserver} disabled={attente}>
            {attente ? 'Ouverture…' : 'Réserver mon appel avec Rony'}
          </button>
          <button type="button" className="idris-copier" onClick={fermer}>Plus tard</button>
        </div>
      </IdrisMessage>
    </section>
  )
}

// --- Notifications sur le telephone (27/10/2026) -------------------------------
function cleVapid(base64) {
  const remplissage = '='.repeat((4 - (base64.length % 4)) % 4)
  const brut = window.atob((base64 + remplissage).replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from([...brut].map((c) => c.charCodeAt(0)))
}

function NotificationsTelephone() {
  const compatible = typeof window !== 'undefined' && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
  const iphone = /iphone|ipad|ipod/i.test(navigator.userAgent || '')
  const installee = window.matchMedia?.('(display-mode: standalone)').matches || window.navigator.standalone === true
  const [cle, setCle] = useState(undefined)
  const [abonne, setAbonne] = useState(false)
  const [attente, setAttente] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    let actif = true
    appelPortail('/push/cle').then((data) => actif && setCle(data.cle)).catch(() => actif && setCle(null))
    if (compatible) {
      navigator.serviceWorker.getRegistration('/sw.js')
        .then((reg) => reg?.pushManager.getSubscription())
        .then((sub) => actif && setAbonne(Boolean(sub)))
        .catch(() => {})
    }
    return () => { actif = false }
  }, [compatible])

  if (!cle) return null

  const activer = async () => {
    setMessage('')
    setAttente(true)
    try {
      const permission = await Notification.requestPermission()
      if (permission !== 'granted') {
        setMessage("Les notifications sont bloquées pour ce site. Tu peux les autoriser dans les réglages de ton téléphone ou de ton navigateur.")
        return
      }
      const reg = await navigator.serviceWorker.register('/sw.js')
      await navigator.serviceWorker.ready
      const sub = (await reg.pushManager.getSubscription()) || (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: cleVapid(cle) }))
      await appelPortail('/push/abonnement', { abonnement: sub.toJSON() })
      setAbonne(true)
      setMessage("C'est activé. Tu recevras ta première notification le matin où une fiche s'ouvre ou qu'une relance t'attend.")
    } catch {
      setMessage("L'activation n'a pas marché. Réessaie dans un instant.")
    } finally {
      setAttente(false)
    }
  }

  const desactiver = async () => {
    setMessage('')
    setAttente(true)
    try {
      const reg = await navigator.serviceWorker.getRegistration('/sw.js')
      const sub = await reg?.pushManager.getSubscription()
      if (sub) {
        await appelPortail('/push/desabonnement', { endpoint: sub.endpoint }).catch(() => {})
        await sub.unsubscribe()
      }
      setAbonne(false)
      setMessage('Notifications désactivées sur cet appareil.')
    } finally {
      setAttente(false)
    }
  }

  return (
    <section className="panel notifications">
      <p className="panel-eyebrow"><Smartphone size={14} /> Notifications sur ton téléphone</p>
      <p className="panel-lead">Un petit rappel quand une fiche s'ouvre, quand Idris t'a répondu et le matin où tu as des relances prévues.</p>
      {!compatible || (iphone && !installee) ? (
        <p className="carnet-aide">
          {iphone ? "Sur iPhone, installe d'abord ton espace sur l'écran d'accueil (voir ci-dessus), puis ouvre-le depuis l'icône pour activer les notifications." : "Ton navigateur ne gère pas les notifications. Essaie avec Chrome, Edge ou Safari."}
        </p>
      ) : abonne ? (
        <button type="button" className="idris-copier" onClick={desactiver} disabled={attente}>Désactiver sur cet appareil</button>
      ) : (
        <button type="button" className="fiche-bouton" onClick={activer} disabled={attente}>{attente ? 'Activation…' : 'Activer les notifications'}</button>
      )}
      {message && <p className="carnet-aide">{message}</p>}
    </section>
  )
}

// Date et heure locales 'AAAA-MM-JJTHH:MM', comparables aux heures de l'agenda
// (toISOString donne l'heure universelle, 4 h d'ecart en Guadeloupe).
function maintenantLocal() {
  const d = new Date()
  const n = (v) => String(v).padStart(2, '0')
  return `${d.getFullYear()}-${n(d.getMonth() + 1)}-${n(d.getDate())}T${n(d.getHours())}:${n(d.getMinutes())}`
}

function dateSession(valeur) {
  const date = valeur ? new Date(valeur) : null
  if (!date || Number.isNaN(date.getTime())) return valeur || ''
  const avecHeure = String(valeur).length > 10
  return date.toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long', ...(avecHeure ? { hour: '2-digit', minute: '2-digit' } : {}) })
}

function lienSur(lien) {
  return typeof lien === 'string' && lien.startsWith('https://') ? lien : null
}

// Onglet Communaute (lot 4) : lien du groupe, prochain point collectif, replays.
function Communaute({ dashboard, points }) {
  const sessions = dashboard.sessions || []
  // Prochain point collectif : session Notion ou point pose dans l'agenda de
  // Rony (28/10/2026), le plus proche des deux.
  const maintenant = maintenantLocal()
  const collectifAgenda = (points || [])
    .filter((p) => p.type === 'collectif' && p.evenement && p.evenement.fin >= maintenant)
    .sort((a, b) => a.evenement.debut.localeCompare(b.evenement.debut))[0]
  const deSession = prochaineSession(sessions)
  const prochaine = collectifAgenda && (!deSession || collectifAgenda.evenement.debut < String(deSession.date_heure || '').slice(0, 16))
    ? { nom: libellePoint(collectifAgenda), date_heure: collectifAgenda.evenement.debut, lien: collectifAgenda.evenement.lieu, lieu: collectifAgenda.evenement.lieu }
    : deSession
  const suggere = !prochaine && (points || []).find((p) => p.type === 'collectif' && p.statut === 'a_planifier' && p.date >= maintenant.slice(0, 10))
  const replays = sessions.filter((s) => lienSur(s.replay))

  return (
    <>
      <section className="panel communaute-groupe">
        <p className="panel-eyebrow"><Users size={14} /> Mon groupe</p>
        {dashboard.cohorte && <p className="panel-lead">Cohorte {dashboard.cohorte.nom}{dashboard.cohorte.statut ? ` · ${dashboard.cohorte.statut}` : ''}</p>}
        {dashboard.lien_groupe ? (
          <>
            <p className="communaute-texte">Échange avec les autres entrepreneurs du programme : questions, victoires de la semaine, entraide.</p>
            <a className="fiche-bouton communaute-bouton" href={dashboard.lien_groupe} target="_blank" rel="noopener noreferrer">
              <MessageCircle size={16} /> Rejoindre le groupe
            </a>
          </>
        ) : (
          <p className="espace-vide">Le lien de ton groupe apparaîtra ici dès qu'il sera ouvert.</p>
        )}
      </section>

      <section className="panel">
        <p className="panel-eyebrow"><CalendarDays size={14} /> Prochain point collectif</p>
        {prochaine ? (
          <div className="communaute-prochaine">
            <p className="communaute-prochaine-date">{dateSession(prochaine.date_heure)}</p>
            <p className="communaute-texte">{prochaine.nom}{prochaine.lieu && !lienSur(prochaine.lieu) ? ` · ${prochaine.lieu}` : ''}</p>
            {lienSur(prochaine.lien) && (
              <a className="fiche-bouton communaute-bouton" href={prochaine.lien} target="_blank" rel="noopener noreferrer">
                <Rocket size={16} /> Rejoindre la session
              </a>
            )}
          </div>
        ) : suggere ? (
          <div className="communaute-prochaine">
            <p className="communaute-prochaine-date">Vers le {new Date(...suggere.date.split('-').map((v, i) => Number(v) - (i === 1 ? 1 : 0))).toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' })}</p>
            <p className="communaute-texte">{libellePoint(suggere)} · Rony te confirme la date et l'heure.</p>
          </div>
        ) : (
          <p className="espace-vide">La date de ton prochain point collectif apparaîtra ici dès qu'elle sera planifiée.</p>
        )}
      </section>

      <section className="panel">
        <p className="panel-eyebrow"><PlayCircle size={14} /> Replays</p>
        {replays.length ? (
          <ul className="communaute-replays">
            {replays.map((s) => (
              <li key={s.id}>
                <a href={s.replay} target="_blank" rel="noopener noreferrer"><PlayCircle size={15} /> {s.nom}</a>
                {s.date_heure && <span>{dateSession(s.date_heure)}</span>}
              </li>
            ))}
          </ul>
        ) : (
          <p className="espace-vide">Les replays des sessions passées seront rangés ici.</p>
        )}
      </section>

      {sessions.length > 0 && (
        <section className="panel">
          <p className="panel-eyebrow">Toutes mes sessions</p>
          {sessions.map((session) => (
            <p key={session.id} className="flex items-center gap-2 text-sm mb-1.5" style={{ color: 'var(--text-dimmed)' }}>
              <CalendarDays size={14} color="var(--text-soft)" />
              {session.nom} {session.date_heure && `· ${dateSession(session.date_heure)}`} {session.statut && `(${session.statut})`}
            </p>
          ))}
        </section>
      )}
    </>
  )
}

// Accueil guide (lot 4) : 3 ecrans a la premiere connexion, tant qu'aucune
// fiche n'est terminee. Memorise sur l'appareil.
const ACCUEIL_VU_KEY = 'accueil_vu'

function accueilAMontrer(dashboard) {
  try {
    if (localStorage.getItem(ACCUEIL_VU_KEY) === '1') return false
  } catch {
    return false
  }
  return !dashboard.fiches.some((f) => f.etat === 'Terminé')
}

function AccueilGuide({ dashboard, fiche, onObjectif, onFini, onOuvrir }) {
  const [etape, setEtape] = useState(0)
  const [objectif, setObjectif] = useState(dashboard.objectif_90j || '')
  const [attente, setAttente] = useState(false)
  const [erreur, setErreur] = useState('')
  const prenom = (dashboard.nom || '').split(' ')[0]

  const terminer = (ouvrir) => {
    try {
      localStorage.setItem(ACCUEIL_VU_KEY, '1')
      localStorage.setItem(IDRIS_PRESENTE_KEY, '1')
    } catch {
      // Navigation privee : l'accueil reviendra a la prochaine visite.
    }
    onFini()
    if (ouvrir && fiche) onOuvrir(fiche.id)
  }

  const garderObjectif = async (event) => {
    event.preventDefault()
    setErreur('')

    if (objectif.trim() && objectif.trim() !== (dashboard.objectif_90j || '')) {
      setAttente(true)
      try {
        onObjectif((await appelPortail('/objectif', { objectif })).objectif_90j)
      } catch {
        setErreur("Ton objectif n'a pas pu être enregistré. Tu pourras le reprendre dans ta fiche « Mon point de départ ».")
        setAttente(false)
        return
      }
      setAttente(false)
    }
    setEtape(1)
  }

  return (
    <div className="accueil-guide-voile" role="dialog" aria-modal="true" aria-labelledby="accueil-guide-titre">
      <div className="accueil-guide">
        <p className="accueil-guide-etapes" aria-label={`Étape ${etape + 1} sur 3`}>
          {[0, 1, 2].map((i) => <span key={i} className={i <= etape ? 'accueil-guide-point-actif' : ''} />)}
        </p>
        {etape === 0 && (
          <form onSubmit={garderObjectif}>
            <p className="panel-eyebrow"><Target size={14} /> Bienvenue{prenom ? ` ${prenom}` : ''}</p>
            <h2 id="accueil-guide-titre" className="accueil-guide-titre">Quel est ton objectif pour les 90 prochains jours ?</h2>
            <p className="communaute-texte">Un objectif simple et chiffré si tu peux : il guidera tes fiches, tes chiffres et les conseils d'Idris.</p>
            <textarea className="field-input" rows={3} maxLength={300} value={objectif} onChange={(e) => setObjectif(e.target.value)} placeholder="Ex. : signer 5 nouveaux clients et remplir mon planning de mars" aria-label="Mon objectif 90 jours" />
            {erreur && <p className="idris-erreur">{erreur}</p>}
            <div className="accueil-guide-actions">
              <button type="button" className="prochaine-etape-lien" onClick={() => setEtape(1)}>Plus tard</button>
              <button type="submit" className="fiche-bouton" disabled={attente}>
                {attente ? <Loader2 size={16} className="animate-spin" /> : null} Continuer
              </button>
            </div>
          </form>
        )}
        {etape === 1 && (
          <>
            <h2 id="accueil-guide-titre" className="accueil-guide-titre">Voici Idris, ton assistant</h2>
            <IdrisMessage titre="Enchanté !">
              <p>Je suis l'assistant IA de ton parcours, aux côtés de Rony. Je connais ton diagnostic, tes fiches et tes chiffres.</p>
              <p>Après chaque fiche, je te fais un retour. Dans l'onglet Idris, pose-moi tes questions de stratégie commerciale ou demande-moi un message prêt à envoyer.</p>
            </IdrisMessage>
            <div className="accueil-guide-actions">
              <button type="button" className="prochaine-etape-lien" onClick={() => setEtape(0)}>Retour</button>
              <button type="button" className="fiche-bouton" onClick={() => setEtape(2)}>Continuer</button>
            </div>
          </>
        )}
        {etape === 2 && (
          <>
            <p className="panel-eyebrow"><Rocket size={14} /> Ta première action</p>
            <h2 id="accueil-guide-titre" className="accueil-guide-titre">{fiche ? lireFiche(fiche.nom).titre : 'Ton parcours commence'}</h2>
            <p className="communaute-texte">
              Une fiche à la fois, quelques minutes chacune. Tu peux t'arrêter quand tu veux : tes réponses sont gardées.
            </p>
            <div className="accueil-guide-actions">
              <button type="button" className="prochaine-etape-lien" onClick={() => terminer(false)}>Voir mon tableau de bord</button>
              {fiche && <button type="button" className="fiche-bouton" onClick={() => terminer(true)}>Commencer</button>}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// Lien de partage (lot 4) : la progression en lecture seule, sans les
// reponses aux fiches. Valable 30 jours.
function PartageProgression() {
  const [lien, setLien] = useState(null)
  const [attente, setAttente] = useState(false)
  const [erreur, setErreur] = useState('')

  const creer = async () => {
    setAttente(true)
    setErreur('')
    try {
      setLien(await appelPortail('/partage', {}))
    } catch {
      setErreur("Le lien n'a pas pu être créé. Réessaie dans quelques minutes.")
    } finally {
      setAttente(false)
    }
  }

  return (
    <section className="panel partage">
      <p className="panel-eyebrow"><Share2 size={14} /> Partager ma progression</p>
      <p className="panel-lead">{lien ? 'Voici ton lien. Copie-le et envoie-le à qui tu veux.' : 'Montre ton avancement à ton banquier, ton associé ou un proche avec un simple lien.'}</p>
      <p className="communaute-texte">La personne voit ton prénom, ton score, tes chiffres et le nombre de fiches terminées. Elle ne peut rien modifier. Tes réponses aux fiches, ton nom de famille, ton e-mail et ton téléphone restent privés. Le lien marche pendant 30 jours.</p>
      {lien ? (
        <div className="partage-lien">
          <input className="field-input" readOnly value={lien.url} aria-label="Lien de partage" onFocus={(e) => e.target.select()} />
          <BoutonCopier texte={lien.url} />
        </div>
      ) : (
        <button type="button" className="fiche-bouton" onClick={creer} disabled={attente}>
          {attente ? <Loader2 size={16} className="animate-spin" /> : <Link2 size={16} />} Créer mon lien de partage
        </button>
      )}
      {erreur && <p className="idris-erreur">{erreur}</p>}
    </section>
  )
}

// Avis a J90 (lot 4) : cite seulement si le client l'accepte.
const AVIS_ENVOYE_KEY = 'avis_j90_envoye'

function AvisJ90() {
  const [envoye, setEnvoye] = useState(() => {
    try {
      return localStorage.getItem(AVIS_ENVOYE_KEY) === '1'
    } catch {
      return false
    }
  })
  const [note, setNote] = useState(null)
  const [avis, setAvis] = useState('')
  const [accord, setAccord] = useState(false)
  const [signature, setSignature] = useState('')
  const [attente, setAttente] = useState(false)
  const [erreur, setErreur] = useState('')

  const envoyer = async (event) => {
    event.preventDefault()
    setAttente(true)
    setErreur('')
    try {
      await appelPortail('/avis-j90', { note, avis, accord_publication: accord, signature })
      try {
        localStorage.setItem(AVIS_ENVOYE_KEY, '1')
      } catch {
        // Navigation privee : sans consequence.
      }
      setEnvoye(true)
    } catch {
      setErreur("Ton avis n'a pas pu être envoyé. Réessaie dans quelques minutes.")
    } finally {
      setAttente(false)
    }
  }

  if (envoye) {
    return (
      <section className="panel avis-j90">
        <p className="panel-eyebrow"><Star size={14} /> Ton avis</p>
        <p className="panel-lead">Merci pour ton avis ! Rony le lira personnellement.</p>
      </section>
    )
  }

  return (
    <section className="panel avis-j90">
      <p className="panel-eyebrow"><Star size={14} /> Ton avis sur ces 90 jours</p>
      <form onSubmit={envoyer}>
        <p className="communaute-texte">Sur 10, recommanderais-tu ce parcours à un autre entrepreneur ?</p>
        <div className="avis-notes" role="radiogroup" aria-label="Ta note sur 10">
          {Array.from({ length: 11 }, (_, i) => (
            <button key={i} type="button" role="radio" aria-checked={note === i} className={`avis-note${note === i ? ' avis-note-active' : ''}`} onClick={() => setNote(i)}>{i}</button>
          ))}
        </div>
        <textarea className="field-input" rows={4} maxLength={1500} value={avis} onChange={(e) => setAvis(e.target.value)} placeholder="Qu'est-ce qui a changé pour toi et pour ton activité ?" aria-label="Ton avis" />
        <label className="avis-accord">
          <input type="checkbox" checked={accord} onChange={(e) => setAccord(e.target.checked)} />
          <span>J'accepte que RL-eVolution cite mon avis (site, réseaux, présentations).</span>
        </label>
        {accord && (
          <input className="field-input" maxLength={120} value={signature} onChange={(e) => setSignature(e.target.value)} placeholder="Signé comment ? Ex. : Marie, coiffeuse à Baie-Mahault" aria-label="Signature de ton avis" />
        )}
        {erreur && <p className="idris-erreur">{erreur}</p>}
        <button type="submit" className="fiche-bouton" disabled={attente || note === null || !avis.trim()}>
          {attente ? <Loader2 size={16} className="animate-spin" /> : null} Envoyer mon avis
        </button>
      </form>
    </section>
  )
}

// Page publique du lien de partage : aucune donnee de session.
function PagePartage({ jeton }) {
  const [donnees, setDonnees] = useState(null)
  const [erreur, setErreur] = useState('')

  useEffect(() => {
    document.body.dataset.ecran = 'partage'
    fetch(`${API_BASE}/public/partage?jeton=${encodeURIComponent(jeton)}`)
      .then(async (response) => {
        if (!response.ok) throw new Error(response.status === 404 ? "Ce lien de partage n'est plus valable. Demandez-en un nouveau à la personne qui vous l'a envoyé." : 'Cette page est indisponible pour le moment.')
        setDonnees(await response.json())
      })
      .catch((err) => setErreur(err.message))
  }, [jeton])

  if (erreur) return <div className="partage-page"><article className="panel"><p className="panel-lead">{erreur}</p></article></div>
  if (!donnees) return <div className="partage-page"><Loader2 className="animate-spin" color="var(--gold)" size={28} /></div>

  const modules = []
  for (const fiche of donnees.fiches) {
    const label = fiche.module || 'Autres'
    let groupe = modules.find((m) => m.label === label)
    if (!groupe) {
      groupe = { label, fiches: [] }
      modules.push(groupe)
    }
    groupe.fiches.push(fiche)
  }
  const fichesFaites = donnees.fiches.filter((f) => f.etat === 'Terminé').length
  const modulesFaits = modules.filter((m) => m.fiches.every((f) => f.etat === 'Terminé')).length
  const jour = jourDuParcours(donnees.date_demarrage)
  const jalons = calculerJalons({ ...donnees, kpi: donnees.kpi }, modules).filter((j) => j.fait)

  return (
    <div className="partage-page">
      <header className="partage-entete">
        <img src={logo} alt="RL-eVolution" className="attestation-logo" />
        <p className="attestation-surtitre">Système eVolution 2.0 · {libelleFormule(donnees.parcours)}</p>
        <h1>La progression de {donnees.prenom || 'ce participant'}</h1>
        {jour !== null && jour >= 0 && <p className="communaute-texte">Jour {jour} du parcours{donnees.date_demarrage ? `, démarré le ${dateLongue(donnees.date_demarrage)}` : ''}</p>}
      </header>
      <div className="jauges">
        <Jauge pct={donnees.fiches.length ? (fichesFaites / donnees.fiches.length) * 100 : 0} titre="Fiches" detail={`${fichesFaites} / ${donnees.fiches.length} fiches`} />
        <Jauge pct={modules.length ? (modulesFaits / modules.length) * 100 : 0} titre="Modules" detail={`${modulesFaits} / ${modules.length} modules`} />
      </div>
      <AvantMaintenant personnalisation={donnees.personnalisation} kpis={donnees.kpi} />
      {(jalons.length > 0 || donnees.regularite) && (
        <section className="panel jalons">
          <p className="panel-eyebrow">Jalons atteints</p>
          {donnees.regularite && (
            <p className="jalons-serie"><strong>{donnees.regularite.serie}</strong> semaine{donnees.regularite.serie > 1 ? 's' : ''} de bilan d'affilée<span> · {donnees.regularite.semaines} au total</span></p>
          )}
          <ul className="jalons-liste">
            {jalons.map((j) => <li key={j.id} className="jalon jalon-fait"><Award size={15} aria-hidden="true" /><span>{j.titre}</span></li>)}
          </ul>
        </section>
      )}
      <p className="attestation-note">Page en lecture seule partagée par {donnees.prenom || 'le participant'}, avec les chiffres saisis dans son espace RL-eVolution.</p>
    </div>
  )
}

// Mon parcours en frise (affichage du 26/10/2026, lot C) : une seule
// colonne rangee par etape, avec le repere « Aujourd'hui ». Les modules
// termines tiennent sur une ligne, le module en cours est ouvert avec sa
// grande illustration, les modules a venir disent quand ils s'ouvrent.
function etapeDuModule(label) {
  const etape = (label || '').replace(/⁠/g, '').split(' · ')[0].trim()
  // « Démarrage · J0 » et « Diagnostic · J1 à J3 » forment une seule etape.
  return etape === 'Diagnostic' ? 'Démarrage' : etape
}

const NOMS_ETAPES = { Démarrage: 'Démarrage et diagnostic' }

function ListeFiches({ fiches, onOpen }) {
  return (
    <ul className="module-carte-fiches">
      {fiches.map((fiche) => {
        const bloquee = fiche.acces?.includes('Bloqué')
        const { numero: n, titre: t } = lireFiche(fiche.nom)
        const etat = fiche.etat === 'Terminé' ? 'fini' : fiche.etat === 'En cours' ? 'actif' : 'avenir'
        const ouverture = bloquee ? fiche.acces.match(/ouvre à (J\d+)/)?.[1] : null

        return (
          <li key={fiche.id}>
            <button disabled={bloquee} onClick={() => onOpen(fiche.id)} className={`module-fiche module-fiche-${etat}`}>
              <span className="module-fiche-numero">{n ?? '•'}</span>
              <span className="module-fiche-titre">{t}</span>
              <BadgePriorite priorite={fiche.priorite} />
              {ouverture && <span className="module-fiche-ouverture">S'ouvre à {ouverture}</span>}
              {bloquee ? (
                <Lock size={13} className="module-fiche-icone" aria-label="Bloquée" />
              ) : etat === 'fini' ? (
                <CheckCircle2 size={14} className="module-fiche-icone module-fiche-icone-fini" aria-label="Terminée" />
              ) : (
                <ChevronRight size={14} className="module-fiche-icone" aria-hidden="true" />
              )}
            </button>
          </li>
        )
      })}
    </ul>
  )
}

function ModuleEtape({ module, enCours, jour, onOpen }) {
  const { surtitre, titre } = lireModule(module.label)
  const [ouvert, setOuvert] = useState(enCours)
  const terminees = module.fiches.filter((f) => f.etat === 'Terminé').length
  const total = module.fiches.length
  const fini = total > 0 && terminees === total
  const statut = fini ? 'fini' : enCours ? 'actif' : 'avenir'
  // Seule la prochaine fiche porte « ouvre à JXX » : sinon, le jour d'ouverture
  // vient du nom du module (« … (J68) »).
  const jourOuverture = Number(
    module.fiches.find((f) => f.etat !== 'Terminé')?.acces?.match(/ouvre à J(\d+)/)?.[1] ??
    (module.label || '').match(/\(J(\d+)/)?.[1],
  )
  const ouverture = statut === 'avenir' && jourOuverture && (jour === null || jourOuverture > jour) ? jourOuverture : null
  const dans = ouverture && jour !== null ? ouverture - jour : null
  // Le surtitre repete l'etape, deja en titre de section : on garde la suite.
  const detail = surtitre.split(' · ').filter((partie) => partie !== etapeDuModule(module.label)).join(' · ')

  return (
    <li className={`etape-module etape-module-${statut}`}>
      <button type="button" className="etape-module-entete" aria-expanded={ouvert} onClick={() => setOuvert((v) => !v)}>
        <img src={illustrationDuModule(module.label)} alt="" className="etape-module-image" loading="lazy" />
        <span className="etape-module-texte">
          <span className="etape-module-titre">{titre}</span>
          <span className="etape-module-detail">{detail}</span>
        </span>
        <span className="etape-module-etat">
          {statut === 'avenir' && ouverture ? (
            <>S'ouvre à J{ouverture}{dans > 0 && <small>dans {dans} jour{dans > 1 ? 's' : ''}</small>}</>
          ) : (
            <>
              {terminees} / {total} fiche{total > 1 ? 's' : ''}
              {statut === 'actif' && <span className="etape-module-barre"><span style={{ width: `${total ? (terminees / total) * 100 : 0}%` }} /></span>}
            </>
          )}
        </span>
        <ChevronDown size={16} aria-hidden="true" className={`etape-module-chevron${ouvert ? ' etape-module-chevron-ouvert' : ''}`} />
      </button>
      {ouvert && <ListeFiches fiches={module.fiches} onOpen={onOpen} />}
    </li>
  )
}

function FriseParcours({ modules, moduleEnCours, rythme, onOpen }) {
  const jour = rythme ? rythme.jour : null
  const etapesCalendrier = rythme?.etapes || []
  const etapeDuJour = etapeDuCalendrier(rythme)

  const groupes = []
  for (const module of modules) {
    const cle = etapeDuModule(module.label)
    const groupe = groupes.find((g) => g.cle === cle)
    if (groupe) groupe.modules.push(module)
    else groupes.push({ cle, modules: [module] })
  }

  const periode = (cle) => {
    const index = etapesCalendrier.findIndex((e) => e.libelle === cle)
    if (index < 0) return null
    const fin = (etapesCalendrier[index + 1]?.debut ?? (rythme.duree + 1)) - 1
    return `J${etapesCalendrier[index].debut} à J${fin}`
  }

  return (
    <div className="frise">
      {jour !== null && jour < 0 && (
        <p className="frise-aujourdhui">Ton parcours démarre dans {-jour} jour{jour < -1 ? 's' : ''}</p>
      )}
      {groupes.map((groupe) => {
        const fini = groupe.modules.every((m) => m.fiches.every((f) => f.etat === 'Terminé'))
        const enCours = groupe.modules.includes(moduleEnCours)
        const statut = fini ? 'fini' : enCours || groupe.cle === etapeDuJour ? 'actif' : 'avenir'

        return (
          <section key={groupe.cle} className="frise-etape">
            <div className="frise-etape-entete">
              <span className={`frise-etape-statut frise-etape-statut-${statut}`}>
                {statut === 'fini' ? <><CheckCircle2 size={13} aria-hidden="true" /> Terminé</> : statut === 'actif' ? 'En cours' : 'À venir'}
              </span>
              <h3 className="frise-etape-titre">{NOMS_ETAPES[groupe.cle] || groupe.cle}</h3>
              {periode(groupe.cle) && <span className="frise-etape-periode">{periode(groupe.cle)}</span>}
            </div>
            {groupe.cle === etapeDuJour && <p className="frise-aujourdhui">Aujourd'hui · J{jour}</p>}
            <ol className="frise-modules">
              {groupe.modules.map((module) => (
                <ModuleEtape key={module.label} module={module} enCours={module === moduleEnCours} jour={jour} onOpen={onOpen} />
              ))}
            </ol>
          </section>
        )
      })}
      {jour !== null && rythme && jour > rythme.duree && (
        <p className="frise-aujourdhui">Aujourd'hui · J{jour} · tes {rythme.duree} jours sont bouclés</p>
      )}
    </div>
  )
}

function IdentiteCard({ identite, cohorte, sessions }) {
  const infos = [
    { icon: Mail, valeur: identite.email },
    { icon: Phone, valeur: identite.telephone || identite.contact },
    { icon: MapPin, valeur: [identite.secteur, identite.territoire].filter(Boolean).join(' · ') },
  ].filter((info) => info.valeur)

  return (
    <section className="panel">
      <p className="panel-eyebrow">Ma fiche</p>

      <div className="space-y-1.5 mb-4">
        {infos.map(({ icon: Icon, valeur }, index) => (
          <p key={index} className="flex items-center gap-2 text-sm" style={{ color: 'var(--text-dimmed)' }}>
            <Icon size={14} color="var(--text-soft)" /> {valeur}
          </p>
        ))}
        {identite.activite && (
          <p className="text-sm" style={{ color: 'var(--text-dimmed)' }}>{identite.activite}</p>
        )}
      </div>

      {cohorte && (
        <div className="flex items-center gap-2 text-sm mb-2" style={{ color: 'var(--text-dimmed)' }}>
          <Users size={14} color="var(--gold)" />
          Cohorte {cohorte.nom} {cohorte.statut && `· ${cohorte.statut}`}
        </div>
      )}

      {sessions.length > 0 && (
        <div className="mt-3 pt-3" style={{ borderTop: '1px solid #E7E5DF' }}>
          <p className="text-sm mb-2 flex items-center gap-2" style={{ color: 'var(--text-soft)' }}>
            <CalendarDays size={14} /> Sessions
          </p>
          {sessions.map((session) => (
            <p key={session.id} className="text-sm" style={{ color: 'var(--text-dimmed)' }}>
              {session.nom} {session.date_heure && `· ${session.date_heure}`} {session.statut && `(${session.statut})`}
            </p>
          ))}
        </div>
      )}
    </section>
  )
}

function KpiPeriod({ label, valeur, objectif }) {
  return (
    <div className="kpi-period">
      <p className="kpi-period-label">{label}</p>
      <p className="kpi-period-valeur">{valeur ?? '—'}</p>
      {objectif !== undefined && (
        <p className="kpi-period-objectif">obj. {objectif ?? '—'}</p>
      )}
    </div>
  )
}

// Un suivi chiffre n'a de sens que si au moins une valeur ou un objectif
// est renseigne (les parcours sans KPI n'affichent alors rien du tout).
const KPI_CHAMPS = ['valeur_j0', 'valeur_j30', 'valeur_j60', 'valeur_j90', 'objectif_j30', 'objectif_j60', 'objectif_j90']

export function kpiRenseignes(kpis) {
  return Array.isArray(kpis) && kpis.some((kpi) => KPI_CHAMPS.some((champ) => kpi[champ] !== null && kpi[champ] !== undefined && kpi[champ] !== ''))
}

// Champs saisissables par le client, dans l'ordre d'affichage du formulaire.
const KPI_SAISIE = [
  { periode: 'J0', valeur: 'valeur_j0' },
  { periode: 'J30', valeur: 'valeur_j30', objectif: 'objectif_j30' },
  { periode: 'J60', valeur: 'valeur_j60', objectif: 'objectif_j60' },
  { periode: 'J90', valeur: 'valeur_j90', objectif: 'objectif_j90' },
]

function versChamp(valeur) {
  return valeur === null || valeur === undefined ? '' : String(valeur)
}

// Petit graphique de progression d'un KPI : realise (trait plein) et objectif
// (pointilles) de J0 a J90, sur une seule echelle.
const KPI_POINTS = [
  { label: 'J0', valeur: 'valeur_j0' },
  { label: 'J30', valeur: 'valeur_j30', objectif: 'objectif_j30' },
  { label: 'J60', valeur: 'valeur_j60', objectif: 'objectif_j60' },
  { label: 'J90', valeur: 'valeur_j90', objectif: 'objectif_j90' },
]

function nombreOuNull(valeur) {
  if (valeur === null || valeur === undefined || valeur === '') return null
  const nombre = Number(valeur)
  return Number.isFinite(nombre) ? nombre : null
}

function formaterKpi(nombre) {
  // Espace insecable classique : l'espace fine du format francais disparait
  // presque en petit corps ("3000 €" au lieu de "3 000 €").
  return nombre.toLocaleString('fr-FR', { maximumFractionDigits: 1 }).replace(/\u202f/g, '\u00a0')
}

function KpiGraphique({ kpi }) {
  const realise = KPI_POINTS.map((p, i) => ({ i, label: p.label, v: nombreOuNull(kpi[p.valeur]) })).filter((p) => p.v !== null)
  const objectif = KPI_POINTS.map((p, i) => ({ i, label: p.label, v: p.objectif ? nombreOuNull(kpi[p.objectif]) : null })).filter((p) => p.v !== null)

  // Une courbe n'a de sens qu'a partir de deux points.
  if (realise.length + objectif.length < 2) return null

  const L = 280
  const H = 96
  const marge = { haut: 14, bas: 18, gauche: 10, droite: 10 }
  const max = Math.max(...realise.map((p) => p.v), ...objectif.map((p) => p.v), 1)
  const x = (i) => marge.gauche + (i * (L - marge.gauche - marge.droite)) / 3
  const y = (v) => H - marge.bas - (v / max) * (H - marge.haut - marge.bas)
  const trace = (points) => points.map((p, k) => `${k ? 'L' : 'M'}${x(p.i)},${y(p.v)}`).join(' ')
  const dernier = realise[realise.length - 1]

  return (
    <figure className="kpi-graphique" aria-label={`Progression ${kpi.nom}`}>
      <svg viewBox={`0 0 ${L} ${H}`} role="img">
        <line x1={marge.gauche} x2={L - marge.droite} y1={H - marge.bas} y2={H - marge.bas} className="kpi-graphique-axe" />
        {KPI_POINTS.map((p, i) => (
          <text key={p.label} x={x(i)} y={H - 4} textAnchor="middle" className="kpi-graphique-label">{p.label}</text>
        ))}
        {objectif.length > 1 && <path d={trace(objectif)} className="kpi-graphique-objectif" />}
        {objectif.map((p) => (
          <circle key={`o${p.i}`} cx={x(p.i)} cy={y(p.v)} r="3" className="kpi-graphique-point-objectif">
            <title>{`${p.label} objectif : ${formaterKpi(p.v)}`}</title>
          </circle>
        ))}
        {realise.length > 1 && <path d={trace(realise)} className="kpi-graphique-realise" />}
        {realise.map((p) => (
          <circle key={`r${p.i}`} cx={x(p.i)} cy={y(p.v)} r="4" className="kpi-graphique-point">
            <title>{`${p.label} réalisé : ${formaterKpi(p.v)}`}</title>
          </circle>
        ))}
        {dernier && (
          <text x={x(dernier.i)} y={y(dernier.v) - 8} textAnchor={dernier.i === 3 ? 'end' : dernier.i === 0 ? 'start' : 'middle'} className="kpi-graphique-valeur">
            {formaterKpi(dernier.v)}
          </text>
        )}
      </svg>
      <figcaption className="kpi-graphique-legende">
        <span><i className="kpi-legende-realise" /> Réalisé</span>
        <span><i className="kpi-legende-objectif" /> Objectif</span>
      </figcaption>
    </figure>
  )
}

function KpiCard({ kpi, onSave }) {
  const [edition, setEdition] = useState(false)
  const [valeurs, setValeurs] = useState({})
  const [enCours, setEnCours] = useState(false)
  const [erreur, setErreur] = useState('')

  const ouvrir = () => {
    setValeurs(Object.fromEntries(KPI_CHAMPS.map((champ) => [champ, versChamp(kpi[champ])])))
    setErreur('')
    setEdition(true)
  }

  const enregistrer = async (event) => {
    event.preventDefault()
    // N'envoie que les champs modifies ; un champ vide efface la valeur.
    const modifies = {}

    for (const champ of KPI_CHAMPS) {
      if (valeurs[champ] === versChamp(kpi[champ])) continue
      const texte = valeurs[champ].trim().replace(',', '.')
      const nombre = texte === '' ? null : Number(texte)

      if (nombre !== null && (!Number.isFinite(nombre) || nombre < 0)) {
        setErreur('Saisis uniquement des nombres positifs.')
        return
      }

      modifies[champ] = nombre
    }

    if (Object.keys(modifies).length === 0) {
      setEdition(false)
      return
    }

    setEnCours(true)
    setErreur('')

    try {
      await onSave(kpi.id, modifies)
      setEdition(false)
    } catch {
      setErreur("Tes chiffres n'ont pas pu être enregistrés. Réessaie.")
    } finally {
      setEnCours(false)
    }
  }

  return (
    <div className="kpi-card">
      <div className="flex items-center justify-between gap-2 mb-3">
        <div>
          <p className="kpi-nom">{kpi.nom}</p>
          <p className="kpi-categorie">{kpi.categorie || '—'}</p>
        </div>
        <AccesBadge acces={kpi.etat} />
      </div>

      {edition ? (
        <form className="kpi-saisie" onSubmit={enregistrer}>
          {KPI_SAISIE.map(({ periode, valeur, objectif }) => (
            <div key={periode} className="kpi-saisie-ligne">
              <span className="kpi-period-label">{periode}</span>
              <input
                className="field-input"
                inputMode="decimal"
                aria-label={`${kpi.nom} ${periode} réalisé`}
                placeholder="Réalisé"
                value={valeurs[valeur]}
                onChange={(e) => setValeurs({ ...valeurs, [valeur]: e.target.value })}
              />
              {objectif ? (
                <input
                  className="field-input"
                  inputMode="decimal"
                  aria-label={`${kpi.nom} ${periode} objectif`}
                  placeholder="Objectif"
                  value={valeurs[objectif]}
                  onChange={(e) => setValeurs({ ...valeurs, [objectif]: e.target.value })}
                />
              ) : <span />}
            </div>
          ))}
          {erreur && <p className="kpi-saisie-erreur">{erreur}</p>}
          <div className="flex items-center gap-3 mt-2">
            <button type="submit" className="fiche-bouton" disabled={enCours}>
              {enCours ? 'Enregistrement…' : 'Enregistrer'}
            </button>
            <button type="button" className="prochaine-etape-lien" disabled={enCours} onClick={() => setEdition(false)}>
              Annuler
            </button>
          </div>
        </form>
      ) : (
        <>
          <div className="kpi-periods">
            <KpiPeriod label="J0" valeur={kpi.valeur_j0} />
            <KpiPeriod label="J30" valeur={kpi.valeur_j30} objectif={kpi.objectif_j30} />
            <KpiPeriod label="J60" valeur={kpi.valeur_j60} objectif={kpi.objectif_j60} />
            <KpiPeriod label="J90" valeur={kpi.valeur_j90} objectif={kpi.objectif_j90} />
          </div>
          <KpiGraphique kpi={kpi} />
          {onSave && (
            <button type="button" className="prochaine-etape-lien kpi-maj" onClick={ouvrir}>
              Mettre à jour mes chiffres
            </button>
          )}
        </>
      )}
    </div>
  )
}

function KpiTable({ kpis, onSave }) {
  // Detail J0 a J90 et saisie, sous « Mes résultats ». Avec la saisie client,
  // les cartes s'affichent meme vides : c'est justement la que le client
  // renseigne ses premiers chiffres.
  if (!Array.isArray(kpis) || kpis.length === 0) return null
  if (!onSave && !kpiRenseignes(kpis)) return null

  return (
    <div className="resultats-detail">
      {onSave && (
        <p className="text-sm mb-3" style={{ color: 'var(--text-secondary)' }}>
          {kpiRenseignes(kpis)
            ? 'Mets tes chiffres à jour à chaque étape (J30, J60, J90) pour suivre ta progression.'
            : 'Commence par tes chiffres de départ (J0) et fixe-toi un objectif pour J30, J60 et J90.'}
          {' '}Tes RDV et tes nouveaux clients se remplissent tout seuls à chaque bilan hebdomadaire.
        </p>
      )}
      <div className="kpi-grid">
        {kpis.map((kpi) => (
          <KpiCard key={kpi.id} kpi={kpi} onSave={onSave} />
        ))}
      </div>
    </div>
  )
}

// « Mes résultats » (affichage du 26/10/2026, remplace les cartes KPI et le
// bloc Avant / Maintenant sur le tableau de bord). Chaque tuile dit combien,
// le gain depuis le depart, un verdict sur la derniere etape passee et la
// progression vers l'objectif J90. Le detail J0 a J90 et la saisie restent
// dans les cartes KpiCard, sous « Mettre à jour mes chiffres ».
const ETAPES_KPI = [
  { jour: 90, valeur: 'valeur_j90', objectif: 'objectif_j90', label: 'J90' },
  { jour: 60, valeur: 'valeur_j60', objectif: 'objectif_j60', label: 'J60' },
  { jour: 30, valeur: 'valeur_j30', objectif: 'objectif_j30', label: 'J30' },
]
const KPI_EN_EUROS = /chiffre d.affaires|\bca\b|€|euro|panier|montant|revenu|marge/i
const SEUIL_PRESQUE = 0.8

function verdictKpi(valeur, objectif) {
  if (objectif === null) return null
  if (valeur === null) return { classe: 'verdict-vide', texte: 'À renseigner' }
  if (valeur >= objectif) return { classe: 'verdict-ok', texte: 'Atteint' }
  if (objectif > 0 && valeur / objectif >= SEUIL_PRESQUE) return { classe: 'verdict-presque', texte: 'Presque' }
  return { classe: 'verdict-retard', texte: 'À pousser' }
}

function MiniCourbe({ kpi, cible }) {
  const points = KPI_POINTS.map((p, i) => ({ i, v: nombreOuNull(kpi[p.valeur]) })).filter((p) => p.v !== null)
  if (!points.length) return null

  const valeurs = [...points.map((p) => p.v), ...(cible !== null ? [cible] : [])]
  const min = Math.min(...valeurs)
  const ecart = Math.max(...valeurs) - min || 1
  const x = (i) => 6 + i * 49.3
  const y = (v) => 34 - ((v - min) / ecart) * 28
  const dernier = points[points.length - 1]

  return (
    <svg viewBox="0 0 160 40" className="resultat-courbe" aria-hidden="true">
      {points.length > 1 && <polyline points={points.map((p) => `${x(p.i)},${y(p.v)}`).join(' ')} className="resultat-courbe-realise" />}
      {cible !== null && dernier.i < 3 && (
        <>
          <line x1={x(dernier.i)} y1={y(dernier.v)} x2={x(3)} y2={y(cible)} className="resultat-courbe-objectif" />
          <circle cx={x(3)} cy={y(cible)} r="3.5" className="resultat-courbe-cible" />
        </>
      )}
      <circle cx={x(dernier.i)} cy={y(dernier.v)} r="4" className="resultat-courbe-point" />
    </svg>
  )
}

export function TuileResultat({ kpi, jour }) {
  const unite = KPI_EN_EUROS.test(kpi.nom || '') ? ' €' : ''
  const montant = (n) => `${formaterKpi(n)}${unite}`
  const depart = nombreOuNull(kpi.valeur_j0)
  const derniere = KPI_DERNIERES.map(([champ, periode]) => ({ periode, valeur: nombreOuNull(kpi[champ]) })).find((p) => p.valeur !== null)
  const valeur = derniere ? derniere.valeur : depart
  const gain = derniere && depart !== null ? derniere.valeur - depart : null
  // Etape jugee : la derniere passee dans le calendrier, sinon (date de
  // demarrage inconnue) la derniere ou un chiffre a ete saisi.
  const etape = jour !== null
    ? ETAPES_KPI.find((e) => jour >= e.jour)
    : ETAPES_KPI.find((e) => nombreOuNull(kpi[e.valeur]) !== null)
  const objectifEtape = etape ? nombreOuNull(kpi[etape.objectif]) : null
  const verdict = etape ? verdictKpi(nombreOuNull(kpi[etape.valeur]), objectifEtape) : null
  const objectifJ30 = nombreOuNull(kpi.objectif_j30)
  const cible = nombreOuNull(kpi.objectif_j90)
  const progression = cible !== null && depart !== null && valeur !== null && cible !== depart
    ? Math.max(0, Math.min(1, (valeur - depart) / (cible - depart)))
    : null

  return (
    <article className="resultat">
      <p className="resultat-nom">{kpi.nom}</p>
      {valeur === null ? (
        <p className="resultat-vide">Pas encore de chiffre</p>
      ) : (
        <p className="resultat-valeur">{formaterKpi(valeur)}{unite && <small>{unite}</small>}</p>
      )}
      {gain !== null && (
        <p className="resultat-gain">
          <strong className={gain > 0 ? 'resultat-gain-plus' : gain < 0 ? 'resultat-gain-moins' : undefined}>
            {gain > 0 ? '+' : gain < 0 ? '−' : ''}{montant(Math.abs(gain))}
          </strong>{' '}depuis le départ
        </p>
      )}
      <MiniCourbe kpi={kpi} cible={cible} />
      <p className="resultat-verdict">
        {verdict ? (
          <>
            <span className={`verdict ${verdict.classe}`}>{verdict.texte}</span>
            <span>visé à {etape.label} : {montant(objectifEtape)}</span>
          </>
        ) : !etape && objectifJ30 !== null ? (
          <span>Premier objectif à J30 : {montant(objectifJ30)}</span>
        ) : null}
      </p>
      {progression !== null && (
        <>
          <div className="resultat-jauge"><span style={{ width: `${progression * 100}%` }} /></div>
          <p className="resultat-cible">
            <span>Vers {montant(cible)} à J90</span>
            <span>{Math.round(progression * 100)} %</span>
          </p>
        </>
      )}
    </article>
  )
}

export function ScoreCommercial({ personnalisation, coach = false }) {
  const diagnostic = personnalisation?.scores_diagnostic
  if (!diagnostic) return null

  const depart = personnalisation.total
  const actuel = personnalisation.total_actuel ?? depart
  const ecart = actuel - depart

  return (
    <div className="resultat-score">
      <div>
        <p className="resultat-nom">{coach ? 'Score commercial' : 'Ton score commercial'}</p>
        <p className="resultat-score-total">{actuel}<small> / 15 · {depart} au diagnostic</small></p>
      </div>
      <ul className="resultat-zones">
        {Object.entries(diagnostic).map(([zone, avant]) => {
          const maintenant = personnalisation.scores?.[zone] ?? avant
          return (
            <li key={zone}>
              <strong>{zone}</strong> {maintenant}
              {maintenant !== avant && (
                <em className={maintenant > avant ? 'resultat-gain-plus' : 'resultat-gain-moins'}>
                  {maintenant > avant ? '+' : '−'}{Math.abs(maintenant - avant)}
                </em>
              )}
            </li>
          )
        })}
      </ul>
      {ecart !== 0 && (
        <span className={`verdict ${ecart > 0 ? 'verdict-ok' : 'verdict-retard'}`}>
          {ecart > 0 ? '+' : '−'}{Math.abs(ecart)} point{Math.abs(ecart) > 1 ? 's' : ''}
        </span>
      )}
      {!personnalisation.chiffres && !coach && (
        <p className="resultat-score-note">Remplis au moins 2 bilans hebdomadaires : ton score suivra alors tes vrais chiffres de prospection, de conversion et de suivi.</p>
      )}
    </div>
  )
}

function MesResultats({ kpis, personnalisation, jour, onSave }) {
  const [detail, setDetail] = useState(false)
  const liste = Array.isArray(kpis) ? kpis : []
  const avecChiffres = kpiRenseignes(liste)

  if (!liste.length && !personnalisation?.scores_diagnostic) return null

  const prochainReleve = jour === null ? null : [30, 60, 90].find((j) => j > jour)

  return (
    <section className="resultats">
      <div className="resultats-entete">
        <h2 className="resultats-titre">Mes résultats</h2>
      </div>
      {avecChiffres && (
        <div className="resultats-grille">
          {liste.map((kpi) => <TuileResultat key={kpi.id} kpi={kpi} jour={jour} />)}
        </div>
      )}
      <ScoreCommercial personnalisation={personnalisation} />
      {liste.length > 0 && (avecChiffres ? (
        <>
          <div className="resultats-maj">
            <span>
              {prochainReleve
                ? `Prochain relevé à J${prochainReleve}, dans ${prochainReleve - jour} jour${prochainReleve - jour > 1 ? 's' : ''}.`
                : jour !== null ? 'Ton relevé J90 clôt le parcours.' : 'Mets tes chiffres à jour à J30, J60 et J90.'}
            </span>
            <button type="button" className="resultats-bouton" aria-expanded={detail} onClick={() => setDetail((v) => !v)}>
              {detail ? 'Masquer le détail' : onSave ? 'Mettre à jour mes chiffres' : 'Voir le détail'}
              <ChevronDown size={15} aria-hidden="true" className={detail ? 'resultats-chevron-ouvert' : undefined} />
            </button>
          </div>
          {detail && <KpiTable kpis={liste} onSave={onSave} />}
        </>
      ) : (
        <KpiTable kpis={liste} onSave={onSave} />
      ))}
    </section>
  )
}

const MODULE_COLORS = ['#8E6C38', '#2B3140', '#C9A265', '#5F7482', '#9A6B55', '#7D8B74']

function ModulesBreakdown({ modules }) {
  const total = modules.reduce((sum, m) => sum + m.fiches.length, 0)

  if (!total) return null

  return (
    <section className="panel">
      <h2 className="panel-title" style={{ color: 'var(--text-pure)' }}>
        Répartition par module
      </h2>
      <div className="module-bar mb-4">
        {modules.map((m, index) => (
          <div
            key={m.label}
            style={{ width: `${(m.fiches.length / total) * 100}%`, background: MODULE_COLORS[index % MODULE_COLORS.length] }}
          />
        ))}
      </div>
      <div className="module-legend">
        {modules.map((m, index) => (
          <span key={m.label} className="module-legend-item" title={`${m.label} (${m.fiches.length})`}>
            <span className="module-legend-dot" style={{ background: MODULE_COLORS[index % MODULE_COLORS.length], flexShrink: 0 }} />
            <span style={{ color: 'var(--text-dimmed)' }}>
              {m.label} ({m.fiches.length})
            </span>
          </span>
        ))}
      </div>
    </section>
  )
}

function AccesBadge({ acces }) {
  const isDone = acces?.includes('Terminé')
  const isActive = acces?.includes('En cours')
  const color = isDone ? 'var(--green)' : isActive ? 'var(--gold)' : 'var(--text-soft)'

  return (
    <span className="text-sm font-medium" style={{ color }}>
      {acces || '—'}
    </span>
  )
}

const VALIDATION_COACH_COLORS = {
  'Validé': 'var(--green)',
  'Soumis': 'var(--gold)',
  'À corriger': 'var(--red)',
  'À faire': 'var(--text-soft)',
}

function LivrablesSection({ livrables, onOpen }) {
  if (!livrables || livrables.length === 0) return null

  return (
    <section className="card-glass p-6 mb-6" style={{ borderRadius: 'var(--radius-md)' }}>
      <h2 className="font-semibold mb-4 flex items-center gap-2" style={{ color: 'var(--text-pure)' }}>
        <CheckCircle2 size={16} color="var(--gold)" />
        Livrables
      </h2>
      <div className="space-y-2">
        {livrables.map((livrable) => (
          <button
            key={livrable.id}
            onClick={() => onOpen(livrable.id)}
            className="w-full text-left flex items-center justify-between gap-3 p-3"
            style={{ background: '#F1F0EC', borderRadius: 'var(--radius-sm)' }}
          >
            <span className="text-sm flex items-center gap-2 min-w-0">
              <span className="truncate" title={livrable.nom}>{livrable.nom}</span>
              {livrable.obligatoire && (
                <span className="text-xs flex-shrink-0" style={{ color: 'var(--red)' }}>obligatoire</span>
              )}
            </span>
            <span
              className="text-xs font-semibold flex-shrink-0"
              style={{ color: VALIDATION_COACH_COLORS[livrable.validation_coach] || 'var(--text-soft)' }}
            >
              {livrable.validation_coach || livrable.etat || '—'}
            </span>
          </button>
        ))}
      </div>
    </section>
  )
}

export default function App() {
  const [jetonPartage] = useState(() => new URLSearchParams(window.location.search).get('partage'))

  // Monogramme RL au meme endroit (en haut a droite) sur tous les ecrans,
  // sauf l'accueil qui porte deja le logo de marque (voir index.css).
  return (
    <>
      <img src={monogramme} alt="RL-eVolution" className="portal-monogramme" />
      {jetonPartage ? <PagePartage jeton={jetonPartage} /> : <Portail />}
    </>
  )
}

function Portail() {
  const [screen, setScreen] = useState('loading')

  useEffect(() => {
    document.body.dataset.ecran = screen
  }, [screen])
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [passwordConfirm, setPasswordConfirm] = useState('')
  const [linkToken, setLinkToken] = useState('')
  const [linkInfo, setLinkInfo] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [dashboard, setDashboard] = useState(null)
  const [activeFicheId, setActiveFicheId] = useState(null)
  const [ficheData, setFicheData] = useState(null)
  const [livrableData, setLivrableData] = useState(null)
  const retourEnCours = ficheData?.entrees?.[ficheData.entrees.length - 1]?.retour_ia?.statut === 'en_cours'

  // Retour IA en cours de redaction : on relit la fiche toutes les 8 s
  // (5 min au plus) sans toucher a ce que le client est en train de saisir.
  // En Autonome le portail le redige lui-meme en quelques secondes.
  useEffect(() => {
    if (!retourEnCours || !activeFicheId) return undefined

    let essais = 0
    const minuteur = setInterval(async () => {
      essais += 1
      if (essais > 40) {
        clearInterval(minuteur)
        return
      }

      try {
        const response = await fetch(`${API_BASE}/portal/fiches/${activeFicheId}`, {
          headers: { Authorization: `Bearer ${localStorage.getItem(SESSION_KEY)}` },
        })
        if (!response.ok) return
        const data = await response.json()
        const derniere = data.entrees[data.entrees.length - 1]
        if (derniere?.retour_ia?.statut && derniere.retour_ia.statut !== 'en_cours') {
          setFicheData((prev) => (prev ? { ...prev, entrees: data.entrees } : prev))
          clearInterval(minuteur)
        }
      } catch {
        // Nouvel essai au prochain tour.
      }
    }, 8000)

    return () => clearInterval(minuteur)
  }, [retourEnCours, activeFicheId])
  const [formValues, setFormValues] = useState({})
  const [saving, setSaving] = useState(false)
  const [validating, setValidating] = useState(false)
  const [onglet, setOnglet] = useState('tableau')
  const [attestationOuverte, setAttestationOuverte] = useState(false)
  const [accueilFerme, setAccueilFerme] = useState(false)
  const [menuOuvert, setMenuOuvert] = useState(false)
  const nouveautes = useNouveautesEleve(screen === 'dashboard' && Boolean(dashboard))
  // Lien direct (WhatsApp du lundi, notification) : ?ouvrir=bilan, prospects,
  // parcours ou fiche:<id>. Garde en memoire le temps de se connecter.
  const [ouvrirEnAttente, setOuvrirEnAttente] = useState(() => {
    const params = new URLSearchParams(window.location.search)
    const valeur = params.get('ouvrir')
    try {
      if (valeur && !params.get('token')) {
        sessionStorage.setItem(OUVRIR_KEY, valeur)
        window.history.replaceState({}, '', window.location.pathname)
      }
      return valeur || sessionStorage.getItem(OUVRIR_KEY)
    } catch {
      return valeur
    }
  })

  const loadDashboard = useCallback(async () => {
    const token = localStorage.getItem(SESSION_KEY)

    if (!token) {
      setScreen('login')
      return
    }

    try {
      const response = await fetch(`${API_BASE}/portal/me`, {
        headers: { Authorization: `Bearer ${token}` },
      })

      if (response.status === 401) {
        localStorage.removeItem(SESSION_KEY)
        setScreen('login')
        return
      }

      if (!response.ok) throw new Error('Erreur de chargement de ton espace.')

      setDashboard(await response.json())
      setScreen('dashboard')
    } catch (err) {
      setError(err.message)
      setScreen('login')
    }
  }, [])

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const token = params.get('token')

    if (!token) {
      loadDashboard()
      return
    }

    // Lien recu par email (ouverture de l'espace ou mot de passe oublie) : il
    // sert uniquement a creer le mot de passe, la connexion se fait ensuite
    // par email + mot de passe.
    window.history.replaceState({}, '', window.location.pathname)

    ;(async () => {
      try {
        const response = await fetch(`${API_BASE}/portal/auth/verify`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token }),
        })

        if (!response.ok) {
          const data = await response.json().catch(() => ({}))
          throw new Error(response.status === 401 && data.detail ? data.detail : 'Ce lien est invalide ou a expiré.')
        }

        const data = await response.json()
        setLinkToken(token)
        setLinkInfo(data)
        setEmail(data.email || '')
        setScreen('set-password')
      } catch (err) {
        setError(err.message)
        setScreen('login')
      }
    })()
  }, [loadDashboard])

  const openSession = (sessionToken) => {
    localStorage.setItem(SESSION_KEY, sessionToken)
    setPassword('')
    setPasswordConfirm('')
    setLinkToken('')
    setLinkInfo(null)
    setScreen('loading')
    loadDashboard()
  }

  const login = async (event) => {
    event.preventDefault()
    setError('')
    setSubmitting(true)

    try {
      const response = await fetch(`${API_BASE}/portal/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })

      const data = await response.json().catch(() => ({}))

      if (!response.ok) throw new Error(data.detail || 'Une erreur est survenue, réessaie.')

      openSession(data.session_token)
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const savePassword = async (event) => {
    event.preventDefault()
    setError('')

    if (password !== passwordConfirm) {
      setError('Les deux mots de passe ne sont pas identiques.')
      return
    }

    setSubmitting(true)

    try {
      const response = await fetch(`${API_BASE}/portal/auth/set-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: linkToken, password }),
      })

      const data = await response.json().catch(() => ({}))

      if (!response.ok) throw new Error(data.detail || 'Une erreur est survenue, réessaie.')

      openSession(data.session_token)
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const requestLink = async (event) => {
    event.preventDefault()
    setError('')
    setSubmitting(true)

    try {
      const response = await fetch(`${API_BASE}/portal/auth/request-link`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      })

      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        throw new Error(data.detail || "Une erreur est survenue, réessaie.")
      }

      setScreen('check-email')
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const openFiche = async (ficheId) => {
    nouveautes.marquerFicheVue(ficheId)
    const token = localStorage.getItem(SESSION_KEY)
    setActiveFicheId(ficheId)
    setFicheData(null)
    setError('')
    setScreen('fiche')

    try {
      const response = await fetch(`${API_BASE}/portal/fiches/${ficheId}`, {
        headers: { Authorization: `Bearer ${token}` },
      })

      if (!response.ok) throw new Error('Impossible de charger cette fiche.')

      const data = await response.json()
      setFicheData(data)

      const latest = data.entrees[data.entrees.length - 1]
      setFormValues(data.mode === 'unique' && latest ? latest.donnees : {})
    } catch (err) {
      setError(err.message)
    }
  }

  const openLivrable = async (livrableId) => {
    const token = localStorage.getItem(SESSION_KEY)
    setLivrableData(null)
    setError('')
    setScreen('livrable')

    try {
      const response = await fetch(`${API_BASE}/portal/livrables/${livrableId}`, {
        headers: { Authorization: `Bearer ${token}` },
      })

      if (!response.ok) throw new Error('Impossible de charger ce livrable.')

      setLivrableData(await response.json())
    } catch (err) {
      setError(err.message)
    }
  }

  const backToFiche = () => {
    setScreen('fiche')
    setLivrableData(null)
  }

  const toggleCheck = async (cle, coche) => {
    // Cases a cocher du modele (ex. "Validation du plan") : etat memorise par
    // client dans une entree speciale "__checklist__".
    const precedent = ficheData?.checks || {}
    const suivant = { ...precedent, [cle]: coche }
    setFicheData((prev) => (prev ? { ...prev, checks: suivant } : prev))

    try {
      const token = localStorage.getItem(SESSION_KEY)
      const response = await fetch(`${API_BASE}/portal/fiches/${activeFicheId}/entries`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ data: { __checklist__: suivant } }),
      })

      if (!response.ok) throw new Error()
    } catch {
      setFicheData((prev) => (prev ? { ...prev, checks: precedent } : prev))
      setError("La case n'a pas pu être enregistrée. Réessaie.")
    }
  }

  const saveKpi = async (kpiId, valeurs) => {
    const token = localStorage.getItem(SESSION_KEY)
    const response = await fetch(`${API_BASE}/portal/kpi/${kpiId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ valeurs }),
    })

    if (!response.ok) throw new Error()
    const data = await response.json()
    if (data.dashboard) setDashboard(data.dashboard)
  }

  const saveCurrentEntry = async () => {
    const token = localStorage.getItem(SESSION_KEY)

    const response = await fetch(`${API_BASE}/portal/fiches/${activeFicheId}/entries`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ data: formValues }),
    })

    if (!response.ok) throw new Error("Erreur lors de l'enregistrement.")

    const { entry: enregistree } = await response.json()
    const entry = ficheData?.retour_ia_actif ? { ...enregistree, retour_ia: { statut: 'en_cours' } } : enregistree

    setFicheData((prev) => {
      if (!prev) return prev
      if (prev.mode === 'unique') return { ...prev, entrees: [entry] }
      return { ...prev, entrees: [...prev.entrees, entry] }
    })

    return entry
  }

  const submitEntry = async (event) => {
    event.preventDefault()
    setSaving(true)
    setError('')

    try {
      await saveCurrentEntry()
      if (ficheData?.mode === 'recurrent') setFormValues({})
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  const backToDashboard = () => {
    setScreen('dashboard')
    setActiveFicheId(null)
    setFicheData(null)
    loadDashboard()
  }

  const validerEtSuivant = async () => {
    const token = localStorage.getItem(SESSION_KEY)
    setValidating(true)
    setError('')

    try {
      if (ficheData?.mode === 'unique' && ficheData.champs.length > 0) {
        await saveCurrentEntry()
      }

      const response = await fetch(`${API_BASE}/portal/fiches/${activeFicheId}/valider`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      })

      if (!response.ok) throw new Error('Erreur lors de la validation.')

      const data = await response.json()
      let freshDashboard = data.dashboard

      if (!freshDashboard) {
        const meResponse = await fetch(`${API_BASE}/portal/me`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        freshDashboard = await meResponse.json()
      }

      setDashboard(freshDashboard)

      const currentIndex = freshDashboard.fiches.findIndex((fiche) => fiche.id === activeFicheId)
      const next = freshDashboard.fiches[currentIndex + 1]

      if (next && !next.acces?.includes('Bloqué')) {
        openFiche(next.id)
      } else {
        setScreen('dashboard')
        setActiveFicheId(null)
        setFicheData(null)
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setValidating(false)
    }
  }

  const logout = () => {
    localStorage.removeItem(SESSION_KEY)
    setDashboard(null)
    setScreen('login')
  }

  useEffect(() => {
    if (screen !== 'dashboard' || !dashboard || !ouvrirEnAttente) return
    const cible = ouvrirEnAttente
    setOuvrirEnAttente(null)
    try {
      sessionStorage.removeItem(OUVRIR_KEY)
    } catch {
      // Rien a nettoyer.
    }
    const ouverte = (fiche) => fiche && !String(fiche.acces || '').includes('Bloqué')

    if (cible === 'bilan') {
      const bilan = dashboard.fiches.find((f) => f.master_id === BILAN_HEBDO_MASTER_ID)
      if (ouverte(bilan)) openFiche(bilan.id)
    } else if (cible.startsWith('fiche:')) {
      const fiche = dashboard.fiches.find((f) => f.id === cible.slice(6))
      if (ouverte(fiche)) openFiche(fiche.id)
    } else if (ONGLETS.some((o) => o.cle === cible)) {
      setOnglet(cible)
    }
    // openFiche change a chaque rendu : on ne reagit qu'au lien en attente.
  }, [screen, dashboard, ouvrirEnAttente])

  if (screen === 'loading') {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="animate-spin" color="var(--gold)" size={32} />
      </div>
    )
  }

  if (['login', 'forgot', 'check-email', 'set-password'].includes(screen)) {
    const goTo = (next) => {
      setError('')
      setPassword('')
      setPasswordConfirm('')
      setScreen(next)
    }

    const submitButton = (label) => (
      <button
        type="submit"
        disabled={submitting}
        className="w-full font-semibold py-2.5 rounded-xl flex items-center justify-center gap-2"
        style={{ background: 'var(--gold)', color: 'var(--bg-dark)', opacity: submitting ? 0.7 : 1 }}
      >
        {submitting && <Loader2 className="animate-spin" size={16} />}
        {label}
      </button>
    )

    const emailField = (
      <div className="flex items-center gap-2 field-input">
        <Mail size={18} color="var(--text-soft)" />
        <input
          type="email"
          required
          autoComplete="email"
          placeholder="nom@exemple.com"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          className="bg-transparent outline-none flex-1"
        />
      </div>
    )

    const passwordField = (value, setValue, placeholder, autoComplete) => (
      <div className="flex items-center gap-2 field-input">
        <Lock size={18} color="var(--text-soft)" />
        <input
          type="password"
          required
          minLength={autoComplete === 'new-password' ? 8 : undefined}
          autoComplete={autoComplete}
          placeholder={placeholder}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          className="bg-transparent outline-none flex-1"
        />
      </div>
    )

    const linkButton = (label, next) => (
      <button
        type="button"
        onClick={() => goTo(next)}
        className="text-sm underline"
        style={{ color: 'var(--text-soft)' }}
      >
        {label}
      </button>
    )

    const errorText = error && <p className="text-sm" style={{ color: 'var(--red)' }}>{error}</p>

    return (
      <div className="min-h-screen flex items-center justify-center p-6">
        <div className="card-glass w-full max-w-md p-8" style={{ borderRadius: 'var(--radius-lg)' }}>
          <h1 className="gold-title text-2xl font-extrabold mb-2">Espace Client eVolution 2.0</h1>

          {screen === 'login' && (
            <>
              <p className="text-sm mb-6" style={{ color: 'var(--text-soft)' }}>
                Connecte-toi avec ton email et ton mot de passe.
              </p>
              <form onSubmit={login} className="space-y-4">
                {emailField}
                {passwordField(password, setPassword, 'Mot de passe', 'current-password')}
                {errorText}
                {submitButton('Se connecter')}
              </form>
              <div className="mt-5 text-center">
                {linkButton('Première connexion ou mot de passe oublié ?', 'forgot')}
              </div>
            </>
          )}

          {screen === 'forgot' && (
            <>
              <p className="text-sm mb-6" style={{ color: 'var(--text-soft)' }}>
                Entre ton email : tu recevras un lien pour créer ton mot de passe.
              </p>
              <form onSubmit={requestLink} className="space-y-4">
                {emailField}
                {errorText}
                {submitButton('Recevoir le lien')}
              </form>
              <div className="mt-5 text-center">{linkButton('Retour à la connexion', 'login')}</div>
            </>
          )}

          {screen === 'set-password' && (
            <>
              <p className="text-sm mb-6" style={{ color: 'var(--text-soft)' }}>
                {linkInfo?.mot_de_passe_existant ? 'Choisis ton nouveau mot de passe' : 'Bienvenue ! Crée ton mot de passe'}
                {linkInfo?.email ? ` pour ${linkInfo.email}` : ''}. Tu l'utiliseras pour tes prochaines connexions
                (8 caractères minimum).
              </p>
              <form onSubmit={savePassword} className="space-y-4">
                <input type="email" value={email} autoComplete="username" readOnly hidden />
                {passwordField(password, setPassword, 'Mot de passe', 'new-password')}
                {passwordField(passwordConfirm, setPasswordConfirm, 'Confirme le mot de passe', 'new-password')}
                {errorText}
                {submitButton('Enregistrer et accéder à mon espace')}
              </form>
            </>
          )}

          {screen === 'check-email' && (
            <div className="text-center py-4">
              <CheckCircle2 className="mx-auto mb-3" color="var(--green)" size={36} />
              <p style={{ color: 'var(--text-dimmed)' }}>
                Vérifie tes emails : si ton adresse correspond à un compte, un lien pour créer ton mot de passe
                t'a été envoyé.
              </p>
              <div className="mt-5">{linkButton('Retour à la connexion', 'login')}</div>
            </div>
          )}
        </div>
      </div>
    )
  }

  if (screen === 'dashboard' && dashboard) {
    const totalFiches = dashboard.fiches.length
    const ficheDoneCount = dashboard.fiches.filter((fiche) => fiche.etat === 'Terminé').length

    const modules = []
    for (const fiche of dashboard.fiches) {
      const label = fiche.module || 'Autres'
      let group = modules.find((m) => m.label === label)
      if (!group) {
        group = { label, fiches: [] }
        modules.push(group)
      }
      group.fiches.push(fiche)
    }

    // Module en cours : le premier non termine (deplie dans Mon parcours).
    const moduleEnCours = modules.find((m) => !m.fiches.every((f) => f.etat === 'Terminé'))
    const ficheAReprendre = moduleEnCours?.fiches.find((f) => f.etat !== 'Terminé' && !f.acces?.includes('Bloqué'))
    const fichesTerminees = dashboard.fiches.filter((f) => f.etat === 'Terminé')

    if (attestationOuverte) {
      return <Attestation dashboard={dashboard} modules={modules} onRetour={() => setAttestationOuverte(false)} />
    }

    const jalons = calculerJalons(dashboard, modules)

    const changerOnglet = (cle) => {
      setOnglet(cle)
      setMenuOuvert(false)
      window.scrollTo(0, 0)
    }

    return (
      <div className="espace">
        <aside className={`espace-menu${menuOuvert ? ' espace-menu-ouvert' : ''}`}>
          <img src={logo} alt="RL-eVolution" className="espace-menu-logo" />
          <nav className="espace-menu-liens">
            {ONGLETS.map(({ cle, libelle, icone: Icone }) => {
              // Badges : RDV nouveaux ou deplaces (tableau de bord), retours d'Idris (parcours).
              const badge = cle === 'tableau' ? nouveautes.rdvNouveaux.length : cle === 'parcours' ? nouveautes.idrisNouveaux.length : 0
              return (
                <button
                  key={cle}
                  type="button"
                  className={`espace-menu-lien${onglet === cle ? ' espace-menu-lien-actif' : ''}`}
                  aria-current={onglet === cle ? 'page' : undefined}
                  onClick={() => changerOnglet(cle)}
                >
                  <Icone size={17} aria-hidden="true" />
                  {libelle}
                  {badge > 0 && <span className="menu-badge" aria-label={`${badge} nouveau${badge > 1 ? 'x' : ''}`}>{badge}</span>}
                </button>
              )
            })}
          </nav>
          <BoutonInstaller />
        </aside>
        {menuOuvert && <div className="espace-voile" onClick={() => setMenuOuvert(false)} />}

        {!accueilFerme && accueilAMontrer(dashboard) && (
          <AccueilGuide
            dashboard={dashboard}
            fiche={ficheAReprendre}
            onObjectif={(objectif) => setDashboard((d) => ({ ...d, objectif_90j: objectif }))}
            onFini={() => setAccueilFerme(true)}
            onOuvrir={openFiche}
          />
        )}
        <main className="espace-contenu">
          <header className="accueil-entete">
            <button
              type="button"
              className="espace-hamburger"
              aria-label={menuOuvert ? 'Fermer le menu' : 'Ouvrir le menu'}
              onClick={() => setMenuOuvert((v) => !v)}
            >
              {menuOuvert ? <X size={20} /> : <Menu size={20} />}
              {!menuOuvert && nouveautes.rdvNouveaux.length + nouveautes.idrisNouveaux.length > 0 && <span className="hamburger-pastille" aria-hidden="true" />}
            </button>
            <div className="accueil-titre">
              <h1>Système eVolution 2.0</h1>
              <p className="accueil-formule">{libelleFormule(dashboard.parcours)}</p>
            </div>
            <div className="accueil-client">
              <p className="accueil-client-nom">{dashboard.nom}</p>
              <button onClick={logout} className="accueil-deconnexion">
                Se déconnecter
              </button>
            </div>
          </header>

          {onglet === 'tableau' && (
            <>
              <h2 className="accueil-section-titre">Tableau de bord</h2>

              {/* Ordre (affichage du 26/10/2026) : ou j'en suis, quoi faire, est-ce que ca marche. */}
              <CapParcours
                rythme={dashboard.rythme}
                objectif={dashboard.objectif_90j}
                fichesFaites={ficheDoneCount}
                fichesTotal={totalFiches}
                regularite={dashboard.regularite}
              />

              {/* RDV avec Rony juste sous le cap 90 jours (demande de Rony, 28/10/2026). */}
              <MesPoints points={nouveautes.points} nouveaux={nouveautes.rdvNouveaux} onVu={nouveautes.marquerRdvVus} onChange={nouveautes.relire} />
              <ReserverRdv points={nouveautes.points} onReserve={nouveautes.relire} />

              <ProchaineEtape
                module={moduleEnCours}
                fiche={ficheAReprendre}
                onOpen={openFiche}
                onParcours={() => changerOnglet('parcours')}
              />

              <RelancesDuJour onOuvrir={() => changerOnglet('prospects')} />

              {bilanFinalOuvert(dashboard) && <BilanFinal onAttestation={() => { setAttestationOuverte(true); window.scrollTo(0, 0) }} />}
              {bilanFinalOuvert(dashboard) && <AvisJ90 />}

              <MesResultats
                kpis={dashboard.kpi}
                personnalisation={dashboard.personnalisation}
                jour={dashboard.rythme ? dashboard.rythme.jour : jourDuParcours(dashboard.date_demarrage)}
                onSave={saveKpi}
              />

              <SyntheseCourte syntheses={dashboard.syntheses} />
              <PasserelleCoaching passerelle={dashboard.passerelle_coaching} />

              <OuMettreTonEnergie
                personnalisation={dashboard.personnalisation}
                fiches={dashboard.fiches}
                jalons={jalons}
                regularite={dashboard.regularite}
                onOpen={openFiche}
                onVoirJalons={() => changerOnglet('parcours')}
              />

              {/* Relue apres l'accueil guide, qui presente deja Idris. */}
              <PresentationIdris key={accueilFerme ? 'apres-accueil' : 'avant-accueil'} nom={dashboard.nom} />

              <IdrisLigne etape={etapeDuCalendrier(dashboard.rythme)} onOuvrir={() => changerOnglet('idris')} />
              <ProchaineSession sessions={dashboard.sessions} onVoir={() => changerOnglet('communaute')} />
            </>
          )}

          {onglet === 'parcours' && (
            <>
              <h2 className="accueil-section-titre">Mon parcours</h2>
              <NouveauxRetoursIdris retours={nouveautes.idrisNouveaux} fiches={dashboard.fiches} onOpen={openFiche} />
              <FriseParcours modules={modules} moduleEnCours={moduleEnCours} rythme={dashboard.rythme} onOpen={openFiche} />
              <ParcoursSurMesure personnalisation={dashboard.personnalisation} fiches={dashboard.fiches} onOpen={openFiche} />
              <Jalons jalons={jalons} regularite={dashboard.regularite} />
            </>
          )}

          {onglet === 'prospects' && (
            <>
              <h2 className="accueil-section-titre">Mes prospects</h2>
              <CarnetProspects />
            </>
          )}

          {onglet === 'idris' && (
            <>
              <h2 className="accueil-section-titre">Idris, ton assistant commercial</h2>
              <EspaceIdris />
            </>
          )}

          {onglet === 'ressources' && (
            <>
              <h2 className="accueil-section-titre">Ressources</h2>
              <Bibliotheque />
              <section className="panel">
                <p className="panel-eyebrow">Mes fiches terminées</p>
                {fichesTerminees.length ? (
                  <ul className="module-carte-fiches ressources-liste">
                    {fichesTerminees.map((fiche) => {
                      const { numero: n, titre: t } = lireFiche(fiche.nom)
                      return (
                        <li key={fiche.id}>
                          <button onClick={() => openFiche(fiche.id)} className="module-fiche module-fiche-fini">
                            <span className="module-fiche-numero">{n ?? '•'}</span>
                            <span className="module-fiche-titre">{t}</span>
                            <ChevronRight size={14} className="module-fiche-icone" aria-hidden="true" />
                          </button>
                        </li>
                      )
                    })}
                  </ul>
                ) : (
                  <p className="espace-vide">Tes fiches terminées apparaîtront ici, prêtes à être relues.</p>
                )}
              </section>
              <ModulesBreakdown modules={modules} />
            </>
          )}

          {onglet === 'communaute' && (
            <>
              <h2 className="accueil-section-titre">Communauté</h2>
              <Communaute dashboard={dashboard} points={nouveautes.points} />
            </>
          )}

          {onglet === 'profil' && (
            <>
              <h2 className="accueil-section-titre">Profil</h2>
              <InstallerAppli />
              <NotificationsTelephone />
              <PartageProgression />
              <div className="portal-secondary-row">
                <IdentiteCard identite={dashboard.identite} cohorte={null} sessions={[]} />
                {dashboard.objectif_90j && (
                  <section className="panel">
                    <p className="panel-eyebrow">Objectif 90 jours</p>
                    <p className="panel-lead">{dashboard.objectif_90j}</p>
                  </section>
                )}
              </div>
            </>
          )}
        </main>
      </div>
    )
  }

  if (screen === 'fiche') {
    return (
      <div className="min-h-screen p-5 md:p-10 reading-column mx-auto page-monogramme">
        <button onClick={backToDashboard} className="flex items-center gap-2 mb-6 text-sm" style={{ color: 'var(--ink-soft)' }}>
          <ArrowLeft size={16} /> Retour au parcours
        </button>

        {!ficheData ? (
          <Loader2 className="animate-spin" color="var(--gold)" size={28} />
        ) : (
          <>
            <PourquoiPourToi
              fiche={dashboard?.fiches?.find((f) => f.id === activeFicheId)}
              personnalisation={dashboard?.personnalisation}
            />

            {/* Pas de titre ici : verifie sur les 22 fiches master, le
                contenu commence toujours par son propre titre en "# "
                (avec emoji) - un h1 au-dessus ferait doublon. */}
            {ficheData.mode === 'recurrent' && ficheData.segments ? (
              <FicheSuivi
                ficheData={ficheData}
                formValues={formValues}
                onChange={(cle, value) => setFormValues((prev) => ({ ...prev, [cle]: value }))}
                onSubmit={submitEntry}
                saving={saving}
                error={error}
                estBilan={dashboard?.fiches?.find((f) => f.id === activeFicheId)?.master_id === BILAN_HEBDO_MASTER_ID}
              />
            ) : ficheData.mode === 'unique' && ficheData.segments ? (
              <>
                {ficheData.mis_a_jour && (
                  <p className="fiche-maj">Mis à jour le {formaterMaj(ficheData.mis_a_jour)}</p>
                )}

                {ficheData.brouillon_ia && (
                  <BrouillonIA
                    ficheId={activeFicheId}
                    champs={ficheData.champs}
                    formValues={formValues}
                    onRemplir={(valeurs) => setFormValues((prev) => ({ ...prev, ...valeurs }))}
                  />
                )}

                <FicheSegments
                  surtitre={surtitreFiche(ficheData.nom)}
                  segments={ficheData.segments}
                  formValues={formValues}
                  onChange={(cle, value) => setFormValues((prev) => ({ ...prev, [cle]: value }))}
                />

                {error && <p className="text-sm mb-3" style={{ color: 'var(--red)' }}>{error}</p>}
              </>
            ) : (
              <>
                <FicheContent
                  surtitre={surtitreFiche(ficheData.nom)}
                  texte={ficheData.contenu}
                  checks={ficheData.checks}
                  onToggleCheck={toggleCheck}
                  saisies={ficheData.mode === 'recurrent' ? { champs: ficheData.champs, entrees: ficheData.entrees } : null}
                />

                {ficheData.mode === 'recurrent' && ficheData.entrees.length > 0
                  && indexTableModele((ficheData.contenu || '').split('\n'), ficheData.champs) < 0 && (
                  <section className="fiche-section fiche-section-isolee">
                    <header className="fiche-section-entete">
                      <ListChecks size={18} className="fiche-section-icone" />
                      <h2 className="fiche-section-titre">Mes entrées</h2>
                    </header>
                    {renderTextLine(tableSaisies(ficheData.champs, ficheData.entrees, null), 'saisies')}
                  </section>
                )}

                {ficheData.champs.length > 0 && (
                <form onSubmit={submitEntry} className="fiche-section fiche-formulaire">
                  <header className="fiche-section-entete">
                    <Rocket size={18} className="fiche-section-icone" />
                    <h2 className="fiche-section-titre">
                      {ficheData.mode === 'recurrent' ? 'Ajouter une entrée' : 'Tes réponses'}
                    </h2>
                  </header>

                  {ficheData.champs.map((champ) => (
                    <div key={champ.cle} className="fiche-champ">
                      <EnteteChamp
                        champ={champ}
                        value={formValues[champ.cle]}
                        onChange={(value) => setFormValues((prev) => ({ ...prev, [champ.cle]: value }))}
                      >
                        {champ.libelle}
                      </EnteteChamp>
                      <FieldInput
                        champ={champ}
                        value={formValues[champ.cle]}
                        onChange={(value) => setFormValues((prev) => ({ ...prev, [champ.cle]: value }))}
                      />
                    </div>
                  ))}

                  {error && <p className="text-sm" style={{ color: 'var(--red)' }}>{error}</p>}

                  <button
                    type="submit"
                    disabled={saving}
                    className="fiche-bouton disabled:opacity-60"
                  >
                    {saving ? 'Enregistrement…' : 'Enregistrer'}
                  </button>
                </form>
                )}

                {error && ficheData.champs.length === 0 && (
                  <p className="text-sm mb-3" style={{ color: 'var(--red)' }}>{error}</p>
                )}
              </>
            )}

            {ficheData.entrainement && <Entrainement />}

            <RetourIA
              actif={ficheData.retour_ia_actif}
              retour={ficheData.entrees[ficheData.entrees.length - 1]?.retour_ia}
            />

            <LivrablesSection livrables={ficheData.livrables} onOpen={openLivrable} />

            <div className="mt-8 validate-bar">
              <button
                onClick={validerEtSuivant}
                disabled={validating}
                className="validate-button font-semibold flex items-center justify-center gap-2 disabled:opacity-60"
                style={{ background: 'var(--green)', color: 'var(--bg-dark)' }}
              >
                <CheckCircle2 size={18} />
                {validating ? 'Validation…' : 'Valider et continuer'}
              </button>
            </div>
          </>
        )}
      </div>
    )
  }

  if (screen === 'livrable') {
    return (
      <div className="min-h-screen p-5 md:p-10 reading-column mx-auto page-monogramme">
        <button onClick={backToFiche} className="flex items-center gap-2 mb-6 text-sm" style={{ color: 'var(--ink-soft)' }}>
          <ArrowLeft size={16} /> Retour à la fiche
        </button>

        {!livrableData ? (
          <Loader2 className="animate-spin" color="var(--gold)" size={28} />
        ) : (
          <FicheContent texte={livrableData.contenu} surtitre="Livrable" />
        )}

        {error && <p className="text-sm" style={{ color: 'var(--red)' }}>{error}</p>}
      </div>
    )
  }

  return null
}
