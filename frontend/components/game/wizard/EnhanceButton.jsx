'use client';

const LABELS = {
	invent: "Inventer avec l'IA",
	reroll: 'Nouvelle version',
	enhance: "Enrichir avec l'IA",
};

/**
 * "Enrichir avec l'IA": the text of the field above enriches the whole step
 * (POST /world/enhance); empty, the step is invented from the other choices;
 * on an AI text, a new version from the player's own text. Undoable like any change.
 */
export default function EnhanceButton({ onEnhance, enhancing, error, mode = 'enhance', hint }) {
	return (
		<div className="mt-2 space-y-1">
			<div className="flex items-center gap-3">
				<button
					type="button"
					onClick={onEnhance}
					disabled={enhancing}
					className="px-3 py-1.5 rounded-lg text-xs font-medium bg-primary/15 border border-primary/40 text-primary hover:bg-primary/25 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center gap-1.5"
				>
					{enhancing ? (
						<>
							<svg className="animate-spin h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" aria-hidden="true">
								<circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
								<path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
							</svg>
							L&apos;IA remplit…
						</>
					) : (
						<>✨ {LABELS[mode]}</>
					)}
				</button>
				<span className="text-xs text-gray-500">{hint}</span>
			</div>
			{error && <p className="text-xs text-red-400" role="alert">{error}</p>}
		</div>
	);
}
