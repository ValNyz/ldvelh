"""
LDVELH - State Normalizer
Normalise l'état du jeu pour le frontend
"""

from typing import Any, Optional
from uuid import UUID
from pydantic import BaseModel, Field
from decimal import Decimal

from config import STATS_DEFAUT


# =============================================================================
# PYDANTIC MODELS (pour validation et sérialisation)
# =============================================================================


class InventaireItem(BaseModel):
    """Item d'inventaire normalisé"""

    id: Optional[UUID] = None
    nom: str
    quantite: int = 1
    localisation: str = "sur_soi"
    categorie: str = "autre"
    etat: str = "bon"
    valeur_neuve: Optional[int] = None
    prete_a: Optional[str] = None


class ValentinState(BaseModel):
    """Stats de Valentin normalisées"""

    energie: float = Field(default=STATS_DEFAUT["energie"])
    moral: float = Field(default=STATS_DEFAUT["moral"])
    sante: float = Field(default=STATS_DEFAUT["sante"])
    credits: int = Field(default=STATS_DEFAUT["credits"])
    inventaire: list[InventaireItem] = Field(default_factory=list)


class PartieState(BaseModel):
    """État de la partie normalisé"""

    id: Optional[UUID] = None
    nom: str = "Partie sans nom"
    cycle_actuel: int = 1
    jour: str = "Lundi"
    date_jeu: Optional[str] = None
    heure: Optional[str] = None
    lieu_actuel: Optional[str] = None
    pnjs_presents: list[str] = Field(default_factory=list)
    status: str = "active"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class IAState(BaseModel):
    """État de l'IA normalisé"""

    nom: Optional[str] = None
    personnalite: Optional[str] = None
    relation: Optional[int] = None


class GameState(BaseModel):
    """État complet du jeu normalisé"""

    partie: Optional[PartieState] = None
    valentin: ValentinState = Field(default_factory=ValentinState)
    ia: Optional[IAState] = None


# =============================================================================
# NORMALIZERS
# =============================================================================


def normalize_inventaire_item(item: Any) -> InventaireItem:
    """
    Normalise un item d'inventaire.
    Supporte ancien format (string) et nouveau format (dict/row).
    """
    # Ancien format: juste un string
    if isinstance(item, str):
        return InventaireItem(nom=item)

    # Format dict ou asyncpg Record
    data = dict(item) if hasattr(item, "keys") else item

    return InventaireItem(
        id=data.get("id"),
        nom=data.get("nom") or data.get("name", "?"),
        quantite=data.get("quantite") or data.get("quantity", 1),
        localisation=data.get("localisation") or data.get("location", "sur_soi"),
        categorie=data.get("categorie") or data.get("category", "autre"),
        etat=data.get("etat") or data.get("condition", "bon"),
        valeur_neuve=data.get("valeur_neuve") or data.get("base_value"),
        prete_a=data.get("prete_a") or data.get("lent_to"),
    )


def normalize_valentin(data: Optional[dict]) -> ValentinState:
    """
    Normalise les données de Valentin.
    """
    if not data:
        return ValentinState()

    # Normaliser l'inventaire
    raw_inventaire = data.get("inventaire") or data.get("inventory") or []
    inventaire = [normalize_inventaire_item(item) for item in raw_inventaire]

    # Convertir Decimal en float si nécessaire
    def to_float(val, default):
        if val is None:
            return default
        if isinstance(val, Decimal):
            return float(val)
        return float(val)

    return ValentinState(
        energie=to_float(
            data.get("energie") or data.get("energy"), STATS_DEFAUT["energie"]
        ),
        moral=to_float(data.get("moral"), STATS_DEFAUT["moral"]),
        sante=to_float(data.get("sante") or data.get("health"), STATS_DEFAUT["sante"]),
        credits=int(data.get("credits", STATS_DEFAUT["credits"])),
        inventaire=inventaire,
    )


def normalize_partie(data: Optional[dict]) -> Optional[PartieState]:
    """
    Normalise les données de la partie.
    """
    if not data:
        return None

    # Gérer les différents noms de champs (snake_case Python vs camelCase ou ancien format)
    return PartieState(
        id=data.get("id") or data.get("partie_id"),
        nom=data.get("nom") or data.get("name", "Partie sans nom"),
        cycle_actuel=data.get("cycle_actuel") or data.get("current_cycle", 1),
        jour=data.get("jour") or data.get("narrative_day", "Lundi"),
        date_jeu=data.get("date_jeu") or data.get("universe_date"),
        heure=data.get("heure") or data.get("time") or data.get("current_time"),
        lieu_actuel=data.get("lieu_actuel") or data.get("current_location"),
        pnjs_presents=data.get("pnjs_presents") or data.get("npcs_present") or [],
        status=data.get("status", "active"),
        created_at=str(data["created_at"]) if data.get("created_at") else None,
        updated_at=str(data["updated_at"]) if data.get("updated_at") else None,
    )


