import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import CoachOnboarding from './CoachOnboarding.jsx'
import { demarrerInstallation, identiteCoach } from './installation.js'

// Espace Coach : adresse /coach (avec ou sans « / » ou « .html » final), ou page
// coach.html elle-meme. Sur iPhone, l'appli installee peut s'ouvrir sur une de
// ces variantes : la page servie fait foi (29/10/2026).
const coach = /^\/coach(\/|\.html)?$/.test(window.location.pathname)
  || document.querySelector('link[rel="manifest"]')?.getAttribute('href') === '/coach.webmanifest'
if (coach) identiteCoach()
demarrerInstallation()

const Root = coach ? CoachOnboarding : App

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)
