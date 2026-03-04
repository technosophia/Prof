#!/usr/bin/env python3
"""
RAG Benchmark — Dataset Prompt Generator

Usage (default — no arguments needed):
    python tools/rag_bench_dataset_prompt_generator.py

Generates one prompt file per level in data/rag_bench/prompts/.
Each file contains a ready-to-paste prompt for your LLM.
The LLM will output a YAML file — save it to data/rag_bench/.

Options (all optional):
    --output-dir DIR    Where to save prompts (default: data/rag_bench/prompts)
    --model NAME        Model hint in the prompt header (default: claude-sonnet-4-6)
    --levels LEVELS     Which levels, e.g. 1-4, 1 2 3, all (default: all)
    --dry-run           Print to stdout instead of saving
    --list-levels       Show level descriptions and exit
"""

import argparse
import os
import sys
import textwrap
from datetime import datetime
from typing import List

# ─────────────────────────────────────────────────────────────────────────────
# LEVEL METADATA
# ─────────────────────────────────────────────────────────────────────────────

LEVEL_META = {
    1:  {"label": "Direct Keyword Match",      "fixable": "✅", "n": 10, "k": 3,  "scoring": "deterministic"},
    2:  {"label": "Keyword in Dense Context",  "fixable": "✅", "n": 8,  "k": 5,  "scoring": "hybrid"},
    3:  {"label": "Temporal / Sequential",     "fixable": "✅", "n": 5,  "k": 5,  "scoring": "hybrid"},
    4:  {"label": "Adversarial Distractor",    "fixable": "✅", "n": 3,  "k": 5,  "scoring": "deterministic"},
    5:  {"label": "Semantic Paraphrase",       "fixable": "⚠️", "n": 10, "k": 3,  "scoring": "llm_judge"},
    6:  {"label": "Negation / Absence",        "fixable": "⚠️", "n": 5,  "k": 5,  "scoring": "llm_judge"},
    7:  {"label": "Numerical / Comparative",   "fixable": "⚠️", "n": 5,  "k": 5,  "scoring": "hybrid"},
    8:  {"label": "Multi-Chunk Synthesis",     "fixable": "⚠️", "n": 5,  "k": 5,  "scoring": "hybrid"},
    9:  {"label": "Long-Range Sparse Signal",  "fixable": "⚠️", "n": 5,  "k": 10, "scoring": "llm_judge"},
    10: {"label": "Cross-Document Retrieval",  "fixable": "❌", "n": 5,  "k": 5,  "scoring": "llm_judge"},
    11: {"label": "Ambiguous / Broad Query",   "fixable": "❌", "n": 5,  "k": 3,  "scoring": "llm_judge"},
}

# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPT (common to all levels)
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
Tu es un expert en évaluation de systèmes RAG (Retrieval-Augmented Generation).
Ta mission est de générer des cas de test pour benchmarker un moteur de recherche sémantique.

Le moteur RAG testé ne contient PAS de LLM. Il reçoit une question et retourne une liste
de chunks (extraits de documents) classés par score de similarité.

RÈGLES STRICTES :
- Génère UNIQUEMENT du YAML valide, sans markdown, sans backticks, sans commentaires supplémentaires.
- Les questions doivent être en français, naturelles, comme les poserait un apprenant.
- Les expected_keywords doivent être des mots/expressions qui apparaissent RÉELLEMENT dans le document fourni.
- Le reference_answer doit être une reformulation naturelle, pas une copie exacte du document.
- Les expected_sources doivent correspondre exactement au nom de fichier fourni par l'utilisateur.
- Le min_score_threshold doit être réaliste (0.55–0.85 selon la difficulté du niveau).
- Chaque case doit avoir un id unique au format l{level}_{seq:03d} (ex: l1_001, l1_002).
"""

# ─────────────────────────────────────────────────────────────────────────────
# USER PROMPTS (one per level)
# ─────────────────────────────────────────────────────────────────────────────

USER_PROMPTS = {

1: """\
Génère {n} cas de test de NIVEAU 1 — Direct Keyword Match.

