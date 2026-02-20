# Plan V3 — Kayak Fishing Forecast

## Objectif

Deux axes de travail :
1. **Scoring** : corriger le traitement des vagues pour que hauteur et période interagissent (une mer hachée de 1m est plus dangereuse qu'une houle de 1.5m longue)
2. **Rapport** : restructurer en 3 niveaux de lecture (aujourd'hui heure par heure → créneaux 3h sur 3 jours → résumé 14 jours)

---

## Axe 1 — Scoring des vagues

### Problème actuel

Le malus bloquant se déclenche dès `wave_height > 1.2m`, sans tenir compte de la période. Résultat :
- Une vague de **1.5m / 14s** (houle douce, période longue) → score plafonné à 20 → trop pénalisé
- Une vague de **1.0m / 5s** (mer hachée, cassante) → aucun malus bloquant → sous-pénalisé

### Solution : malus basé sur la raideur (steepness = H / T)

La raideur d'une vague `H/T` (hauteur en mètres / période en secondes) quantifie physiquement son caractère dangereux pour un kayak :

| Exemple | H/T | Caractère |
|---|---|---|
| 0.5m / 14s | 0.036 | Houle douce |
| 1.0m / 8s | 0.125 | Assez hachée |
| 1.0m / 5s | 0.200 | Très dangereuse |
| 1.5m / 14s | 0.107 | Gérable mais haute |
| 2.0m / 12s | 0.167 | Limite absolue |

#### Modification de `_blocking_malus()` dans `scoring.py`

Remplacer la condition `wave_m > 1.2` par deux critères combinés :

```python
# Nouveau malus vagues : steepness OU hauteur absolue extrême
if wave_m is not None and period_s is not None:
    steepness = wave_m / period_s
    if steepness > 0.18:          # mer hachée dangereuse (ex: 1m/5s = 0.20)
        return True
elif wave_m is not None and wave_m > 1.4:
    # Si période inconnue, utiliser seuil hauteur légèrement assoupli
    return True

if wave_m is not None and wave_m > 2.0:  # limite absolue
    return True
```

La signature de `_blocking_malus()` passe de `(wind, gust, wave_m)` à `(wind, gust, wave_m, period_s)`.

#### Modification de `score_wave_height()` (courbe ajustée)

Assouplir légèrement la courbe de hauteur (la période s'en charge désormais via le malus) :

```python
(0.0, 100), (0.5, 100), (0.8, 75), (1.2, 40), (1.5, 10), (2.0, 0)
```

#### Rééquilibrage des poids (config.yaml)

| Facteur | V2 | V3 |
|---|---|---|
| Vent | 0.25 | 0.25 |
| Rafales | 0.20 | 0.20 |
| Hauteur vagues | 0.20 | 0.15 |
| Période vagues | 0.15 | 0.20 ← |
| Pluie | 0.10 | 0.10 |
| Température | 0.10 | 0.10 |

La période passe de 15% à 20% (et hauteur de 20% à 15%), pour refléter que la période est co-décisive.

---

## Axe 2 — Restructuration du rapport

### Nouvelle structure (ordre de lecture)

```
┌─────────────────────────────────────────────┐
│  SECTION 1 — AUJOURD'HUI (heure par heure)  │  ← première chose visible
│  Score global du jour + tableau horaire      │
│  Colonnes : Heure | Score | Vent | Rafales   │
│             | Vagues | Période | Pluie | Temp│
│  Meilleure(s) heure(s) mise(s) en valeur     │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│  SECTION 2 — 3 PROCHAINS JOURS (créneaux 3h)│
│  Pour chaque jour : J+1, J+2, J+3           │
│  Créneaux : 06h-09h | 09h-12h | 12h-15h     │
│             | 15h-18h | 18h-20h             │
│  Score moyen + indicateurs clés par créneau  │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│  SECTION 3 — 14 PROCHAINS JOURS (journalier)│
│  Résumé une ligne / un card par jour        │
│  Score | Verdict | Vent moy | Vagues | Créneau│
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│  GRAPHIQUES (inchangés, en bas)             │
└─────────────────────────────────────────────┘
```

---

## Fichiers à modifier

### 1. `src/scoring.py`

**a)** Modifier `_blocking_malus(wind_kts, gust_kts, wave_m, period_s)` — ajouter `period_s`, logique steepness

**b)** Modifier `compute_hourly_score()` — passer `period_s` au malus bloquant

**c)** Ajouter `get_today_hourly(df_scored, config) → list[dict]`
- Filtre les lignes du jour courant
- Retourne une liste de dicts horaires avec : `hour`, `time_str`, `score`, `verdict`, `wind_kts`, `gust_kts`, `wave_height_m`, `wave_period_s`, `rain_mmh`, `temp_c`, `css_class`

