/**
 * Banques de noms pour la diversité de génération
 */

// ============================================================================
// NOMS À EXCLURE (trop courants, clichés SF)
// ============================================================================

export const EXCLUSIONS = {
	ia: [
		'Nova', 'Aurora', 'Stella', 'Luna', 'Aria', 'Echo', 'Iris', 'Astra',
		'Vega', 'Lyra', 'Zara', 'Nyx', 'Athena', 'Cortana', 'Samantha', 'Friday',
		'Jarvis', 'Hal', 'Ava', 'Alexa', 'Siri', 'Oracle', 'Sage', 'Cipher'
	],

	station: [
		'Nova Station', 'Nexus', 'Horizon', 'Eclipse', 'Aurora', 'Prometheus',
		'Olympus', 'Elysium', 'Arcadia', 'Zenith', 'Apex', 'Vanguard', 'Sentinel',
		'Gateway', 'Pinnacle', 'Sanctuary', 'Haven', 'Citadel', 'Bastion'
	],

	pnj_prenoms: [
		'Zara', 'Nova', 'Luna', 'Aria', 'Kai', 'Max', 'Alex', 'Sam',
		'Eve', 'Ada', 'Mia', 'Leo', 'Finn', 'Jade', 'Ruby', 'Ivy'
	],

	lieux: [
		'Le Nebula', 'Eclipse Bar', 'Nova Café', 'Stellar Lounge',
		'Cosmos', 'Galaxy', 'Astral', 'Orbital', 'Zero-G'
	]
};

// ============================================================================
// ORIGINES CULTURELLES (pour diversité des noms)
// ============================================================================

export const ORIGINES = [
	{ code: 'slave', label: 'slave (russe, polonais, tchèque)', exemples: ['Milena', 'Darya', 'Yelena', 'Zoya', 'Katka', 'Oksana'] },
	{ code: 'nordique', label: 'nordique (scandinave, islandais)', exemples: ['Sigrid', 'Astrid', 'Freya', 'Ingrid', 'Solveig', 'Ylva'] },
	{ code: 'mediterraneen', label: 'méditerranéen (italien, grec, turc)', exemples: ['Chiara', 'Elettra', 'Despina', 'Sevda', 'Filiz', 'Ariadne'] },
	{ code: 'asiatique', label: 'asiatique (japonais, coréen, vietnamien)', exemples: ['Haruki', 'Yuna', 'Linh', 'Sora', 'Mirae', 'Thao'] },
	{ code: 'africain', label: 'africain (swahili, yoruba, amharique)', exemples: ['Amara', 'Zuri', 'Nneka', 'Desta', 'Makena', 'Oluwaseun'] },
	{ code: 'latinoamericain', label: 'latino-américain', exemples: ['Paloma', 'Marisol', 'Ximena', 'Luz', 'Socorro', 'Graciela'] },
	{ code: 'moyenoriental', label: 'moyen-oriental (persan, arabe, hébreu)', exemples: ['Shirin', 'Leila', 'Farah', 'Noor', 'Yasmin', 'Tamar'] },
	{ code: 'celtique', label: 'celtique (irlandais, gallois, breton)', exemples: ['Siobhan', 'Niamh', 'Bronwen', 'Eira', 'Maëlle', 'Aoife'] },
	{ code: 'indien', label: 'indien (hindi, tamoul, bengali)', exemples: ['Priya', 'Ananya', 'Kavitha', 'Meera', 'Devika', 'Lakshmi'] },
	{ code: 'basque', label: 'basque', exemples: ['Amaia', 'Itziar', 'Nerea', 'Leire', 'Garazi', 'Miren'] }
];

// ============================================================================
// STYLES DE NOMS DE STATIONS
// ============================================================================

export const STYLES_STATION = [
	{
		code: 'numerique',
		label: 'code alphanumérique industriel',
		exemples: ['Station K-7', 'Plateforme 12-Sigma', 'Hub G-349', 'Avant-poste R-18']
	},
	{
		code: 'corporatif',
		label: 'nom d\'entreprise/fondateur',
		exemples: ['Station Matsuda', 'Complexe Okonkwo', 'Hub Lebedev', 'Terminal Johansson']
	},
	{
		code: 'geographique',
		label: 'référence géographique terrestre',
		exemples: ['Nouveau-Valparaiso', 'Port-Kerguelen', 'Baie-Tranquille', 'Anse-Profonde']
	},
	{
		code: 'mythologie_obscure',
		label: 'mythologie non-gréco-romaine',
		exemples: ['Sedna', 'Morrigan', 'Anansi', 'Quetzal', 'Freyr', 'Inari']
	},
	{
		code: 'pragmatique',
		label: 'nom fonctionnel/descriptif',
		exemples: ['Le Relais', 'Point-Milieu', 'Escale-7', 'Le Carrefour', 'La Jonction']
	},
	{
		code: 'vernaculaire',
		label: 'surnom donné par les habitants',
		exemples: ['La Rouille', 'Le Bout du Monde', 'La Passoire', 'Le Trou', 'La Conserve']
	}
];

// ============================================================================
// TRAITS DE PNJ POUR DIVERSITÉ
// ============================================================================

export const CONTRAINTES_PNJ = [
	{ type: 'age', options: ['plus de 55 ans', 'moins de 25 ans', 'dans la quarantaine'] },
	{ type: 'physique', options: ['utilise un fauteuil hover', 'a des modifications cybernétiques visibles', 'de très grande taille', 'albinos', 'porte des vêtements traditionnels de sa culture'] },
	{ type: 'espece', options: ['non-humanoïde', 'hybride humain-alien', 'humain génétiquement modifié', 'androïde social', 'espèce à durée de vie très longue'] },
	{ type: 'background', options: ['ancien militaire', 'réfugié d\'un conflit', 'artiste reconverti', 'ex-criminel réhabilité', 'aristocrate déchu'] }
];

// ============================================================================
// LETTRES AVEC PRÉNOMS MOINS COMMUNS
// ============================================================================

export const LETTRES_INTERESSANTES = ['B', 'D', 'G', 'H', 'K', 'M', 'N', 'O', 'P', 'R', 'S', 'T', 'V', 'Y', 'Z'];
