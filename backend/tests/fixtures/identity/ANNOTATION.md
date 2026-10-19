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
genre: sf                    # sf | dark_fantasy | … (≥ 2 genres dans le corpus)
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

Tous les champs sont obligatoires sauf `turn` ; une clé inconnue (faute de frappe) est refusée au chargement.

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
- les **pronoms** (il, elle, lui, toi, quelqu'un, personne, celui-ci…) : le resolver travaille sur les groupes nominaux ; un pronom n'est jamais une mention, ni liée ni SKIP ;
- les objets et lieux de **décor** sans lien avec une entité du `world` et hors des cas SKIP (« le comptoir », « les bols sales », « une flaque ») ;
- les noms communs non référentiels (« le reste », « les formulaires » au sens générique).

### 4.2 Frontières

- La mention **inclut le déterminant** : article, possessif, démonstratif (« la Kethari âgée », « sa paume », « ce Bureau des Résidences »). Sans déterminant dans le texte, la surface commence au nom (« Nahle Irun-Sa »).
- Elle inclut les compléments qui identifient (« le Kethari au tablier », « la voix basse sur ton terminal », « la femme grise à la tablette »), et s'arrête avant une relative ou une incise qui raconte (« le Kethari au tablier » dans « le Kethari au tablier, qui empile les bols »).
- Une préposition contractée (du, des, au, aux) reste hors de la surface, même si elle contient l'article : « du Bureau des Résidences » → « Bureau des Résidences » ; « au quai » → « quai » ; « cligne des yeux » → « yeux ». Une préposition non contractée aussi : « de mon ancien habitat » → « mon ancien habitat ».
- La majuscule de début de phrase est recopiée telle quelle (« Sa poche de tablier »).
- **Imbrication** : une mention peut en contenir une autre qui désigne une **autre** entité (« la voix basse sur ton terminal » → compagnon, et à l'intérieur « ton terminal » → objet ; « le terminal du Kethari au tablier » → SKIP, et à l'intérieur « Kethari au tablier » → le gérant). On n'imbrique jamais un SKIP dans un SKIP (« la poche de son tablier » est une seule mention SKIP). Deux mentions qui se chevauchent sans être imbriquées sont interdites.

### 4.3 Champs d'une mention or

```yaml
- surface: La Kethari âgée
  start: 0
  category: DESC                       # § 5
  expected: MATCH character_kethari_agee
  accept_also: []                      # équivalences légitimes, même syntaxe que expected
  trap: false                          # true seulement sur un NEW piège (§ 5.1, NEW)
```

`expected` prend l'une des quatre formes :

| Forme | Sens |
|---|---|
| `MATCH <id>` | la mention désigne l'entité `<id>` par un nom, un alias ou une description qu'il n'est pas nécessaire d'enregistrer comme alias |
| `ALIAS <id> <kind>` | la mention désigne `<id>` **et** apporte un alias nouveau de genre `<kind>` qui doit être enregistré (révélation de nom, forme courte d'un nom révélé, surnom, ancien nom) |
| `NEW <type>` | entité réellement nouvelle de type `character`, `location`, `organization`, `object` ou `arc` |
| `SKIP` | à ne pas lier |

Quand choisir `ALIAS` plutôt que `MATCH` : seulement pour une information **de nom** absente du `world` (vrai nom révélé, forme courte de ce nom, surnom, ancien nom). Une description nouvelle (« la cheffe de serre » pour Oriane) est un `MATCH <id>` avec `accept_also: [ALIAS <id> descriptor]` : le système peut, sans faute, l'enregistrer comme descripteur.

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
3. L'entité est-elle **absente du `world`** ? → **NEW**, `expected: NEW <type>`. Si une entité du `world` du **même type** pourrait être prise pour elle (même titre ou même nom partiel, même espèce et même rôle, même descripteur), c'est un **NEW piège** : `trap: true`. Preuve exigée dans le texte : la nouvelle entité **parle à** l'entité existante ou agit en même temps qu'elle dans la scène (`talks_to`), **ou** elle se trouve dans un **autre lieu** que celui de l'entité existante. Sans cette preuve, on ne peut pas affirmer que c'est une autre personne : on n'écrit pas la scène ainsi.
4. La mention **révèle-t-elle un nom** que le PJ ne connaissait pas ? → **REVEAL**, `expected: ALIAS <id> true_name`. Cas : auto-présentation d'une entité présente (« Je m'appelle Nahle », « — Nahle Irun-Sa, dit-elle »), un tiers qui la nomme devant le PJ, une source du monde (badge, écriteau, document, terminal) qui donne le nom d'un PNJ, d'un lieu, d'une organisation ou d'un objet connus jusque-là par un descripteur. Seule la **première occurrence complète** du nom dans le tour est REVEAL ; une scène REVEAL a toujours une entrée `gold_effects.reveals` pour cette entité (§ 6). Le nom révélé peut être absent du `world` (`true_name: null`, cas Kethari) ou y figurer comme alias `known: false` (cas Tesk).
5. La surface (normalisée : casse, accents, article de tête) est-elle un nom ou un alias porté par **au moins deux entités du `world`** ? → **XTYPE** (« Bureau des Résidences » lieu et organisation ; « Voss » pour Rizka Voss et Elara Voss). `expected` désigne celle que le contexte impose (le lieu si l'on y entre, l'organisation si elle agit ou décide).
6. L'entité est-elle **absente de tout l'`history`** et `last_seen_turn ≤ turn − 5` ? → **GAP** (« Voss t'attend au labo » au tour 21, vue au tour 3).
7. La surface **décrit**-elle l'entité sans employer son nom ? → **DESC**. Pour un personnage, tout ce qui n'est pas son vrai nom ou une partie de ce nom est une description, y compris son propre descripteur enregistré (« la Kethari âgée », « le Kethari au tablier », « le gérant », « la cheffe de serre »). Pour un lieu, une organisation, un objet : une désignation qui n'emploie aucun mot de son `label` (« la salle au bout du couloir », « l'administration »).
8. La surface est-elle une **variante** du nom ou du libellé ? → **PART** : nom partiel (« Ondrev », « Nahle »), titre (« le Pater »), mot-tête du libellé avec un autre déterminant (« ton terminal » pour Terminal personnel, « la Coopérative » pour Coopérative Agronomique d'Ombelle), casse, accent, ponctuation, faute (« Eloise »/« Éloïse », « Quai n°9 »/« Quai 9 »), mots ajoutés ou retirés.
9. Sinon : le nom complet ou le libellé exact (à l'article de tête près) d'une entité citée dans l'`history` → **EASY**.

Formes d'un nom révélé dans le même tour : la première occurrence complète est REVEAL ; une forme courte qui suit (« Nahle suffit ») est **PART** avec `expected: ALIAS <id> short` et `accept_also: [MATCH <id>]` (les formes courtes sont dérivées automatiquement du vrai nom) ; une répétition de la forme complète est **EASY** avec `expected: ALIAS <id> true_name`.

### 5.2 Quand une mention est SKIP (liste fermée)

On annote en SKIP, et seulement dans ces cas :
1. **Partie du corps, vêtement, possession ou lieu d'origine** d'une entité du `world` : « sa paume », « sa mâchoire », « les doigts » (de la Kethari), « sa poche de tablier », « sa valise » (celle de la Kethari), « ton bol », « mon ancien habitat ». Exception : une possession du PJ qui est un objet d'inventaire du `world` est liée (« ton terminal » → `object_terminal_personnel`).
2. **Foule ou groupe générique** : « les clients », « trois clients », « des gardes », « les anciens ».
3. **Descripteur indéfini sans rôle** : « un type », « une passante », « un client » quand la personne ne fait rien d'autre que d'être là. Dès qu'elle parle, agit sur l'intrigue, est décrite pour être retrouvée ou revient plus tard, ce n'est plus SKIP (NEW ou DESC selon le `world`).
4. **Objet vu mais non acquis**, quand il partage un mot-tête avec une entité du `world` ou qu'il est l'objet d'une action passagère : « un couteau sur la table », « son terminal » (celui du gérant, pas celui du PJ).
5. **Faux ami d'une entité** : groupe nominal qui reprend un mot distinctif d'une entité sans la désigner (« une serre » quelconque quand le `world` contient la Serre Numéro Quatre et que le texte parle d'une autre).

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
| EASY | non | `MATCH <id>` | « Pater Ondrev » cité au tour précédent |
| PART | oui | `MATCH <id>` | « la Coopérative », « Ondrev », « ton terminal » |
| DESC | oui | `MATCH <id>` | « la Kethari âgée », « la cheffe de serre » → Oriane |
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
- `kind: name` : `text` est le nom inconnu, recopié exactement depuis le `true_name` ou un alias `known: false` de l'entité ; une seule entrée par nom (les formes courtes sont impliquées). `state` doit correspondre au drapeau `secret` de cet alias (ou de l'entité) : la validation le vérifie.
- `kind: fact` : `text` est une phrase autonome qui énonce le fait (un attribut, une relation, le contenu d'un objet, le but d'un arc). L'or ne contient que des faits que la fiction établit (base réelle, scénario de l'issue, ou scène synthétique écrite pour cela).
- Un élément révélé **dans** le tour reste listé avec son état d'avant le tour : le contrôle de révélation `R` le retrouve par `gold_effects.reveals`.

### 7.3 Point de vue, révélation diégétique, fuite

Ces définitions servent aux juges `P`, `R`, `L` (§ 3.4 bis de la spécification) et à l'écriture des scènes synthétiques.

- **Voix narrative** : tout le texte hors dialogue et hors source diégétique. Les répliques (après un tiret de dialogue ou entre guillemets), les textes lus par le PJ (badge, écriteau, document, écran) et les messages du compagnon (en italique dans les parties réelles : *…*) n'en font pas partie.
- **Erreur de point de vue (`P`)** : un élément **inconnu du PJ** (état 2 ou 3, nom ou fait) apparaît dans la **voix narrative**. Exemple : « Tesk empile les bols » alors que le PJ ne connaît que « le Kethari au tablier ». Ce n'est **pas** une erreur : le même nom dans une réplique (« — Tesk, ferme la plonge ! » lancé par un client) ou sur un badge que le PJ lit ; le descripteur dans la voix narrative ; le nom dans la voix narrative **après** sa révélation diégétique plus tôt dans le même texte.
- **Révélation diégétique (`R`)** : un élément inconnu fait surface **dans la fiction** (réplique, présentation, badge, écriteau, document, terminal), **naturellement** (le PJ l'a demandé, la personne se présente, la logique de la scène l'amène), **et** il est enregistré sur la bonne entité ou le bon fait. Exemple : « Comment vous appelez-vous ? » → « — Nahle Irun-Sa, dit-elle. » Un secret n'est une révélation correcte que si une divulgation était ouverte (`scene.open_disclosures`).
- **Fuite (`L`)** : un élément **secret** sans divulgation ouverte apparaît sous **quelque forme que ce soit** (voix narrative, dialogue, document, champ joueur, prompt narrateur). Doit être 0.

Une scène synthétique qui teste `P` contient l'élément inconnu dans le `world` et dans `gold_knowledge`, et sa `narration` est **correcte** (descripteur dans la voix narrative ; le nom seulement en dialogue ou par une source) : le corpus contient l'or, pas des fautes à détecter. Les narrations fautives sont produites par l'évaluation live et jugées avec la grille `POV_GRID.md`.

---

## 8. Couverture visée

- **≥ 50 mentions par catégorie dure** (PART, DESC, GAP, REVEAL, NEW, XTYPE), ≈ 100 EASY, ≈ 60 SKIP, ≈ 30 PC : ≈ 500 mentions.
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

Une clé de `gold_clusters` est un id d'entité (du `world` final, ou un id choisi pour une entité née dans la séquence) ; chaque valeur liste les mentions or de cette entité sous la forme `<id de scène du tour>:<start>`. Chaque mention liée (non SKIP) de la séquence apparaît dans exactement un cluster. Les ids de scène des tours sont uniques dans tout le corpus.

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

Le split dev 60 % / test 40 % (stratifié par catégorie) est produit par `scripts/identity_corpus_split.py` ; le test est annoté avant tout réglage de prompt et gelé par `TEST_SHA256`. Toute correction d'or du test impose une PR qui l'explique. Le compte rendu de la seconde annotation à l'aveugle du split test (taux de désaccord, corrections) est ajouté ci-dessous dans une section « Relecture du <date> ».

---

## 13. Cas tranchés

- **f134, tour 15 — « sa paume »** (`_example.yaml`, historique) : l'ancien resolver liait « sa paume », « sa mâchoire » et « son terminal » au gérant. Ce sont une partie du corps et une possession : SKIP (§ 5.2, cas 1 et 4).
- **f134 — « la Kethari âgée »** : PNJ sans vrai nom, connu par son seul descripteur ; DESC, même quand la surface est exactement son descripteur enregistré (§ 5.1, question 7). « Nahle Irun-Sa » au tour 15 : REVEAL ; « Nahle » juste après : PART, `ALIAS … short`.
- **f134 — « sa valise »** quand le PJ possède la Valise souple : désigne la valise de la Kethari, SKIP (§ 5.2, cas 1) ; « ta valise » désignerait l'objet d'inventaire (PART).
- **f134 — la voix du terminal** (« la voix basse sur ton terminal », « ta compagne ») : le compagnon Pervenche, PC.
