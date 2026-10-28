import React, { useState } from 'react'
import { formaterMaj } from './dates'
import { Lock, Search, UserPlus, CheckCircle2, AlertCircle, ClipboardCheck, ChevronDown, ListChecks, Users, Menu, X } from 'lucide-react'
import logo from './assets/logo.svg'
import BoutonInstaller from './BoutonInstaller.jsx'
import CoachSuiviClients from './CoachSuiviClients.jsx'
import CoachEleves from './CoachEleves.jsx'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8013'
const COACH_KEY_STORAGE = 'coach_onboard_key'

// Messages fixes : aucun detail technique ni donnee du client n'est affiche.
const MESSAGE_SERVICE_INDISPONIBLE = 'Service momentanément indisponible. Réessayez dans quelques minutes.'
const MESSAGE_FORMULAIRE_INVALIDE = 'Formulaire incomplet ou invalide.'
const MESSAGE_REPONSE_INATTENDUE = 'Réponse inattendue du serveur. Vérifiez la liste des clients avant de réessayer.'

// Menu lateral de l'Espace Coach, meme presentation que l'espace client.
const ONGLETS_COACH = [
  {
    cle: 'eleves', libelle: 'Élèves', icone: Users, titre: 'Mes élèves',
    intro: 'Ce que chaque élève fait dans son espace client : fiches, résultats, bilans, carnet de prospects. Lecture seule.',
  },
  {
    cle: 'diagnostics', libelle: 'Diagnostics', icone: ClipboardCheck, titre: 'Diagnostics à valider',
    intro: 'Fiche 8 (résultat de diagnostic) des clients en cours : relisez, corrigez et validez sans ouvrir Notion.',
  },
  {
    cle: 'suivi', libelle: 'Suivi client', icone: ListChecks, titre: 'Suivi client',
    intro: 'Avancement du process client, lu dans le cockpit Google Sheets. Lecture seule.',
  },
  {
    cle: 'onboarding', libelle: 'Onboarding', icone: UserPlus, titre: 'Onboarder un client',
    intro: "Cherchez le contact dans systeme.io ou saisissez-le à la main : ses fiches et son accès au portail sont créés d'un coup.",
  },
]

const emptyForm = {
  nom: '', email: '', telephone: '', activite: '', secteur: '', territoire: '',
  contact: '', site_reseaux: '', offre_principale: '', client_cible: '',
  objectif_90j: '', urgence_echeance: '', parcours: 'Coaching 90 jours',
  leads_j0: '', rdv_j0: '', nouveaux_clients_j0: '', ca_j0: '',
}

