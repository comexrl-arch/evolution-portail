import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import CoachOnboarding from './CoachOnboarding.jsx'
import Ouverture from './Ouverture.jsx'
import { demarrerInstallation, identiteCoach } from './installation.js'

const coach = window.location.pathname === '/coach'
if (coach) identiteCoach()
demarrerInstallation()

const Root = coach ? CoachOnboarding : App

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <Root />
    <Ouverture coach={coach} />
  </StrictMode>,
)
