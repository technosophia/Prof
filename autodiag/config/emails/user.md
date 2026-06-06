---
subject: "{{ profile.email_subject }}"
style: user
---
{% set share_subject = "J'ai fait ce diagnostic de souveraineté — tu devrais le faire aussi" %}
{% set share_body = "Salut,\n\nJe viens de faire le diagnostic Souveraineté. En 5 minutes, tu identifies exactement sur quel front tu perds de l'autonomie — énergie, attention, liens ou moyens.\n\nC'est gratuit, c'est direct, ça fait mal au bon endroit.\n\nFais-le ici : " + share_url %}

*{{ profile.tagline }}*

{{ profile.body }}

<p style="margin:2em 0 0.5em;">
<a href="{{ result_url }}"
   style="display:inline-block;background:#c8843a;color:#fff;padding:13px 28px;text-decoration:none;border-radius:4px;font-family:sans-serif;font-size:15px;font-weight:bold;">
  Voir ton diagnostic complet →
</a>
</p>

---

*Ce diagnostic t'a parlé ? Un ami ou un collègue gagnerait peut-être à le faire.*

<p style="margin:1em 0 2em;">
<a href="mailto:?subject={{ share_subject | urlencode }}&body={{ share_body | urlencode }}"
   style="display:inline-block;background:#f7f7f7;color:#444;border:1px solid #ddd;padding:10px 22px;text-decoration:none;border-radius:4px;font-family:sans-serif;font-size:13px;">
  Faire passer à un ami →
</a>
</p>
