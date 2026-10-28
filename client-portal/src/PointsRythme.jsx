import React, { useState } from 'react'
import { X } from 'lucide-react'
import { FORMULES, appelAgenda, dateLongue, heureFr, nouveauRdv } from './CoachAgenda.jsx'

// Rythme des points individuels et collectifs (28/10/2026) : dates suggerees
// selon le jour de parcours, calculees par le serveur (rythme_service).

const DUREES_POINT = [15, 20, 30, 45, 60, 90, 120, 180]

const STATUTS = {
  fait: 'Fait',
  planifie: 'Planifié',
  a_planifier: 'À planifier',
}

function aujourdhuiIso() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function ajouter(iso, jours) {
  const [a, m, j] = iso.split('-').map(Number)
  const d = new Date(a, m - 1, j + jours)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function libellePoint(p) {
  const nature = p.type === 'collectif' ? 'Point collectif' : 'Point individuel'
  return p.total > 1 ? `${nature} ${p.numero}/${p.total}` : nature
}

function dateCourte(iso) {
  return dateLongue(iso).replace(/ \d{4}$/, '')
}

// Liste des points d'un eleve. coach : vouvoiement et bouton « Planifier ».
export function ListePoints({ points, coach = false, onPlanifier }) {
  if (!points?.length) {
    return <p className="espace-vide">{coach ? 'Aucun point prévu pour cette formule.' : 'Tes points avec Rony apparaîtront ici.'}</p>
  }
  return (
    <ul className="points-liste">
      {points.map((p) => (
        <li key={`${p.type}-${p.numero}-${p.evenement?.debut || p.date}`} className={`points-ligne points-${p.statut}`}>
          <span className="points-quand">
            {p.evenement ? `${dateCourte(p.evenement.debut)}, ${heureFr(p.evenement.debut)}` : `vers le ${dateCourte(p.date)}`}
          </span>
          <span className="points-quoi">
            <strong>{libellePoint(p)}</strong>
            <small>{p.jour != null ? `J${p.jour} · ` : ''}{p.duree} min{p.evenement?.lieu ? ` · ${p.evenement.lieu}` : ''}</small>
          </span>
          {coach && p.statut === 'a_planifier' && onPlanifier ? (
            <button type="button" className="resultats-bouton points-planifier" onClick={() => onPlanifier(p)}>Planifier</button>
          ) : (
            <span className={`coach-puce points-statut-${p.statut}`}>
              {!coach && p.statut === 'a_planifier' ? 'Date à confirmer' : STATUTS[p.statut]}
            </span>
          )}
        </li>
      ))}
    </ul>
  )
}

// Points a planifier bientot (en retard ou dans les `jours` a venir). Un point
// collectif concerne toute une formule : il n'apparait qu'une fois.
export function pointsAPlanifier(eleves, jours = 14) {
  const aujourdhui = aujourdhuiIso()
  const limite = ajouter(aujourdhui, jours)
  const depuis = ajouter(aujourdhui, -14)
  const vus = new Set()
  const liste = []
  for (const eleve of eleves || []) {
    for (const p of eleve.points || []) {
      if (p.statut !== 'a_planifier' || p.date > limite || p.date < depuis) continue
      const cle = p.type === 'collectif' ? `collectif-${eleve.parcours}-${p.date}` : `${eleve.client_page_id}-${p.numero}`
      if (vus.has(cle)) continue
      vus.add(cle)
      liste.push({ ...p, eleve })
    }
  }
  return liste.sort((a, b) => a.date.localeCompare(b.date))
}

// Pre-remplit le formulaire de RDV pour un point : sa date suggeree (jamais
// dans le passe), a l'heure de la premiere plage de RDV de ce jour-la.
export function rdvPourPoint(point, eleve, plages = []) {
  const aujourdhui = aujourdhuiIso()
  const jour = point.date < aujourdhui ? aujourdhui : point.date
  const [a, m, j] = jour.split('-').map(Number)
  const jourSemaine = (new Date(a, m - 1, j).getDay() + 6) % 7
  const plage = plages.filter((p) => p.jour === jourSemaine).sort((x, y) => x.debut.localeCompare(y.debut))[0]
  const collectif = point.type === 'collectif'
  return {
    ...nouveauRdv({
      jour,
      heure: plage?.debut || '10:00',
      eleve: collectif ? null : eleve,
      type: collectif ? 'collectif' : 'rdv',
      parcours: collectif ? eleve.parcours : '',
    }),
    duree: point.duree,
  }
}

// Fenetre « Rythme des points » : par formule, points individuels et collectifs.
export function ReglagesRythme({ initial, coachKey, onAuthFailure, onFerme, onEnregistre }) {
  const [regles, setRegles] = useState(initial)
  const [attente, setAttente] = useState(false)
  const [erreur, setErreur] = useState('')

  const changer = (formule, type, cle, valeur) => setRegles((r) => ({
    ...r,
    [formule]: { ...r[formule], [type]: { ...r[formule][type], [cle]: valeur } },
  }))

  async function enregistrer(e) {
    e.preventDefault()
    setAttente(true)
    setErreur('')
    const r = await appelAgenda('/coach/points/regles', coachKey, onAuthFailure, { method: 'PUT', body: JSON.stringify({ regles }) })
    setAttente(false)
    if (r.erreur !== undefined) return setErreur(r.erreur)
    onEnregistre(r.data.regles)
  }

  const nombre = (formule, type, cle, min, max) => (
    <input
      type="number"
      min={min}
      max={max}
      required
      className="field-input"
      value={regles[formule][type][cle]}
      onChange={(e) => changer(formule, type, cle, Number(e.target.value))}
    />
  )

  return (
    <div className="agenda-voile" onClick={onFerme}>
      <form className="agenda-panneau rythme-panneau" onClick={(e) => e.stopPropagation()} onSubmit={enregistrer}>
        <div className="agenda-panneau-entete">
          <div>
            <p className="energie-surtitre">Rythme des points</p>
            <h3 className="coach-module-titre">Quand voir vos élèves ?</h3>
          </div>
          <button type="button" className="coach-bouton-icone" onClick={onFerme} aria-label="Fermer"><X size={16} /></button>
        </div>
        <p className="coach-intro" style={{ margin: '0 0 0.9rem' }}>
          Les dates suggérées partent du jour de démarrage de chaque élève. Un point est « planifié » dès qu'un RDV
          (ou un point collectif de la formule) est dans votre agenda.
        </p>

        {FORMULES.map((formule) => (
          <fieldset key={formule} className="rythme-formule">
            <legend>{formule}</legend>
            {['individuel', 'collectif'].map((type) => {
              const r = regles[formule][type]
              return (
                <div key={type} className={`rythme-ligne${r.actif ? '' : ' rythme-inactif'}`}>
                  <label className="rythme-actif">
                    <input type="checkbox" checked={r.actif} onChange={(e) => changer(formule, type, 'actif', e.target.checked)} />
                    Points {type === 'individuel' ? 'individuels' : 'collectifs'}
                  </label>
                  {r.actif && (
                    <div className="rythme-champs">
                      <label>{nombre(formule, type, 'nombre', 1, 20)} point{r.nombre > 1 ? 's' : ''}</label>
                      <label>dès J{nombre(formule, type, 'debut', 0, 120)}</label>
                      {r.nombre > 1 && <label>tous les {nombre(formule, type, 'tous_les', 1, 60)} j</label>}
                      <label>
                        <select className="field-input" value={r.duree} onChange={(e) => changer(formule, type, 'duree', Number(e.target.value))}>
                          {DUREES_POINT.map((d) => <option key={d} value={d}>{d} min</option>)}
                        </select>
                      </label>
                    </div>
                  )}
                </div>
              )
            })}
          </fieldset>
        ))}

        {erreur && <p className="text-sm mt-3" style={{ color: 'var(--danger)' }}>{erreur}</p>}

        <div className="agenda-actions">
          <button type="submit" className="fiche-bouton" disabled={attente}>{attente ? 'Enregistrement...' : 'Enregistrer le rythme'}</button>
        </div>
      </form>
    </div>
  )
}