export default function CoachOnboarding() {
  const [coachKey, setCoachKey] = useState(() => localStorage.getItem(COACH_KEY_STORAGE) || '')
  const [pinInput, setPinInput] = useState('')
  const [unlockError, setUnlockError] = useState('')
  const [tab, setTab] = useState('eleves')
  const [menuOuvert, setMenuOuvert] = useState(false)
  const [eleveOuvert, setEleveOuvert] = useState(false)

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
  const [champs, setChamps] = useState(null)
  const [originalChamps, setOriginalChamps] = useState(null)
  const [champsError, setChampsError] = useState('')
  const [ficheLoading, setFicheLoading] = useState(false)
  const [validating, setValidating] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [misAJour, setMisAJour] = useState(null)

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
      setChamps(null)
      return
    }
    setExpandedFicheId(diag.fiche_client_id)
    setChamps(null)
    setOriginalChamps(null)
    setMisAJour(null)
    setChampsError('')
    setSaved(false)
    setFicheLoading(true)
    try {
      await rechargerChamps(diag.fiche_client_id)
    } catch (err) {
      setChampsError(err.message)
    } finally {
      setFicheLoading(false)
    }
  }

  async function rechargerChamps(ficheClientId) {
    // Relit la fiche dans Notion : ce qui s'affiche est ce que voit le client.
    const res = await fetch(`${API_BASE}/coach/fiches/${ficheClientId}/diagnostic-champs`, {
      headers: { 'X-Coach-Key': coachKey },
    })
    if (res.status === 401) return handleAuthFailure()
    if (!res.ok) throw new Error((await res.json()).detail || 'Erreur de chargement')
    const data = await res.json()
    setChamps(data.champs)
    setOriginalChamps(data.champs)
    setMisAJour(data.mis_a_jour || null)
  }

  function updateChampValeur(index, valeur) {
    setSaved(false)
    setChamps((prev) => prev.map((c, i) => (i === index ? { ...c, valeur } : c)))
  }

  function cancelChampsEdit() {
    setChamps(originalChamps)
    setChampsError('')
    setSaved(false)
  }

  async function saveChamps(ficheClientId) {
    setSaving(true)
    setChampsError('')
    try {
      const res = await fetch(`${API_BASE}/coach/fiches/${ficheClientId}/diagnostic-champs`, {
        method: 'POST',
        headers: { 'X-Coach-Key': coachKey, 'Content-Type': 'application/json' },
        body: JSON.stringify({ updates: champs }),
      })
      if (res.status === 401) return handleAuthFailure()
      if (!res.ok) throw new Error((await res.json()).detail || 'Erreur de sauvegarde')
      await rechargerChamps(ficheClientId)
      setSaved(true)
    } catch (err) {
      setChampsError(err.message)
    } finally {
      setSaving(false)
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

  function changerOnglet(cle) {
    setTab(cle)
    setMenuOuvert(false)
    window.scrollTo(0, 0)
    if (cle === 'diagnostics' && !diagnostics.length) loadDiagnostics()
  }

  function verrouiller() {
    localStorage.removeItem(COACH_KEY_STORAGE)
    setCoachKey('')
    setPinInput('')
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
      let res
      try {
        res = await fetch(`${API_BASE}/coach/clients/onboard`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Coach-Key': coachKey },
          body: JSON.stringify(payload),
        })
      } catch {
        setResult({ kind: 'erreur', message: MESSAGE_SERVICE_INDISPONIBLE })
        return
      }
      if (res.status === 401) return handleAuthFailure()
      let data = null
      try {
        data = await res.json()
      } catch {
        data = null
      }
      if (res.ok) {
        if (!data) {
          setResult({ kind: 'erreur', message: MESSAGE_REPONSE_INATTENDUE })
          return
        }
        setResult({ kind: data.invite_envoyee === false ? 'invitation_echouee' : 'succes', data })
        setSelectedLeadId(null)
        setForm(emptyForm)
        setLeads([])
        setLeadsQuery('')
      } else if (res.status === 409 && data?.code === 'client_deja_existant') {
        // Formulaire conserve : le coach peut corriger l'email saisi.
        setResult({ kind: 'client_existant' })
      } else {
        setResult({
          kind: 'erreur',
          message: res.status === 422 ? MESSAGE_FORMULAIRE_INVALIDE : MESSAGE_SERVICE_INDISPONIBLE,
        })
      }
    } finally {
      setSubmitting(false)
    }
  }

  if (!coachKey) {
    return (
      <div className="coach-verrou page-monogramme">
        <div className="card-glass coach-verrou-carte">
          <img src={logo} alt="RL-eVolution" className="coach-verrou-logo" />
          <p className="cap-surtitre coach-verrou-surtitre"><Lock size={13} aria-hidden="true" /> Accès réservé</p>
          <h1 className="coach-verrou-titre">Espace Coach</h1>
          <p className="text-sm mb-6" style={{ color: 'var(--text-secondary)' }}>
            Suivi des élèves, diagnostics et onboarding. Entrez votre code d'accès.
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
            <button type="submit" className="fiche-bouton w-full">
              Déverrouiller
            </button>
          </form>
        </div>
      </div>
    )
  }

  const ongletActif = ONGLETS_COACH.find((o) => o.cle === tab) || ONGLETS_COACH[0]

  return (
    <div className="espace espace-coach">
      <aside className={`espace-menu${menuOuvert ? ' espace-menu-ouvert' : ''}`}>
        <img src={logo} alt="RL-eVolution" className="espace-menu-logo" />
        <p className="espace-menu-rubrique">Espace Coach</p>
        <nav className="espace-menu-liens">
          {ONGLETS_COACH.map(({ cle, libelle, icone: Icone }) => (
            <button
              key={cle}
              type="button"
              className={`espace-menu-lien${tab === cle ? ' espace-menu-lien-actif' : ''}`}
              aria-current={tab === cle ? 'page' : undefined}
              onClick={() => changerOnglet(cle)}
            >
              <Icone size={17} aria-hidden="true" />
              {libelle}
            </button>
          ))}
        </nav>
        <BoutonInstaller />
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
            <h1>Espace Coach</h1>
            <p className="accueil-formule">Pilotage des élèves</p>
          </div>
          <div className="accueil-client">
            <p className="accueil-client-nom">Rony</p>
            <button onClick={verrouiller} className="accueil-deconnexion">
              Verrouiller
            </button>
          </div>
        </header>

        {!(tab === 'eleves' && eleveOuvert) && (
          <>
            <h2 className="accueil-section-titre">{ongletActif.titre}</h2>
            <p className="coach-intro">{ongletActif.intro}</p>
          </>
        )}

      {tab === 'suivi' && <CoachSuiviClients coachKey={coachKey} onAuthFailure={handleAuthFailure} />}
      {tab === 'eleves' && <CoachEleves coachKey={coachKey} onAuthFailure={handleAuthFailure} onDetail={setEleveOuvert} />}


      {tab === 'diagnostics' && (
        <div className="coach-colonne">

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
                    <p className="coach-carte-nom">{diag.client_nom}</p>
                    <span className={`coach-puce ${diag.etat === 'Terminé' ? 'coach-puce-ok' : 'coach-puce-attente'}`}>
                      {diag.etat === 'Terminé' ? 'Validée' : diag.etat || 'Non renseigné'}
                    </span>
                  </div>
                  <ChevronDown
                    size={18}
                    color="var(--text-secondary)"
                    style={{ transform: expandedFicheId === diag.fiche_client_id ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s' }}
                  />
                </button>

                {expandedFicheId === diag.fiche_client_id && (
                  <div className="mt-4 pt-4" style={{ borderTop: 'var(--border-subtle)' }}>
                    {ficheLoading && <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>Chargement...</p>}
                    {champsError && <p className="text-sm mb-2" style={{ color: 'var(--danger)' }}>{champsError}</p>}

                    {champs && misAJour && (
                      <p className="text-xs mb-3" style={{ color: 'var(--text-tertiary)' }}>
                        Dernière mise à jour : {formaterMaj(misAJour)}
                      </p>
                    )}

                    {champs && (
                      <div className="space-y-2.5 mb-4">
                        {champs.map((champ, index) => (
                          <div key={champ.block_id}>
                            <label className="text-xs" style={{ color: 'var(--text-tertiary)' }}>{champ.label}</label>
                            <input
                              type="text"
                              value={champ.valeur}
                              onChange={(e) => updateChampValeur(index, e.target.value)}
                              className="w-full field-input bg-transparent outline-none px-3 py-1.5 text-sm mt-0.5"
                            />
                          </div>
                        ))}
                      </div>
                    )}

                    {champs && (
                      <button
                        onClick={() => saveChamps(diag.fiche_client_id)}
                        disabled={saving}
                        className="w-full font-semibold py-2 rounded-xl flex items-center justify-center gap-2 disabled:opacity-50 mb-2"
                        style={{ background: 'var(--accent)', color: 'var(--text-on-accent)' }}
                      >
                        {saving ? 'Enregistrement...' : saved ? '✓ Enregistré' : 'Enregistrer les modifications'}
                      </button>
                    )}
                    {champs && (
                      <button
                        onClick={cancelChampsEdit}
                        className="w-full font-medium py-2 rounded-xl mb-2"
                        style={{ color: 'var(--text-secondary)', border: 'var(--border-subtle)' }}
                      >
                        Annuler
                      </button>
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

      {tab === 'onboarding' && (<div className="coach-colonne">

      {result?.kind === 'succes' && (
        <div className="card-glass p-4 mb-4 flex gap-3" style={{ borderRadius: 'var(--radius-md)' }}>
          <CheckCircle2 color="var(--success)" size={20} />
          <div>
            <p className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>Client onboardé avec succès</p>
            <p className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>
              {result.data.fiches_creees ?? 0} fiches créées
              {result.data.kpi_a_completer?.length ? ` · KPI à compléter : ${result.data.kpi_a_completer.join(', ')}` : ''}
            </p>
          </div>
        </div>
      )}
      {result?.kind === 'invitation_echouee' && (
        <div className="card-glass p-4 mb-4 flex gap-3" style={{ borderRadius: 'var(--radius-md)' }}>
          <AlertCircle color="var(--warning)" size={20} />
          <div>
            <p className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>Client créé, lien d'accès non envoyé</p>
            <p className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>
              {result.data.fiches_creees ?? 0} fiches créées
              {result.data.kpi_a_completer?.length ? ` · KPI à compléter : ${result.data.kpi_a_completer.join(', ')}` : ''}
            </p>
            <p className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>
              Le client peut demander un nouveau lien depuis la page de connexion du portail.
            </p>
          </div>
        </div>
      )}
      {result?.kind === 'client_existant' && (
        <div className="card-glass p-4 mb-4 flex gap-3" style={{ borderRadius: 'var(--radius-md)' }}>
          <AlertCircle color="var(--warning)" size={20} />
          <div>
            <p className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>Ce client existe déjà</p>
            <p className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>
              Aucun nouveau dossier n'a été créé. Vérifiez l'email saisi.
            </p>
          </div>
        </div>
      )}
      {result?.kind === 'erreur' && (
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
          <select value={form.parcours}
            onChange={(e) => setForm({ ...form, parcours: e.target.value })}
            className="w-full field-input bg-transparent outline-none px-3 py-2 text-sm">
            <option value="Coaching 90 jours">Parcours : Coaching 90 jours</option>
            <option value="Atelier">Parcours : Atelier Collectif Terrain</option>
            <option value="Autonome">Parcours : eVolution Autonome</option>
          </select>
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
          <button
            type="button"
            onClick={() => { setSelectedLeadId(null); setForm(emptyForm); setResult(null); }}
            className="w-full mt-2 font-medium py-2.5 rounded-xl"
            style={{ color: 'var(--text-secondary)', border: 'var(--border-subtle)' }}
          >
            Annuler
          </button>
        </form>
      )}
      </div>)}
      </main>
    </div>
  )
}