CONTEXTE :
La question utilise EXACTEMENT le même vocabulaire que le document.
C'est le niveau de base : si un moteur échoue ici, il est inutilisable.

CONSIGNES :
- Les questions doivent contenir des mots qui apparaissent mot pour mot dans le document.
- expected_keywords : 2 à 4 expressions exactes tirées du document.
- min_score_threshold : 0.75 à 0.85
- required_rank : null
- scoring_method : "deterministic"
- default_top_k : {k}

DOCUMENT SOURCE en attaché

Génère le YAML complet. Commence directement par `meta:`.
Le fichier résultant devra être sauvegardé sous : data/rag_bench/level_01_direct_keyword.yaml
""",

2: """\
Génère {n} cas de test de NIVEAU 2 — Keyword in Dense Context.

CONTEXTE :
La réponse est un fait précis (nombre, règle, nom propre) qui se trouve dans un chunk long et dense.
Le moteur doit ranker ce chunk spécifique au-dessus des chunks génériques.

CONSIGNES :
- Questions ciblant des faits précis : chiffres, seuils, règles spécifiques, noms.
- expected_keywords doit inclure la valeur précise telle qu'elle apparaît dans le doc (ex: "48 heures", "article 5").
- min_score_threshold : 0.70 à 0.80
- scoring_method : "hybrid"
- default_top_k : {k}

DOCUMENT SOURCE en attaché

Génère le YAML complet. Commence directement par `meta:`.
Le fichier résultant devra être sauvegardé sous : data/rag_bench/level_02_keyword_dense_context.yaml
""",

3: """\
Génère {n} cas de test de NIVEAU 3 — Temporal / Sequential.

CONTEXTE :
La question implique un ordre, une étape, un prérequis, une progression.
Le moteur doit retrouver le chunk décrivant la bonne étape dans une séquence.

CONSIGNES :
- Questions du type : "Que faut-il faire avant X ?", "Quelle est l'étape suivant Y ?",
  "Qu'est-ce qui est obligatoire avant de passer au module N ?"
- expected_keywords : marqueurs de séquence présents dans le doc (ex : "étape 2", "avant de", "prérequis").
- min_score_threshold : 0.65 à 0.75
- scoring_method : "hybrid"
- default_top_k : {k}

DOCUMENT SOURCE en attaché

Génère le YAML complet. Commence directement par `meta:`.
Le fichier résultant devra être sauvegardé sous : data/rag_bench/level_03_temporal_sequential.yaml
""",

4: """\
Génère {n} cas de test de NIVEAU 4 — Adversarial Distractor.

CONTEXTE :
Deux informations similaires pourraient exister dans le corpus, une correcte et une légèrement erronée.
Le moteur doit ranker le bon chunk AU-DESSUS du distracteur potentiel.

CONSIGNES :
- Identifie des faits qui pourraient avoir des variantes proches (deux valeurs numériques,
  deux procédures ressemblantes, une règle générale et une exception).
