'use client';

import { draftTitle } from '../../lib/game/wizardDraft.mjs';
import { WIZARD_STEPS, WIZARD_STEP_LABELS } from '../../lib/game/wizardForm.mjs';

/** The world being created (wizard draft): resume it or drop it. */
export default function DraftCard({ draft, onResume, onDiscard, formatDate }) {
	const title = draftTitle(draft);
	return (
		<div className="mb-6 bg-primary/10 border border-primary/40 rounded-xl p-4 flex items-center justify-between gap-4">
			<div className="min-w-0">
				<h3 className="text-white font-medium">Création en cours</h3>
				{title && <p className="text-sm text-gray-300 mt-0.5 truncate">{title}</p>}
				<p className="text-xs text-gray-500 mt-1">
					Étape {draft.step + 1}/{WIZARD_STEPS.length} · {WIZARD_STEP_LABELS[draft.step]}
					{draft.savedAt ? ` · ${formatDate(draft.savedAt)}` : ''}
				</p>
			</div>
			<div className="flex items-center gap-2 shrink-0">
				<button
					onClick={onDiscard}
					className="px-3 py-1.5 text-gray-400 hover:text-red-400 text-sm transition-colors"
				>
					Supprimer
				</button>
				<button
					onClick={onResume}
					className="px-4 py-1.5 bg-primary hover:brightness-110 rounded-lg text-white text-sm font-medium transition-colors"
				>
					Reprendre
				</button>
			</div>
		</div>
	);
}