def normalize_ia(data: Optional[dict]) -> Optional[IAState]:
    """
    Normalise les données de l'IA.
    """
    if not data:
        return None

    return IAState(
        nom=data.get("nom") or data.get("name"),
        personnalite=data.get("personnalite") or data.get("personality"),
        relation=data.get("relation") or data.get("relationship_level"),
    )


def normalize_game_state(
    partie_data: Optional[dict] = None,
    valentin_data: Optional[dict] = None,
    ia_data: Optional[dict] = None,
    flat_data: Optional[dict] = None,
) -> GameState:
    """
    Normalise l'état complet du jeu.

    Peut recevoir soit des données structurées (partie_data, valentin_data, ia_data),
    soit un dict plat (flat_data) qu'il faut parser.
    """
    # Si on reçoit un dict plat, extraire les données
    if flat_data:
        # Vérifier si c'est déjà structuré
        if "partie" in flat_data or "valentin" in flat_data:
            partie_data = flat_data.get("partie")
            valentin_data = flat_data.get("valentin")
            ia_data = flat_data.get("ia")
        else:
            # Extraire depuis un dict plat (ex: réponse BDD directe)
            partie_data = extract_partie_from_flat(flat_data)
            valentin_data = extract_valentin_from_flat(flat_data)

    return GameState(
        partie=normalize_partie(partie_data),
        valentin=normalize_valentin(valentin_data),
        ia=normalize_ia(ia_data),
    )


def extract_partie_from_flat(data: dict) -> dict:
    """
    Extrait les infos de partie depuis un dict plat.
    """
    keys = [
        "id",
        "nom",
        "name",
        "heure",
        "time",
        "current_time",
        "lieu_actuel",
        "current_location",
        "pnjs_presents",
        "npcs_present",
        "cycle_actuel",
        "current_cycle",
        "jour",
        "narrative_day",
        "date_jeu",
        "universe_date",
        "status",
        "created_at",
        "updated_at",
    ]
    return {k: data[k] for k in keys if k in data}


def extract_valentin_from_flat(data: dict) -> dict:
    """
    Extrait les stats de Valentin depuis un dict plat.
    """
    keys = [
        "energie",
        "energy",
        "moral",
        "morale",
        "sante",
        "health",
        "credits",
        "inventaire",
        "inventory",
    ]
    return {k: data[k] for k in keys if k in data}


# =============================================================================
# MERGE HELPERS
# =============================================================================


def merge_game_states(prev: GameState, update: dict) -> GameState:
    """
    Fusionne un état existant avec une mise à jour partielle.
    Utile pour les updates SSE qui ne contiennent qu'une partie des données.
    """
    # Normaliser l'update
    update_state = normalize_game_state(flat_data=update)

    # Fusionner
    new_partie = None
    if prev.partie or update_state.partie:
        prev_dict = prev.partie.model_dump() if prev.partie else {}
        update_dict = update_state.partie.model_dump() if update_state.partie else {}
        # Filtrer les None de l'update
        update_dict = {k: v for k, v in update_dict.items() if v is not None}
        merged = {**prev_dict, **update_dict}
        new_partie = PartieState(**merged)

    new_valentin = merge_valentin(prev.valentin, update_state.valentin)

    new_ia = None
    if prev.ia or update_state.ia:
        prev_dict = prev.ia.model_dump() if prev.ia else {}
        update_dict = update_state.ia.model_dump() if update_state.ia else {}
        update_dict = {k: v for k, v in update_dict.items() if v is not None}
        if update_dict:
            merged = {**prev_dict, **update_dict}
            new_ia = IAState(**merged)
        else:
            new_ia = prev.ia

    return GameState(partie=new_partie, valentin=new_valentin, ia=new_ia)


def merge_valentin(prev: ValentinState, update: ValentinState) -> ValentinState:
    """
    Fusionne les stats de Valentin.
    L'inventaire est toujours remplacé (source de vérité = BDD).
    """
    return ValentinState(
        energie=update.energie
        if update.energie != STATS_DEFAUT["energie"]
        else prev.energie,
        moral=update.moral if update.moral != STATS_DEFAUT["moral"] else prev.moral,
        sante=update.sante if update.sante != STATS_DEFAUT["sante"] else prev.sante,
        credits=update.credits
        if update.credits != STATS_DEFAUT["credits"]
        else prev.credits,
        # L'inventaire du serveur a priorité (même si vide)
        inventaire=update.inventaire if update.inventaire else prev.inventaire,
    )


# =============================================================================
# SERIALIZATION HELPERS
# =============================================================================


def game_state_to_dict(state: GameState) -> dict:
    """
    Convertit un GameState en dict pour JSON.
    Utilise les alias français pour le frontend.
    """
    return state.model_dump(exclude_none=True)


def game_state_to_json(state: GameState) -> str:
    """
    Convertit un GameState en JSON string.
    """
    return state.model_dump_json(exclude_none=True)
