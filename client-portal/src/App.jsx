import { useCallback, useEffect, useState } from 'react'
import { ArrowLeft, BookOpen, CalendarDays, CheckCircle2, ChevronDown, ChevronRight, Compass, ListChecks, LayoutDashboard, Loader2, Lock, Mail, Map as IconeCarte, MapPin, Menu, MessageCircle, Phone, Quote, Rocket, Sparkles, Target, TrendingUp, UserRound, Users, X } from 'lucide-react'
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

  return (
    <textarea
      className="field-input"
      rows={3}
      placeholder="Écris ici..."
      value={value ?? ''}
      onChange={(event) => onChange(event.target.value)}
    />
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

function KpiTable({ kpis }) {
  if (!kpiRenseignes(kpis)) return null

  return (
    <section className="panel">
      <h2 className="panel-title flex items-center gap-2" style={{ color: 'var(--text-pure)' }}>
        <TrendingUp size={16} color="var(--gold)" />
        Mes indicateurs (KPI)
      </h2>
      <div className="kpi-grid">
        {kpis.map((kpi) => (
          <div key={kpi.id} className="kpi-card">
            <div className="flex items-center justify-between gap-2 mb-3">
              <div>
                <p className="kpi-nom">{kpi.nom}</p>
                <p className="kpi-categorie">{kpi.categorie || '—'}</p>
              </div>
              <AccesBadge acces={kpi.etat} />
            </div>
            <div className="kpi-periods">
              <KpiPeriod label="J0" valeur={kpi.valeur_j0} />
              <KpiPeriod label="J30" valeur={kpi.valeur_j30} objectif={kpi.objectif_j30} />
              <KpiPeriod label="J60" valeur={kpi.valeur_j60} objectif={kpi.objectif_j60} />
              <KpiPeriod label="J90" valeur={kpi.valeur_j90} objectif={kpi.objectif_j90} />
            </div>
          </div>
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
  const [formValues, setFormValues] = useState({})
  const [saving, setSaving] = useState(false)
  const [validating, setValidating] = useState(false)
  const [onglet, setOnglet] = useState('tableau')
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

  const saveCurrentEntry = async () => {
    const token = localStorage.getItem(SESSION_KEY)

    const response = await fetch(`${API_BASE}/portal/fiches/${activeFicheId}/entries`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ data: formValues }),
    })

    if (!response.ok) throw new Error("Erreur lors de l'enregistrement.")

    const { entry } = await response.json()

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

              <ProchaineEtape
                module={moduleEnCours}
                fiche={ficheAReprendre}
                onOpen={openFiche}
                onParcours={() => changerOnglet('parcours')}
              />

              {dashboard.objectif_90j && (
                <section className="panel">
                  <p className="panel-eyebrow">Objectif 90 jours</p>
                  <p className="panel-lead">{dashboard.objectif_90j}</p>
                </section>
              )}

              <SynthesesSection syntheses={dashboard.syntheses} />
              <KpiTable kpis={dashboard.kpi} />
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
