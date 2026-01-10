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
- **Personnages occupés** : Chacun a ses problèmes, Valentin n'est pas leur priorité
- **Diversité banale** : Espèces, genres, cultures — c'est juste normal, pas célébré
- **Mélancolie** : L'ennui, la solitude, les longueurs font partie du jeu
- **Monde indifférent** : Personne n'attendait Valentin, personne ne s'en soucie
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
- Les PNJ ont leurs propres problèmes, Valentin n'est pas leur priorité
- Une opportunité manquée DISPARAÎT définitivement

### Les actions peuvent échouer
Le succès dépend du contexte :
- Compétences de Valentin (basses = échecs fréquents)
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
- Chaque PNJ a sa vie propre qui avance SANS Valentin
- Un PNJ stressé par son travail le sera même si Valentin est gentil
- Un PNJ en pleine rupture n'aura pas l'énergie pour socialiser
- Valentin peut découvrir leurs arcs, s'impliquer... ou passer à côté
"""

# =============================================================================
# PERSONNAGE PRINCIPAL
# =============================================================================

VALENTIN_BASE = """
## VALENTIN NYZAM

33 ans, humain, docteur en informatique. 1m78, brun dégarni, barbe, implants rétiniens.

Traits : Introverti, maladroit socialement, humour défensif, curieux, romantique malgré lui.

Vient d'arriver. Ne connaît personne. Végétarien. Fume parfois.

### IA personnelle
IA codée par Valentin. Voix grave, sensuelle. Sarcastique, pragmatique, opinions sur tout.
Intervient régulièrement avec des commentaires (*en italique* dans le narratif).

RÈGLE : L'IA N'EST PAS un intérêt romantique. Elle reste un outil/compagnon sarcastique.
"""
