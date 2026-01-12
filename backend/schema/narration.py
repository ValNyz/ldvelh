"""
LDVELH - Narration Schema
Input/Output pour le LLM narrateur
"""

from typing import Optional
from pydantic import BaseModel, Field

from .core import (
    ArcDomain,
    EntityRef,
    Phrase,
    Tag,
    Text,
)


# =============================================================================
# CONTEXT BUILDING BLOCKS (Input pour le narrateur)
# =============================================================================


class GaugeState(BaseModel):
    """État d'une jauge du protagoniste"""

    value: float = Field(..., ge=0, le=5)
    trend: Optional[str] = None  # "↑", "↓", "stable"


class ProtagonistState(BaseModel):
    """État actuel du protagoniste"""

    name: str
    credits: int
    energy: GaugeState
    morale: GaugeState
    health: GaugeState
    # skills: list[str]  # "architecture_systemes (4), cuisine (3)"
    hobbies: list[str]
    current_occupation: Optional[str] = None
    employer: Optional[str] = None


class InventoryItem(BaseModel):
    """Objet dans l'inventaire"""

    name: str
    category: str
    quantity: int = 1
    emotional: bool = False  # A une signification émotionnelle


class LocationSummary(BaseModel):
    """Résumé d'un lieu"""

    name: str
    type: str
    sector: str
    atmosphere: str
    accessible: bool = True


class ArcSummary(BaseModel):
    """Résumé d'un arc de personnage"""

    domain: ArcDomain
    title: str
    situation_brief: str
    intensity: int  # 1-5


class NPCLightSummary(BaseModel):
    """Résumé léger d'un PNJ pour le contexte"""

    name: str
    occupation: str | None
    species: str = "human"
    relationship_level: int | None
    usual_location: str | None
    known: bool


class NPCSummary(NPCLightSummary):
    """Résumé d'un PNJ pour le contexte"""

    traits: list[str]  # 2-3 traits principaux
    relationship_to_protagonist: Optional[str] = (
        None  # "collègue", "voisine", "inconnu"
    )
    relationship_level: Optional[int] = None  # 0-10 si connu
    active_arcs: list[ArcSummary] = Field(default_factory=list)
    last_seen: Optional[str] = None  # "cycle 3, au café"
    notes: Optional[str] = None  # Infos importantes connues


class OrganizationSummary(BaseModel):
    """Résumé d'une organisation pour le contexte"""

    name: str
    org_type: str | None
    domain: str | None
    protagonist_relation: str | None  # ex: "employed_by"


class CommitmentSummary(BaseModel):
    """Résumé d'un engagement narratif actif"""

    type: str  # foreshadowing, secret, setup, chekhov_gun, arc
    title: str
    description_brief: str
    involved: list[str]  # Noms des entités impliquées
    deadline_cycle: Optional[int] = None
    urgency: str = "normal"  # low, normal, high, critical


class EventSummary(BaseModel):
    """Résumé d'un événement à venir"""

    title: str
    planned_cycle: int
    planned_time: Optional[str] = None
    location: Optional[str] = None
    participants: list[str] = Field(default_factory=list)
    type: str  # appointment, deadline, etc.


class Fact(BaseModel):
    """Fait"""

    cycle: int
    description: str
    importance: int  # 1-5
    involves: list[str] = Field(default_factory=list)


class MessageSummary(BaseModel):
    """Résumé d'un message passé"""

    role: str  # "user" ou "assistant"
    summary: str
    cycle: int
    time: Optional[str] = None


class CycleSummary(BaseModel):
    """Résumé d'un message passé"""

    summary: Text
    cycle: int
    date: Tag | None
    events: list[Phrase] = Field(default_factory=list)


class PersonalAISummary(BaseModel):
    """Résumé de l'IA personnelle de Valentin"""

    name: str
    voice_description: Optional[str] = None
    personality_traits: list[str] = Field(default_factory=list)
    quirk: Optional[str] = None


# =============================================================================
# NARRATION CONTEXT (Input complet)
# =============================================================================


