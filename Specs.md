**Application de Tutoring IA**

Objectif final : créer une application de tutoring basée sur des LLM et sur une formation externe et un parcours pédagogique. L'utilisateur interagit avec un coach IA personnel 

# Spécification fonctionnelles

## Fenêtre de chat

L'application est multi-utilisateur.
L'utilisateur peut créer une discussion avec un LLM de son choix, parmi ceux qui sont configurés.
Les LLM disponibles sont : gemini, deepseek, grok de xai.
Les discussions précédentes sont enregistrées et consultables.

## Administration

Certains utilisateurs peuvent être admin et avoir des droits spécifiques.
Les prompts utilisés par l'appi sont stockés à part et éditables dans un onglet.
Les statistiques d'usage des tokens des utilisateurs sont disponibles dans un onglet.

## Gestion du RAG

Les documents utilisés par l'appli sont stockés à part et éditables dans un onglet.
Les documents sont utilisés pour générer des réponses aux questions posées par l'utilisateur.

# Spécifications techniques
Les spécification techniques sont les suivantes : 
- le code et les commentaires sont exclusivement en anglais
- l'application est multilingue fr/eng, géré via gettext
- les noms de fonctions ou de classe sont explicites
- les fonctions utilitaires standalone sont regroupées par thématiques dans un répertoire "lib"
- pour savoir si une fonction est utilitaire il faut se poser la question suivante : pourrait-elle servir dans un tout autre programme, sans rapport avec les specs actuelles ? si oui, c'est une fonction utilitaire, sinon, ça fait partie d'un module
- toute configuration est stockée dans un fichier JSON à part du code
- on met en configuration toute valeur qui peut être changée sans qu'on ne doive modifier le code et qui n'est pas une donnée utilisateur
- toute donnée utilisateur est stockée en base de donnée
- toute clé ou information qui ne doit pas être dans le git est stockée dans .env, chargé au démarrage
- donne les instructions shell pour lancer
- tout prompte est stocké dans un YAML
- fichier requirements.txt ne contient pas de n° de version

Tests : 
- chaque fonction principale des spects dispose d'un test de non regression pour son workflow
- une fonction d'initialisation permet de créer un jeu de test de départ qui sera remis à zéro avant de lancer les tests

Modules: 
- tout module est pensé pour être évolutif et plug and play : l'application doit pouvoir fonctionner, même si elle est amoindrie, si le module est absent
- le module est un répertoire qui contient TOUS les fichiers nécessaires à son fonctionnement (test, configuration, prompts)
- un module injecte dans l'application à travers des points d'injections ce qui lui permet de fonctionner
- l'architecture est modulaire et évolutive, les modules sont tous dans un repertoire "modules"
- un module regroupe ce qui sert à coder une unité sémantique ou une unité fonctionnelle qui utilise les unités sémantiques
- chaque module contient une spécification en entête
- chaque module dispose de tests de unitaire associés
- un module contient : ses traductions (json), ses prompts (yaml), sa configuration (json), ses tests (pytest), son affichage, sa logique métier, ses librairies. Les fichiers sont toujours les même d'un module à l'autre.
- un module doit être indépendant des autres modules, sauf des fonctionnalités communes
- un module peut avoir des sous modules et ses propres points d'injections, mais les seules dépendances sont le module parent et les les fonctionnalités communes de l'application. Il ne doit pas y avoir de module qui dépende de plusieurs modules. C'est un arborescence.

Commun : 
- les modules partagés sont dans un répertoire "shared" dédié pour bien les séparer des modules débrayables, ces modules ne sont pas désactivables
- l'application fournit pour les modules des points d'injections pour : les traductions, les prompts et l'appel de LLM, la configuration, les tests, l'affichage (side bar, page principale, onglet de settings, config utilisateur)
- tout ce qui est commun vient avec un Mock pour les tests

Fonctiionnalités prévues : 
- La base : multiuser, multilingue, multillm, multiconversations
- Les fonctionnalités MVP : 
- RAG avec différents moteurs de RAG, le moyen de les comparer et debugger
- Token stats : monitoring de l'usage des tokens par utilisateurs
- Parcours pédagogique, évaluation du niveau par discussion plutôt que par questionnaire
- Les plus : 
- Récupération de playlist YT et de PDF pour l'importation de contenu du RAG
- Metadata pour le RAG si nécessaire pour parcours pédagogique
