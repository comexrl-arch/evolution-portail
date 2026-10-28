import React from 'react'
import { Download } from 'lucide-react'
import { installer, useInstallation } from './installation.js'

// Bas du menu lateral : visible seulement quand le navigateur propose
// l'installation (Chrome, Edge, Android) et que l'appli n'est pas deja installee.
export default function BoutonInstaller() {
  const { invite, installee } = useInstallation()
  if (installee || !invite) return null
  return (
    <button type="button" className="espace-menu-lien espace-menu-installer" onClick={installer}>
      <Download size={17} aria-hidden="true" />
      Installer l'application
    </button>
  )
}
