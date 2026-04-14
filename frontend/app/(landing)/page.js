'use client';

import Link from 'next/link';

// ---------------------------------------------------------------------------
// SVG Icon components (replacing material-symbols-outlined)
// ---------------------------------------------------------------------------

function IconBlock({ className }) {
	return (
		<svg className={className} viewBox="0 0 24 24" fill="currentColor" width="1em" height="1em">
			<path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2ZM4 12c0-4.42 3.58-8 8-8 1.85 0 3.55.63 4.9 1.69L5.69 16.9A7.902 7.902 0 0 1 4 12Zm8 8c-1.85 0-3.55-.63-4.9-1.69L18.31 7.1A7.902 7.902 0 0 1 20 12c0 4.42-3.58 8-8 8Z" />
		</svg>
	);
}

function IconMemory({ className }) {
	return (
		<svg className={className} viewBox="0 0 24 24" fill="currentColor" width="1em" height="1em">
			<path d="M15 9H9v6h6V9Zm-2 4h-2v-2h2v2Zm8-2V9h-2V7c0-1.1-.9-2-2-2h-2V3h-2v2h-2V3H9v2H7c-1.1 0-2 .9-2 2v2H3v2h2v2H3v2h2v2c0 1.1.9 2 2 2h2v2h2v-2h2v2h2v-2h2c1.1 0 2-.9 2-2v-2h2v-2h-2v-2h2Zm-4 6H7V7h10v10Z" />
		</svg>
	);
}

function IconSkull({ className }) {
	return (
		<svg className={className} viewBox="0 0 24 24" fill="currentColor" width="1em" height="1em">
			<path d="M12 2C6.48 2 2 6.48 2 12c0 3.07 1.39 5.81 3.57 7.64L6 22h3v-2h2v2h2v-2h2v2h3l.43-2.36A9.984 9.984 0 0 0 22 12c0-5.52-4.48-10-10-10ZM9 14c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2Zm6 0c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2Z" />
		</svg>
	);
}

function IconGavel({ className }) {
	return (
		<svg className={className} viewBox="0 0 24 24" fill="currentColor" width="1em" height="1em">
			<path d="M1 21h12v2H1v-2Zm5.245-4.741L3.414 19.09l1.414 1.414 2.831-2.831-1.414-1.414ZM21.193 6.05l-3.536-3.536-1.414 1.414 1.06 1.06-3.182 3.182-1.768-1.767-1.414 1.414 1.768 1.768-3.182 3.182-1.06-1.06-1.415 1.413 3.536 3.536 1.414-1.414-1.06-1.06 3.182-3.182 1.768 1.768 1.414-1.415-1.768-1.767 3.182-3.182 1.061 1.06 1.414-1.414Z" />
		</svg>
	);
}

function IconPsychology({ className }) {
	return (
		<svg className={className} viewBox="0 0 24 24" fill="currentColor" width="1em" height="1em">
			<path d="M13 8.57a1.43 1.43 0 1 0 0 2.86 1.43 1.43 0 0 0 0-2.86ZM13 3C9.25 3 6.2 5.94 6.02 9.64L4.1 12.2a.5.5 0 0 0 .4.8H6v3c0 1.1.9 2 2 2h1v3h7v-4.68a7 7 0 0 0 4-6.32c0-3.87-3.13-7-7-7Zm3.72 7.41.13.04-.01.01A4.992 4.992 0 0 1 13 15a5 5 0 0 1-1-.1v-1.33A2.86 2.86 0 0 0 13 14a2.86 2.86 0 0 0 2.86-2.86c0-.93-.46-1.76-1.15-2.28V7.08A4.997 4.997 0 0 1 18 12c0 .58-.1 1.14-.28 1.41Z" />
		</svg>
	);
}

function IconSettings({ className }) {
	return (
		<svg className={className} viewBox="0 0 24 24" fill="currentColor" width="1em" height="1em">
			<path d="M7 16h10v-2H7v2Zm0-4h10v-2H7v2Zm0-4h10V6H7v2ZM3 20V4h18v16H3Z" />
		</svg>
	);
}

function IconTrending({ className }) {
	return (
		<svg className={className} viewBox="0 0 24 24" fill="currentColor" width="1em" height="1em">
			<path d="m16 6-2.29 2.29-4.88-4.88-7.29 7.3 1.41 1.41 5.88-5.88 4.88 4.88L20.59 4.1l1.41 1.41-6-6Zm0 6-2.29 2.29-4.88-4.88-7.29 7.3 1.41 1.41 5.88-5.88 4.88 4.88L20.59 10.1l1.41 1.41-6-6Z" />
		</svg>
	);
}

function IconMagic({ className }) {
	return (
		<svg className={className} viewBox="0 0 24 24" fill="currentColor" width="1em" height="1em">
			<path d="M19 9l1.25-2.75L23 5l-2.75-1.25L19 1l-1.25 2.75L15 5l2.75 1.25L19 9Zm-7.5.5L9 4 6.5 9.5 1 12l5.5 2.5L9 20l2.5-5.5L17 12l-5.5-2.5ZM19 15l-1.25 2.75L15 19l2.75 1.25L19 23l1.25-2.75L23 19l-2.75-1.25L19 15Z" />
		</svg>
	);
}

