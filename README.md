# 🤖 X Poster Bot — Telegram → X (auto-poster planifié)

Bot asynchrone, autonome 24/7 et résilient. Il **surveille un/des canaux Telegram**,
détecte les **vidéos**, les **télécharge + vérifie**, et les **publie sur X** selon
un planning strict (**1 toutes les 3 h** par défaut), avec file d'attente persistée,
retries intelligents, anti-rate-limit, dédup, compression et monitoring.

> ✅ **Déploiement 100 % cloud : GitHub + Railway. Rien à exécuter en local.**

---

## ✨ Fonctionnalités

- 📡 **Ingestion automatique** depuis un/des canaux (le bot doit y être admin).
- 🎬 Détection vidéo (video, animation, document vidéo) + **téléchargement**.
- 🧪 **Vérification multiple** : taille stable, checksum SHA-256, sonde ffprobe
  (durée/dimensions/flux), bornes X.
- 🗂️ **File d'attente durable** (base de données = source de vérité ; Redis optionnel).
- ⏱️ **Planification** « 1 vidéo / 3 h », FIFO, **résiliente au redémarrage**
  (créneau persisté) et **auto-rattrapante**.
- 🐦 **Publication X** : **2 modes** — `unofficial` (compte X **sans clés dev**,
  via twikit) ou `official` (Tweepy, upload chunked v1.1 + tweet v2).
- 🛡️ **Robustesse extrême** : retries backoff+jitter (**7 tentatives**), gestion
  fine des rate-limits (lecture de `x-rate-limit-reset`), erreurs serveur,
  suspensions, instabilités réseau ; **aucune erreur visible**.
- ♻️ **Reprise exacte** après crash (machine à états + reprise des jobs en cours).
- 🔁 **Dédup** par `file_unique_id` (Telegram) et par **checksum** (contenu).
- 🗜️ **Compression intelligente** (ffmpeg, par paliers) si la vidéo dépasse X.
- 🏷️ **Légende auto** (template + hashtags, tronquée à 280).
- 📊 **Monitoring** : commandes `/status /pause /resume /next`, notifications admin,
  logs structurés + rotation.

---

## 🧱 Architecture (design patterns)

- **Injection de dépendances** : `app/container.py` (composition root).
- **Repository pattern** : `app/db/repositories/`.
- **Service layer** : `app/services/`.
- **Strategy** : backend de file (`app/queue/`), interfaces `app/core/interfaces.py`.
- **State machine** : `app/core/state_machine.py` (transitions validées).
- **Décorateurs** : `@silent`, `@timed`, `@async_retry` (`app/utils/`).
- **Hiérarchie d'exceptions** Retryable vs Fatal : `app/core/exceptions.py`.

```
app/
├── __main__.py              # entrée + boucle polling
├── container.py             # DI / câblage
├── config/settings.py
├── core/                    # enums, exceptions, interfaces (ABC), state machine
├── models/                  # ORM : video, system_state, post_log
├── db/                      # engine + repositories
├── services/                # ingest, download, verification, compression,
│                            #   x_client, publish, monitoring
├── queue/                   # db_backend (défaut) + redis_backend
├── schedulers/              # posting_scheduler (APScheduler, tick + créneau)
├── handlers/                # channel_posts, admin_commands, errors
├── middlewares/access.py
└── utils/                   # logging, retry, files, decorators, timeutils
alembic/ + alembic.ini · Dockerfile · railway.json · .env.example
```

---

## 🔄 Cycle de vie d'une vidéo (machine à états)

```
PENDING → DOWNLOADING → DOWNLOADED → VERIFYING → READY
                                                   │
                                          (planning, 1/3h)
                                                   ▼
                                    PUBLISHING → PUBLISHED ✅
   doublon → SKIPPED_DUPLICATE                  └→ (échec) READY/FAILED
```

---

## 🚀 Déploiement (GitHub + Railway)

