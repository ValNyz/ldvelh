# Règles d'annotation du corpus or d'identité (P6, #151)

Ce document fixe les règles d'annotation du corpus `backend/tests/fixtures/identity/`. Il est écrit et relu **avant** la première scène (décision D25). Il doit permettre à un autre annotateur, qui n'a vu ni le code ni les scènes déjà écrites, de produire le même or. En cas de doute, on suit l'**ordre de décision** du § 5, et on consigne le cas dans le § 13 (« Cas tranchés ») pour que la règle serve à tous.

Le format est vérifié par `backend/evals/identity/corpus.py` (`validate_scene`, `validate_sequence`) et par `tests/identity/test_corpus.py` : une scène invalide fait échouer la CI.

---

## 1. Ce qu'on mesure, et ce que l'or représente

Une scène pose une question unique : **à quelle entité du monde chaque groupe nominal de la narration renvoie-t-il ?** L'or est la réponse qu'un lecteur attentif donnerait **en connaissant le monde complet** (le `world`, y compris les noms cachés), et non ce que le système a fait à l'époque.

Conséquences :
- le `world` est le **graphe or avant le tour** : on y corrige les défauts de la base réelle (doublons fusionnés, entités inventées supprimées, entités manquantes ajoutées) ; il ne reproduit pas la base telle quelle ;
- les mentions de l'`history` sont les liens que le système **aurait dû** enregistrer aux tours précédents, exprimés dans ce `world` ;
- l'or ne dépend jamais de ce qu'un modèle « pourrait raisonnablement deviner » : seulement du texte et du monde.

Les chiffres de la gate se lisent comme « accord avec l'annotateur unique » ; le plafond d'accord humain n'est pas mesuré (§ 3.3 de la spécification).

---

## 2. Format d'un fichier de scène (`scenes/<id>.yaml`)

Un fichier = une scène. Le nom du fichier est l'id de la scène suivi de `.yaml`. Les fichiers dont le nom commence par `_` (`_example.yaml`) sont des **exemples** : validés par la CI, mais exclus du corpus mesuré (`load_scenes` ne les charge qu'avec `include_examples=True`) et donc jamais dans le split dev/test.

```yaml
id: real-f134-t15            # unique dans tout le corpus ; voir § 2.1
genre: sf                    # étiquette libre (≥ 2 genres dans le corpus) ; le code n'en connaît aucun
campaign: real-f134          # obligatoire : groupe de scènes qui partagent un monde ou un historique (§ 12)
language: fr                 # facultatif, "fr" par défaut : choisit evals/identity/lexicon/<language>.yaml
source: real                 # real (parties de la base dev) | synthetic | issue
turn: 15                     # numéro du tour narré dans la partie (facultatif, requis pour GAP)
world: [...]                 # § 3
history: [...]               # § 4.4
scene: {...}                 # § 3.4
narration: |-                # texte brut du tour, tel quel (markdown compris)
  ...
gold: [...]                  # § 4 et § 5
gold_effects: {...}          # § 6
gold_knowledge: [...]        # § 7
```

Tous les champs sont obligatoires sauf `turn` et `language` ; `campaign` vaut `real-<game4>` pour tous les tours d'une partie réelle, le nom du monde pour les scènes synthétiques d'un même univers (`halcyon-7`, `vargne`…), le nom de la famille pour des scènes d'issue qui partagent un monde (`voss`), l'id de la scène pour une scène isolée, l'id de la séquence pour ses tours ; une clé inconnue (faute de frappe) est refusée au chargement.

**Langue et lexique.** Le code de validation ne contient aucun mot d'une langue : les déterminants, les pronoms personnels et les pronoms indéfinis ou démonstratifs des § 4.1, § 4.2 et § 5.2 sont lus dans `backend/evals/identity/lexicon/<language>.yaml` (listes fermées). Une scène dans une autre langue déclare `language: <code>` et s'appuie sur le lexique de cette langue ; une langue sans lexique est refusée au chargement. Les exemples de ce document sont en français parce que le corpus l'est.

### 2.1 Ids

- **Ids de scène** : `real-<4 premiers caractères du game_id>-t<NN>` pour les tours réels (`real-f134-t15`), `syn-<genre>-<catégorie>-<nn>` pour les scènes synthétiques (`syn-sf-desc-03`), les ids fixés par le plan pour les issues (`issue-25-voss`, `issue-26-gap21`, `roadmap-rizka-elara`), `example-…` pour les exemples.
- **Ids d'entité** : `<type>_<slug>`, où le slug est le libellé (`label`) en minuscules, sans accents, sans article de tête, mots joints par `_` : `character_tesk_vahrun_oo`, `location_cantine_du_puits`, `organization_bureau_des_residences`, `object_terminal_personnel`. Pour une entité sans nom, le slug vient du descripteur (`character_kethari_agee`). L'id est stable : il ne change pas quand l'entité est révélée ou renommée dans une scène ultérieure.

### 2.2 Offsets

`start` est l'indice (base 0) du premier caractère de la surface dans le texte, compté en **caractères Unicode** (indice d'une chaîne Python), sur le texte **brut** stocké (`narration` ou `history[i].text`), astérisques et tirets de dialogue compris. La surface est recopiée **exactement** (casse, accents, apostrophe typographique) : `narration[start:start+len(surface)] == surface` est vérifié. Pour une surface qui apparaît plusieurs fois, chaque occurrence est une mention distincte avec son propre `start`.

---

## 3. Le monde (`world`) et la scène (`scene`)

### 3.1 Entités

```yaml
- id: character_tesk_vahrun_oo
  type: character            # character | location | organization | object | protagonist | companion | arc
  label: Tesk Vahrun-Oo      # libellé canonique interne : le vrai nom s'il existe, sinon le descripteur
  true_name: Tesk Vahrun-Oo  # vrai nom (null si l'entité n'en a pas encore)
  descriptor: Le Kethari au tablier   # ce que le PJ voit (null si sans objet)
  known: false               # le PJ connaît-il le nom (true_name) ? cf. § 7
  secret: false              # l'entité entière est-elle gardée par le Director ? cf. § 7
  occupation: gérant de la Cantine du Puits
  location: location_cantine_du_puits   # id d'un lieu du world, ou null
  last_seen_turn: 14         # dernier tour où l'entité est apparue ou a été citée (null si jamais)
  aliases:
    - {text: Tesk Vahrun-Oo, kind: true_name, known: false}
    - {text: Tesk, kind: short, known: false}
    - {text: Le Kethari au tablier, kind: descriptor, known: true}
```

- `kind` d'alias : `true_name`, `descriptor`, `short`, `title`, `former_name`, `nickname`, `label` (mêmes valeurs que `entity_aliases.kind`, § 4.2 de la spécification).
- On liste **tous** les alias que le système devrait connaître avant le tour : vrai nom, formes courtes (prénom seul, nom seul : « Elara », « Voss »), titre + nom (« Pater Ondrev »), descripteurs déjà employés, anciens noms. Un alias `true_name` ou `short` d'un nom que le PJ ignore a `known: false` ; un descripteur a toujours `known: true` (c'est ce que le PJ voit).
- Lieux, organisations, objets : `label` est leur nom (« Cantine du Puits », « Terminal personnel »), avec un alias `label` `known: true` ; `true_name` n'est renseigné que si l'entité a un nom caché distinct (« la salle au bout du couloir » → `true_name: Serre Numéro Quatre`).
- Protagoniste (`protagonist_<prénom>`) et compagnon (`companion_<nom>`) sont toujours présents dans le `world`, même quand la base réelle ne les a pas comme entités (la voix du terminal de f134, « Pervenche »).
- Les objets d'inventaire du PJ sont des entités `object` ; un objet n'entre dans le `world` que s'il a un rôle (§ 5.3).
- `occupation` (et tout autre attribut) est la valeur du graphe or, **sans état de connaissance** : le champ ne dit pas si le PJ la connaît. Un attribut inconnu du PJ ou secret (l'occupation d'Oriane, que le PJ n'a pas rencontrée ; le vrai employeur d'un espion) s'exprime dans `gold_knowledge` comme `kind: fact` (§ 7.2).
- **`known` d'une entité** : `true` si le PJ connaît au moins un **nom** de l'entité (son `true_name`, ou un alias de genre `true_name`, `label`, `short`, `title`, `nickname`, `former_name` marqué `known: true`) ; `false` sinon. Une entité que le PJ ne connaît que par un descripteur (`true_name: null`, ou `true_name` inconnu) a donc `known: false`, **quel que soit son type** : la Kethari âgée, mais aussi « la salle au bout du couloir » dont aucun nom n'est connu, ou « la caisse » avant qu'on lise « conteneur 47 ». C'est ce qui rend une révélation possible (§ 5.1, question 4). Un lieu, une organisation ou un objet connu par son nom porte un alias `label` `known: true` et a `known: true`. Le `label` d'une entité sans nom connu est un descripteur, pas un nom (il ne compte ni pour EASY ni pour XTYPE). La validation refuse `known: true` sur une entité sans nom connu.
- Pour un titre : si le titre fait partie du nom d'usage complet (« Pater Ondrev » est le nom du PNJ), il est dans `true_name` ; la forme « le Pater » est un alias `title`.

