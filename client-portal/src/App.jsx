import { useCallback, useEffect, useState } from 'react'
import { ArrowLeft, CalendarDays, CheckCircle2, ChevronDown, Loader2, Lock, Mail, MapPin, Phone, Rocket, TrendingUp, Users } from 'lucide-react'
import logo from './assets/logo.jpeg'

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
      placeholder="Écrivez ici..."
      value={value ?? ''}
      onChange={(event) => onChange(event.target.value)}
    />
  )
}

function GaugeAvancement({ pct, label, compact }) {
  const clamped = Math.max(0, Math.min(100, Math.round(pct || 0)))
  const needleRotation = clamped * 1.8 - 90
  const arcColor = clamped < 34 ? 'var(--red)' : clamped < 67 ? 'var(--gold)' : 'var(--green)'

  return (
    <div className={`gauge-wrap${compact ? ' gauge-wrap-compact' : ''}`}>
      <svg viewBox="0 0 200 115" className="w-full">
        <path d="M 20 100 A 80 80 0 0 1 180 100" className="gauge-track" />
        <path
          d="M 20 100 A 80 80 0 0 1 180 100"
          className="gauge-progress"
          pathLength="100"
          style={{ stroke: arcColor, strokeDasharray: 100, strokeDashoffset: 100 - clamped }}
        />
        <line
          x1="100"
          y1="100"
          x2="100"
          y2="32"
          className="gauge-needle"
          style={{ transform: `rotate(${needleRotation}deg)`, transformOrigin: '100px 100px' }}
        />
        <circle cx="100" cy="100" r="6" className="gauge-hub" />
      </svg>
      <p className={`gauge-value${compact ? ' gauge-value-compact' : ''}`}>{clamped}%</p>
      {label && <p className="gauge-label">{label}</p>}
    </div>
  )
}

const TABLE_LINE_PREFIX = '##TABLE## '

