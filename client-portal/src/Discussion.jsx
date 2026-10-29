// Fil de discussion facon WhatsApp (demande de Rony du 29/10/2026) : la
// derniere question et sa reponse restent visibles, le reste se deplie.
// Partage entre l'Espace Coach et, une fois valide, l'espace eleve.
import { useEffect, useRef, useState } from 'react'
import { CheckCheck, ChevronUp, Clock } from 'lucide-react'

function jourIso(iso) {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? String(iso || '').slice(0, 10) : `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function libelleJour(iso) {
  const jour = jourIso(iso)
  const aujourdhui = jourIso(new Date().toISOString())
  const hier = new Date()
  hier.setDate(hier.getDate() - 1)
  if (jour === aujourdhui) return "Aujourd'hui"
  if (jour === jourIso(hier.toISOString())) return 'Hier'
  const d = new Date(`${jour}T12:00:00`)
  const texte = Number.isNaN(d.getTime()) ? jour : d.toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' })
  return texte.charAt(0).toUpperCase() + texte.slice(1)
}

function heure(iso) {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) || !String(iso).includes('T') ? '' : d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
}

// Questions (de la plus recente a la plus ancienne, comme l'API) -> messages
// dans l'ordre de lecture, une question suivie de sa reponse.
export function messagesDepuisQuestions(questions) {
  return [...(questions || [])]
    .sort((a, b) => String(a.posee_le || '').localeCompare(String(b.posee_le || '')))
    .flatMap((q) => [
      { id: `${q.id}-q`, question: q, de: 'eleve', texte: q.question, date: q.posee_le },
      ...(q.reponse ? [{ id: `${q.id}-r`, question: q, de: 'coach', texte: q.reponse, date: q.repondu_le }] : []),
    ])
}

// messages : [{ id, de: 'eleve' | 'coach', texte, date, question }]
// moi : qui lit ('coach' ou 'eleve'), ses bulles sont a droite.
export default function Discussion({ messages, moi, noms, enAttente, cible, onCibler, vide }) {
  const [tout, setTout] = useState(false)
  const fil = useRef(null)

  // Comme WhatsApp : on arrive en bas du fil, sur le dernier message.
  useEffect(() => {
    if (fil.current) fil.current.scrollTop = fil.current.scrollHeight
  }, [tout, messages.length])

  if (!messages.length) return <p className="discussion-vide">{vide}</p>

  // Dernier echange visible : la derniere question et ce qui la suit.
  // Les questions encore sans reponse restent toutes visibles.
  const debutDernier = messages.map((m) => m.de).lastIndexOf('eleve')
  const premiereAttente = messages.findIndex((m) => m.de === 'eleve' && !m.question?.reponse)
  const debut = premiereAttente >= 0 ? Math.min(premiereAttente, debutDernier) : debutDernier
  const coupe = tout ? 0 : Math.max(0, debut)
  const visibles = messages.slice(coupe)
  const caches = coupe

  return (
    <div className="discussion" role="log" aria-label="Discussion" ref={fil}>
      {caches > 0 && (
        <button type="button" className="discussion-plus" onClick={() => setTout(true)}>
          Voir {caches} message{caches > 1 ? 's' : ''} précédent{caches > 1 ? 's' : ''}
        </button>
      )}
      {tout && messages.length > 2 && (
        <button type="button" className="discussion-plus" onClick={() => setTout(false)}>
          <ChevronUp size={14} aria-hidden="true" /> Replier
        </button>
      )}
      {visibles.map((m, i) => {
        const precedent = visibles[i - 1]
        const nouveauJour = !precedent || jourIso(precedent.date) !== jourIso(m.date)
        const mien = m.de === moi
        const attente = m.de === 'eleve' && !m.question?.reponse
        return (
          <div key={m.id} className="discussion-groupe">
            {nouveauJour && <p className="discussion-jour"><span>{libelleJour(m.date)}</span></p>}
            <div className={`discussion-ligne${mien ? ' discussion-ligne-moi' : ''}`}>
              <div
                className={`discussion-bulle${mien ? ' discussion-bulle-moi' : ''}${attente && enAttente > 1 && cible === m.question?.id ? ' discussion-bulle-cible' : ''}`}
              >
                {!mien && noms?.[m.de] && <p className="discussion-auteur">{noms[m.de]}</p>}
                <p className="discussion-texte">{m.texte}</p>
                <p className="discussion-meta">
                  {heure(m.date)}
                  {m.de === 'coach' && <CheckCheck size={14} aria-label="Envoyé" />}
                  {attente && <Clock size={12} aria-label="En attente de réponse" />}
                </p>
              </div>
            </div>
            {attente && enAttente > 1 && onCibler && cible !== m.question.id && (
              <button type="button" className="discussion-cibler" onClick={() => onCibler(m.question.id)}>Répondre à ce message</button>
            )}
          </div>
        )
      })}
    </div>
  )
}
