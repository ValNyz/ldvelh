import './globals.css'

export const metadata = {
  title: 'LDVELH',
  description: 'Simulation de vie SF',
}

export default function RootLayout({ children }) {
  return (
    <html lang="fr">
      <body>{children}</body>
    </html>
  )
}
