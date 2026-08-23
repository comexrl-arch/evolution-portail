import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import CoachOnboarding from './CoachOnboarding.jsx'

const Root = window.location.pathname === '/coach' ? CoachOnboarding : App

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)