function renderTextLine(ligne, key) {
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
      <div key={key} className="overflow-x-auto my-3">
        <table className="w-full text-sm" style={{ borderCollapse: 'collapse' }}>
          {headerRow && (
            <thead>
              <tr>
                {headerRow.map((cell, i) => (
                  <th
                    key={i}
                    className="text-left p-2 font-semibold"
                    style={{ borderBottom: '1px solid rgba(255,255,255,0.12)', color: 'var(--text-pure)' }}
                  >
                    {cell}
                  </th>
                ))}
              </tr>
            </thead>
          )}
          <tbody>
            {bodyRows.map((row, ri) => (
              <tr key={ri}>
                {row.map((cell, ci) => (
                  <td
                    key={ci}
                    className="p-2 align-top"
                    style={{ borderBottom: '1px solid rgba(255,255,255,0.06)', color: 'var(--text-dimmed)' }}
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }
  if (ligne.startsWith('### ')) {
    return <h3 key={key} className="font-semibold mt-3">{ligne.slice(4)}</h3>
  }
  if (ligne.startsWith('## ')) {
    return <h3 key={key} className="text-lg font-semibold mt-3">{ligne.slice(3)}</h3>
  }
  if (ligne.startsWith('# ')) {
    return <h2 key={key} className="gold-title text-xl mt-2">{ligne.slice(2)}</h2>
  }
  if (ligne.startsWith('- ')) {
    return <p key={key} className="pl-4" style={{ color: 'var(--text-dimmed)' }}>• {ligne.slice(2)}</p>
  }
  if (ligne.startsWith('> ')) {
    return (
      <p key={key} className="pl-3 border-l-2 italic" style={{ color: 'var(--text-soft)', borderColor: 'var(--gold)' }}>
        {ligne.slice(2)}
      </p>
    )
  }
  return <p key={key} style={{ color: 'var(--text-dimmed)' }}>{ligne}</p>
}

function FicheContent({ texte }) {
  if (!texte) return null

  return (
    <div className="card-glass p-6 mb-6 space-y-2" style={{ borderRadius: 'var(--radius-md)' }}>
      {texte.split('\n').map((ligne, index) => renderTextLine(ligne, index))}
    </div>
  )
}

function FicheSegments({ segments, formValues, onChange }) {
  return (
    <div className="card-glass p-6 mb-6 space-y-4" style={{ borderRadius: 'var(--radius-md)' }}>
      {segments.map((segment, index) => {
        if (segment.type === 'texte') {
          return renderTextLine(segment.texte, index)
        }

        const champ = segment.champ

        if (champ.type === 'case') {
          return (
            <label
              key={champ.cle}
              className="checklist-item flex items-start gap-3 cursor-pointer"
            >
              <input
                type="checkbox"
                className="mt-1"
                checked={Boolean(formValues[champ.cle])}
                onChange={(event) => onChange(champ.cle, event.target.checked)}
              />
              <span style={{ color: 'var(--text-dimmed)' }}>{champ.libelle}</span>
            </label>
          )
        }

        return (
          <div key={champ.cle} className="pl-4 py-1">
            <p className="font-medium mb-2">{champ.libelle}</p>
            <FieldInput
              champ={champ}
              value={formValues[champ.cle]}
              onChange={(value) => onChange(champ.cle, value)}
            />
          </div>
        )
      })}
    </div>
  )
}

function IdentiteCard({ identite, cohorte, sessions }) {
  const infos = [
    { icon: Mail, valeur: identite.email },
    { icon: Phone, valeur: identite.telephone || identite.contact },
    { icon: MapPin, valeur: [identite.secteur, identite.territoire].filter(Boolean).join(' — ') },
  ].filter((info) => info.valeur)

  return (
    <section className="card-glass p-6 mb-8" style={{ borderRadius: 'var(--radius-md)' }}>
      <p className="text-sm mb-3" style={{ color: 'var(--text-soft)' }}>Ma fiche</p>

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
        <div className="mt-3 pt-3" style={{ borderTop: '1px solid rgba(255,255,255,0.08)' }}>
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

function KpiTable({ kpis }) {
  if (!kpis || kpis.length === 0) return null

  return (
    <section className="card-glass p-6" style={{ borderRadius: 'var(--radius-md)' }}>
      <h2 className="font-semibold mb-4 flex items-center gap-2" style={{ color: 'var(--text-pure)' }}>
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

const MODULE_COLORS = ['#f59e0b', '#38bdf8', '#a78bfa', '#fb7185', '#34d399', '#facc15']

function ModulesBreakdown({ modules }) {
  const total = modules.reduce((sum, m) => sum + m.fiches.length, 0)

  if (!total) return null

  return (
    <section className="card-glass p-6 mb-8" style={{ borderRadius: 'var(--radius-md)' }}>
      <h2 className="font-semibold mb-4" style={{ color: 'var(--text-pure)' }}>
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
      <div className="grid gap-1 text-[10px]" style={{ gridTemplateColumns: `repeat(${modules.length}, minmax(0, 1fr))` }}>
        {modules.map((m, index) => (
          <span key={m.label} className="flex items-center gap-1 min-w-0" title={`${m.label} (${m.fiches.length})`}>
            <span className="module-legend-dot" style={{ background: MODULE_COLORS[index % MODULE_COLORS.length], flexShrink: 0 }} />
            <span className="truncate" style={{ color: 'var(--text-dimmed)' }}>
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
            style={{ background: 'rgba(255,255,255,0.03)', borderRadius: 'var(--radius-sm)' }}
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
  const [screen, setScreen] = useState('loading')
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')
  const [dashboard, setDashboard] = useState(null)
  const [activeFicheId, setActiveFicheId] = useState(null)
  const [ficheData, setFicheData] = useState(null)
  const [livrableData, setLivrableData] = useState(null)
  const [formValues, setFormValues] = useState({})
  const [saving, setSaving] = useState(false)
  const [validating, setValidating] = useState(false)

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

      if (!response.ok) throw new Error('Erreur de chargement de votre espace.')

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

    ;(async () => {
      try {
        const response = await fetch(`${API_BASE}/portal/auth/verify`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token }),
        })

        if (!response.ok) throw new Error('Ce lien est invalide ou a expiré.')

        const data = await response.json()
        localStorage.setItem(SESSION_KEY, data.session_token)
        window.history.replaceState({}, '', window.location.pathname)
        loadDashboard()
      } catch (err) {
        setError(err.message)
        setScreen('login')
      }
    })()
  }, [loadDashboard])

  const requestLink = async (event) => {
    event.preventDefault()
    setError('')

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

      const meResponse = await fetch(`${API_BASE}/portal/me`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      const freshDashboard = await meResponse.json()
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

  if (screen === 'login' || screen === 'check-email') {
    return (
      <div className="min-h-screen flex items-center justify-center p-6">
        <div className="card-glass w-full max-w-md p-8" style={{ borderRadius: 'var(--radius-lg)' }}>
          <h1 className="gold-title text-2xl font-extrabold mb-2">Espace Client eVolution 2.0</h1>

          {screen === 'login' ? (
            <>
              <p className="text-sm mb-6" style={{ color: 'var(--text-soft)' }}>
                Entrez votre email pour recevoir votre lien d'accès sécurisé.
              </p>
              <form onSubmit={requestLink} className="space-y-4">
                <div className="flex items-center gap-2 field-input">
                  <Mail size={18} color="var(--text-soft)" />
                  <input
                    type="email"
                    required
                    placeholder="vous@exemple.com"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    className="bg-transparent outline-none flex-1"
                  />
                </div>
                {error && <p className="text-sm" style={{ color: 'var(--red)' }}>{error}</p>}
                <button
                  type="submit"
                  className="w-full font-semibold py-2.5 rounded-xl"
                  style={{ background: 'var(--gold)', color: 'var(--bg-dark)' }}
                >
                  Recevoir mon lien d'accès
                </button>
              </form>
            </>
          ) : (
            <div className="text-center py-4">
              <CheckCircle2 className="mx-auto mb-3" color="var(--green)" size={36} />
              <p style={{ color: 'var(--text-dimmed)' }}>
                Vérifiez vos emails — un lien d'accès vous a été envoyé s'il correspond à un compte.
              </p>
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

    return (
      <div className="min-h-screen p-6 md:p-10 max-w-4xl mx-auto">
        <header className="flex items-center justify-between mb-8">
          <div>
            <h1 className="gold-title text-2xl font-extrabold">{dashboard.nom}</h1>
            <p style={{ color: 'var(--ink-soft)' }}>{dashboard.phase_parcours}</p>
          </div>
          <button onClick={logout} className="text-sm" style={{ color: 'var(--ink-soft)' }}>
            Se déconnecter
          </button>
        </header>

        {/* Ligne 1 : logo a la taille d'une jauge, puis Ma fiche prend le
            reste de la largeur - meme grille 4 colonnes que la ligne des
            jauges, pour que la case du logo fasse exactement la meme taille
            qu'une case de jauge. */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8 items-stretch">
          <section className="card-glass p-4 flex items-center justify-center" style={{ borderRadius: 'var(--radius-md)' }}>
            <img src={logo} alt="RL-eVolution" className="logo-plate logo-plate-tile" />
          </section>
          <div className="col-span-2 md:col-span-3">
            <IdentiteCard identite={dashboard.identite} cohorte={dashboard.cohorte} sessions={dashboard.sessions} />
          </div>
        </div>

        {/* Ligne 2 : les 4 jauges d'avancement. */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          <section className="card-glass p-4 flex flex-col items-center" style={{ borderRadius: 'var(--radius-md)' }}>
            <GaugeAvancement pct={avancementPct} compact />
            <p className="kpi-tile-label">{ficheDoneCount} / {totalFiches} fiches</p>
          </section>
          <section className="card-glass p-4 flex flex-col items-center" style={{ borderRadius: 'var(--radius-md)' }}>
            <GaugeAvancement pct={modulesPct} compact />
            <p className="kpi-tile-label">{modulesDoneCount} / {modules.length} modules</p>
          </section>
          <section className="card-glass p-4 flex flex-col items-center" style={{ borderRadius: 'var(--radius-md)' }}>
            <GaugeAvancement pct={kpiPct} compact />
            <p className="kpi-tile-label">Progression KPI J90</p>
          </section>
          <section className="card-glass p-4 flex flex-col items-center" style={{ borderRadius: 'var(--radius-md)' }}>
            <GaugeAvancement pct={livrablesPct} compact />
            <p className="kpi-tile-label">Livrables ({livrablesTermines}/{livrablesTotal})</p>
          </section>
        </div>

        {/* Ligne 3 : indicateurs KPI a 50% de largeur, Objectif 90 jours a
            cote sur l'autre moitie. */}
        <div className="grid md:grid-cols-2 gap-5 mb-8 items-start">
          <KpiTable kpis={dashboard.kpi} />

          <section className="card-glass p-6" style={{ borderRadius: 'var(--radius-md)' }}>
            <p className="text-sm mb-2" style={{ color: 'var(--text-soft)' }}>
              Objectif 90 jours
            </p>
            <p className="text-lg font-medium">{dashboard.objectif_90j || '—'}</p>
          </section>
        </div>

        <ModulesBreakdown modules={modules} />

        <h2 className="text-lg font-semibold mb-1">Mon parcours</h2>
        {(() => {
          const activeIndex = modules.findIndex((group) => group.fiches.some((f) => f.etat === 'En cours'))
          const defaultOpenIndex = activeIndex === -1 ? 0 : activeIndex

          return modules.map((group, index) => (
            <details key={group.label} className="module-accordion" open={index === defaultOpenIndex}>
              <summary className="module-heading">
                <ChevronDown size={14} className="module-heading-chevron" />
                {group.label} ({group.fiches.length})
              </summary>
              <div className="grid md:grid-cols-2 gap-2">
                {group.fiches.map((fiche) => {
                  const locked = fiche.acces?.includes('Bloqué')
                  return (
                    <button
                      key={fiche.id}
                      disabled={locked}
                      onClick={() => openFiche(fiche.id)}
                      className="text-left card-glass p-2.5 flex items-center justify-between disabled:opacity-50"
                      style={{ borderRadius: 'var(--radius-sm)' }}
                    >
                      <span className="flex items-center gap-2 text-sm">
                        {locked && <Lock size={14} color="var(--text-soft)" />}
                        {sansNomClient(fiche.nom)}
                      </span>
                      <AccesBadge acces={fiche.acces} />
                    </button>
                  )
                })}
              </div>
            </details>
          ))
        })()}
      </div>
    )
  }

  if (screen === 'fiche') {
    return (
      <div className="min-h-screen p-6 md:p-10 max-w-2xl mx-auto">
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
            {ficheData.mode === 'unique' && ficheData.segments ? (
              <>
                <FicheSegments
                  segments={ficheData.segments}
                  formValues={formValues}
                  onChange={(cle, value) => setFormValues((prev) => ({ ...prev, [cle]: value }))}
                />

                {error && <p className="text-sm mb-3" style={{ color: 'var(--red)' }}>{error}</p>}
              </>
            ) : (
              <>
                <FicheContent texte={ficheData.contenu} />

                {ficheData.mode === 'recurrent' && ficheData.entrees.length > 0 && (
                  <div className="mb-8 overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr style={{ color: 'var(--ink-soft)' }}>
                          <th className="text-left pr-4 pb-2">Date</th>
                          {ficheData.champs.map((champ) => (
                            <th key={champ.cle} className="text-left pr-4 pb-2">{champ.libelle}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {ficheData.entrees.map((entry) => (
                          <tr key={entry.id} className="border-t" style={{ borderColor: 'rgba(28,25,23,0.1)' }}>
                            <td className="pr-4 py-2">{entry.date}</td>
                            {ficheData.champs.map((champ) => (
                              <td key={champ.cle} className="pr-4 py-2">{String(entry.donnees[champ.cle] ?? '')}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {ficheData.champs.length > 0 && (
                <form onSubmit={submitEntry} className="card-glass p-6 space-y-5" style={{ borderRadius: 'var(--radius-md)' }}>
                  <h2 className="font-semibold flex items-center gap-2">
                    <Rocket size={16} color="var(--gold)" />
                    {ficheData.mode === 'recurrent' ? 'Ajouter une entrée' : 'Vos réponses'}
                  </h2>

                  {ficheData.champs.map((champ) => (
                    <div key={champ.cle}>
                      <label className="block text-sm mb-1.5" style={{ color: 'var(--text-dimmed)' }}>
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
                    className="font-semibold py-2.5 px-6 rounded-xl disabled:opacity-60"
                    style={{ background: 'var(--gold)', color: 'var(--bg-dark)' }}
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

            <div className="mt-6 flex justify-end">
              <button
                onClick={validerEtSuivant}
                disabled={validating}
                className="text-sm font-semibold py-2 px-4 rounded-lg flex items-center gap-1.5 disabled:opacity-60"
                style={{ background: 'var(--green)', color: 'var(--bg-dark)' }}
              >
                <CheckCircle2 size={15} />
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
      <div className="min-h-screen p-6 md:p-10 max-w-2xl mx-auto">
        <button onClick={backToFiche} className="flex items-center gap-2 mb-6 text-sm" style={{ color: 'var(--ink-soft)' }}>
          <ArrowLeft size={16} /> Retour à la fiche
        </button>

        {!livrableData ? (
          <Loader2 className="animate-spin" color="var(--gold)" size={28} />
        ) : (
          <FicheContent texte={livrableData.contenu} />
        )}

        {error && <p className="text-sm" style={{ color: 'var(--red)' }}>{error}</p>}
      </div>
    )
  }

  return null
}