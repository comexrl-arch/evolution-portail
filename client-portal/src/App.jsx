import { useCallback, useEffect, useRef, useState } from 'react'
import { formaterMaj } from './dates'
import { ArrowLeft, Award, BookOpen, CalendarDays, CheckCircle2, ChevronDown, ChevronRight, Compass, Copy, ListChecks, LayoutDashboard, Loader2, Lock, Mail, Map as IconeCarte, MapPin, Menu, MessageCircle, Mic, Phone, Printer, Quote, Smartphone, Rocket, Sparkles, Target, TrendingUp, UserRound, Users, X } from 'lucide-react'
import logo from './assets/logo.svg'
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
          Choisir...
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

  const zone = (
    <textarea
      className="field-input"
      rows={3}
      placeholder="Écris ici..."
      value={value ?? ''}
      onChange={(event) => onChange(event.target.value)}
    />
  )

  if (!CHAMP_ORAL.test(champ.libelle || '')) return zone

  return (
    <>
      {zone}
      <DicteeVocale value={value ?? ''} onChange={onChange} />
    </>
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
        <p className="fiche-champ-libelle">{renderInline(champ.libelle_affiche || champ.libelle)}</p>
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

function FicheSuivi({ ficheData, formValues, onChange, onSubmit, saving, error }) {
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
            <label className="fiche-champ-libelle">
              {lisible(champ.libelle)}
            </label>
            <FieldInput champ={champ} value={formValues[champ.cle]} onChange={(value) => onChange(champ.cle, value)} />
          </div>
        ))}

        {error && <p className="text-sm" style={{ color: 'var(--red)' }}>{error}</p>}

        <button type="submit" disabled={saving} className="fiche-bouton disabled:opacity-60">
          {saving ? 'Enregistrement...' : 'Enregistrer ma semaine'}
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