### Étape 0 — Telegram
1. **@BotFather** → `/newbot` → récupère **`BOT_TOKEN`**.
2. **@BotFather** → `/setprivacy` → **Disable** (pour bien recevoir les posts).
3. Crée/choisis ton **canal source**, ajoute le **bot comme administrateur**.
4. Récupère l'**id du canal** (`-100…`) : transfère un message du canal à
   [@userinfobot](https://t.me/userinfobot), ou lis-le dans les logs. → `SOURCE_CHANNELS`
5. Ton **user-id** (via @userinfobot) → `ADMIN_USER_IDS` et `ADMIN_CHAT_ID`.

### Étape 1 — X / Twitter (2 modes possibles)

**🅰️ Mode `unofficial` — SANS compte développeur (défaut, le plus simple)**
On se connecte avec un **compte X classique** via `twikit`.
- `X_MODE=unofficial`
- `X_USERNAME` (handle sans @), `X_EMAIL`, `X_PASSWORD`
- Si 2FA : `X_TOTP_SECRET` (le secret de ton app d'authentification)
> ⚠️ **Avertissement** : automatiser un compte via un client non-officiel est
> **contraire aux CGU de X** et peut entraîner une **suspension**. Utilise un
> compte que tu acceptes de risquer, garde l'espacement (3 h), active la 2FA.
> Les cookies de session sont mémorisés en base pour limiter les reconnexions.

**🅱️ Mode `official` — avec compte développeur (developer.x.com)**
- `X_MODE=official`
- App **OAuth 1.0a + Read and Write** → `X_CONSUMER_KEY/SECRET`,
  `X_ACCESS_TOKEN/SECRET`
- ⚠️ Régénère les Access Tokens **après** avoir mis Read+Write.

### Étape 2 — GitHub
Crée un dépôt privé et **glisse tout le contenu** du dossier `x-poster-bot` à la
racine (dossiers `app/`, `alembic/` + `Dockerfile`, `railway.json`,
`requirements.txt`…). Voir la note « pièges d'upload » plus bas.

### Étape 3 — Railway
1. **New Project → Deploy from GitHub repo** → sélectionne le dépôt.
2. **New → Database → PostgreSQL** (recommandé).
3. Onglet **Variables** du service bot : colle le bloc ci-dessous.

### Étape 4 — Variables Railway (Raw Editor)

```
BOT_TOKEN=
SOURCE_CHANNELS=-1001234567890
ADMIN_CHAT_ID=
ADMIN_USER_IDS=
X_MODE=unofficial
X_USERNAME=
X_EMAIL=
X_PASSWORD=
X_TOTP_SECRET=
DATABASE_URL=postgresql+asyncpg://${{Postgres.PGUSER}}:${{Postgres.PGPASSWORD}}@${{Postgres.PGHOST}}:${{Postgres.PGPORT}}/${{Postgres.PGDATABASE}}
QUEUE_BACKEND=db
POST_INTERVAL_SECONDS=10800
SCHEDULER_TICK_SECONDS=60
LOG_JSON=true
```

> Mode développeur : remplace les `X_USERNAME/EMAIL/PASSWORD` par `X_MODE=official`
> + les 4 clés `X_CONSUMER_*` / `X_ACCESS_*`.

> Remplace `Postgres` par le nom exact de ton plugin si différent. Liste complète
> et commentée dans **`.env.example`**.

### Étape 5 — Vérifier
Logs Railway → tu dois voir `db.initialized`, `scheduler.started`, `boot.ready`.
Le bot t'envoie « 🤖 Bot démarré » en privé. Teste `/status`.

---

## 🕹️ Utilisation & monitoring

| Commande | Effet |
|---|---|
| `/status` | File d'attente, publiés, échecs, prochain créneau |
| `/pause` / `/resume` | Suspendre / reprendre la publication |
| `/next` | Publier immédiatement (hors planning) |
| `/id` | Afficher chat_id / user_id |

Poste une vidéo dans le canal surveillé → elle est ingérée, vérifiée, mise en file,
puis publiée au prochain créneau. Suis tout via `/status` et les notifications.

---

## 🛡️ Stratégies anti-rate-limit & anti-erreur

- **Backoff exponentiel + full jitter**, jusqu'à 7 tentatives (`utils/retry.py`).
- **Respect des délais serveur** : lecture de `retry-after` / `x-rate-limit-reset`
  des réponses X → on attend exactement le temps imposé.
- **Classement des erreurs** : `RetryableError` (réseau, 429, 5xx) → on réessaie ;
  `FatalError` (token invalide, contenu refusé, suspension) → on abandonne vite.
- **Espacement** : sur échec réessayable, le planificateur ne re-tente pas en boucle
  serrée (court délai), évitant de marteler X.
- **Vérifications avant action** : intégrité fichier (×) + credentials X au boot +
  re-vérification juste avant chaque publication (+ re-téléchargement de secours).
- **Idempotence & dédup** : aucune vidéo publiée deux fois (état persistant +
  `file_unique_id` + checksum).

---

## ⚠️ Limites & notes importantes

- **Limite de téléchargement Telegram = 20 Mo** via l'API Bot standard. Pour des
  vidéos plus lourdes, lance un **serveur Bot API local** et renseigne
  `TELEGRAM_API_URL` (la limite passe à 2 Go). Sinon, ces vidéos sont marquées
  en échec (proprement, sans crash).
- **PostgreSQL** : préfixe `postgresql+asyncpg://` (pas `postgres://`).
- **SQLite sans Volume** : la base et les fichiers sont perdus au redéploiement →
  utilise **PostgreSQL** + (si besoin) un **Volume** sur `/app/data`.
- **Politique X** : respecte les CGU de X, le droit d'auteur et la vie privée.
  Tu es responsable du contenu republié.

---

## 🧩 Dépannage

| Symptôme | Piste |
|---|---|
| Aucune vidéo détectée | Bot admin du canal ? Privacy désactivée (@BotFather) ? `SOURCE_CHANNELS` correct ? |
| `x.healthcheck_failed` / `twikit.cookies_invalid` | unofficial : identifiants erronés, ou 2FA → renseigne `X_TOTP_SECRET`, ou challenge X à valider. official : régénère les Access Tokens en Read+Write |
| Vidéos « FAILED » immédiates | Souvent > 20 Mo → serveur Bot API local requis |
| Rien ne se publie | `/status` : en pause ? prochain créneau ? file vide ? |
| Base perdue au redeploy | Passe en PostgreSQL (ou Volume sur `/app/data`) |
```
