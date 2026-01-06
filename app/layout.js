import './globals.css';

export const metadata = {
	title: 'LDVELH - Chroniques de l\'Exil Stellaire',
	description: 'Jeu de rôle solo SF narratif',
};

export const viewport = {
	width: 'device-width',
	initialScale: 1,
	themeColor: '#111827',
};

export default function RootLayout({ children }) {
	return (
		<html lang="fr" className="dark">
			<head>
				<link rel="icon" href="/favicon.ico" sizes="any" />
			</head>
			<body className="min-h-screen bg-gray-900 text-white antialiased">
				{children}
			</body>
		</html>
	);
}