class NarrationContext(BaseModel):
    """Contexte complet fourni au narrateur"""

    # === TEMPS ===
    current_cycle: int
    current_date: str  # "Mercredi 15 Mars 2847"
    current_time: str  # "14h30"

    # === ESPACE ===
    current_location: LocationSummary
    connected_locations: list[LocationSummary] = Field(
        default_factory=list,
        description="Lieux directement accessibles depuis le lieu actuel",
    )

    # === PROTAGONISTE ===
    protagonist: ProtagonistState
    inventory: list[InventoryItem] = Field(default_factory=list)

    # === IA PERSONNELLE ===
    personal_ai: Optional[PersonalAISummary] = Field(
        default=None, description="IA personnelle de Valentin (nom, traits, quirk)"
    )

    # === ORGANISATIONS ===
    organizations: list[OrganizationSummary]

    # === PNJs ===
    all_npcs: list[NPCLightSummary]
    npcs_present: list[NPCSummary] = Field(
        default_factory=list, description="PNJs actuellement présents dans le lieu"
    )
    npcs_relevant: list[NPCSummary] = Field(
        default_factory=list,
        description="PNJs connus pertinents (mentionnés, attendus, proches)",
    )

    # === NARRATIF ===
    active_commitments: list[CommitmentSummary] = Field(
        default_factory=list, description="Arcs et engagements narratifs actifs"
    )
    upcoming_events: list[EventSummary] = Field(
        default_factory=list, description="Événements prévus dans les prochains cycles"
    )

    # === FAITS ===
    facts: list[Fact] = Field(
        default_factory=list, description="Faits importants récents (importance >= 4)"
    )

    # === HISTORIQUE ===
    cycle_summaries: list[CycleSummary] = Field(
        default_factory=list, description="Résumés des derniers cycles"
    )
    recent_messages: list[MessageSummary] = Field(
        default_factory=list, description="Les derniers messages (détaillés)"
    )
    earlier_cycle_messages: list[MessageSummary] = Field(
        default_factory=list,
        description="Résumés courts des messages plus anciens du cycle en cours",
    )

    # === INPUT JOUEUR ===
    player_input: str = Field(..., description="Ce que le joueur a dit/choisi")

    # === META ===
    world_name: str
    world_atmosphere: str
    tone_notes: str = ""


# =============================================================================
# NARRATION HINTS (Signaux pour l'extracteur)
# =============================================================================


class NarrationHints(BaseModel):
    """Indices du narrateur pour guider l'extraction"""

    # Nouvelles entités mentionnées/introduites
    new_entities_mentioned: list[str] = Field(
        default_factory=list,
        description="Noms de nouveaux PNJs, lieux, objets mentionnés pour la première fois",
    )

    # Changements détectés
    relationships_changed: bool = Field(
        default=False,
        description="Une relation a évolué (amitié, tension, romance, pro...)",
    )
    protagonist_state_changed: bool = Field(
        default=False, description="Jauges, crédits, inventaire, skills ont changé"
    )
    information_learned: bool = Field(
        default=False, description="Le protagoniste a appris quelque chose de nouveau"
    )

    # Narrative
    commitment_advanced: list[str] = Field(
        default_factory=list,
        description="Titres des arcs/engagements qui ont progressé",
    )
    commitment_resolved: list[str] = Field(
        default_factory=list, description="Titres des arcs/engagements résolus"
    )
    new_commitment_created: bool = Field(
        default=False,
        description="Un nouveau secret, foreshadowing, setup a été introduit",
    )

    # Événements
    event_scheduled: bool = Field(
        default=False, description="Un rendez-vous ou événement futur a été planifié"
    )
    event_occurred: bool = Field(
        default=False, description="Un événement prévu s'est produit"
    )

    @property
    def needs_extraction(self) -> bool:
        """Détermine si une extraction est nécessaire"""
        return any(
            [
                self.new_entities_mentioned,
                self.relationships_changed,
                self.protagonist_state_changed,
                self.information_learned,
                self.commitment_advanced,
                self.commitment_resolved,
                self.new_commitment_created,
                self.event_scheduled,
                self.event_occurred,
            ]
        )


# =============================================================================
# NARRATION OUTPUT
# =============================================================================


class TimeProgression(BaseModel):
    """Progression temporelle"""

    new_time: str = Field(..., description="Nouvelle heure: 'HHhMM'")
    ellipse: bool = Field(
        default=False,
        description="True si saut temporel significatif (ellipse narrative)",
    )
    ellipse_summary: Phrase | None = None  # 150 chars


class DayTransition(BaseModel):
    """Transition vers un nouveau jour"""

    new_cycle: int
    new_date: str  # "Jeudi 16 Mars 2847"
    night_summary: Phrase | None = None  # 150 chars


class NarrationOutput(BaseModel):
    """Output complet du LLM narrateur"""

    # === NARRATION ===
    narrative_text: str = Field(
        ...,
        min_length=100,
        description="Texte narratif en Markdown. Ton Becky Chambers.",
    )

    # === TEMPS ===
    time: TimeProgression
    day_transition: Optional[DayTransition] = Field(
        default=None, description="Rempli seulement si on passe à un nouveau jour"
    )

    # === ESPACE ===
    current_location: EntityRef = Field(
        ..., description="Nom EXACT du lieu actuel (doit exister)"
    )

    # === PNJs ===
    npcs_present: list[EntityRef] = Field(
        default_factory=list, description="Noms EXACTS des PNJs présents dans la scène"
    )

    # === CHOIX ===
    suggested_actions: list[Phrase] = Field(
        ...,
        min_length=2,
        max_length=5,
        description="Suggestions d'actions possibles",
    )

    # === HINTS POUR EXTRACTION ===
    hints: NarrationHints

    # === META ===
    scene_mood: Tag | None = None  # 50 chars - Ambiance en 2-3 mots
    narrator_notes: Text | None = None  # 300 chars - Notes internes