### 3.2 Corrections par rapport à la base réelle

Pour une scène `real`, on part de l'export (`identity_corpus_export.py`) et on corrige :
- **doublons** : une seule entité ; le libellé du doublon devient un alias de l'entité gardée (« Cheffe de serre » → alias `descriptor` « la cheffe de serre » d'Oriane Mbeki-Larsson ; « Coopérative » → alias `short` de la Coopérative Agronomique d'Ombelle) ;
- **canoniques inventés** par l'ancien resolver (« Le Kethari de la cantine ») : supprimés, leurs mentions rattachées à la bonne entité (Tesk) ;
- **entités manquantes** à rôle avéré (Pervenche) : ajoutées ;
- **homonymes inter-types légitimes** (« Bureau des Résidences » lieu et organisation) : deux entités, deux ids.

### 3.3 Arcs

Un arc (`type: arc`) a pour `label` son titre ; ses éléments cachés (manipulateur, but réel) vont dans `gold_knowledge` (§ 7). Une mention d'arc est rare : « la disparition des sondeurs » quand un arc porte ce titre.

### 3.4 Scène courante (`scene`)

```yaml
scene:
  location: location_cantine_du_puits    # id du lieu courant ("" si inconnu)
  present: [protagonist_valentin, companion_pervenche, character_kethari_agee]
  reveals:                               # reveals émis par le narrateur pour ce tour, tels quels
    - {ref: La Kethari âgée, real_name: Nahle Irun-Sa}
  planned_npcs: []                       # ids des PNJ planifiés par le Director pour la scène
  secrets: []                            # ids des entités portant un élément secret (§ 7)
  open_disclosures: []                   # [{handle: <id>, kind: name|fact, condition: <texte>}]
```

`present` liste les entités physiquement présentes ou en communication directe (le compagnon, une voix au terminal). Tous les ids de `location`, `present`, `planned_npcs`, `secrets` et des `open_disclosures` doivent exister dans le `world`.

---

## 4. Les mentions

### 4.1 Ce qui est une mention

Une mention est un **groupe nominal** du texte qui désigne (ou pourrait être pris pour) une personne, un lieu, une organisation, un objet ou un arc. On annote :
1. **toute** référence à une entité du `world` (nom, nom partiel, titre, descripteur, périphrase) ;
2. **toute** entité nouvelle à rôle (§ 5.3) ;
3. les **pièges SKIP** de la liste fermée du § 5.2.

On n'annote **pas** :
- les **pronoms personnels** (je, tu, il, elle, on, nous, vous, ils, elles, me, te, se, le, la, les, lui, leur, eux, moi, toi, soi) : jamais une mention, ni liée ni SKIP ; la validation refuse une mention dont la surface est un pronom personnel. Écart documenté avec la spécification (§ 13). En revanche, les **pronoms indéfinis et démonstratifs** qu'un resolver pourrait lier ou dont il pourrait créer une entité sont annotés **SKIP** (§ 5.2, cas 6) ;
- les **groupes pluriels** qui désignent plusieurs entités du `world` à la fois (« les deux Kethari », « les Voss ») : non annotés, parce qu'aucune décision `MATCH` unique n'est juste. Des noms coordonnés sont annotés chacun (« Tesk et Nahle » → « Tesk », « Nahle ») ;
- les objets et lieux de **décor** sans lien avec une entité du `world` et hors des cas SKIP (« le comptoir », « les bols sales », « une flaque ») ;
- les noms communs non référentiels (« le reste », « les formulaires » au sens générique).

### 4.2 Frontières

- La mention **inclut le déterminant** : article, possessif, démonstratif (« la Kethari âgée », « sa paume », « ce Bureau des Résidences »). Sans déterminant dans le texte, la surface commence au nom (« Nahle Irun-Sa »).
- Elle inclut les compléments qui identifient (« le Kethari au tablier », « la voix basse sur ton terminal », « la femme grise à la tablette »), et s'arrête avant une relative ou une incise qui raconte (« le Kethari au tablier » dans « le Kethari au tablier, qui empile les bols »).
- Une préposition contractée (du, des, au, aux) reste hors de la surface, même si elle contient l'article : « du Bureau des Résidences » → « Bureau des Résidences » ; « au quai » → « quai » ; « cligne des yeux » → « yeux ». Une préposition non contractée aussi : « de mon ancien habitat » → « mon ancien habitat ».
- La majuscule de début de phrase est recopiée telle quelle (« Sa poche de tablier »).
- **Partie ou accessoire d'une possession** : quand tout le groupe est un cas SKIP (§ 5.2), une construction « le/la N de son/sa N' » forme **une seule** mention SKIP qui commence au premier déterminant : « la poignée de sa valise », « la poche de son tablier ». On ne découpe pas « sa valise » à l'intérieur. Si le complément désigne une entité liée, elle est annotée à l'intérieur (« le terminal du Kethari au tablier » : SKIP, et « Kethari au tablier » lié). Si le nom de tête est du décor et le complément une entité, seul le complément est annoté (« la porte de la coursive » → « la coursive »).
- **Imbrication** : une mention peut en contenir une autre qui désigne une **autre** entité (« la voix basse sur ton terminal » → compagnon, et à l'intérieur « ton terminal » → objet ; « le terminal du Kethari au tablier » → SKIP, et à l'intérieur « Kethari au tablier » → le gérant). On n'imbrique jamais un SKIP dans un SKIP (« la poche de son tablier » est une seule mention SKIP). Deux mentions qui se chevauchent sans être imbriquées sont interdites, et deux mentions ne commencent jamais au même caractère (une mention imbriquée qui commencerait au même endroit que l'englobante n'est pas annotée : on garde la plus longue).

### 4.3 Champs d'une mention or

```yaml
- surface: La Kethari âgée
  start: 0
  category: DESC                       # § 5
  expected: MATCH character_kethari_agee
  accept_also: []                      # équivalences légitimes, même syntaxe que expected
  trap: false                          # true seulement sur un NEW piège (§ 5.1, NEW)
  pov_error: false                     # true seulement sur le REVEAL d'une narration réelle fautive (§ 7.4)
```

`expected` prend l'une des cinq formes :