- Ajoute le champ `distractor_description` : décrit CE QUE SERAIT un chunk trompeur
  (tu ne le crées pas, tu le décris pour que le testeur l'injecte manuellement).
- required_rank : null
- min_score_threshold : 0.65 à 0.75
- scoring_method : "deterministic"
- default_top_k : {k}

DOCUMENT SOURCE en attaché

Génère le YAML complet. Commence directement par `meta:`.
Le fichier résultant devra être sauvegardé sous : data/rag_bench/level_04_adversarial_distractor.yaml
""",

5: """\
Génère {n} cas de test de NIVEAU 5 — Semantic Paraphrase.

CONTEXTE :
La question utilise des SYNONYMES ou un vocabulaire DIFFÉRENT de celui du document.
Le moteur doit trouver le bon chunk malgré cet écart sémantique.

CONSIGNES :
- Reformule les questions avec des synonymes (ex : "supprimer" → "effacer",
  "durée" → "période", "apprenant" → "participant").
- Les expected_keywords doivent rester ceux du DOCUMENT (pas de la question reformulée).
- min_score_threshold : 0.60 à 0.75 (score attendu plus faible qu'au niveau 1)
- scoring_method : "llm_judge"
- default_top_k : {k}

DOCUMENT SOURCE en attaché

Génère le YAML complet. Commence directement par `meta:`.
Le fichier résultant devra être sauvegardé sous : data/rag_bench/level_05_semantic_paraphrase.yaml
""",

6: """\
Génère {n} cas de test de NIVEAU 6 — Negation / Absence.

CONTEXTE :
La réponse est une interdiction, une impossibilité, ou une contrainte forte.
Le moteur doit ranker le chunk contenant la NÉGATION, pas un chunk qui répondrait positivement.

CONSIGNES :
- Questions où la réponse dans le document est NON ou une limite stricte.
  Ex : "Est-il possible de...?", "Peut-on faire X sans Y ?"
- Ajoute le champ `negation_keywords` : mots négatifs/contraignants présents dans le doc
  (ex: "impossible", "interdit", "ne peut pas", "obligatoire", "sans exception").
- min_score_threshold : 0.60 à 0.70
- scoring_method : "llm_judge"
- default_top_k : {k}

DOCUMENT SOURCE en attaché

Génère le YAML complet. Commence directement par `meta:`.
Le fichier résultant devra être sauvegardé sous : data/rag_bench/level_06_negation_absence.yaml
""",

7: """\
Génère {n} cas de test de NIVEAU 7 — Numerical / Comparative.

CONTEXTE :
La réponse est un chiffre, un seuil, une durée, ou une comparaison entre deux valeurs.
Le moteur doit retrouver le chunk contenant ces données quantitatives précises.

CONSIGNES :
- Questions du type : "Combien de...?", "Quelle est la différence entre X et Y ?",
  "Quel est le seuil minimum pour...?"
- expected_keywords DOIT inclure la valeur numérique EXACTE telle qu'elle apparaît dans le doc
  (ex: "12 apprenants", "4 heures", "72%").
- min_score_threshold : 0.65 à 0.75
- scoring_method : "hybrid"
- default_top_k : {k}

DOCUMENT SOURCE en attaché

Génère le YAML complet. Commence directement par `meta:`.
Le fichier résultant devra être sauvegardé sous : data/rag_bench/level_07_numerical_comparative.yaml
""",

8: """\
Génère {n} cas de test de NIVEAU 8 — Multi-Chunk Synthesis.

CONTEXTE :
La réponse complète nécessite de combiner 2 ou 3 passages du même document.
Un seul chunk ne suffit pas — le moteur doit retourner TOUS les chunks pertinents dans son top-K.

CONSIGNES :
- Questions ouvertes : "Quelles sont toutes les conditions pour...?",
  "Décris le processus complet de...", "Quels sont tous les prérequis pour...?"
- Utilise `all_required_sources` (liste) plutôt que `expected_sources`.
- Dans `notes`, indique les 2-3 éléments de réponse attendus dans des chunks distincts.
- min_score_threshold : 0.65
- scoring_method : "hybrid"
- default_top_k : {k}

DOCUMENT SOURCE en attaché

Génère le YAML complet. Commence directement par `meta:`.
Le fichier résultant devra être sauvegardé sous : data/rag_bench/level_08_multi_chunk.yaml
""",

9: """\
Génère {n} cas de test de NIVEAU 9 — Long-Range Sparse Signal.

CONTEXTE :
L'information pertinente est dans un chunk court, peu dense, ou exprimé avec très peu de mots.
Le moteur doit retrouver ce chunk malgré un faible signal lexical.

CONSIGNES :
- Identifie des faits importants mais exprimés brièvement : définitions courtes,
  termes techniques rares, notes marginales.
- Questions ciblant précisément ces informations peu denses.
- min_score_threshold : 0.55 à 0.65 (signal faible — sois réaliste sur le seuil)
- scoring_method : "llm_judge"
- default_top_k : {k}

DOCUMENT SOURCE en attaché

Génère le YAML complet. Commence directement par `meta:`.
Le fichier résultant devra être sauvegardé sous : data/rag_bench/level_09_sparse_signal.yaml
""",

10: """\
Génère {n} cas de test de NIVEAU 10 — Cross-Document Retrieval.

CONTEXTE :
La réponse nécessite des chunks de PLUSIEURS documents différents simultanément.
Le moteur doit retrouver des informations pertinentes réparties sur plusieurs fichiers.

CONSIGNES :
- Questions qui font le lien entre concepts présents dans des documents différents.
  Ex : "Quel concept du module A est prérequis pour l'exercice du module B ?"
- `all_required_sources` doit lister PLUSIEURS fichiers différents (au moins 2).
- min_score_threshold : 0.60
- scoring_method : "llm_judge"
- default_top_k : {k}

DOCUMENT SOURCE en attaché

Génère le YAML complet. Commence directement par `meta:`.
Le fichier résultant devra être sauvegardé sous : data/rag_bench/level_10_cross_document.yaml
""",

11: """\
Génère {n} cas de test de NIVEAU 11 — Ambiguous / Broad Query.

CONTEXTE :
La question est vague, plusieurs chunks sont plausiblement pertinents.
Le moteur doit ranker LE MEILLEUR chunk en première position absolue.

CONSIGNES :
- Questions générales et ouvertes : "Comment fonctionne l'authentification ?",
  "Parle-moi des évaluations.", "Qu'est-ce qu'un module ?"
- `required_rank` doit être 1 — le meilleur chunk DOIT être en position 1.
- Dans `notes`, explique POURQUOI le expected_source est le meilleur chunk
  parmi les candidats plausibles.
- min_score_threshold : 0.60
- scoring_method : "llm_judge"
- default_top_k : {k}

DOCUMENT SOURCE en attaché-

Génère le YAML complet. Commence directement par `meta:`.
Le fichier résultant devra être sauvegardé sous : data/rag_bench/level_11_ambiguous_broad.yaml
""",
}

# ─────────────────────────────────────────────────────────────────────────────
# FILE WRITER
# ─────────────────────────────────────────────────────────────────────────────

def write_prompt_file(output_dir: str, level: int, model: str) -> str:
    os.makedirs(output_dir, exist_ok=True)

    meta = LEVEL_META[level]
    label_slug = meta["label"].lower().replace(" ", "_").replace("/", "_")
    fname = f"level_{level:02d}_{label_slug}.txt"
    fpath = os.path.join(output_dir, fname)

    user_prompt = USER_PROMPTS[level].format(n=meta["n"], k=meta["k"])

    sep = "=" * 72
    content = f"""{sep}
RAG BENCHMARK — PROMPT DE GÉNÉRATION DE DATASET
Niveau {level} : {meta["label"]}
Réparabilité : {meta["fixable"]}  |  Scoring : {meta["scoring"]}  |  Top-K : {meta["k"]}  |  Questions : {meta["n"]}
Généré le : {datetime.now().strftime("%Y-%m-%d %H:%M")}
Modèle suggéré : {model}
{sep}

INSTRUCTIONS :
  1. Ouvre {model} (ou tout LLM capable)
  2. Si l'interface a un champ SYSTEM prompt séparé → colle le bloc SYSTEM ci-dessous
     Sinon → colle les deux blocs à la suite dans le même message
  3. Remplace les placeholders [NOM_DU_FICHIER.md] et [CONTENU DU DOCUMENT ICI]
     par le vrai nom et le vrai contenu de ton fichier markdown
  4. Envoie et récupère le YAML généré
  5. Sauvegarde-le dans data/rag_bench/
"""

    content = f"""
{"─" * 72}
SYSTEM PROMPT
{"─" * 72}
{SYSTEM_PROMPT}
{"─" * 72}
USER PROMPT
{"─" * 72}
{user_prompt}
{sep}
FIN DU PROMPT — NIVEAU {level}
{sep}
"""
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(content)
    return fpath


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def parse_levels(tokens: List[str]) -> List[int]:
    result = set()
    for t in tokens:
        if t == "all":
            return list(range(1, 12))
        if "-" in t:
            a, b = t.split("-", 1)
            result.update(range(int(a), int(b) + 1))
        else:
            result.add(int(t))
    return sorted(result)


def main():
    parser = argparse.ArgumentParser(
        prog="rag_bench_dataset_prompt_generator.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--output-dir", "-o", default="data/rag_bench/prompts",
                        help="Répertoire de sortie (défaut: data/rag_bench/prompts)")
    parser.add_argument("--model", "-m", default="claude-sonnet-4-6",
                        help="Modèle suggéré dans l'en-tête (défaut: claude-sonnet-4-6)")
    parser.add_argument("--levels", "-l", nargs="+", default=["all"],
                        help="Niveaux à générer : 1 2 3, 1-4, all (défaut: all)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Affiche les prompts dans le terminal au lieu de sauvegarder")
    parser.add_argument("--list-levels", action="store_true",
                        help="Liste les niveaux disponibles et quitte")
    args = parser.parse_args()

    if args.list_levels:
        print(f"\n{'Lvl':<5} {'Fixable':<8} {'Scoring':<14} {'K':<4} {'N':<4}  Label")
        print("─" * 60)
        for lvl, m in LEVEL_META.items():
            print(f"  {lvl:<4} {m['fixable']:<8} {m['scoring']:<14} {m['k']:<4} {m['n']:<4}  {m['label']}")
        print()
        sys.exit(0)

    try:
        levels = parse_levels(args.levels)
    except ValueError as e:
        parser.error(f"Niveaux invalides : {e}")

    invalid = [l for l in levels if l not in LEVEL_META]
    if invalid:
        parser.error(f"Niveaux inconnus : {invalid}. Plage valide : 1–11.")

    print(f"\n🔧 RAG Benchmark Prompt Generator")
    print(f"   Niveaux  : {levels}")
    print(f"   Sortie   : {args.output_dir}")
    print(f"   Modèle   : {args.model}")
    print()

    for level in levels:
        meta = LEVEL_META[level]
        if args.dry_run:
            user = USER_PROMPTS[level].format(n=meta["n"], k=meta["k"])
            print(f"\n{'=' * 72}")
            print(f"NIVEAU {level} : {meta['label']}  [{meta['fixable']}]  —  {meta['n']} questions")
            print("─" * 72)
            print(SYSTEM_PROMPT)
            print("─" * 72)
            print(user)
        else:
            fpath = write_prompt_file(args.output_dir, level, args.model)
            print(f"  ✅ Niveau {level:2d}  [{meta['fixable']}]  {meta['label']:<30}  ({meta['n']} questions)  →  {fpath}")

    if not args.dry_run:
        print(f"\n✔  {len(levels)} fichier(s) sauvegardé(s) dans {args.output_dir}/")
        print()
        print("Étapes suivantes :")
        print("  1. Ouvre un fichier .txt dans data/rag_bench/prompts/")
        print("  2. Remplace [NOM_DU_FICHIER.md] et [CONTENU DU DOCUMENT ICI]")
        print(f"  3. Colle dans {args.model}")
        print("  4. Sauvegarde le YAML produit dans data/rag_bench/")
        print("  5. Lance le benchmark dans l'UI admin\n")


if __name__ == "__main__":
    main()
