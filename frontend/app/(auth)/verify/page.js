'use client';

import { useState, useEffect, useRef, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { api } from '../../../lib/api';

function VerifyContent() {
	const searchParams = useSearchParams();
	const token = searchParams.get('token');
	const [status, setStatus] = useState('loading'); // loading, success, already, error
	const [errorMsg, setErrorMsg] = useState('');
	const calledRef = useRef(false);

	useEffect(() => {
		if (!token) {
			setStatus('error');
			setErrorMsg('Token de vérification manquant.');
			return;
		}

		// Prevent double call from React strict mode / re-renders
		if (calledRef.current) return;
		calledRef.current = true;

		api.get(`/auth/verify?token=${encodeURIComponent(token)}`)
			.then((data) => {
				setStatus(data.already_verified ? 'already' : 'success');
			})
			.catch((e) => {
				setStatus('error');
				setErrorMsg(e.message || 'Token invalide ou expiré.');
			});
	}, [token]);

	return (
		<div className="bg-surface border border-outline-variant/20 rounded-xl p-8 space-y-5 shadow-[0_8px_32px_rgba(0,0,0,0.4)] text-center">
			{status === 'loading' && (
				<>
					<div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin mx-auto" />
					<p className="text-on-surface-variant">Vérification en cours...</p>
				</>
			)}

			{status === 'success' && (
				<>
					<div className="w-12 h-12 rounded-full bg-green-500/20 flex items-center justify-center mx-auto">
						<CheckIcon className="w-6 h-6 text-green-400" />
					</div>
					<h2 className="text-xl font-headline font-semibold text-on-surface">Email vérifié !</h2>
					<p className="text-on-surface-variant">Votre adresse email a été confirmée avec succès.</p>
					<a
						href="/login/"
						className="inline-block mt-4 px-6 py-3 bg-primary text-on-primary font-bold uppercase tracking-widest text-sm rounded-lg hover:brightness-110 transition-all active:scale-[0.98]"
					>
						Se connecter
					</a>
				</>
			)}

			{status === 'already' && (
				<>
					<h2 className="text-xl font-headline font-semibold text-on-surface">Déjà vérifié</h2>
					<p className="text-on-surface-variant">Votre email est déjà vérifié.</p>
					<a
						href="/game"
						className="inline-block mt-4 px-6 py-3 bg-primary text-on-primary font-bold uppercase tracking-widest text-sm rounded-lg hover:brightness-110 transition-all active:scale-[0.98]"
					>
						Continuer
					</a>
				</>
			)}

			{status === 'error' && (
				<>
					<div className="w-12 h-12 rounded-full bg-red-500/20 flex items-center justify-center mx-auto">
						<XIcon className="w-6 h-6 text-red-400" />
					</div>
					<h2 className="text-xl font-headline font-semibold text-on-surface">Erreur de vérification</h2>
					<p className="text-error text-sm">{errorMsg}</p>
					<a
						href="/login/"
						className="inline-block mt-4 px-6 py-3 bg-surface-container border border-outline-variant/20 text-on-surface-variant font-bold uppercase tracking-widest text-sm rounded-lg hover:brightness-110 transition-all active:scale-[0.98]"
					>
						Retour à la connexion
					</a>
				</>
			)}
		</div>
	);
}

export default function VerifyPage() {
	return (
		<Suspense fallback={
			<div className="bg-surface border border-outline-variant/20 rounded-xl p-8 space-y-5 shadow-[0_8px_32px_rgba(0,0,0,0.4)] text-center">
				<div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin mx-auto" />
				<p className="text-on-surface-variant">Chargement...</p>
			</div>
		}>
			<VerifyContent />
		</Suspense>
	);
}

function CheckIcon({ className }) {
	return (
		<svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
			<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
		</svg>
	);
}

function XIcon({ className }) {
	return (
		<svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
			<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
		</svg>
	);
}