**d)** Ajouter `compute_3h_windows(df_scored, config, n_days=3) → list[dict]`
- Pour J+1, J+2, J+3 : groupe les lignes par tranches de 3h (06-09, 09-12, 12-15, 15-18, 18-20)
- Calcule pour chaque créneau : avg score, verdict, avg wind, max gust, avg wave_m, avg period_s, max rain
- Retourne une liste de dicts incluant `date`, `day_short`, `slot`, `score`, `verdict`, etc.

---

### 2. `config/config.yaml`

Mettre à jour les poids :
```yaml
wave_height: 0.15
wave_period: 0.20
```

---

### 3. `src/report.py`

**a)** Modifier `_build_template_context()` — accepter et intégrer `today_hourly` et `windows_3h` dans le contexte Jinja2

**b)** Modifier `generate_report()` — accepter `today_hourly: list[dict]` et `windows_3h: list[dict]` en paramètres

**c)** Ajouter helper `_group_windows_by_day(windows_3h)` → dict `{date: [fenêtres]}` pour faciliter le rendu dans le template

---

### 4. `templates/report.html`

Restructurer le template en 3 sections dans l'ordre défini ci-dessus :

**Section 1 — Aujourd'hui :**
- Bandeau score global (existant, conservé)
- Tableau HTML responsive avec une ligne par heure
- Chaque ligne colorée selon verdict (fond vert/jaune/orange/rouge)
- Badge "Meilleure heure" sur la ou les lignes au score max

**Section 2 — Créneaux 3h :**
- 3 blocs côte à côte (J+1, J+2, J+3), chacun avec 5 créneaux max
- Chaque créneau : card compact avec score (badge coloré), icônes vent + vagues + période
- Fond coloré selon verdict

**Section 3 — 14 jours :**
- Table compacte avec une ligne par jour
- Colonnes : Date | Score | Verdict | Vent moy | Rafales max | Vagues | Période | Pluie | Meilleur créneau

**Graphiques :**
- Déplacés en bas (après les 3 sections)
- Conservés tels quels

---

### 5. `main.py`

Après `compute_scores()`, appeler les deux nouvelles fonctions :
```python
from src.scoring import compute_scores, get_today_hourly, compute_3h_windows

df_scored, daily_summaries = compute_scores(df, config)
today_hourly = get_today_hourly(df_scored, config)
windows_3h   = compute_3h_windows(df_scored, config, n_days=3)
```

Passer ces nouvelles données à `generate_report()`.

---

## Ce qui ne change pas

- `fetch_data.py` — aucun changement
- `fetch_waves.py` — aucun changement
- `process_data.py` — aucun changement
- `visualize.py` — aucun changement (graphiques conservés)
- `email_sender.py` — aucun changement
- Signature de retour de `compute_scores()` — inchangée `(df_scored, daily_summaries)`

---

## Ordre d'implémentation

1. `scoring.py` — nouveau malus + nouvelles fonctions (testable en isolation)
2. `config.yaml` — mise à jour des poids
3. `main.py` — appels des nouvelles fonctions
4. `report.py` — intégration des nouvelles données dans le contexte
5. `templates/report.html` — refonte du template (le plus long)