function libelleFormule(parcours) {
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
function lireModule(label) {
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

function lireFiche(nom) {
  const propre = sansNomClient(nom || '').trim()
  const numero = propre.match(/^(\d+)\s*[.)]\s*(.*)$/)
  return numero ? { numero: numero[1], titre: casseDePhrase(numero[2]) } : { numero: null, titre: casseDePhrase(propre) }
}

const ONGLETS = [
  { cle: 'tableau', libelle: 'Tableau de bord', icone: LayoutDashboard },
  { cle: 'parcours', libelle: 'Mon parcours', icone: IconeCarte },
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

  return (
    <section className="prochaine-etape">
      <img src={illustrationDuModule(module.label)} alt="" className="prochaine-etape-image" />
      <div className="prochaine-etape-corps">
        <p className="prochaine-etape-surtitre">Prochaine étape · {surtitre}</p>
        <h3 className="prochaine-etape-titre">{titre}</h3>
        {fiche && <p className="prochaine-etape-fiche">{lireFiche(fiche.nom).titre}</p>}
        <div className="prochaine-etape-actions">
          {fiche && (
            <button type="button" className="fiche-bouton" onClick={() => onOpen(fiche.id)}>
              Reprendre <ChevronRight size={15} aria-hidden="true" />
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
        {attente ? 'Idris rédige...' : 'Demander un brouillon à Idris'}
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
  const response = await fetch(`${API_BASE}/portal/idris${chemin}`, {
    method: corps ? 'POST' : 'GET',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem(SESSION_KEY)}` },
    body: corps ? JSON.stringify(corps) : undefined,
  })
  if (!response.ok) {
    const erreur = new Error('idris')
    erreur.status = response.status
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

function Jalons({ jalons, regularite }) {
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

  if (!faits.length && !regularite) return null

  return (
    <section className="panel jalons">
      <p className="panel-eyebrow">Mes jalons</p>
      {aFeter && (
        <div className="jalons-fete">
          <IdrisMessage titre={`Bravo · ${aFeter.titre}`}>
            <p>{aFeter.bravo}</p>
            <button type="button" className="brouillon-ia-bouton" onClick={merci}>Merci Idris !</button>
          </IdrisMessage>
        </div>
      )}
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
          RL-Evolution atteste que <strong>{dashboard.nom}</strong> a suivi le parcours d'accompagnement commercial
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
          <p className="attestation-signature">Rony<br /><span>Coach, RL-Evolution</span></p>
        </div>
      </article>
    </div>
  )
}

// Installation sur le telephone : bouton natif quand le navigateur le
// propose (Android, Chrome), sinon la marche a suivre (iPhone, Safari).
function InstallerAppli() {
  const [invite, setInvite] = useState(null)
  const [installee, setInstallee] = useState(() => window.matchMedia?.('(display-mode: standalone)').matches || window.navigator.standalone === true)

  useEffect(() => {
    const garder = (event) => {
      event.preventDefault()
      setInvite(event)
    }
    const fini = () => setInstallee(true)
    window.addEventListener('beforeinstallprompt', garder)
    window.addEventListener('appinstalled', fini)
    return () => {
      window.removeEventListener('beforeinstallprompt', garder)
      window.removeEventListener('appinstalled', fini)
    }
  }, [])

  if (installee) return null

  return (
    <section className="panel installer-appli">
      <p className="panel-eyebrow"><Smartphone size={14} /> Ton espace sur ton téléphone</p>
      <p className="panel-lead">Ajoute eVolution 2.0 sur ton écran d'accueil : tu l'ouvres en un geste, comme une application.</p>
      {invite ? (
        <button type="button" className="fiche-bouton" onClick={async () => { invite.prompt(); await invite.userChoice; setInvite(null) }}>
          Installer l'application
        </button>
      ) : (
        <ul className="installer-etapes">
          <li><strong>iPhone (Safari) :</strong> touche le bouton Partager, puis « Sur l'écran d'accueil ».</li>
          <li><strong>Android (Chrome) :</strong> touche le menu ⋮, puis « Installer l'application » ou « Ajouter à l'écran d'accueil ».</li>
        </ul>
      )}
    </section>
  )
}

function ModuleCarte({ module, onOpen, ouvertParDefaut }) {
  const { surtitre, titre } = lireModule(module.label)
  const illustration = illustrationDuModule(module.label)
  const [ouvert, setOuvert] = useState(ouvertParDefaut)
  const terminees = module.fiches.filter((f) => f.etat === 'Terminé').length
  const total = module.fiches.length
  const pct = total ? Math.round((terminees / total) * 100) : 0
  const statut = terminees === total ? 'Terminé' : module.fiches.some((f) => f.etat === 'En cours' || f.etat === 'Terminé') ? 'En cours' : 'À venir'

  return (
    <article className={`module-carte module-carte-${statut === 'Terminé' ? 'fini' : statut === 'En cours' ? 'actif' : 'avenir'}`}>
      {illustration && <img src={illustration} alt="" className="module-carte-image" loading="lazy" />}
      <div className="module-carte-corps">
        <div className="module-carte-entete">
          <p className="module-carte-surtitre">{surtitre}</p>
          <span className={`module-carte-statut module-carte-statut-${statut === 'Terminé' ? 'fini' : statut === 'En cours' ? 'actif' : 'avenir'}`}>
            {statut}
          </span>
        </div>
        <h3 className="module-carte-titre">{titre}</h3>
        <div className="module-carte-progression">
          <div className="module-carte-barre"><span style={{ width: `${pct}%` }} /></div>
          <span>{terminees} / {total} fiches</span>
        </div>
        <button
          type="button"
          className="module-carte-bascule"
          aria-expanded={ouvert}
          onClick={() => setOuvert((v) => !v)}
        >
          <span>{ouvert ? 'Masquer les fiches' : `Afficher les fiches (${total})`}</span>
          <ChevronDown size={15} className={`module-carte-bascule-icone${ouvert ? ' module-carte-bascule-icone-ouverte' : ''}`} aria-hidden="true" />
        </button>
        {ouvert && <ul className="module-carte-fiches">
          {module.fiches.map((fiche) => {
            const bloquee = fiche.acces?.includes('Bloqué')
            const { numero: n, titre: t } = lireFiche(fiche.nom)
            const etat = fiche.etat === 'Terminé' ? 'fini' : fiche.etat === 'En cours' ? 'actif' : 'avenir'

            return (
              <li key={fiche.id}>
                <button disabled={bloquee} onClick={() => onOpen(fiche.id)} className={`module-fiche module-fiche-${etat}`}>
                  <span className="module-fiche-numero">{n ?? '•'}</span>
                  <span className="module-fiche-titre">{t}</span>
                  <BadgePriorite priorite={fiche.priorite} />
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
        </ul>}
      </div>
    </article>
  )
}

function IdentiteCard({ identite, cohorte, sessions }) {
  const infos = [
    { icon: Mail, valeur: identite.email },
    { icon: Phone, valeur: identite.telephone || identite.contact },
    { icon: MapPin, valeur: [identite.secteur, identite.territoire].filter(Boolean).join(' — ') },
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
              {session.nom} {session.date_heure && `— ${session.date_heure}`} {session.statut && `(${session.statut})`}
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

function kpiRenseignes(kpis) {
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
  return nombre.toLocaleString('fr-FR', { maximumFractionDigits: 1 })
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
  // Avec la saisie client, les cartes s'affichent meme vides : c'est
  // justement la que le client renseigne ses premiers chiffres.
  if (!Array.isArray(kpis) || kpis.length === 0) return null
  if (!onSave && !kpiRenseignes(kpis)) return null

  return (
    <section className="panel">
      <h2 className="panel-title flex items-center gap-2" style={{ color: 'var(--text-pure)' }}>
        <TrendingUp size={16} color="var(--gold)" />
        Mes indicateurs (KPI)
      </h2>
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
  // Monogramme RL au meme endroit (en haut a droite) sur tous les ecrans,
  // sauf l'accueil qui porte deja le logo de marque (voir index.css).
  return (
    <>
      <img src={monogramme} alt="RL-eVolution" className="portal-monogramme" />
      <Portail />
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
  const [menuOuvert, setMenuOuvert] = useState(false)

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

      if (!response.ok) throw new Error(data.detail || 'Une erreur est survenue, réessayez.')

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

      if (!response.ok) throw new Error(data.detail || 'Une erreur est survenue, réessayez.')

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
        throw new Error(data.detail || "Une erreur est survenue, réessayez.")
      }

      setScreen('check-email')
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const openFiche = async (ficheId) => {
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
    const avancementPct = totalFiches ? (ficheDoneCount / totalFiches) * 100 : 0

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

    const modulesDoneCount = modules.filter((m) => m.fiches.every((f) => f.etat === 'Terminé')).length
    // Seul le module en cours (le premier non termine) est deplie a l'ouverture.
    const moduleOuvertParDefaut = modules.find((m) => !m.fiches.every((f) => f.etat === 'Terminé'))?.label
    const modulesPct = modules.length ? (modulesDoneCount / modules.length) * 100 : 0

    // Les rollups Notion renvoient des tableaux (une valeur par ligne liee),
    // et peuvent etre exprimes en fraction (0-1) ou deja en pourcentage -
    // on normalise au mieux pour l'affichage de la jauge.
    const toPct = (valeur) => {
      const valeurs = (Array.isArray(valeur) ? valeur : [valeur]).filter((v) => typeof v === 'number')
      if (!valeurs.length) return 0
      const moyenne = valeurs.reduce((a, b) => a + b, 0) / valeurs.length
      return moyenne <= 1 ? moyenne * 100 : moyenne
    }

    const livrablesTermines = (Array.isArray(dashboard.progression_livrables) ? dashboard.progression_livrables : [])
      .filter((etat) => etat === 'Terminé').length
    const livrablesTotal = Array.isArray(dashboard.progression_livrables) ? dashboard.progression_livrables.length : 0
    const livrablesPct = livrablesTotal ? (livrablesTermines / livrablesTotal) * 100 : 0

    const kpiPct = toPct(dashboard.progression_kpi_j90)
    const avecKpi = kpiRenseignes(dashboard.kpi)

    const moduleEnCours = modules.find((m) => m.label === moduleOuvertParDefaut)
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
            {ONGLETS.map(({ cle, libelle, icone: Icone }) => (
              <button
                key={cle}
                type="button"
                className={`espace-menu-lien${onglet === cle ? ' espace-menu-lien-actif' : ''}`}
                aria-current={onglet === cle ? 'page' : undefined}
                onClick={() => changerOnglet(cle)}
              >
                <Icone size={17} aria-hidden="true" />
                {libelle}
              </button>
            ))}
          </nav>
        </aside>
        {menuOuvert && <div className="espace-voile" onClick={() => setMenuOuvert(false)} />}

        <main className="espace-contenu">
          <header className="accueil-entete">
            <button
              type="button"
              className="espace-hamburger"
              aria-label={menuOuvert ? 'Fermer le menu' : 'Ouvrir le menu'}
              onClick={() => setMenuOuvert((v) => !v)}
            >
              {menuOuvert ? <X size={20} /> : <Menu size={20} />}
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
              <div className="jauges">
                <Jauge pct={avancementPct} titre="Fiches" detail={`${ficheDoneCount} / ${totalFiches} fiches`} />
                <Jauge pct={modulesPct} titre="Modules" detail={`${modulesDoneCount} / ${modules.length} modules`} />
                {avecKpi && <Jauge pct={kpiPct} titre="KPI J90" detail="Progression vers tes objectifs" />}
                {livrablesTotal > 0 && (
                  <Jauge pct={livrablesPct} titre="Livrables" detail={`${livrablesTermines} / ${livrablesTotal} livrables`} />
                )}
              </div>

              <PresentationIdris nom={dashboard.nom} />

              <button type="button" className="idris-raccourci" onClick={() => changerOnglet('idris')}>
                <IdrisAvatar taille={36} />
                <span>
                  <strong>Une question sur ta stratégie commerciale ?</strong>
                  <span>Demande à Idris, prépare un message ou un rendez-vous.</span>
                </span>
                <ChevronRight size={16} aria-hidden="true" />
              </button>

              <ProchaineEtape
                module={moduleEnCours}
                fiche={ficheAReprendre}
                onOpen={openFiche}
                onParcours={() => changerOnglet('parcours')}
              />

              {bilanFinalOuvert(dashboard) && <BilanFinal onAttestation={() => { setAttestationOuverte(true); window.scrollTo(0, 0) }} />}

              <AvantMaintenant personnalisation={dashboard.personnalisation} kpis={dashboard.kpi} />

              <Jalons jalons={jalons} regularite={dashboard.regularite} />

              <ParcoursSurMesure personnalisation={dashboard.personnalisation} fiches={dashboard.fiches} onOpen={openFiche} />

              {dashboard.objectif_90j && (
                <section className="panel">
                  <p className="panel-eyebrow">Objectif 90 jours</p>
                  <p className="panel-lead">{dashboard.objectif_90j}</p>
                </section>
              )}

              <SynthesesSection syntheses={dashboard.syntheses} />
              <KpiTable kpis={dashboard.kpi} onSave={saveKpi} />
            </>
          )}

          {onglet === 'parcours' && (
            <>
              <h2 className="accueil-section-titre">Mon parcours</h2>
              <div className="modules-grille parcours-frise">
                {modules.map((group) => (
                  <ModuleCarte
                    key={group.label}
                    module={group}
                    onOpen={openFiche}
                    ouvertParDefaut={group.label === moduleOuvertParDefaut}
                  />
                ))}
              </div>
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
              <section className="panel">
                <p className="panel-eyebrow">Ma cohorte et mes sessions</p>
                {dashboard.cohorte && (
                  <p className="flex items-center gap-2 text-sm mb-3" style={{ color: 'var(--text-dimmed)' }}>
                    <Users size={14} color="var(--gold)" />
                    Cohorte {dashboard.cohorte.nom} {dashboard.cohorte.statut && `· ${dashboard.cohorte.statut}`}
                  </p>
                )}
                {dashboard.sessions.length > 0 ? (
                  dashboard.sessions.map((session) => (
                    <p key={session.id} className="flex items-center gap-2 text-sm mb-1.5" style={{ color: 'var(--text-dimmed)' }}>
                      <CalendarDays size={14} color="var(--text-soft)" />
                      {session.nom} {session.date_heure && `— ${session.date_heure}`} {session.statut && `(${session.statut})`}
                    </p>
                  ))
                ) : (
                  <p className="espace-vide">Les dates de tes prochains points collectifs apparaîtront ici dès qu'elles seront planifiées.</p>
                )}
              </section>
            </>
          )}

          {onglet === 'profil' && (
            <>
              <h2 className="accueil-section-titre">Profil</h2>
              <InstallerAppli />
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
                      {ficheData.mode === 'recurrent' ? 'Ajouter une entrée' : 'Vos réponses'}
                    </h2>
                  </header>

                  {ficheData.champs.map((champ) => (
                    <div key={champ.cle} className="fiche-champ">
                      <label className="fiche-champ-libelle">
                        {champ.libelle}
                      </label>
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
                    {saving ? 'Enregistrement...' : 'Enregistrer'}
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
                {validating ? 'Validation...' : 'Valider et continuer'}
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
