<!-- /_docs/SPECS.md --> 

# Intention

I make training workshop in videos. I want to build a compagnon chatbot that uses that content so that students can be coached by it instead of me. To do that, I must minimally build a chatbot with a RAG, a memory, and I would like it to be proactive. The difficulty is that LLM responses are not deterministic, so I must build a system to evaluate different rag and memory and coaching systems. More over I want to build this system with agentic coding and make a formation out of it (that will be integrated in the system itself as a training program)?

# Functional High-Level Specifications

The goal is to build a "Professor" application. It takes training material (pdf, markdown) of a real training course, and give it to an LLM to help students so that they can learn more interactively. So basically it's a RAG, but with a memory of the student pedagogical progression. The main benefit is in that memory and pro-active suggestions.

Planned Features:
- Base: 
  - multi-user, multilingual, multi-LLM, multi-conversation.
- MVP Features:
  - RAG with different RAG engines, means to compare and debug them.
  - Token stats: monitoring token usage per user.
  - Training : follow user progression, learning path, level assessment through discussion rather than questionnaires. The core is the memory : it compress the discussions and follow the progression of the student. Multiple memory plugin can be compared.


Additional Features:
  - Benchmarker : allow to compare in real situation different combinations of rag engines and memory plugins
  - Retrieval of YouTube playlists and PDFs for importing RAG content.
  - mem0 advanced memory
  - semantic graph RAG

# Subscription & User Onboarding

Students access the app after purchasing a product on Payhip. The purchase triggers a webhook
that auto-creates their account.

## Multi-master / Multi-training
A user can be enrolled in several training programs (one per master). After login they pick
which training to enter; the active training context is stored in `profile.active_master_id`.
See `shared/users.py` `UserEnrollment` and `user_enrollments` table.

## Webhook-to-account flow
```
Payhip purchase
  → POST /api/webhooks/payhip
  → resolve product_key → master_id (master_product_keys table)
  → create user OR add enrollment to existing user
  → send welcome email with reset code (MailerSend transactional + MailerLite automation)
  → user receives email → clicks link → sets password → enters app
```

## Email strategy
Two complementary channels, both optional but recommended:
- **MailerSend** (`MAILERSEND_API_KEY`) — immediate transactional email containing the reset code and a direct login link. Best for password setup.
- **MailerLite** (`MAILER_LITE_API` + `MAILER_LITE_GROUP_ID`) — subscriber upsert that triggers an automation campaign. Best for onboarding sequences. Template variable for the reset code: `{{ subscriber.fields.reset_code }}` (new builder) or `{$reset_code}` (classic).

Both are configurable and testable from **Admin → Debug → MailerLite** tab without touching `.env`.
