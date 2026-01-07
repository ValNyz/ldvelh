import { NextResponse } from 'next/server';
import { formatTooltip } from '../../../lib/kg/knowledgeService';
import { supabase } from '../../../lib/supabase.js';

/**
 * GET /api/tooltips?partieId=xxx
 * Retourne les données tooltip pour toutes les entités connues
 */
export async function GET(request) {
	const { searchParams } = new URL(request.url);
	const partieId = searchParams.get('partieId');

	if (!partieId) {
		return NextResponse.json({ error: 'partieId requis' }, { status: 400 });
	}

	try {
		// Récupérer les données via la vue
		const { data, error } = await supabase
			.from('kg_v_tooltip')
			.select('*')
			.eq('partie_id', partieId);

		if (error) {
			console.error('[API Tooltips] Erreur:', error);
			return NextResponse.json({ error: error.message }, { status: 500 });
		}

		// Construire l'objet tooltips indexé par nom/alias
		const tooltips = {};

		for (const entity of data || []) {
			// Pré-formater les données tooltip
			const formatted = formatTooltip(entity);

			// Stocker avec nom comme clé
			tooltips[entity.entite_nom.toLowerCase()] = {
				...entity,
				formatted
			};

			// Ajouter les alias comme clés alternatives
			if (entity.alias?.length > 0) {
				for (const alias of entity.alias) {
					tooltips[alias.toLowerCase()] = {
						...entity,
						formatted
					};
				}
			}
		}

		return NextResponse.json({
			tooltips,
			count: data?.length || 0
		});

	} catch (err) {
		console.error('[API Tooltips] Exception:', err);
		return NextResponse.json({ error: err.message }, { status: 500 });
	}
}
