---
subject: "[Diag] {{ profile.name }} / {{ situation }}"
style: owner
---

## Nouvelle soumission

| Champ | Valeur |
|---|---|
| **Email** | {{ email }} |
| **Situation** | {{ situation }} |
| **Contrainte déclarée** | {{ felt_constraint }} |
| **Énergie** | {{ scores.energie }}/12 |
| **Attention** | {{ scores.attention }}/12 |
| **Liens** | {{ scores.liens }}/12 |
| **Moyens** | {{ scores.moyens }}/12 |
| **Total** | {{ score_total }}/48 |
| **Profil** | {{ profile.name }} (`{{ profile_key }}`) |
| **Rationalisateur** | {{ "oui" if is_rationalisateur else "non" }} |
{% if felt_constraint and profile.front and felt_constraint != profile.front %}
| **Écart ressenti/réel** | {{ felt_constraint }} → {{ profile.front }} |
{% endif %}
| **Soumis le** | {{ submitted_at }} |

[Voir la page de résultat →]({{ result_url }})
