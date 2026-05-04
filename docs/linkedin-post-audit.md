Audit statique + IA corrective : de 865 à 550 findings en une session

J'ai un side project full-stack (FastAPI + vanilla JS, ~50 000 lignes de code). Le genre de codebase qui grossit vite, où les raccourcis techniques s'accumulent silencieusement.

J'ai décidé de le soumettre à un audit complet avec StaticCodeAudit, l'outil d'analyse statique que je développe chez CodeFixture. Voici le cheminement.


1/ Lancement de l'audit

L'outil a scanné le projet avec 159 règles génériques (sécurité, architecture, UX, maintenance…), des règles spécifiques écrites pour ce projet, et des fixtures adaptées aux patterns du framework (Templates.render, service layer, AsyncSession). L'ensemble permet de réduire les faux positifs et de détecter les vrais problèmes dans leur contexte.


2/ Réception du rapport

Résultat : 865 findings répartis sur 6 catégories.

105 HIGH — XSS, path traversal, Dockerfile root, crypto faible
354 MEDIUM — PII dans les logs, toasts éphémères, logique DB dans les routes
406 LOW — console.log résiduels, chaînes non traduites

Chaque finding est documenté : fichier, ligne, code concerné, risque, solution recommandée.


3/ Validation humaine

J'ai passé en revue le rapport pour distinguer les vrais positifs des faux positifs. Certains findings XSS, par exemple, concernaient des appels à Templates.render — un mécanisme d'échappement propre au projet. D'autres findings LOW relevaient de choix d'architecture assumés. Cette étape de triage est indispensable : l'outil détecte, l'humain décide.


4/ Correction assistée par IA

En utilisant le rapport comme backlog priorisé, j'ai demandé à une IA de corriger par ordre de sévérité :

Sécurité : sanitization HTML via DOMParser, protection path traversal, MD5 → SHA-256, conteneurs non-root
Architecture : élimination des N+1 queries, extraction de la logique DB vers la couche service
UX : 180 toasts d'erreur rendus persistants
Logging : 47 emails retirés des logs (conformité RGPD), 63 console.log de debug supprimés

75 fichiers modifiés. 820 lignes ajoutées, 519 supprimées.


5/ Relance de l'audit

Second scan, mêmes règles, même configuration. Le rapport génère automatiquement la comparaison avec la baseline précédente : nouveaux problèmes, problèmes résolus, problèmes persistants.


6/ Avant / Après

Sévérité | Avant | Après | Delta
HIGH     |   105 |    96 | -8,6 %
MEDIUM   |   354 |   111 | -68,6 %
LOW      |   406 |   343 | -15,5 %
Total    |   865 |   550 | -36,4 %

Les 550 restants ? Principalement des choix d'architecture assumés (createElement pour des éléments simples, SVG inline pour les icônes) et des patterns que l'on conserve en connaissance de cause. La différence entre un finding et un problème, c'est la décision humaine.

Ce que ce cycle démontre : un outil d'audit statique ne remplace pas le jugement. Il fournit une cartographie précise de la dette technique, un backlog actionnable. On corrige, on relance, on mesure. C'est un processus d'amélioration continue — pas un exercice ponctuel.


#SAST #CodeQuality #StaticAnalysis #DevSecOps #AI #TechDebt #CodeReview #OWASP #CodeFixture