| Forme | Sens |
|---|---|
| `MATCH <id>` | la mention désigne l'entité `<id>` par un nom, un alias ou une description qu'il n'est pas nécessaire d'enregistrer comme alias |
| `ALIAS <id> <kind>` | la mention désigne `<id>` **et** apporte un alias nouveau de genre `<kind>` qui doit être enregistré (révélation de nom, forme courte d'un nom révélé, surnom, ancien nom) |
| `NEW <type>` | entité réellement nouvelle de type `character`, `location`, `organization` ou `object` (jamais `arc`, § 5.3) : **sa première mention** dans la narration |
| `SAME <start>` | mention suivante d'une entité **née dans le tour** : `<start>` est le `start` de sa mention `NEW`, plus tôt dans la même narration (§ 13, cas tranché a) |
| `SKIP` | à ne pas lier |

**`SAME <start>`.** Une entité absente du `world` n'a pas d'id or ; ses mentions suivantes dans le tour renvoient donc à sa mention `NEW`. Catégorie : celle de la nature de la surface, **EASY**, **PART** ou **DESC** (« Une Kethari âgée » … « La Kethari âgée » : DESC ; « Quai 9 » … « le Quai 9 » : EASY ; « la Guilde des Convoyeurs » … « Convoyeurs » : PART ; « Une médecin aux cheveux ras » … « Mirelle Faucon », le nom donné ensuite : EASY). Pas d'`accept_also`, pas de `trap` (le piège reste sur la mention `NEW`), jamais dans l'historique. Notation (`evals/identity/scorer.py`) : la mention `NEW` et ses répétitions `SAME` forment une **chaîne**, parcourue dans l'ordre du texte contre les décisions du système. La première mention de la chaîne où le système décide `NEW` est la **naissance** : chaque mention suivante est juste ssi elle est un `MATCH` ou un `ALIAS` (de tout genre) vers l'id donné à la naissance (`Decision.entity_id`) ; un lien ailleurs y est une fusion abusive, un second `NEW` un doublon, et une naissance sans id ne laisse rien à quoi lier (aucune décision n'est juste). Avant la naissance (le système a manqué le `NEW` en tête, et peut-être aux répétitions précédentes), une répétition est notée exactement comme un or `NEW <type de la tête>` : comptée dans le rappel du NEW, un lien y est une fusion abusive, et UNSURE y est juste si la tête est un piège. Ainsi « SKIP, NEW, MATCH » sur une tête et deux répétitions donne deux répétitions justes, et « SKIP, NEW, NEW » un doublon. Le type de la mention, pour la ventilation catégorie × type, est celui du `NEW` en tête. Dans une séquence, la répétition est dans le cluster de sa mention `NEW`.

Quand choisir `ALIAS` plutôt que `MATCH` : seulement pour une information **de nom** absente du `world` **ou inconnue du PJ** (`known: false`) avant le tour : vrai nom révélé (même s'il figure déjà comme alias `true_name` `known: false`, cas Tesk), forme courte de ce nom, surnom, ancien nom. Raison : la décision attendue du système est d'**enregistrer** que le PJ connaît désormais ce nom (alias `known: true`, révélation) ; un `MATCH` laisserait l'entité dans l'état inconnu, ce qui est précisément l'échec Kethari. Un nom que le PJ connaît déjà, répété, est un `MATCH <id>`. Une description nouvelle (« la cheffe de serre » pour Oriane) est un `MATCH <id>` avec `accept_also: [ALIAS <id> descriptor]` : le système peut, sans faute, l'enregistrer comme descripteur.

Les formes du tableau ci-dessus s'appliquent aussi aux noms nouveaux d'une entité **connue** (§ 13, cas tranché d) : le nouveau nom d'une organisation renommée est **PART** `ALIAS <id> label` ; un surnom tout neuf (objet, personnage, organisation) est **DESC** `ALIAS <id> nickname` ; une forme à mot-tête d'un nom révélé plus tôt dans le tour (« ce coffret » après « Coffret des Sept Clés », « la venelle » après « la Venelle des Muets ») est **PART** `ALIAS <id> short` avec `accept_also: [MATCH <id>]`, comme une forme courte de nom de personne.

`accept_also` ne sert qu'aux cas fixés par ces règles (descripteur nouveau, forme courte d'un nom révélé dans le tour, § 5.1). On ne l'utilise pas pour absoudre une hésitation : si l'on hésite entre deux entités, la scène est mal écrite ou le cas va au § 13.

### 4.4 Historique (`history`)

`history` contient les **K derniers messages assistant** avant le tour, contigus, du plus ancien au plus récent, chacun avec ses mentions. K = 6 pour les scènes exportées (moins en début de partie) ; une scène écrite à la main peut en garder moins, mais toujours les plus récents. Les mentions de l'historique suivent les mêmes règles de frontière et de catégorie, mais :
- elles sont exprimées dans le `world` de la scène : `expected` vaut `MATCH <id>` ou `SKIP` (les entités et alias existent déjà) ;
- elles ne sont **pas** notées ; elles représentent ce que le système a stocké, corrigé (les erreurs de l'époque, comme « sa paume » liée au gérant, y deviennent `SKIP`) ;
- leurs offsets sont vérifiés comme ceux de la narration.

Une scène synthétique peut avoir un historique vide ou court ; elle ne peut pas utiliser la catégorie GAP sans un historique qui montre l'absence de l'entité.

---

## 5. Catégories et ordre de décision

### 5.1 Ordre de décision

Pour chaque mention, appliquer les questions **dans cet ordre** ; la première réponse « oui » donne la catégorie.

1. **La mention doit-elle être liée ?** Non (cas du § 5.2) → **SKIP**, `expected: SKIP`.
2. Désigne-t-elle le **protagoniste** ou le **compagnon** ? → **PC**, `MATCH protagonist_…` / `MATCH companion_…` (« l'IA », « ARIA-7 », le nom du PJ, « la voix basse sur ton terminal »).
3. L'entité est-elle **absente du `world`** ? À sa **première** mention de la narration → **NEW**, `expected: NEW <type>` ; à ses mentions suivantes dans le même tour → `expected: SAME <start de la mention NEW>`, catégorie selon la surface (questions 7 à 9 : EASY, PART ou DESC, § 4.3). Si une entité du `world` du **même type** pourrait être prise pour elle (même titre ou même nom partiel, même espèce et même rôle, même descripteur), c'est un **NEW piège** : `trap: true`. Preuve exigée dans le texte : la nouvelle entité **parle à** l'entité existante ou agit en même temps qu'elle dans la scène (`talks_to`), **ou** elle se trouve dans un **autre lieu** que celui de l'entité existante. Sans cette preuve, on ne peut pas affirmer que c'est une autre personne : on n'écrit pas la scène ainsi.
4. La mention **révèle-t-elle un nom** que le PJ ne connaissait pas (entité `known: false`) ? → **REVEAL**, `expected: ALIAS <id> true_name`. Cas : auto-présentation d'une entité présente (« Je m'appelle Nahle », « — Nahle Irun-Sa, dit-elle »), un tiers qui la nomme devant le PJ, une source du monde (badge, écriteau, document, terminal) qui donne le nom d'un PNJ, d'un lieu, d'une organisation ou d'un objet connus jusque-là par un descripteur, ou, dans une narration réelle seulement, la voix narrative qui le donne à tort (§ 7.4). Est REVEAL la **première occurrence du nom révélé dans le tour, quelle que soit sa forme** (« Nahle » seul dans « Je m'appelle Nahle ») ; le genre est toujours `true_name` (c'est le nom que le texte donne ; le `real_name` de `gold_effects.reveals` le recopie). Une mention REVEAL a toujours une entrée `gold_effects.reveals` pour cette entité (§ 6). Le nom révélé peut être absent du `world` (`true_name: null`, cas Kethari) ou y figurer comme alias `known: false` (cas Tesk).
5. La surface (normalisée : casse, accents, déterminant de tête) est-elle un **nom** porté par **au moins deux entités du `world`** ? → **XTYPE**. Un nom, ici, c'est le `label` (pour un personnage, seulement s'il est son vrai nom), le `true_name` ou un alias de genre `true_name`, `label`, `short`, `title`, `nickname`, `former_name` ; jamais un descripteur (deux gardes « le garde » relèvent de DESC ou du NEW piège). Exemples : « Bureau des Résidences » (lieu et organisation) ; « Voss » (alias `short` de Rizka Voss et d'Elara Voss). « Rizka Voss » en entier n'est porté que par une entité : pas XTYPE. `expected` désigne celle que le contexte impose (le lieu si l'on y entre, l'organisation si elle agit ou décide).
6. L'entité est-elle **absente de toutes les mentions de l'`history`**, avec `turn` renseigné, `last_seen_turn` renseigné et `last_seen_turn ≤ turn − 5`, **et n'a-t-elle pas été réintroduite plus tôt dans la narration par une mention REVEAL** ? → **GAP** (« Voss t'attend au labo » au tour 21, vue au tour 3). GAP passe **avant** DESC, PART et EASY exprès : un descripteur, un nom partiel ou un nom complet après un long silence mesurent tous l'horizon du blocage. `last_seen_turn: null` (jamais vue) n'est jamais GAP. Une fois l'entité réintroduite dans le tour par un REVEAL, ses mentions suivantes ne mesurent plus l'horizon : elles suivent la règle des formes d'un nom révélé (« — Tesk Vahrun-Oo, dit-il. Tesk suffit. » vu au tour 3 et narré au tour 21 : REVEAL puis **PART** `ALIAS … short`, jamais GAP).
7. La surface **décrit**-elle l'entité sans employer son nom ? → **DESC**. Pour un personnage (ou le PJ, le compagnon : mais la question 2 les a déjà pris), tout ce qui n'est **ni son vrai nom, ni une partie de ce nom, ni un alias enregistré de genre `title`, `nickname` ou `former_name`** est une description, y compris son propre descripteur enregistré (« la Kethari âgée », « le Kethari au tablier », « la cheffe de serre ») et son métier (« le gérant » : une occupation n'est pas un alias de nom). Pour un lieu, une organisation, un objet : une désignation qui n'emploie aucun mot de son `label` ni de son `true_name` (« la salle au bout du couloir », « l'administration »).
8. Sinon, la surface est-elle une **variante** du nom ou du libellé, et non sa forme exacte ? → **PART** : nom partiel (« Ondrev », « Nahle »), alias `title`/`nickname`/`former_name` (« le Pater », alias `title` de Pater Ondrev), mot-tête du libellé avec un autre mot ou sans ses compléments (« ton terminal » pour Terminal personnel, « la Coopérative » pour Coopérative Agronomique d'Ombelle), casse, accent, ponctuation, faute (« Eloise »/« Éloïse », « Quai n°9 »/« Quai 9 »), mots ajoutés ou retirés.
9. Sinon → **EASY** : la surface est, à un déterminant de tête près, **exactement** (casse et accents compris) le vrai nom d'un personnage, ou le `label`/`true_name` d'un lieu, d'une organisation, d'un objet ; que l'entité figure ou non dans l'`history` (« Résidence Les Fougères » jamais vue, `last_seen_turn: null` : EASY).

Les questions 7, 8 et 9 forment une **partition** des mentions liées restantes (description / variante / forme exacte) : toute mention reçoit exactement une catégorie. La frontière DESC/PART reste un jugement humain ; les autres catégories sont vérifiées par le code (§ 14).

Formes d'un nom révélé dans le même tour : la première occurrence est REVEAL ; une forme courte qui suit (« Nahle suffit ») est **PART** avec `expected: ALIAS <id> short` et `accept_also: [MATCH <id>]` (les formes courtes sont dérivées automatiquement du vrai nom) ; une répétition de la forme complète est **EASY** avec `expected: ALIAS <id> true_name`.

### 5.2 Quand une mention est SKIP (liste fermée)

On annote en SKIP, et seulement dans ces cas :
1. **Partie du corps, vêtement, possession ou lieu d'origine** d'une entité du `world` : « sa paume », « sa mâchoire », « les doigts » (de la Kethari), « sa poche de tablier », « sa valise » (celle de la Kethari), « ton bol », « mon ancien habitat ». Exception : une possession qui est **elle-même une entité du `world`** est liée, que le possesseur soit le PJ ou un PNJ (« ton terminal » → `object_terminal_personnel` ; « son conteneur 47 » → l'objet conteneur 47).
2. **Foule ou groupe générique** : « les clients », « trois clients », « des gardes », « les anciens ».
3. **Descripteur indéfini sans rôle** : « un type », « une passante », « un client » quand la personne ne fait rien d'autre que d'être là. Dès qu'elle parle, agit sur l'intrigue, est décrite pour être retrouvée ou revient plus tard, ce n'est plus SKIP (NEW ou DESC selon le `world`).
4. **Objet vu mais non acquis**, quand il partage un mot-tête avec une entité du `world` ou qu'il est l'objet d'une action passagère : « un couteau sur la table », « son terminal » (celui du gérant, pas celui du PJ).
5. **Faux ami d'une entité** : groupe nominal qui reprend un mot distinctif d'une entité sans la désigner (« une serre » quelconque quand le `world` contient la Serre Numéro Quatre et que le texte parle d'une autre).
6. **Pronom indéfini ou démonstratif** (liste fermée) : « quelqu'un », « quiconque », « personne » (pronom, sans déterminant), « l'un », « l'une », « l'autre », « les autres » (pronoms, sans nom qui suit), « chacun », « chacune », « celui-ci », « celle-ci », « ceux-ci », « celles-ci », « celui-là », « celle-là », « ceux-là », « celles-là ». Toujours SKIP, même quand le contexte permet de deviner la personne (« Il y a quelqu'un devant toi » désigne le gérant : SKIP quand même ; un pronom n'est jamais lié). La validation impose SKIP sur ces surfaces et vérifie que chaque occurrence des formes non ambiguës (« quelqu'un », « quiconque », « celui-ci »… « celles-là ») est annotée ; pour « personne », « l'autre », « chacun », qui peuvent être un nom ou un déterminant, c'est l'annotateur qui juge.

Tout autre groupe nominal non lié n'est pas annoté (§ 4.1). Une mention SKIP a toujours `category: SKIP` et `expected: SKIP` ; la validation refuse une catégorie dure sur un or SKIP, et SKIP sur un or lié.

### 5.3 Rôle d'une entité (création)

Une entité nouvelle n'est un `NEW` que si elle a un **rôle** :
- **personnage** : nommé, ou qui parle, agit sur l'intrigue, est décrit pour être retrouvé, ou dont le texte annonce le retour ;
- **lieu** : nommé, ou dans lequel on entre, vers lequel on se dirige, qu'on donne comme repère réutilisable (« le panneau du hall » ne l'est pas ; « la salle des pompes » où l'on doit aller l'est) ;
- **organisation** : nommée, ou qui agit (emploie, décide, poursuit) ;
- **objet** : nommé ou identifié (« le conteneur 47 », « le lot 2851-09 »), **acquis** par le PJ, ou au centre d'une action durable (donné, volé, cherché). Un objet seulement vu ou utilisé en passant n'est pas une entité : SKIP s'il entre dans le § 5.2, sinon non annoté ;
- **arc** : jamais créé par une mention.

### 5.4 Récapitulatif

| Code | Dure ? | `expected` habituel | Exemple |
|---|---|---|---|
| EASY | non | `MATCH <id>` | « Pater Ondrev » (son vrai nom), « la Serre Numéro Quatre » |
| PART | oui | `MATCH <id>` | « la Coopérative », « Ondrev », « le Pater » (alias `title`), « ton terminal » |
| DESC | oui | `MATCH <id>` | « la Kethari âgée », « le gérant », « la cheffe de serre » → Oriane |
| GAP | oui | `MATCH <id>` | « Voss » au tour 21, vue au tour 3 |
| REVEAL | oui | `ALIAS <id> true_name` | « Nahle Irun-Sa » dit par la Kethari âgée |
| NEW | oui | `NEW <type>` (+ `trap: true`) | une seconde Kethari qui parle à la première |
| XTYPE | oui | `MATCH <id>` | « Bureau des Résidences » (lieu ou organisation) |
| SKIP | non | `SKIP` | « sa paume » |
| PC | non | `MATCH protagonist_…` / `companion_…` | « la voix basse sur ton terminal » |

---

## 6. Effets attendus (`gold_effects`)

```yaml
gold_effects:
  reveals:            # une entrée par entité dont le nom est révélé dans le tour
    - {ref: character_kethari_agee, real_name: Nahle Irun-Sa}
  merges: []          # [{keep: <id>, drop: <id>}] : deux entités du world qui s'avèrent la même
  forbidden_merges:   # [{a: <id>, b: <id>}] : paires proches qu'aucun effet du tour ne doit fusionner
    - {a: character_kethari_agee, b: character_tesk_vahrun_oo}
```

- Toute mention REVEAL exige une entrée `reveals` avec le même id (la validation le vérifie). `real_name` est le nom tel que la narration le donne.
- `merges` : seulement quand le texte établit que deux entités du `world` sont la même (« la cheffe de serre, c'est Oriane »). `keep` est la plus ancienne.
- `forbidden_merges` : les paires d'entités du `world` toutes deux mentionnées dans le tour et qu'une fusion abusive pourrait réunir (deux Kethari dans la même scène, Rizka Voss et Elara Voss). Le cas d'une entité nouvelle proche d'une entité existante est couvert par `trap: true` sur la mention NEW, pas par `forbidden_merges` (la nouvelle entité n'a pas d'id).
- Tous les ids de `gold_effects` existent dans le `world`.

---

## 7. Connaissance : `known`, `secret`, `gold_knowledge`

### 7.1 Les trois états

Chaque élément (nom ou fait, de toute entité) est dans un et un seul état :

| État | Drapeaux | Sens |
|---|---|---|
| **1. connu** | `known: true` | le PJ le sait ; la narration peut le dire librement |
| **2. inconnu ordinaire** | `known: false`, `secret: false` | le PJ ne le sait pas encore, rien n'empêche qu'il l'apprenne ; le narrateur le voit marqué « inconnu du PJ » |
| **3. secret** | `secret: true` (et `known: false`) | gardé par le Director ; le narrateur ne le voit pas tant qu'aucune divulgation n'est ouverte |

**Inconnu n'est pas secret.** Par défaut, tout ce que le PJ ignore est **inconnu ordinaire**. On ne marque `secret` que ce que la génération du monde ou le Director marque comme tel, ou, pour une scène synthétique, ce dont la révélation prématurée ferait tomber un arc : la vraie identité d'un espion, la pièce dissimulée d'un lieu, la vraie nature d'une organisation-écran, le contenu réel d'un conteneur, le manipulateur d'un arc. Le nom d'un gérant de cantine qu'on n'a pas encore demandé est ordinaire. Dans une scène `real`, on ne marque secret que ce que la base marquait secret (f134 et 9f55 n'en ont pas) : on ne fabrique pas de secret dans une scène réelle.

Drapeaux dans le `world` :
- nom inconnu ordinaire : alias `true_name` (et `short`) `known: false`, entité `known: false` ;
- nom secret : alias `true_name` (et `short`) `known: false, secret: true` ;
- entité entièrement secrète (pièce dissimulée, organisation que personne ne connaît) : `secret: true` sur l'entité et sur son alias `label` ;
- toute entité portant un élément secret figure dans `scene.secrets`.

### 7.2 `gold_knowledge`

`gold_knowledge` liste **tous** les éléments d'états 2 et 3 portés par les entités du `world` :

```yaml
gold_knowledge:
  - {ref: character_tesk_vahrun_oo, kind: name, state: unknown, text: Tesk Vahrun-Oo}
  - {ref: organization_cooperative_x, kind: fact, state: secret, text: La coopérative finance la milice du Puits.}
```

- `ref` : id d'une entité du `world`.
- `kind: name` : `text` est le nom inconnu, recopié exactement depuis le `true_name` ou un alias `known: false` de l'entité ; **exactement une** entrée par nom (les formes courtes sont impliquées). Sont obligatoires : le `true_name` de toute entité `known: false`, et tout alias `true_name` ou `label` `known: false` (le `label` secret d'une entité secrète). `state` doit correspondre au drapeau `secret` de cet alias (ou de l'entité). La validation vérifie l'exhaustivité, l'unicité et l'état.
- `kind: fact` : `text` est une phrase autonome qui énonce le fait (un attribut comme l'occupation, une relation, le contenu d'un objet, le but d'un arc). L'or ne contient que des faits que la fiction établit (base réelle, scénario de l'issue, ou scène synthétique écrite pour cela). L'exhaustivité des faits **ne peut pas** être vérifiée par le code (le `world` ne porte pas d'état sur ses attributs) : c'est à l'annotateur de lister tout attribut ou fait inconnu du PJ qu'il connaît.
- Un élément révélé **dans** le tour reste listé avec son état d'avant le tour, **si le nom figure dans le `world`** (cas Tesk) : le contrôle de révélation `R` le retrouve par `gold_effects.reveals`. Un nom absent du `world` (cas Kethari, `true_name: null`) n'a pas d'entrée.

### 7.3 Point de vue, révélation diégétique, fuite

Ces définitions servent aux juges `P`, `R`, `L` (§ 3.4 bis de la spécification) et à l'écriture des scènes synthétiques.

- **Voix narrative** : tout le texte hors dialogue et hors source diégétique. Les répliques (après un tiret de dialogue ou entre guillemets), les textes lus par le PJ (badge, écriteau, document, écran) et les messages du compagnon (en italique dans les parties réelles : *…*) n'en font pas partie.
- **Erreur de point de vue (`P`)** : un élément **inconnu du PJ** (état 2 ou 3, nom ou fait) apparaît dans la **voix narrative**. Exemple : « Tesk empile les bols » alors que le PJ ne connaît que « le Kethari au tablier ». Ce n'est **pas** une erreur : le même nom dans une réplique (« — Tesk, ferme la plonge ! » lancé par un client) ou sur un badge que le PJ lit ; le descripteur dans la voix narrative ; le nom dans la voix narrative **après** sa révélation diégétique plus tôt dans le même texte.
- **Révélation diégétique (`R`)** : un élément inconnu fait surface **dans la fiction** (réplique, présentation, badge, écriteau, document, terminal), **naturellement** (le PJ l'a demandé, la personne se présente, la logique de la scène l'amène), **et** il est enregistré sur la bonne entité ou le bon fait. Exemple : « Comment vous appelez-vous ? » → « — Nahle Irun-Sa, dit-elle. » Un secret n'est une révélation correcte que si une divulgation était ouverte (`scene.open_disclosures`).
- **Fuite (`L`)** : un élément **secret** sans divulgation ouverte apparaît sous **quelque forme que ce soit** (voix narrative, dialogue, document, champ joueur, prompt narrateur). Doit être 0.

Une scène **synthétique** ou **issue** qui teste `P` contient l'élément inconnu dans le `world` et dans `gold_knowledge`, et sa `narration` est **correcte** (descripteur dans la voix narrative ; le nom seulement en dialogue ou par une source) : on n'écrit pas de fautes. Les narrations fautives sont produites par l'évaluation live et jugées avec la grille `POV_GRID.md`. Les narrations **réelles**, elles, ne sont pas corrigées (§ 7.4).

### 7.4 Narration réelle qui nomme un inconnu dans la voix narrative

Une scène `real` reprend le texte tel que le joueur l'a lu ; elle peut contenir une erreur de point de vue (le narrateur écrit « Tesk empile les bols » alors que le PJ ne connaît que « le Kethari au tablier »). Règle, cohérente avec la spécification (§ 4.8, `reveal_implicit` : un nom ordinaire lu par le joueur est enregistré comme révélé ; § 3.4 bis : le juge `P` dit s'il est apparu à tort) :
- la **première** occurrence du nom inconnu dans la voix narrative est **REVEAL**, `expected: ALIAS <id> true_name`, avec une entrée `gold_effects.reveals` (le joueur l'a lu : l'état doit devenir connu) et **`pov_error: true`** ;
- les occurrences suivantes du tour suivent la règle des formes d'un nom révélé (§ 5.1) ;
- le `gold_knowledge` garde le nom avec son état d'avant le tour ; le texte n'est pas corrigé.

`pov_error: true` n'est permis que sur une mention REVEAL de la narration d'une scène `real` (la validation le vérifie). Les scènes ainsi marquées servent d'or positif au juge `P` : il doit y signaler une erreur. Un nom **secret** donné ainsi serait en plus une fuite (`L`) ; f134 et 9f55 n'ont pas de secret, et un tel cas irait au § 13. Un **fait** inconnu énoncé dans la voix narrative n'est pas une mention : on le consigne au § 13 avec l'id de la scène.

---

## 8. Couverture visée

- **≥ 50 mentions par catégorie dure** (PART, DESC, GAP, REVEAL, NEW, XTYPE), ≥ 100 EASY, ≥ 60 SKIP, ≥ 30 PC, comptées sur les mentions or des narrations des **scènes** (les seules que notent les métriques par catégorie ; les séquences ne servent qu'à B³ et CEAF-e). Une mention `SAME` compte dans la catégorie de sa surface, avec le type de sa mention NEW.
- **Ventilation catégorie × type** : pour chaque catégorie dure, aucun des types `character`, `location`, `organization`, `object` ne pèse moins de **15 %** des mentions de la catégorie. Les lieux et organisations sont les oubliés des audits : on écrit d'abord les scènes qui les couvrent.
- **≥ 2 genres** (`sf` et `dark_fantasy` au minimum) pour ne pas sur-apprendre l'univers Ombelle.
- `gold_knowledge` couvre un élément inconnu ordinaire **et** un élément secret pour chacun des types `character`, `location`, `organization`, `object`, `arc`.
- Scènes obligatoires : les 6 cas de l'audit de données (Kethari/Nahle, Cheffe de serre/Oriane, Coopérative, Bureau des Résidences, Pervenche, Tesk et ses deux canoniques), `issue-25-voss`, `issue-26-gap21`, `roadmap-rizka-elara`.

---

## 9. Séquences (`sequences/<id>.yaml`)

Une séquence enchaîne 5 à 10 tours : `id`, `turns` (liste de scènes complètes au format ci-dessus ; le `world` du tour n+1 inclut les effets or du tour n) et `gold_clusters` :

```yaml
gold_clusters:
  character_kethari_agee: [seq-f134-a-t1:0, seq-f134-a-t2:0, seq-f134-a-t3:83]
```

Une clé de `gold_clusters` est un id d'entité (du `world` final, ou un id choisi pour une entité née dans la séquence) ; chaque valeur liste les mentions or de cette entité sous la forme `<id de scène du tour>:<start>`. Chaque mention liée (non SKIP) de la séquence apparaît dans exactement un cluster ; une mention `MATCH`/`ALIAS` est dans le cluster de son id `expected` ; une mention `NEW` est dans le cluster de l'id choisi pour l'entité née (celui que le `world` des tours suivants lui donne). Les ids de scène des tours sont uniques dans la séquence et dans tout le corpus (scènes comprises).

---

## 10. Scènes synthétiques

- Français soigné, au présent, deuxième personne, comme le narrateur du jeu (dialogues au tiret cadratin, compagnon en italique).
- Une scène vise **une** catégorie dure et **un** type en priorité, mais toutes ses mentions sont annotées selon ces règles.
- Les noms du corpus ne sont jamais repris dans les exemples ou les règles du prompt du resolver, et les exemples du prompt ne viennent jamais du split test.
- Un NEW piège met en scène la preuve exigée (§ 5.1, question 3).

---

## 11. Procédure d'annotation d'une scène

1. Lire le `world` (et le corriger, § 3.2) puis l'`history`.
2. Lire la `narration` une fois en entier.
3. Repérer les groupes nominaux candidats (§ 4.1), fixer leurs frontières (§ 4.2).
4. Pour chacun, appliquer l'ordre de décision (§ 5.1), écrire `expected`, `accept_also` éventuel, `trap` éventuel.
5. Écrire `gold_effects` et `gold_knowledge`.
6. Lancer `scripts/test-backend.sh tests/identity/test_corpus.py` : 0 erreur.

---

## 12. Relecture et gel

L'export « surfaces seules » de la relecture à l'aveugle s'écrit dans `fixtures/identity/surfaces-only/`, ignoré par git (fichiers dérivés). Le split dev 60 % / test 40 % est produit par `scripts/identity_corpus_split.py` **par campagne** (`campaign`) : l'historique d'une scène porte les narrations précédentes de sa campagne avec leurs liens relus, donc couper une campagne montrerait l'or du test côté dev. Le script répartit des campagnes entières de façon que chaque catégorie ait 35 à 45 % de ses mentions en test (recherche gloutonne puis améliorations par déplacement et échange, depuis plusieurs ordres tirés avec la graine) ; un test vérifie qu'aucune narration d'un côté n'apparaît dans un historique (ou une narration) de l'autre, ni dans une séquence pour le test ; le test est annoté avant tout réglage de prompt et gelé par `TEST_SHA256`. Toute correction d'or du test impose une PR qui l'explique. Le compte rendu de la seconde annotation à l'aveugle du split test (taux de désaccord, corrections) est ajouté ci-dessous dans une section « Relecture du <date> ».

### Relecture à l'aveugle du 2026-10-19

Seconde annotation du split test **d'avant le regroupement par campagne** (42 scènes, 610 mentions) par un agent indépendant qui n'avait lu que ce document et `_example.yaml`, sans voir l'or ; comparaison faite une seule fois, après sa propre validation.

| Mesure | Accord |
|---|---|
| `expected` exact | 605/610 = 99,2 % |
| catégorie | 604/610 = 99,0 % (κ de Cohen = 0,988) |
| catégories dures (411 mentions) | 99,8 % `expected`, 99,5 % catégorie |
| SKIP (117) | 96,6 % |
| `trap` | 608/610 |
| noms de `gold_knowledge`, `gold_effects.reveals` | 100 % |

Sur les 8 désaccords, deux étaient des erreurs de l'or, corrigées : « Ton papier » (lien, et non SKIP) et le piège manquant sur « Une femme en blouse blanche ». Deux restaient ouverts et sont tranchés au § 13 : le piège des « Fondeurs Unis » (retiré : pas d'ancrage enregistré) et « deux silhouettes en manteau vert » (SKIP : groupe compté). Les autres suivaient déjà l'or, mais ont montré des trous du guide, comblés au § 13 : membres d'une organisation au pluriel, signalétique, base d'un piège, libellés à trait d'union.

**Ce que ces chiffres ne disent pas.**
- **Les spans étaient fournis.** La détection et les frontières des mentions (§ 4.1, § 4.2) ne sont **pas mesurées**, et la présence d'un span renseigne sur sa décision (un span sur « Les lampions » annonce un SKIP plutôt qu'une absence). Les 99 % sont un plafond de reproductibilité des étiquettes à spans donnés, pas une mesure de tout l'or.
- **Le second annotateur est un agent LLM**, probablement proche de celui qui a écrit l'or : leurs erreurs sont corrélées. Ce n'est pas un plafond d'accord humain (§ 1).
- **Deux scènes recoupaient l'exemple** : les narrations de `real-f134-t12` et `-t13` sont des messages d'historique de `_example.yaml`, que l'annotateur pouvait lire avec leurs étiquettes. Sans elles : 99,1 % / 99,0 %.
- La validation mécanique, lancée avant la comparaison, fait une partie du travail (GAP, XTYPE, EASY, REVEAL sont imposés par le code) et gonfle l'accord sur ces catégories ; les désaccords tombent tous sur des jugements (DESC/PART, lien ou SKIP, piège).
- La mesure porte sur l'ancien split ; le split par campagne qui l'a suivi a déplacé des scènes de dev en test, qui n'ont pas eu de seconde annotation.

---

## 13. Cas tranchés

- **f134, tour 15 — « sa paume »** (`_example.yaml`, historique) : l'ancien resolver liait « sa paume », « sa mâchoire » et « son terminal » au gérant. Ce sont une partie du corps et une possession : SKIP (§ 5.2, cas 1 et 4).
- **f134 — « la Kethari âgée »** : PNJ sans vrai nom, connu par son seul descripteur ; DESC, même quand la surface est exactement son descripteur enregistré (§ 5.1, question 7). « Nahle Irun-Sa » au tour 15 : REVEAL ; « Nahle » juste après : PART, `ALIAS … short`.
- **f134 — « sa valise »** quand le PJ possède la Valise souple : désigne la valise de la Kethari, SKIP (§ 5.2, cas 1) ; « ta valise » désignerait l'objet d'inventaire (PART). **« la poignée de sa valise »** (tours 13 et 15) : une seule mention SKIP depuis « la » (§ 4.2, partie d'une possession), comme « la poche de son tablier » ; on ne découpe pas « sa valise ».
- **f134 — la voix du terminal** (« la voix basse sur ton terminal », « ta compagne ») : le compagnon Pervenche, PC.
- **Pronoms : écart documenté avec la spécification § 3.2** (décision du contrôleur, 2026-10-19 ; à faire valider par l'utilisateur dans la PR). La ligne SKIP de la spécification cite les pronoms. Les **pronoms personnels** ne sont pas annotés : chaque mesure du § 3.4 est calculée par mention or, donc un pronom non annoté n'est pas mal noté, il n'est simplement pas compté ; annoter chaque « il / elle » gonflerait la réserve EASY+PC+SKIP (≥ 0,97) de réussites triviales et masquerait les vrais SKIP. Le risque visé par la spécification (un resolver qui lie ou crée une entité à partir d'un pronom) est couvert par le **compromis** : les pronoms indéfinis et démonstratifs (« quelqu'un », « l'autre », « celui-ci »…, § 5.2, cas 6) sont annotés SKIP. Dans `_example.yaml` : « quelqu'un » (tours 11, 13, 15) et « Personne » (tours 12 et 14) sont SKIP.
- **Révélation d'une entité vue il y a longtemps** : REVEAL d'abord, puis PART pour la forme courte, jamais GAP après le REVEAL (§ 5.1, question 6).
- **Lieu sans nom connu** (« la salle au bout du couloir ») : `known: false`, label = descripteur ; un badge « Salle des Pompes » est un REVEAL valide (§ 3.1).

Cas tranchés par le contrôleur à la consolidation du corpus (2026-10-19) ; chacun est appliqué à tout le corpus, et ceux qui sont mécaniques sont vérifiés (§ 14).

- **(a) Entité née dans le tour, mentionnée plusieurs fois.** Sa **première** mention de la narration est `NEW <type>` ; les suivantes sont `SAME <start de la mention NEW>`, catégorie EASY, PART ou DESC selon la surface (§ 4.3). Les annotateurs avaient marqué chaque répétition NEW (f134 t1 « La Kethari âgée » ; 9f55 « mon fils », « Le mécanicien », « la rampe » ; les scènes `syn-sf-new-*`, `audit-*`, `issue-25-voss`, `roadmap-rizka-elara-arrivee` et les séquences) ou les avaient évitées par l'écriture (`syn-df-*`) : 33 répétitions converties, plus 3 appositions ajoutées (cas e). Quand la première mention est un descripteur et que le nom vient ensuite (« Une jeune femme en combinaison de plongée » … « Mila Voss »), le nom est un `SAME` EASY ; le piège (`trap: true`) reste sur la mention NEW s'il y en avait un, et une fusion avec l'homonyme du `world` reste notée fausse (fusion abusive).
- **(b) Lieu, organisation ou objet sans nom connu du PJ** (`known: false`) : toute désignation est **DESC**, y compris le mot-tête de son descripteur (« le cylindre », « la boîte », « la rampe »), même quand elle partage un mot avec un nom caché ; PART n'est possible qu'après un REVEAL de l'entité plus tôt dans le tour. Vérifié pour les personnages et les choses (pas pour les arcs, dont le libellé est un titre : « MIGRATION » sur la borne de f134 reste PART).
- **(c) L'or n'exige jamais la connaissance d'un secret non divulgué dans la scène.** Une mention qu'on ne peut lier qu'en connaissant un élément `secret` sans `open_disclosures` est **SKIP**. `seq-sf-identite-secrete` tour 2 : « un déserteur de la flotte » (le mécanicien n'est déserteur que dans son secret) passe de DESC à SKIP, dans la narration et dans l'historique du tour 3, et sort du cluster. Revue des autres mentions liées à une entité porteuse d'un secret : aucune autre ne dépend du secret (les descripteurs vus par le PJ, « l'homme au tablier de cuir », restent liés).
- **(d) Noms nouveaux d'une entité connue** : nouveau nom d'une organisation renommée = **PART** `ALIAS <id> label` (« les Passeurs Libres de Vharn ») ; surnom tout neuf = **DESC** `ALIAS <id> nickname` (« la Bouilloire », « la Rouge », « Les Cendrés » ; « la Rouge » était PART) ; forme à mot-tête d'un nom révélé dans le tour = **PART** `ALIAS <id> short` + `accept_also: [MATCH <id>]` (« la venelle », « ce coffret », « le conteneur », « l'entrepôt », « la Flotte », « cette maison » étaient `MATCH`). Exception : un surnom du compagnon reste PC (question 2).
- **(e) Attributs et appositions** : un groupe nominal attribut (« Le Baron est **mon oncle** », « Le Hall d'Arrivée Quai Sud est **une longue boîte de métal gris** », « Ce sont **les loyalistes** ») ou en apposition (« Basile Krantz, **le recruteur des Convoyeurs** », « l'Albatros-7, **le vaisseau jumeau** ») qui désigne une entité est annoté **DESC** (ou `SAME` DESC si l'entité est née dans le tour), sauf si une question antérieure de l'ordre du § 5.1 le prend (PC, REVEAL, XTYPE, GAP : « L'autre, c'est la toubib du troisième niveau » reste GAP dans `issue-26-gap21`).
- **Frontière DESC / PART**, alignée sur tout le corpus : un mot-tête du libellé connu avec d'autres mots est PART (« le grand couperet à lame noire » pour Couperet de Saint Varon, « La guilde loyaliste », « Les gens du Lys » pour l'Ordre du Lys, membres désignés par un mot du libellé) ; un alias `title` enregistré seul, à la casse près, est PART (« Le cellérier » pour l'alias `title` « le Cellérier ») ; un titre nu quand l'alias enregistré est titre + nom (« la capitaine » pour « la capitaine Ostrowska », « le sergent ») est une occupation : DESC.
- **SKIP ou non annoté** : partie du corps, vêtement et possession concrète d'une entité du `world` (y compris du PJ) sont SKIP (« ses dents », « ton casque », « sa sacoche », « son flanc » de la caisse) : 45 mentions ajoutées là où certains annotateurs les avaient laissées. Restent non annotés les abstraits (« son nom », « sa voix », « ta prise de poste », « sa façon de compter ») et le décor.
- **NEW piège** : `trap: true` sur la mention NEW d'une entité qu'une entité du `world` du même type pourrait capter. Le piège se juge sur **l'entité**, c'est-à-dire sur toutes ses mentions du tour (un descripteur en tête puis un nom : « Une femme en blouse blanche » … « Elara Voss » face à Rizka Voss est un piège, porté par la mention NEW en tête), et il lui faut un **ancrage enregistré dans le `world`** : un mot de nom partagé, un mot d'un descripteur ou d'un titre enregistré, ou (personnages) la même occupation enregistrée. Une simple parenté de sens que le `world` n'enregistre pas (« les Fondeurs Unis » face à La Forge) ne suffit pas : pas de piège. Appliqué : piège ajouté à « la Chapelle de Brumecourt », au second jeton (`seq-df-renommage` t3), à « l'Infirmerie de la Méridienne », et rétabli sur les têtes des homonymes Voss et Morvaine (`issue-25-voss` 116, `roadmap-rizka-elara-arrivee` 85, `seq-df-homonymes` t2 66) ; retiré des « Fondeurs Unis de l'Anneau C » (`syn-sf-new-01`) ; gardé sur « Brecht » (brassard de contremaître, ancré dans le descripteur « la contremaîtresse au casque rayé »). Jamais sur une mention `SAME`.
- **Nom complet répété après un REVEAL du même tour** : le nom est désormais connu ; la répétition (EASY `ALIAS <id> true_name`) accepte aussi `MATCH <id>` (`accept_also`), comme une forme courte. 16 mentions corrigées (revue I4) ; vérifié par le code.
- **Membres d'une organisation au pluriel** : le groupe est lié à l'organisation (PART s'il emploie un mot du libellé, « les Lanterniers », « Les gens du Lys » ; DESC sinon, « les loyalistes ») seulement quand il **tient lieu de l'organisation** dans l'intrigue (il décide, emploie, poursuit, possède, on parle de lui comme du corps) ; un groupe de membres compté, indéfini ou qui réagit seulement comme une foule présente (« deux silhouettes en manteau vert », « des gardes », « Les passeurs se lèvent en grondant », « les maîtres de la guilde dorment ») est SKIP (§ 5.2, cas 2). Revue du corpus : aucun groupe indéfini ou compté n'était lié ; aucun changement.
- **Signalétique** : un mot de direction d'un panneau ou d'une flèche qui ne reproduit pas exactement le nom d'une entité (« Résidences », « Serres 1-6 ») est SKIP (faux ami, § 5.2 cas 5) ; un panneau qui porte le nom exact d'une entité est lié (« Cantine du Puits » : EASY).
- **Libellés à trait d'union** : pour les questions 7 et 8, les composants d'un libellé à trait d'union comptent comme des mots (« ce port » pour Port-Cendre : PART).
- **Possession qui est une entité** : « Ton papier » (`audit-org-nom-court` 812), dit de la lettre de change du PJ, est lié (DESC → `object_lettre_de_change`, § 5.2 cas 1, exception) ; la consolidation l'avait marqué SKIP à tort (relecture à l'aveugle).
- **Compagnon** : toute désignation du compagnon (nom, descripteur, appareil qui parle : « ta chouette », « l'IA de la base ») est PC ; l'appareil seul, sans la voix (« ton oreillette », « ton casque »), est une possession : SKIP.
- **9f55, tour 1** : « La balise quarante » (« on la passe ce soir ou demain ? ») est un repère de route que la cité-chenille franchit : NEW **location** (et non object) ; « mon fils » et « Le mécanicien » sont des `SAME` DESC du « jeune mécanicien » ; « Le vaisseau » dans la bouche de l'oracle désigne Vergence : DESC. « l'arrière » (« rentrée par l'arrière ») reste non annoté (locution adverbiale). « la baie de proue », où se tient Pater Ondrev, est un repère réutilisable dans la Proue : NEW location (revue M7).

---

## 14. Contrôles mécaniques (`validate_scene`, `validate_sequence`)

La CI refuse une scène qui enfreint l'une de ces règles ; chacune a son test dans `tests/identity/test_corpus.py`.

- **Forme** (au chargement) : clé inconnue n'importe où (y compris dans `gold_effects`, `scene.reveals`, `open_disclosures`) ; catégorie manquante ou hors liste ; `start < 0` ; `expected`/`accept_also` mal formé, genre d'alias inconnu, `NEW arc`, `NEW protagonist`.
- **Offsets** : surface absente à `start` (narration et historique) ; deux mentions au même `start` ; chevauchement sans imbrication entre **toutes** les mentions (balayage avec pile, pas seulement entre voisines) ; SKIP imbriqué dans un SKIP ; occurrence non annotée d'un pronom indéfini non ambigu.
- **Ids** : tout id de `expected`, `accept_also`, `scene`, `gold_effects`, `gold_knowledge`, `location` d'une entité existe dans le `world` ; ids de `world` uniques ; entité `secret` présente dans `scene.secrets` ; entité sans nom connu ⇒ `known: false` (§ 3.1).
- **`SAME <start>`** (cas tranché a) : la cible est une mention or de la même narration, **antérieure**, d'`expected: NEW <type>` ; catégorie EASY, PART ou DESC ; pas d'`accept_also`, et `SAME` n'est jamais une forme d'`accept_also` ; jamais dans l'historique ; dans une séquence, la répétition est dans le cluster de sa mention NEW.
- **Formes de nom** (cas tranchés b et d) : PART refusé sur un personnage, lieu, organisation ou objet dont le PJ ne connaît **aucun nom** (ni alias de nom `known: true`, ni vrai nom connu) sans REVEAL antérieur dans le tour (DESC) ; une mention EASY d'une entité révélée plus tôt dans le tour accepte `MATCH <id>` ; une mention PART d'une entité révélée plus tôt dans le tour, dont la surface n'est pas un nom déjà connu, doit être `ALIAS <id> short` avec `accept_also: [MATCH <id>]` ; `ALIAS <id> label` n'est jamais DESC ; `ALIAS <id> nickname` n'est jamais PART.
- **Lexique** : `language` doit avoir un fichier `evals/identity/lexicon/<language>.yaml` ; un test vérifie que le code de `evals/identity/` et des scripts du corpus ne contient aucun mot d'un lexique ni aucun nom de genre du corpus.
- **Catégories** (ordre du § 5.1) : SKIP ⇔ `expected: SKIP` ; NEW ⇔ `expected: NEW <type>` ; PC ⇔ cible protagoniste ou compagnon ; REVEAL ⇒ `ALIAS <id> true_name`, entrée `gold_effects.reveals` pour l'id, cible `known: false` ; XTYPE ⇔ nom porté par ≥ 2 entités (sauf REVEAL, NEW, PC, SKIP) ; GAP ⇔ conditions de la question 6, y compris l'absence de REVEAL antérieur de l'entité dans la narration (une mention DESC, PART ou EASY qui les remplit doit être GAP) ; EASY ⇒ forme exacte (question 9 ; le `label` d'une entité sans nom connu n'en est pas une) ; pronom personnel refusé comme mention ; pronom indéfini ou démonstratif ⇒ SKIP ; `trap` seulement sur NEW ; `pov_error` seulement sur un REVEAL de narration `real`.
- **`accept_also`** (§ 4.3) : chaque forme désigne l'entité de `expected` (`MATCH <id>` ou `ALIAS <id> <kind>` du même id) ; jamais `NEW` ni `SKIP`, jamais un autre id.
- **Historique** : `expected` vaut `MATCH` ou `SKIP` ; pas de catégorie GAP ni REVEAL.
- **Connaissance** : chaque nom inconnu obligatoire (§ 7.2) a exactement une entrée `kind: name`, avec le bon état ; toute entrée `kind: name` est un nom inconnu de sa cible.
- **Séquences** : ids de tour uniques ; chaque mention liée dans exactement un cluster ; clé de cluster = id `expected` pour MATCH/ALIAS ; une mention `SAME` est dans le cluster de sa mention NEW.
- **Couverture** (`test_corpus_meets_the_coverage_targets`, sur les scènes) : les seuils du § 8.
- **Campagnes et split** : `campaign` obligatoire ; deux scènes dont l'une montre la narration de l'autre dans son historique ont la même campagne ; une campagne est entière d'un côté du split ; aucune narration du test n'apparaît dans une scène dev ni dans une séquence, aucune narration dev dans une scène test.

Ce que le code ne vérifie pas : la frontière DESC/PART, le choix entre lien et SKIP, la preuve d'un NEW piège, l'exhaustivité des faits de `gold_knowledge`. C'est l'objet de la relecture (§ 12).
