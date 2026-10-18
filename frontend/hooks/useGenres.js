'use client';

import { useEffect, useState } from 'react';
import { api } from '../lib/api';

/** The genres ({ slug, label, ... }) from GET /genres; [] until loaded or on failure. */
export function useGenres() {
	const [genres, setGenres] = useState([]);
	useEffect(() => {
		let cancelled = false;
		api.get('/genres')
			.then(data => { if (!cancelled) setGenres(data?.genres || []); })
			.catch(() => {});
		return () => { cancelled = true; };
	}, []);
	return genres;
}

/** A genre's label, else its slug. */
export function genreLabel(genres, slug) {
	return genres.find(g => g.slug === slug)?.label || slug;
}
