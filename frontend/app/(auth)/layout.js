'use client';

export default function AuthLayout({ children }) {
	return (
		<div className="min-h-screen bg-gray-950 flex items-center justify-center p-4">
			<div className="w-full max-w-md">
				<div className="text-center mb-8">
					<h1 className="text-3xl font-bold text-white">LDVELH</h1>
					<p className="text-gray-500 text-sm mt-1">Chroniques de l'Exil Stellaire</p>
				</div>
				{children}
			</div>
		</div>
	);
}
