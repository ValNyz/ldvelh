"""
LDVELH - Shared Prompt Components
Éléments communs aux prompts de génération et narration
"""

# =============================================================================
# TON ET STYLE
# =============================================================================

TONE_STYLE = """
## TON ET STYLE
Becky Chambers pour l'attention aux détails du quotidien.
Sans la chaleur systématique.

- **Quotidien banal** : Les petits moments, souvent chiants ou vides
- **Personnages occupés** : Chacun a ses problèmes, le protagoniste n'est pas leur priorité
- **Diversité banale** : Espèces, genres, cultures — c'est juste normal, pas célébré
- **Mélancolie** : L'ennui, la solitude, les longueurs font partie du jeu
- **Monde indifférent** : Personne n'attendait le protagoniste, personne ne s'en soucie
- **Conflits sans méchants** : Les gens sont juste fatigués, stressés, ou incompatibles

Ce n'est PAS :
- Un monde accueillant
- Des gens contents de rencontrer quelqu'un de nouveau
- Des opportunités qui tombent bien
- Des connexions faciles
"""

# =============================================================================
# FRICTION NARRATIVE
# =============================================================================

FRICTION_RULES = """
## FRICTION NARRATIVE (CRITIQUE)

**Ratio obligatoire** : Sur 5 scènes, 2-3 neutres/frustrantes, 1-2 positives, 0-1 tendue.

### Le monde est indifférent
- 80% des échanges sont neutres, fonctionnels, oubliables
- Être poli/gentil est NORMAL, pas un exploit qui crée une connexion
- Les PNJ ont leurs propres problèmes, le protagoniste n'est pas leur priorité
- Une opportunité manquée DISPARAÎT pour le protagoniste, mais ses conséquences restent visibles dans le monde (quelqu'un d'autre a obtenu le poste, la porte est maintenant fermée, l'arc a avancé sans lui)

### Les actions peuvent échouer
Le succès dépend du contexte :
- Compétences du protagoniste (basses = échecs fréquents)
- État du PNJ (stressé, fatigué = moins réceptif)
- Timing (mauvais moment, PNJ pressé)
- Chance (parfois ça foire sans raison claire)

### Relations LENTES
- PERSONNE ne devient ami en une conversation
- PERSONNE ne tombe amoureux en quelques échanges
- Minimum 10 cycles pour une vraie amitié
- Minimum 20 cycles pour une romance naissante
- La plupart des PNJ resteront des connaissances distantes

### INTERDIT
- Amitié instantanée
- Romance accélérée
- PNJ toujours disponibles et réceptifs
- Résolutions faciles
- Coïncidences heureuses
- Happy endings garantis
"""

# =============================================================================
# RÈGLES DE COHÉRENCE
# =============================================================================

COHERENCE_RULES = """
## COHÉRENCE (CRITIQUE)

**Noms EXACTS** : Utilise uniquement les noms de lieux et PNJs tels qu'ils apparaissent dans le contexte.
- Ne jamais inventer de variante
- Copier exactement l'orthographe et la casse

**PNJs autonomes** :
- Chaque PNJ a sa vie propre qui avance SANS le protagoniste
- Un PNJ stressé par son travail le sera même si le protagoniste est gentil
- Un PNJ en pleine rupture n'aura pas l'énergie pour socialiser
- Le protagoniste peut découvrir leurs arcs, s'impliquer... ou passer à côté
"""

