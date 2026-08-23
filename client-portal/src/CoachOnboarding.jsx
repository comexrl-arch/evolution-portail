import React, { useState } from 'react'
import { Lock, Search, UserPlus, CheckCircle2, AlertCircle, ClipboardCheck, ChevronDown } from 'lucide-react'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8013'
const COACH_KEY_STORAGE = 'coach_onboard_key'

const emptyForm = {
  nom: '', email: '', telephone: '', activite: '', secteur: '', territoire: '',
  contact: '', site_reseaux: '', offre_principale: '', client_cible: '',
  objectif_90j: '', urgence_echeance: '',
  leads_j0: '', rdv_j0: '', nouveaux_clients_j0: '', ca_j0: '',
}

function renderDiagnosticLine(ligne, key) {
  const texte = ligne.replace(/^#{1,3}\s*/, '').trim()

  if (ligne.startsWith('###') || ligne.startsWith('##') || ligne.startsWith('#')) {
    return <p key={key} className="font-semibold mt-3" style={{ color: 'var(--text-primary)' }}>{texte}</p>
  }
  if (ligne.trim().startsWith('-')) {
    return <p key={key} className="pl-3">• {ligne.trim().slice(1).trim()}</p>
  }
  return <p key={key}>{ligne}</p>
}

export default function CoachOnboarding() {
  const [coachKey, setCoachKey] = useState(() => localStorage.getItem(COACH_KEY_STORAGE) || '')
  const [pinInput, setPinInput] = useState('')
  const [unlockError, setUnlockError] = useState('')
  const [tab, setTab] = useState('onboarding')

  const [leadsQuery, setLeadsQuery] = useState('')
  const [leads, setLeads] = useState([])
  const [leadsLoading, setLeadsLoading] = useState(false)
  const [leadsError, setLeadsError] = useState('')
  const [selectedLeadId, setSelectedLeadId] = useState(null)
  const [form, setForm] = useState(emptyForm)
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState(null)

  const [diagnostics, setDiagnostics] = useState([])
  const [diagnosticsLoading, setDiagnosticsLoading] = useState(false)
  const [diagnosticsError, setDiagnosticsError] = useState('')
  const [expandedFicheId, setExpandedFicheId] = useState(null)
  const [ficheContent, setFicheContent] = useState(null)
  const [ficheLoading, setFicheLoading] = useState(false)
  const [validating, setValidating] = useState(false)

  async function loadDiagnostics() {
    setDiagnosticsLoading(true)
    setDiagnosticsError('')
    try {
      const res = await fetch(`${API_BASE}/coach/diagnostics`, {
        headers: { 'X-Coach-Key': coachKey },
      })
      if (res.status === 401) return handleAuthFailure()
      if (!res.ok) throw new Error((await res.json()).detail || 'Erreur de chargement')
      const data = await res.json()
      setDiagnostics(data.diagnostics)
    } catch (err) {
      setDiagnosticsError(err.message)
    } finally {
      setDiagnosticsLoading(false)
    }
  }

  async function toggleFiche(diag) {
    if (expandedFicheId === diag.fiche_client_id) {
      setExpandedFicheId(null)
      setFicheContent(null)
      return
    }
    setExpandedFicheId(diag.fiche_client_id)
    setFicheContent(null)
    setFicheLoading(true)
    try {
      const params = new URLSearchParams({ client_page_id: diag.client_page_id })
      const res = await fetch(`${API_BASE}/coach/fiches/${diag.fiche_client_id}?${params}`, {
        headers: { 'X-Coach-Key': coachKey },
      })
      if (res.status === 401) return handleAuthFailure()
      if (!res.ok) throw new Error((await res.json()).detail || 'Erreur de chargement')
      setFicheContent(await res.json())
    } catch (err) {
      setFicheContent({ error: err.message })
    } finally {
      setFicheLoading(false)
    }
  }

  async function validerFiche(ficheClientId) {
    setValidating(true)
    try {
      const res = await fetch(`${API_BASE}/coach/fiches/${ficheClientId}/valider`, {
        method: 'POST',
        headers: { 'X-Coach-Key': coachKey },
      })
      if (res.status === 401) return handleAuthFailure()
      if (!res.ok) throw new Error((await res.json()).detail || 'Erreur de validation')
      setDiagnostics((prev) => prev.map((d) =>
        d.fiche_client_id === ficheClientId ? { ...d, etat: 'Terminé' } : d
      ))
    } catch (err) {
      setDiagnosticsError(err.message)
    } finally {
      setValidating(false)
    }
  }

  function handleAuthFailure() {
    localStorage.removeItem(COACH_KEY_STORAGE)
    setCoachKey('')
    setUnlockError("Code d'accès invalide ou expiré.")
  }

  async function tryUnlock(e) {
    e.preventDefault()
    setUnlockError('')
    try {
      const res = await fetch(`${API_BASE}/coach/leads/systeme-io?query=`, {
        headers: { 'X-Coach-Key': pinInput },
      })
      if (res.status === 401) {
        setUnlockError("Code d'accès invalide.")
        return
      }
      localStorage.setItem(COACH_KEY_STORAGE, pinInput)
      setCoachKey(pinInput)
    } catch {
      setUnlockError('Connexion impossible. Réessaie.')
    }
  }

  async function searchLeads(query) {
    setLeadsLoading(true)
    setLeadsError('')
    try {
      const res = await fetch(`${API_BASE}/coach/leads/systeme-io?query=${encodeURIComponent(query)}`, {
        headers: { 'X-Coach-Key': coachKey },
      })
      if (res.status === 401) return handleAuthFailure()
      if (!res.ok) throw new Error((await res.json()).detail || 'Erreur systeme.io')
      const data = await res.json()
      setLeads(data.leads)
    } catch (err) {
      setLeadsError(err.message)
      setLeads([])
    } finally {
      setLeadsLoading(false)
    }
  }

  function selectLead(lead) {
    setSelectedLeadId(lead.id)
    setForm((prev) => ({
      ...prev,
      nom: `${lead.prenom} ${lead.nom_famille}`.trim(),
      email: lead.email,
      telephone: lead.telephone,
    }))
    setResult(null)
  }

  function startManualEntry() {
    setSelectedLeadId('manual')
    setForm(emptyForm)
    setResult(null)
  }

  async function submitOnboard(e) {
    e.preventDefault()
    setSubmitting(true)
    setResult(null)
    try {
      const payload = { ...form }
      for (const k of ['leads_j0', 'rdv_j0', 'nouveaux_clients_j0', 'ca_j0']) {
        payload[k] = payload[k] === '' ? null : Number(payload[k])
      }
      const res = await fetch(`${API_BASE}/coach/clients/onboard`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Coach-Key': coachKey },
        body: JSON.stringify(payload),
      })
      if (res.status === 401) return handleAuthFailure()
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Erreur onboarding')
      setResult({ ok: true, data })
      setSelectedLeadId(null)
      setForm(emptyForm)
      setLeads([])
      setLeadsQuery('')
    } catch (err) {
      setResult({ ok: false, message: err.message })
    } finally {
      setSubmitting(false)
    }
  }

  if (!coachKey) {
    return (
      <div className="min-h-screen flex items-center justify-center p-6">
        <div className="card-glass w-full max-w-sm p-8" style={{ borderRadius: 'var(--radius-lg)' }}>
          <Lock className="mb-3" color="var(--accent)" size={28} />
          <h1 className="gold-title text-xl font-extrabold mb-2">Espace Coach</h1>
          <p className="text-sm mb-6" style={{ color: 'var(--text-secondary)' }}>
            Code d'accès requis pour onboarder un client.
          </p>
          <form onSubmit={tryUnlock} className="space-y-4">
            <div className="flex items-center gap-2 field-input">
              <input
                type="password"
                required
                autoFocus
                placeholder="Code d'accès"
                value={pinInput}
                onChange={(e) => setPinInput(e.target.value)}
                className="bg-transparent outline-none flex-1"
              />
            </div>
            {unlockError && <p className="text-sm" style={{ color: 'var(--danger)' }}>{unlockError}</p>}
            <button
              type="submit"
              className="w-full font-semibold py-2.5 rounded-xl"
              style={{ background: 'var(--accent)', color: 'var(--text-on-accent)' }}
            >
              Déverrouiller
            </button>
          </form>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen p-4 md:p-8 max-w-lg mx-auto">
      <header className="mb-4">
        <h1 className="gold-title text-xl font-extrabold">Espace Coach</h1>
      </header>

      <div className="flex gap-2 mb-6">
        <button
          onClick={() => setTab('onboarding')}
          className="flex-1 py-2 rounded-xl text-sm font-semibold flex items-center justify-center gap-1.5"
          style={{
            background: tab === 'onboarding' ? 'var(--accent)' : 'transparent',
            color: tab === 'onboarding' ? 'var(--text-on-accent)' : 'var(--text-secondary)',
            border: tab === 'onboarding' ? 'none' : 'var(--border-subtle)',
          }}
        >
          <UserPlus size={15} /> Onboarding
        </button>
        <button
          onClick={() => { setTab('diagnostics'); if (!diagnostics.length) loadDiagnostics() }}
          className="flex-1 py-2 rounded-xl text-sm font-semibold flex items-center justify-center gap-1.5"
          style={{
            background: tab === 'diagnostics' ? 'var(--accent)' : 'transparent',
            color: tab === 'diagnostics' ? 'var(--text-on-accent)' : 'var(--text-secondary)',
            border: tab === 'diagnostics' ? 'none' : 'var(--border-subtle)',
          }}
        >
          <ClipboardCheck size={15} /> Diagnostics
        </button>
      </div>

      {tab === 'diagnostics' && (
        <div>
          <p className="text-sm mb-4" style={{ color: 'var(--text-secondary)' }}>
            Fiche 8 (résultat de diagnostic) des clients en cours — valide sans ouvrir Notion.
          </p>

          {diagnosticsLoading && <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>Chargement...</p>}
          {diagnosticsError && <p className="text-sm" style={{ color: 'var(--danger)' }}>{diagnosticsError}</p>}
          {!diagnosticsLoading && diagnostics.length === 0 && !diagnosticsError && (
            <p className="text-sm" style={{ color: 'var(--text-tertiary)' }}>Aucun client "En cours" trouvé.</p>
          )}

          <div className="space-y-3">
            {diagnostics.map((diag) => (
              <div key={diag.fiche_client_id} className="card-glass p-4" style={{ borderRadius: 'var(--radius-md)' }}>
                <button
                  onClick={() => toggleFiche(diag)}
                  className="w-full flex items-center justify-between text-left"
                >
                  <div>
                    <p className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>{diag.client_nom}</p>
                    <p className="text-xs" style={{ color: diag.etat === 'Terminé' ? 'var(--success)' : 'var(--warning)' }}>
                      {diag.etat === 'Terminé' ? '✅ Validée' : diag.etat || 'Non renseigné'}
                    </p>
                  </div>
                  <ChevronDown
                    size={18}
                    color="var(--text-secondary)"
                    style={{ transform: expandedFicheId === diag.fiche_client_id ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s' }}
                  />
                </button>

                {expandedFicheId === diag.fiche_client_id && (
                  <div className="mt-4 pt-4" style={{ borderTop: 'var(--border-subtle)' }}>
                    {ficheLoading && <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>Chargement du contenu...</p>}
                    {ficheContent?.error && <p className="text-sm" style={{ color: 'var(--danger)' }}>{ficheContent.error}</p>}
                    {ficheContent?.segments && (
                      <div className="space-y-1.5 mb-4 text-sm" style={{ color: 'var(--text-secondary)' }}>
                        {ficheContent.segments
                          .filter((s) => s.type === 'texte' && s.texte?.trim())
                          .map((s, i) => renderDiagnosticLine(s.texte, i))}
                      </div>
                    )}
                    {diag.etat !== 'Terminé' && (
                      <button
                        onClick={() => validerFiche(diag.fiche_client_id)}
                        disabled={validating}
                        className="w-full font-semibold py-2 rounded-xl flex items-center justify-center gap-2 disabled:opacity-50"
                        style={{ background: 'var(--success)', color: 'var(--text-on-accent)' }}
                      >
                        <CheckCircle2 size={16} />
                        {validating ? 'Validation...' : 'Valider cette fiche'}
                      </button>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === 'onboarding' && (<>

      {result?.ok && (
        <div className="card-glass p-4 mb-4 flex gap-3" style={{ borderRadius: 'var(--radius-md)' }}>
          <CheckCircle2 color="var(--success)" size={20} />
          <div>
            <p className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>Client onboardé avec succès</p>
            <p className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>
              {result.data.fiches_creees ?? 0} fiches créées
              {result.data.kpi_a_completer?.length ? ` — KPI à compléter : ${result.data.kpi_a_completer.join(', ')}` : ''}
            </p>
          </div>
        </div>
      )}
      {result && !result.ok && (
        <div className="card-glass p-4 mb-4 flex gap-3" style={{ borderRadius: 'var(--radius-md)' }}>
          <AlertCircle color="var(--danger)" size={20} />
          <p className="text-sm" style={{ color: 'var(--text-primary)' }}>{result.message}</p>
        </div>
      )}

      <div className="card-glass p-5 mb-4" style={{ borderRadius: 'var(--radius-lg)' }}>
        <div className="flex gap-2 mb-3">
          <input
            type="text"
            value={leadsQuery}
            onChange={(e) => setLeadsQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && searchLeads(leadsQuery)}
            placeholder="Email ou nom du contact..."
            className="flex-1 field-input bg-transparent outline-none px-3 py-2 text-sm"
          />
          <button
            onClick={() => searchLeads(leadsQuery)}
            disabled={leadsLoading}
            className="px-4 rounded-xl flex items-center gap-1.5 text-sm font-semibold disabled:opacity-50"
            style={{ background: 'var(--accent)', color: 'var(--text-on-accent)' }}
          >
            <Search size={14} />
          </button>
        </div>

        {leadsError && <p className="text-xs mb-2" style={{ color: 'var(--danger)' }}>{leadsError}</p>}

        <div className="space-y-2 max-h-56 overflow-y-auto mb-3">
          {leads.map((lead) => (
            <button
              key={lead.id}
              onClick={() => selectLead(lead)}
              className="w-full text-left p-3 rounded-xl border transition-all"
              style={{
                borderColor: selectedLeadId === lead.id ? 'var(--accent)' : 'var(--border-subtle)',
                background: selectedLeadId === lead.id ? 'var(--accent-soft)' : 'transparent',
              }}
            >
              <p className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>{lead.prenom} {lead.nom_famille}</p>
              <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>{lead.email}</p>
            </button>
          ))}
        </div>

        <button onClick={startManualEntry} className="text-xs underline" style={{ color: 'var(--text-secondary)' }}>
          Saisir un client manuellement
        </button>
      </div>

      {selectedLeadId !== null && (
        <form onSubmit={submitOnboard} className="card-glass p-5 space-y-3" style={{ borderRadius: 'var(--radius-lg)' }}>
          <input required placeholder="Nom complet" value={form.nom}
            onChange={(e) => setForm({ ...form, nom: e.target.value })}
            className="w-full field-input bg-transparent outline-none px-3 py-2 text-sm" />
          <input required type="email" placeholder="Email" value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
            className="w-full field-input bg-transparent outline-none px-3 py-2 text-sm" />
          <input placeholder="Téléphone" value={form.telephone}
            onChange={(e) => setForm({ ...form, telephone: e.target.value })}
            className="w-full field-input bg-transparent outline-none px-3 py-2 text-sm" />
          <input placeholder="Activité" value={form.activite}
            onChange={(e) => setForm({ ...form, activite: e.target.value })}
            className="w-full field-input bg-transparent outline-none px-3 py-2 text-sm" />
          <input placeholder="Objectif 90 jours" value={form.objectif_90j}
            onChange={(e) => setForm({ ...form, objectif_90j: e.target.value })}
            className="w-full field-input bg-transparent outline-none px-3 py-2 text-sm" />

          <p className="text-xs font-semibold uppercase tracking-wider pt-1" style={{ color: 'var(--text-secondary)' }}>KPI J0 (optionnel)</p>
          <div className="grid grid-cols-2 gap-2">
            <input type="number" placeholder="Leads" value={form.leads_j0}
              onChange={(e) => setForm({ ...form, leads_j0: e.target.value })}
              className="field-input bg-transparent outline-none px-2 py-2 text-xs" />
            <input type="number" placeholder="RDV" value={form.rdv_j0}
              onChange={(e) => setForm({ ...form, rdv_j0: e.target.value })}
              className="field-input bg-transparent outline-none px-2 py-2 text-xs" />
            <input type="number" placeholder="Nouv. clients" value={form.nouveaux_clients_j0}
              onChange={(e) => setForm({ ...form, nouveaux_clients_j0: e.target.value })}
              className="field-input bg-transparent outline-none px-2 py-2 text-xs" />
            <input type="number" placeholder="CA" value={form.ca_j0}
              onChange={(e) => setForm({ ...form, ca_j0: e.target.value })}
              className="field-input bg-transparent outline-none px-2 py-2 text-xs" />
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="w-full mt-2 font-bold py-2.5 rounded-xl flex items-center justify-center gap-2 disabled:opacity-50"
            style={{ background: 'var(--accent)', color: 'var(--text-on-accent)' }}
          >
            <UserPlus size={16} />
            {submitting ? 'Création en cours...' : 'Onboarder ce client'}
          </button>
        </form>
      )}
      </>)}
    </div>
  )
}