function IconCheck({ className }) {
	return (
		<svg className={className} viewBox="0 0 24 24" fill="currentColor" width="1em" height="1em">
			<path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2Zm-2 15-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9Z" />
		</svg>
	);
}

function IconCancel({ className }) {
	return (
		<svg className={className} viewBox="0 0 24 24" fill="currentColor" width="1em" height="1em">
			<path d="M12 2C6.47 2 2 6.47 2 12s4.47 10 10 10 10-4.47 10-10S17.53 2 12 2Zm5 13.59L15.59 17 12 13.41 8.41 17 7 15.59 10.59 12 7 8.41 8.41 7 12 10.59 15.59 7 17 8.41 13.41 12 17 15.59Z" />
		</svg>
	);
}

function IconDocument({ className }) {
	return (
		<svg className={className} viewBox="0 0 24 24" fill="currentColor" width="1em" height="1em">
			<path d="M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6Zm2 16H8v-2h8v2Zm0-4H8v-2h8v2ZM13 9V3.5L18.5 9H13Z" />
		</svg>
	);
}

function IconVignette({ className }) {
	return (
		<svg className={className} viewBox="0 0 24 24" fill="currentColor" width="1em" height="1em">
			<circle cx="12" cy="12" r="5" />
		</svg>
	);
}

function IconHeartBroken({ className }) {
	return (
		<svg className={className} viewBox="0 0 24 24" fill="currentColor" width="1em" height="1em">
			<path d="M16.5 3c-1.74 0-3.41.81-4.5 2.09C10.91 3.81 9.24 3 7.5 3 4.42 3 2 5.42 2 8.5c0 3.78 3.4 6.86 8.55 11.54L12 21.35l1.45-1.32C18.6 15.36 22 12.28 22 8.5 22 5.42 19.58 3 16.5 3Zm-3.83 14.83-.67.6-.67-.6C6.74 13.62 4 11 4 8.5 4 6.5 5.5 5 7.5 5c1.04 0 2.04.44 2.73 1.21L12 8.25l-2 2.75 4 2.5-2 3.5 1.67-1.17Z" />
		</svg>
	);
}

function IconTerminal({ className }) {
	return (
		<svg className={className} viewBox="0 0 24 24" fill="currentColor" width="1em" height="1em">
			<path d="M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2Zm0 14H4V8h16v10Zm-2-1h-6v-2h6v2ZM7.5 17l-1.41-1.41L8.67 13l-2.59-2.59L7.5 9l4 4-4 4Z" />
		</svg>
	);
}

function IconHub({ className }) {
	return (
		<svg className={className} viewBox="0 0 24 24" fill="currentColor" width="1em" height="1em">
			<path d="M8.4 18.2C8.78 18.7 9 19.32 9 20c0 1.66-1.34 3-3 3s-3-1.34-3-3 1.34-3 3-3c.44 0 .85.09 1.23.26l1.41-1.77a4.504 4.504 0 0 1-1.09-3.69l-2.03-.68A2.975 2.975 0 0 1 3 13c-1.66 0-3-1.34-3-3s1.34-3 3-3c1.3 0 2.4.84 2.82 2l2.01.67A4.47 4.47 0 0 1 10.2 7.2L9.98 5.17A2.992 2.992 0 0 1 8 2.23C8 .57 9.34-.77 11-.77s3 1.34 3 3c0 1.3-.84 2.4-2 2.82l.22 2.02A4.5 4.5 0 0 1 16.5 12c0 .21-.02.42-.05.62l2.05.68c.42-1.16 1.52-2 2.82-2 1.66 0 3 1.34 3 3s-1.34 3-3 3a2.99 2.99 0 0 1-2.52-1.37l-2.03-.68a4.468 4.468 0 0 1-3.13 1.93l-.22 2.02c1.16.42 2 1.52 2 2.82 0 1.66-1.34 3-3 3s-3-1.34-3-3c0-1.05.55-1.97 1.37-2.49L8.4 18.2Z" />
		</svg>
	);
}

// ---------------------------------------------------------------------------
// Main Landing Page
// ---------------------------------------------------------------------------

