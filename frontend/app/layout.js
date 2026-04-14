import './globals.css';
import { AuthProvider } from '../lib/AuthContext';

export const metadata = {
	title: 'LDVELH - Chroniques de l\'Exil Stellaire',
	description: 'Jeu de rôle solo SF narratif',
};

export const viewport = {
	width: 'device-width',
	initialScale: 1,
	themeColor: '#131318',
};

export default function RootLayout({ children }) {
	return (
		<html lang="fr" className="dark">
			<head>
				<link rel="icon" href="/favicon.ico" sizes="any" />
				<link rel="preconnect" href="https://fonts.googleapis.com" />
				<link
					rel="preconnect"
					href="https://fonts.gstatic.com"
					crossOrigin="anonymous"
				/>
				<link
					href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=Newsreader:ital,wght@0,400;0,600;0,700;0,800;1,400;1,700&display=swap"
					rel="stylesheet"
				/>
			</head>
			<body className="min-h-screen bg-surface text-white antialiased">
				<AuthProvider>
					{children}
				</AuthProvider>
			</body>
		</html>
	);
}
