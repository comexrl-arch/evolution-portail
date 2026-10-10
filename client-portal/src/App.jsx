import { useCallback, useEffect, useState } from 'react'
import { ArrowLeft, CalendarDays, CheckCircle2, ChevronDown, Loader2, Lock, Mail, MapPin, Phone, Rocket, TrendingUp, Users } from 'lucide-react'
import logo from './assets/logo.svg'

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

function renderInline(texte) {
  if (typeof texte !== 'string' || !texte.includes('**')) return texte
  return texte.split(/\*\*(.+?)\*\*/g).map((part, i) =>
    i % 2 === 1 ? <strong key={i}>{part}</strong> : part
  )
}

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
                    style={{ borderBottom: '1px solid #D6D3CA', color: 'var(--text-pure)' }}
                  >
                    {renderInline(cell)}
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
                    style={{ borderBottom: '1px solid #E7E5DF', color: 'var(--text-dimmed)' }}
                  >
                    {renderInline(cell)}
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
    return <h3 key={key} className="font-semibold mt-3">{renderInline(ligne.slice(4))}</h3>
  }
  if (ligne.startsWith('## ')) {
    return <h3 key={key} className="text-lg font-semibold mt-3">{renderInline(ligne.slice(3))}</h3>
  }
  if (ligne.startsWith('# ')) {
    return <h2 key={key} className="gold-title text-xl mt-2">{renderInline(ligne.slice(2))}</h2>
  }
  if (ligne.startsWith('- ')) {
    return <p key={key} className="pl-4" style={{ color: 'var(--text-dimmed)' }}>• {renderInline(ligne.slice(2))}</p>
  }
  if (ligne.startsWith('> ')) {
    return (
      <p key={key} className="pl-3 border-l-2 italic" style={{ color: 'var(--text-soft)', borderColor: 'var(--gold)' }}>
        {renderInline(ligne.slice(2))}
      </p>
    )
  }
  return <p key={key} style={{ color: 'var(--text-dimmed)' }}>{renderInline(ligne)}</p>
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
  const [screen, setScreen] = useState('loading')
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

    return (
      <div className="min-h-screen p-5 md:p-10 max-w-4xl mx-auto">
        <header className="portal-header">
          <img src={logo} alt="RL-eVolution" className="portal-logo" />
          <div className="portal-header-identity">
            <h1 className="gold-title text-2xl font-extrabold">{dashboard.nom}</h1>
            <p style={{ color: 'var(--ink-soft)' }}>{dashboard.phase_parcours}</p>
          </div>
          <button onClick={logout} className="portal-logout text-sm" style={{ color: 'var(--ink-soft)' }}>
            Se déconnecter
          </button>
        </header>

        {/* Bandeau de progression compact : une ligne discrete, sans jauge.
            Les indicateurs sans donnee (pas de KPI, aucun livrable) ne sont
            pas affiches. */}
        <div className="progress-strip">
          <ProgressStat pct={avancementPct}>{ficheDoneCount} / {totalFiches} fiches</ProgressStat>
          <ProgressStat pct={modulesPct}>{modulesDoneCount} / {modules.length} modules</ProgressStat>
          {avecKpi && <ProgressStat pct={kpiPct}>Progression KPI J90</ProgressStat>}
          {livrablesTotal > 0 && (
            <ProgressStat pct={livrablesPct}>Livrables ({livrablesTermines}/{livrablesTotal})</ProgressStat>
          )}
        </div>

        {/* Le parcours est l'action principale : il vient juste apres. */}
        <h2 className="section-title">Mon parcours</h2>
        {(() => {
          const activeIndex = modules.findIndex((group) => group.fiches.some((f) => f.etat === 'En cours'))
          const defaultOpenIndex = activeIndex === -1 ? 0 : activeIndex

          return modules.map((group, index) => (
            <details key={group.label} className="module-accordion" open={index === defaultOpenIndex}>
              <summary className="module-heading">
                <ChevronDown size={16} className="module-heading-chevron" />
                <span className="module-heading-label">{group.label} ({group.fiches.length})</span>
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

        {/* Informations de reference, apres le parcours, en presentation
            sobre. Un bloc sans donnee n'est pas affiche. */}
        <div className="portal-secondary">
          <div className="portal-secondary-row">
            <IdentiteCard identite={dashboard.identite} cohorte={dashboard.cohorte} sessions={dashboard.sessions} />

            {dashboard.objectif_90j && (
              <section className="panel">
                <p className="panel-eyebrow">
                  Objectif 90 jours
                </p>
                <p className="panel-lead">{dashboard.objectif_90j}</p>
              </section>
            )}
          </div>

          <KpiTable kpis={dashboard.kpi} />

          <ModulesBreakdown modules={modules} />
        </div>
      </div>
    )
  }

  if (screen === 'fiche') {
    return (
      <div className="min-h-screen p-5 md:p-10 reading-column mx-auto">
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
      <div className="min-h-screen p-5 md:p-10 reading-column mx-auto">
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