export default function LandingPage() {
	return (
		<div className="selection:bg-primary selection:text-on-primary">
			{/* TopAppBar */}
			<nav className="fixed top-0 w-full z-50 bg-[#131318]/90 backdrop-blur-xl flex justify-between items-center px-6 md:px-8 py-3 shadow-[0_2px_15px_rgba(0,0,0,0.5)] border-b border-outline-variant/10">
				<div className="flex items-center gap-4">
					<img
						alt="InkRealm Logo"
						className="h-10 md:h-14 w-auto object-contain"
						src="/images/inkrealm.png"
					/>
				</div>
				<div className="hidden md:flex gap-8 items-center">
					<a className="text-primary border-b-2 border-primary pb-1 font-label uppercase tracking-widest text-sm" href="#">
						ACCUEIL
					</a>
					<a className="text-on-surface-variant font-label hover:text-white uppercase tracking-widest text-sm transition-all duration-300" href="#">
						MOTEUR DE MONDE
					</a>
					<a className="text-on-surface-variant font-label hover:text-white uppercase tracking-widest text-sm transition-all duration-300" href="#">
						MÉCANIQUE
					</a>
				</div>
				<div className="flex gap-3 items-center">
					<Link
						href="/login/"
						className="text-on-surface-variant font-label uppercase tracking-widest text-xs md:text-sm hover:text-white transition-all duration-300"
					>
						CONNEXION
					</Link>
					<Link
						href="/register/"
						className="bg-primary text-on-primary px-4 md:px-6 py-2 font-label font-bold uppercase tracking-widest text-xs md:text-sm transition-all duration-300 hover:brightness-110 active:scale-95"
					>
						COMMENCER
					</Link>
				</div>
			</nav>

			{/* Hero Section */}
			<header className="relative pt-40 pb-32 px-8 overflow-hidden min-h-screen flex flex-col items-center justify-center text-center">
				<div className="absolute inset-0 -z-20">
					<div className="w-full h-full bg-surface" />
					<div className="absolute inset-0 bg-gradient-to-t from-[#131318] via-[#131318]/40 to-[#131318]" />
				</div>
				<div className="absolute inset-0 hero-gradient -z-10" />
				<div className="max-w-5xl mx-auto relative flex flex-col items-center">
					{/* Cinematic Logo */}
					<img
						alt="InkRealm Logo"
						className="w-72 md:w-[28rem] lg:w-[32rem] h-auto object-contain mb-8 amber-glow"
						style={{ animationDuration: '3000ms' }}
						src="/images/inkrealm.png"
					/>
					<span className="text-primary font-label uppercase tracking-[0.3em] text-xs md:text-sm mb-6 block drop-shadow-lg">
						LA PROCHAINE ÉVOLUTION DU NARRATIF
					</span>
					<h1 className="text-5xl md:text-8xl font-headline font-extrabold mb-8 leading-tight tracking-tight drop-shadow-2xl">
						L'échec est réel. <br />
						<span className="text-primary italic">L'histoire s'en souvient.</span>
					</h1>
					<p className="text-on-surface-variant text-lg md:text-2xl max-w-2xl mx-auto mb-12 font-body font-light leading-relaxed drop-shadow-lg">
						Un jeu de rôle IA où le moteur impose les règles et le monde n'oublie jamais. Vivez de vraies conséquences dans un paysage d'obsidienne mouvant.
					</p>
					<div className="flex flex-col md:flex-row gap-6 justify-center items-center w-full">
						<Link
							href="/register/"
							className="w-full md:w-auto bg-primary text-on-primary px-10 py-5 text-lg font-bold uppercase tracking-widest hover:brightness-110 transition-all active:scale-95 shadow-[0_0_20px_rgba(242,161,27,0.2)] text-center"
						>
							Commencer l'aventure
						</Link>
						<a
							href="#how-it-works"
							className="w-full md:w-auto border border-outline-variant text-on-surface px-10 py-5 text-lg font-bold uppercase tracking-widest hover:bg-surface-container-high transition-all active:scale-95 backdrop-blur-sm text-center"
						>
							Découvrir comment ça marche
						</a>
					</div>
				</div>
				<div className="mt-20 flex flex-col items-center opacity-40">
					<span className="text-[10px] tracking-[0.5em] uppercase mb-4">Descendre dans les Archives</span>
					<div className="w-px h-16 bg-gradient-to-b from-primary to-transparent" />
				</div>
			</header>

			{/* Stats Bar */}
			<section className="bg-surface-container-lowest border-y border-outline-variant/10 py-8">
				<div className="max-w-7xl mx-auto px-8 flex flex-col md:flex-row justify-around items-center gap-8 text-center">
					<div className="flex flex-col">
						<span className="text-3xl font-headline font-bold text-primary">4</span>
						<span className="text-xs uppercase tracking-widest text-on-surface-variant">Moteurs de jeu</span>
					</div>
					<div className="flex flex-col">
						<span className="text-3xl font-headline font-bold text-on-surface">∞</span>
						<span className="text-xs uppercase tracking-widest text-on-surface-variant">Mémoire persistante</span>
					</div>
					<div className="flex flex-col">
						<span className="text-3xl font-headline font-bold text-on-surface">100%</span>
						<span className="text-xs uppercase tracking-widest text-on-surface-variant">Vrais jets de dés</span>
					</div>
					<div className="flex flex-col">
						<span className="text-3xl font-headline font-bold text-on-surface">0€</span>
						<span className="text-xs uppercase tracking-widest text-on-surface-variant">Pour commencer</span>
					</div>
				</div>
			</section>

			{/* The Problem: Anti-Competitor Cards */}
			<section className="py-32 px-8 max-w-7xl mx-auto">
				<div className="mb-20">
					<h2 className="text-4xl font-headline font-bold mb-4">L&rsquo;illusion de l&rsquo;IA est brisée.</h2>
					<div className="w-24 h-1 bg-primary" />
				</div>
				<div className="grid md:grid-cols-3 gap-8">
					{/* Card 1 */}
					<div className="bg-surface-container-high p-10 border-l-4 border-error/50">
						<IconBlock className="text-error mb-6 text-4xl w-9 h-9" />
						<h3 className="text-2xl font-headline font-bold mb-4">L&rsquo;IA béni-oui-oui</h3>
						<p className="text-on-surface-variant leading-relaxed">
							Les autres IA vous laissent tout faire. Vous voulez tuer un dragon avec une cuillère ? Elles disent oui. Dans InkRealm, si le moteur dit que vous échouez, <span className="text-on-surface font-bold">vous échouez.</span>
						</p>
					</div>
					{/* Card 2 */}
					<div className="bg-surface-container-high p-10 border-l-4 border-outline-variant">
						<IconMemory className="text-outline mb-6 text-4xl w-9 h-9" />
						<h3 className="text-2xl font-headline font-bold mb-4">Mémoire de poisson rouge</h3>
						<p className="text-on-surface-variant leading-relaxed">
							Vous avez oublié l&apos;aubergiste que vous avez trahi il y a 10 chapitres ? Pas lui. InkRealm utilise un graphe de connaissances pour que chaque action laisse une cicatrice permanente sur le monde.
						</p>
					</div>
					{/* Card 3 */}
					<div className="bg-surface-container-high p-10 border-l-4 border-primary/50">
						<IconSkull className="text-primary mb-6 text-4xl w-9 h-9" />
						<h3 className="text-2xl font-headline font-bold mb-4">Enjeux factices</h3>
						<p className="text-on-surface-variant leading-relaxed">
							S&apos;il n&apos;y a pas de risque de mort ou de ruine durable, ce n&apos;est pas un jeu. C&apos;est une histoire pour s&apos;endormir hallucinée. InkRealm restaure le poids de vos choix.
						</p>
					</div>
				</div>
			</section>

			{/* How it Works: Steps */}
			<section id="how-it-works" className="py-32 bg-surface-container-lowest">
				<div className="max-w-7xl mx-auto px-8">
					<div className="text-center mb-24">
						<h2 className="text-5xl font-headline font-bold mb-6 italic">Réalités infinies, un seul moteur</h2>
						<p className="text-on-surface-variant max-w-xl mx-auto">
							Des dystopies baignées de néon aux cauchemars gothiques, InkRealm adapte sa logique à l'âme de votre univers.
						</p>
					</div>
					{/* Genre showcase: B+ staggered layout */}
					<div className="relative">
						{/* Desktop layout */}
						<div className="hidden md:grid md:grid-cols-3 gap-8 items-end max-w-5xl mx-auto">
							<div className="group relative overflow-hidden border border-outline-variant/20 aspect-[3/4] cursor-pointer transition-all duration-500 ease-out hover:scale-[1.03] hover:brightness-110 hover:border-primary/30">
								<img src="/images/genres/sf.webp" alt="Science-Fiction" className="absolute inset-0 w-full h-full object-cover" />
								<div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent group-hover:from-black/60 transition-all duration-500" />
								<div className="absolute bottom-0 left-0 right-0 p-8">
									<span className="text-primary text-xs font-label tracking-[0.3em] uppercase mb-2 block">Science-Fiction</span>
									<h3 className="text-2xl font-headline font-bold text-white">Néons &amp; Chrome</h3>
									<p className="text-on-surface-variant text-sm mt-2 opacity-0 group-hover:opacity-100 transition-opacity duration-500">Dystopies cyberpunk, voyages spatiaux et intrigues corporatistes.</p>
								</div>
							</div>
							<div className="group relative overflow-hidden border border-primary/20 aspect-[3/4] cursor-pointer transition-all duration-500 ease-out hover:scale-[1.03] hover:brightness-110 shadow-[0_0_30px_rgba(242,161,27,0.08)] -mt-8">
								<img src="/images/genres/fantasy.webp" alt="Fantasy" className="absolute inset-0 w-full h-full object-cover" />
								<div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent group-hover:from-black/60 transition-all duration-500" />
								<div className="absolute bottom-0 left-0 right-0 p-8">
									<span className="text-primary text-xs font-label tracking-[0.3em] uppercase mb-2 block">Fantasy</span>
									<h3 className="text-2xl font-headline font-bold text-white">Royaumes Oubliés</h3>
									<p className="text-on-surface-variant text-sm mt-2 opacity-0 group-hover:opacity-100 transition-opacity duration-500">Magie ancienne, quêtes épiques et royaumes en guerre.</p>
								</div>
							</div>
							<div className="group relative overflow-hidden border border-outline-variant/20 aspect-[3/4] cursor-pointer transition-all duration-500 ease-out hover:scale-[1.03] hover:brightness-110 hover:border-primary/30">
								<img src="/images/genres/horror.webp" alt="Horreur" className="absolute inset-0 w-full h-full object-cover" />
								<div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent group-hover:from-black/60 transition-all duration-500" />
								<div className="absolute bottom-0 left-0 right-0 p-8">
									<span className="text-primary text-xs font-label tracking-[0.3em] uppercase mb-2 block">Horreur</span>
									<h3 className="text-2xl font-headline font-bold text-white">Terreur Indicible</h3>
									<p className="text-on-surface-variant text-sm mt-2 opacity-0 group-hover:opacity-100 transition-opacity duration-500">Santé mentale fragile, horreur cosmique et cauchemars vivants.</p>
								</div>
							</div>
						</div>
						{/* Mobile: horizontal scroll carousel */}
						<div className="md:hidden flex gap-4 overflow-x-auto snap-x snap-mandatory pb-4 -mx-4 px-4 scrollbar-hide">
							<div className="group relative overflow-hidden border border-outline-variant/20 snap-center shrink-0 w-[75vw] aspect-[3/4]">
								<img src="/images/genres/sf.webp" alt="Science-Fiction" className="absolute inset-0 w-full h-full object-cover" />
								<div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent" />
								<div className="absolute bottom-0 left-0 right-0 p-6">
									<span className="text-primary text-xs font-label tracking-[0.3em] uppercase mb-2 block">Science-Fiction</span>
									<h3 className="text-xl font-headline font-bold text-white">Néons &amp; Chrome</h3>
									<p className="text-on-surface-variant text-xs mt-1">Dystopies cyberpunk, voyages spatiaux et intrigues corporatistes.</p>
								</div>
							</div>
							<div className="group relative overflow-hidden border border-primary/20 snap-center shrink-0 w-[75vw] aspect-[3/4]">
								<img src="/images/genres/fantasy.webp" alt="Fantasy" className="absolute inset-0 w-full h-full object-cover" />
								<div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent" />
								<div className="absolute bottom-0 left-0 right-0 p-6">
									<span className="text-primary text-xs font-label tracking-[0.3em] uppercase mb-2 block">Fantasy</span>
									<h3 className="text-xl font-headline font-bold text-white">Royaumes Oubliés</h3>
									<p className="text-on-surface-variant text-xs mt-1">Magie ancienne, quêtes épiques et royaumes en guerre.</p>
								</div>
							</div>
							<div className="group relative overflow-hidden border border-outline-variant/20 snap-center shrink-0 w-[75vw] aspect-[3/4]">
								<img src="/images/genres/horror.webp" alt="Horreur" className="absolute inset-0 w-full h-full object-cover" />
								<div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent" />
								<div className="absolute bottom-0 left-0 right-0 p-6">
									<span className="text-primary text-xs font-label tracking-[0.3em] uppercase mb-2 block">Horreur</span>
									<h3 className="text-xl font-headline font-bold text-white">Terreur Indicible</h3>
									<p className="text-on-surface-variant text-xs mt-1">Santé mentale fragile, horreur cosmique et cauchemars vivants.</p>
								</div>
							</div>
						</div>
					</div>
					<div className="grid md:grid-cols-4 gap-12 mt-24 relative opacity-80">
						<div className="relative">
							<div className="text-8xl font-headline font-black text-white/5 absolute -top-12 -left-4">01</div>
							<h4 className="text-xl font-bold mb-4 text-primary font-label tracking-widest uppercase">Création du monde</h4>
							<p className="text-on-surface-variant text-sm leading-relaxed">
								Semez votre réalité. Définissez la physique, les panthéons et les systèmes socio-politiques. L'IA construit une fondation ontologique cohérente.
							</p>
						</div>
						<div className="relative">
							<div className="text-8xl font-headline font-black text-white/5 absolute -top-12 -left-4">02</div>
							<h4 className="text-xl font-bold mb-4 text-primary font-label tracking-widest uppercase">Choix du moteur</h4>
							<p className="text-on-surface-variant text-sm leading-relaxed">
								Choisissez votre logique : RPG Hardcore, Horreur Lovecraftienne ou Liberté Narrative. Chaque moteur impose ses propres limites mécaniques strictes.
							</p>
						</div>
						<div className="relative">
							<div className="text-8xl font-headline font-black text-white/5 absolute -top-12 -left-4">03</div>
							<h4 className="text-xl font-bold mb-4 text-primary font-label tracking-widest uppercase">Narration authentique</h4>
							<p className="text-on-surface-variant text-sm leading-relaxed">
								Interagissez avec des PNJ qui ont de vraies motivations. Ils ne vous attendent pas ; ils vivent leur vie dans la simulation en arrière-plan.
							</p>
						</div>
						<div className="relative">
							<div className="text-8xl font-headline font-black text-white/5 absolute -top-12 -left-4">04</div>
							<h4 className="text-xl font-bold mb-4 text-primary font-label tracking-widest uppercase">Évolution persistante</h4>
							<p className="text-on-surface-variant text-sm leading-relaxed">
								Les Archives ne se réinitialisent jamais. Votre héritage reste en base de données, influençant le monde même si votre héros tombe.
							</p>
						</div>
					</div>
				</div>
			</section>

			{/* Feature Grid: Bento Style */}
			<section className="py-32 px-8 max-w-7xl mx-auto">
				<div className="grid grid-cols-1 md:grid-cols-12 md:grid-rows-2 gap-6 min-h-[800px]">
					<div className="md:col-span-8 bg-surface-container-high p-12 flex flex-col justify-end relative overflow-hidden group border border-outline-variant/10">
						<div className="absolute top-0 right-0 p-8 opacity-20 group-hover:opacity-40 transition-opacity">
							<IconGavel className="text-primary w-24 h-24" />
						</div>
						<h3 className="text-4xl font-headline font-bold mb-4">Règles incassables</h3>
						<p className="text-on-surface-variant text-lg max-w-md">
							Le moteur agit comme le Maître du Jeu ultime. Il vérifie votre inventaire, vos stats et l'environnement avant de valider toute action. Fini les boutons &ldquo;je gagne&rdquo;.
						</p>
					</div>
					<div className="md:col-span-4 bg-primary p-8 flex flex-col justify-center text-on-primary">
						<IconPsychology className="w-9 h-9 mb-6" />
						<h3 className="text-2xl font-headline font-bold mb-4">Mémoire par graphe de connaissances</h3>
						<p className="font-body text-sm opacity-90">
							Chaque interaction avec un PNJ est indexée et référencée. La trahison a de longues conséquences sur toute votre campagne narrative.
						</p>
					</div>
					<div className="md:col-span-3 bg-surface-container-highest p-8 flex flex-col gap-4 border border-outline-variant/10">
						<IconSettings className="text-primary w-7 h-7" />
						<h4 className="text-xl font-headline font-bold">Multi-moteur</h4>
						<p className="text-on-surface-variant text-xs">
							Basculez entre D20, PbtA ou des systèmes logiques personnalisés à la volée. Chaque monde maintient sa propre intégrité mécanique.
						</p>
					</div>
					<div className="md:col-span-6 bg-surface-container-low p-8 flex items-center gap-8 border border-outline-variant/20">
						<div className="hidden sm:block">
							<IconTrending className="text-primary w-12 h-12" />
						</div>
						<div>
							<h4 className="text-xl font-headline font-bold mb-2">Progression automatique</h4>
							<p className="text-on-surface-variant text-sm">
								Votre personnage évolue selon ses actes, pas juste des chiffres. Les événements traumatiques laissent des traits mentaux ; les exploits héroïques forgent des légendes automatiquement.
							</p>
						</div>
					</div>
					<div className="md:col-span-3 bg-[#2a292f] p-8 flex flex-col justify-between border-t-2 border-primary">
						<h4 className="text-xl font-headline font-bold">Assistant de création</h4>
						<IconMagic className="self-end w-9 h-9 text-primary/30" />
					</div>
				</div>
			</section>

			{/* Comparison Table */}
			<section className="py-32 bg-surface">
				<div className="max-w-7xl mx-auto px-8 overflow-x-auto">
					<h2 className="text-4xl font-headline font-bold mb-16 text-center">Le champ de bataille narratif</h2>
					<table className="w-full text-left border-collapse">
						<thead>
							<tr className="border-b border-outline-variant">
								<th className="py-6 px-4 font-label uppercase tracking-widest text-xs text-on-surface-variant">Fonctionnalité</th>
								<th className="py-6 px-4 font-headline font-bold text-primary text-xl">InkRealm</th>
								<th className="py-6 px-4 font-body font-semibold text-on-surface-variant">Concurrent A</th>
								<th className="py-6 px-4 font-body font-semibold text-on-surface-variant">Concurrent B</th>
							</tr>
						</thead>
						<tbody className="text-sm">
							<tr className="border-b border-outline-variant/10">
								<td className="py-6 px-4 font-bold">
									Vrais enjeux narratifs<br />
									<span className="text-[10px] font-normal text-on-surface-variant/60 uppercase tracking-wider">L'échec mécanique est définitif</span>
								</td>
								<td className="py-6 px-4 text-primary"><IconCheck className="w-6 h-6" /></td>
								<td className="py-6 px-4 text-on-surface-variant/40"><IconCancel className="w-6 h-6" /></td>
								<td className="py-6 px-4 text-on-surface-variant/40"><IconCancel className="w-6 h-6" /></td>
							</tr>
							<tr className="border-b border-outline-variant/10">
								<td className="py-6 px-4 font-bold">
									Graphe de connaissances long terme<br />
									<span className="text-[10px] font-normal text-on-surface-variant/60 uppercase tracking-wider">PNJ mémorisés sur des mois</span>
								</td>
								<td className="py-6 px-4 text-primary"><IconCheck className="w-6 h-6" /></td>
								<td className="py-6 px-4 text-on-surface-variant/40">Limité</td>
								<td className="py-6 px-4 text-on-surface-variant/40">Contexte seul</td>
							</tr>
							<tr className="border-b border-outline-variant/10">
								<td className="py-6 px-4 font-bold">
									Logique systémique du monde<br />
									<span className="text-[10px] font-normal text-on-surface-variant/60 uppercase tracking-wider">Physique et règles sociales cohérentes</span>
								</td>
								<td className="py-6 px-4 text-primary"><IconCheck className="w-6 h-6" /></td>
								<td className="py-6 px-4 text-on-surface-variant/40"><IconCancel className="w-6 h-6" /></td>
								<td className="py-6 px-4 text-on-surface-variant/40"><IconCancel className="w-6 h-6" /></td>
							</tr>
							<tr className="border-b border-outline-variant/10">
								<td className="py-6 px-4 font-bold">
									Progression automatisée<br />
									<span className="text-[10px] font-normal text-on-surface-variant/60 uppercase tracking-wider">Évolution basée sur les actes, pas les saisies</span>
								</td>
								<td className="py-6 px-4 text-primary"><IconCheck className="w-6 h-6" /></td>
								<td className="py-6 px-4 text-on-surface-variant/40">Manuel</td>
								<td className="py-6 px-4 text-on-surface-variant/40">Scripté</td>
							</tr>
							<tr className="border-b border-outline-variant/10">
								<td className="py-6 px-4 font-bold">
									Flexibilité du moteur<br />
									<span className="text-[10px] font-normal text-on-surface-variant/60 uppercase tracking-wider">Fate Core, D6, ou Résistance Narrative</span>
								</td>
								<td className="py-6 px-4 text-primary"><IconCheck className="w-6 h-6" /></td>
								<td className="py-6 px-4 text-on-surface-variant/40"><IconCancel className="w-6 h-6" /></td>
								<td className="py-6 px-4 text-on-surface-variant/40"><IconCancel className="w-6 h-6" /></td>
							</tr>
						</tbody>
					</table>
				</div>
			</section>

			{/* Forge Your Legend Section */}
			<section className="py-32 px-8 bg-[#0e0e13] border-y border-primary/10">
				<div className="max-w-7xl mx-auto">
					<div className="text-center mb-20">
						<h2 className="text-5xl font-headline font-bold mb-4">Forge ta légende</h2>
						<p className="text-on-surface-variant font-body">Forge ton identité. Les Archives sont prêtes à enregistrer ton ascension -- ou ta ruine.</p>
					</div>
					<div className="grid lg:grid-cols-2 gap-12 items-start">
						{/* Left: Character Portrait */}
						<div className="relative group">
							<div className="absolute -inset-1 bg-gradient-to-r from-primary/20 to-transparent blur opacity-75 group-hover:opacity-100 transition duration-1000" />
							<div className="relative bg-surface-container-lowest border border-outline-variant/30 aspect-[3/4] overflow-hidden">
								<div className="w-full h-full bg-gradient-to-br from-surface-container-high to-surface-container-lowest" />
								<div className="absolute inset-0 bg-gradient-to-t from-[#0e0e13] via-transparent to-transparent" />
								<div className="absolute bottom-8 left-8 right-8">
									<span className="text-primary font-label uppercase tracking-widest text-xs mb-2 block">Identité vérifiée</span>
									<h3 className="text-3xl font-headline font-bold text-white italic">Le Vagabond d'Obsidienne</h3>
								</div>
							</div>
							<div className="absolute -top-4 -right-4 w-24 h-24 border-t border-r border-primary/40 pointer-events-none" />
							<div className="absolute -bottom-4 -left-4 w-24 h-24 border-b border-l border-primary/40 pointer-events-none" />
						</div>
						{/* Right: Character Sheet & Config */}
						<div className="flex flex-col gap-8">
							{/* Stats Sheet */}
							<div className="bg-surface-container-high border border-outline-variant/20 p-8 shadow-2xl relative overflow-hidden">
								<div className="absolute top-0 right-0 p-4 opacity-10">
									<IconDocument className="w-16 h-16" />
								</div>
								<h4 className="text-xs font-label uppercase tracking-[0.4em] text-primary mb-8 border-b border-outline-variant/20 pb-4">
									Codex : Attributs
								</h4>
								<div className="space-y-8">
									<div>
										<div className="flex justify-between mb-2">
											<span className="font-headline font-bold text-lg italic">Force</span>
											<span className="font-label text-primary font-bold">14/20</span>
										</div>
										<div className="h-1 w-full bg-surface-container-lowest relative">
											<div className="absolute top-0 left-0 h-full bg-primary amber-glow" style={{ width: '70%' }} />
										</div>
									</div>
									<div>
										<div className="flex justify-between mb-2">
											<span className="font-headline font-bold text-lg italic">Intellect</span>
											<span className="font-label text-primary font-bold">18/20</span>
										</div>
										<div className="h-1 w-full bg-surface-container-lowest relative">
											<div className="absolute top-0 left-0 h-full bg-primary amber-glow" style={{ width: '90%' }} />
										</div>
									</div>
									<div>
										<div className="flex justify-between mb-2">
											<span className="font-headline font-bold text-lg italic">Volonté</span>
											<span className="font-label text-primary font-bold">09/20</span>
										</div>
										<div className="h-1 w-full bg-surface-container-lowest relative">
											<div className="absolute top-0 left-0 h-full bg-primary amber-glow" style={{ width: '45%' }} />
										</div>
									</div>
								</div>
							</div>
							{/* Persistent Traits */}
							<div className="bg-surface-container-high border border-outline-variant/20 p-8">
								<h4 className="text-xs font-label uppercase tracking-[0.4em] text-primary mb-6">Cicatrices narratives persistantes</h4>
								<div className="flex flex-wrap gap-4">
									<div className="flex items-center gap-3 bg-surface-container-lowest border border-primary/10 px-4 py-3 group hover:border-primary/50 transition-colors">
										<IconVignette className="text-primary w-4 h-4" />
										<span className="font-headline italic text-sm">Marqué par le Vide</span>
									</div>
									<div className="flex items-center gap-3 bg-surface-container-lowest border border-error/10 px-4 py-3 group hover:border-error/50 transition-colors">
										<IconHeartBroken className="text-error w-4 h-4" />
										<span className="font-headline italic text-sm">Parjure</span>
									</div>
									<div className="flex items-center gap-3 bg-surface-container-lowest border border-outline-variant/10 px-4 py-3 group hover:border-white/50 transition-colors">
										<IconMagic className="text-on-surface-variant w-4 h-4" />
										<span className="font-headline italic text-sm">Touché par les étoiles</span>
									</div>
								</div>
							</div>
						</div>
					</div>
				</div>
			</section>

			{/* Final CTA */}
			<section className="py-40 relative overflow-hidden text-center px-8">
				<div className="absolute inset-0 bg-[#0e0e13] -z-20" />
				<div className="max-w-4xl mx-auto border border-primary/20 p-12 md:p-20 bg-surface-container relative">
					<div className="absolute -top-4 -left-4 w-12 h-12 border-t-2 border-l-2 border-primary" />
					<div className="absolute -bottom-4 -right-4 w-12 h-12 border-b-2 border-r-2 border-primary" />
					<h2 className="text-4xl md:text-5xl font-headline font-bold mb-8">Prêt à écrire votre héritage ?</h2>
					<p className="text-on-surface-variant mb-12 text-lg">Le vide attend. Le moteur est prêt. Les Archives attendent leur prochaine entrée.</p>
					<div className="flex flex-col gap-6 items-center">
						<Link
							href="/register/"
							className="bg-primary text-on-primary px-12 py-5 font-bold uppercase tracking-[0.2em] hover:scale-105 transition-all shadow-[0_0_40px_rgba(242,161,27,0.15)] inline-block"
						>
							Commencer l'aventure
						</Link>
						<p className="text-on-surface-variant/60 font-label text-[10px] uppercase tracking-widest">
							Gratuit pour commencer. Pas de carte bancaire requise.
						</p>
					</div>
				</div>
			</section>

			{/* Footer */}
			<footer className="bg-[#0e0e13] w-full py-16 px-8 border-t border-[#524434]/20">
				<div className="flex flex-col md:flex-row justify-between items-center gap-10 max-w-7xl mx-auto">
					<div className="flex flex-col items-center md:items-start gap-4">
						<div className="flex items-center gap-3">
							<img
								alt="InkRealm Logo"
								className="h-10 w-auto object-contain"
								src="/images/inkrealm.png"
							/>
						</div>
						<p className="font-label uppercase text-[10px] tracking-widest text-on-surface-variant/40 text-center md:text-left">
							&copy; 2025 LES ARCHIVES D'OBSIDIENNE. FORGÉ DANS LE VIDE.
						</p>
					</div>
					<div className="flex flex-wrap justify-center gap-8">
						<a className="text-on-surface-variant/60 hover:text-primary font-label uppercase text-xs tracking-tighter hover:tracking-widest transition-all duration-500" href="#">CHRONIQUES</a>
						<a className="text-on-surface-variant/60 hover:text-primary font-label uppercase text-xs tracking-tighter hover:tracking-widest transition-all duration-500" href="#">LA MÉCANIQUE</a>
						<a className="text-on-surface-variant/60 hover:text-primary font-label uppercase text-xs tracking-tighter hover:tracking-widest transition-all duration-500" href="#">COMMUNAUTÉ</a>
						<a className="text-on-surface-variant/60 hover:text-primary font-label uppercase text-xs tracking-tighter hover:tracking-widest transition-all duration-500" href="#">CONFIDENTIALITÉ</a>
					</div>
					<div className="flex gap-6">
						<IconTerminal className="w-6 h-6 text-on-surface-variant/20 cursor-pointer hover:text-primary transition-colors" />
						<IconHub className="w-6 h-6 text-on-surface-variant/20 cursor-pointer hover:text-primary transition-colors" />
					</div>
				</div>
			</footer>
		</div>
	);
}
