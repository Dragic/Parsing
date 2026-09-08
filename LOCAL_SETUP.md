# Local development setup (Windows, native venv, no Docker)

How to run the **Parsing** repository on a Windows workstation for development and
inspection only. Everything below was executed and verified on 2026-09-08 against
Windows 10 / PowerShell 7 / Python 3.12.10 / PostgreSQL 18 on `localhost:5432`.

> **Read [Do not run this locally](#8-do-not-run-this-locally) before starting anything.**
> These parsers normally run through **paid proxies** and **paid OpenAI** calls, and they
> write into the **real local `allvart` database**. A local instance must never be left
> running a parsing loop.

---

## 1. What this repository is

Twelve independent scrapers for Ukrainian real-estate classifieds. Each one lives in its
own directory, is a near-copy of the others, and is a **standalone program** — there is no
package, no shared library, no `__init__.py`. Every parser imports its neighbours as
top-level modules (`from settings import settings`, `import models`), so **a parser only
works when its own directory is the current working directory.**

All twelve write into the same schema — the main Allvart Laravel schema, which locally is
the PostgreSQL database `allvart`. They do not talk to each other and they do not talk to
the Laravel app; the database *is* the interface.

### Sibling services under `D:\Allvart`

| Service | Local port | Called by | Endpoint the parsers use |
| --- | --- | --- | --- |
| `Photo_duplicates_M2P` | 8008 | all 12, via `vector_service.api_send_task()` | `POST /api/v1/task/` |
| `OLX_numbers_M2P` | 8007 | `olx_parser` only, via `api_phone_service.add_task_to_phone()` | `POST /api/v1/tasks/` |
| `OLX_Messages_M2P` | 8006 | nobody in this repo | — |

Both calls are **fire-and-forget**: `vector_service.py` and `api_phone_service.py` wrap the
request in a bare `except Exception` and only log a warning. Neither service has to be
running for a parser to work — you get one `WARNING` line per skipped call.

External APIs every parser touches regardless of site: `api.privatbank.ua` for the
UAH exchange rate (`currency_api.py`, anonymous, free) and the OpenAI API
(`ai_repair.py` / `ai_agent.py`, **billed**).

---

## 2. Per-parser reference

`Entry point` is the file to run; run it **from that parser's own directory**.
`Loop` says what happens when you do: `once` = one full pass then exit,
`forever` = `while True` with sleeps, so it never stops on its own.

| Directory | Entry point | Target site | `source` value | Loop | Proxy | OpenAI | Extra scripts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `100rielty_parser` | `main.py` | 100realty.ua | `100REALTYUA` | forever | **yes** (`settings.PROXY`) | yes (`ai_repair`, `ai_agent`) | — |
| `avisoua_parser` | `parser.py` | aviso.ua | `AVISOUA` | once | no | yes (`ai_repair`) | — |
| `bomberua_parser` | `parser.py` | ua.m2bomber.com | `M2BOMBER` | once | **yes** (`requests` proxies) | yes (`ai_repair`, `ai_agent`) | — |
| `dim_ria_parser` | `ria_parser.py` | dom.ria.com | `DOMRIA` | forever | no | yes (`ai_repair`, `ai_agent`) | `test_result.py` (network probe, no DB) |
| `domikua_parser` | `parser.py` | domik.ua | `DOMIKUA` | once | no | yes (`ai_repair`, `ai_agent`) | — |
| `est_ua_parser` | `parser.py` | est.ua | `ESTUA` | once | no | yes (`ai_repair`, `ai_agent`) | — |
| `lun_main_parser` | `parser.py` | lun.ua | `LUNUA` | once | **yes** | yes (`ai_repair`) | `extract_location.py`, `link_parser_script.py`, `test_pars.py` |
| `obyavaua_parser` | `parser.py` | obyava.ua | `OBYAVAUA` | once | no | yes (`ai_repair`, `ai_agent`) | — |
| `olx_parser` | `main.py` | olx.ua API | `OLX` | once (`while True` is commented out) | **yes** | yes (`ai_repair`, `ai_agent`) | 8 further runnable scripts — **2 destructive**, see §8 |
| `rieltor_ua_parser` | `parser.py` | rieltor.ua | `RIELTORUA` | once | **yes** (proxy-seller pool, mandatory) | yes (`ai_repair`, `ai_agent`) | `pars_location.py`, `autocomplite_pars.py`, `autocomlite_revrite.py` (all write JSON files, not the DB) |
| `thecapital_parser` | `parser.py` | thecapital.com.ua | `THECAPITAL` | once | no | yes (`ai_repair`) | — |
| `valion_parser` | `parser.py` | valion.ua | `VALIONUA` | once | no | yes (`ai_repair`) | — |

**`rieltor_ua_parser` cannot run without a proxy at all** — its `__main__` block loads a
proxy-seller pool first and aborts with `No active proxies loaded` when the pool is empty.
That is the desired local behaviour; leave `PROXY_SELLER_KEY` empty.

### Tables written

Every parser writes the same core set through the same `models.py` helpers:

| Table | Written by | How |
| --- | --- | --- |
| `offers` | all 12 | `Offer.bulk_create_offers`, `Offer.bulk_update_offers`, `Offer.update` |
| `offer_logs` | all 12 | `Offer.log_change`, `Offer.batch_create_logs`, `Offer.log_new_ads` |
| `offer_views` | all 12 | via `Offer` helpers |
| `offer_similarities` | all 12 | `OfferSimilar.create_similar` |
| `offer_requests` | all 12 | read + `mark_succeeded` / `mark_failed` |
| `contacts`, `contact_platforms` | all except `thecapital_parser` | `ContactNew` / `ContactPlatform` |
| `builders_housing_complexes` | `dim_ria_parser`, `olx_parser`, `rieltor_ua_parser` | `ResidentialComplex` |
| `keywords`, `keyword_logs` | `olx_parser` only | `Keyword`, `KeywordLog` |
| `countries`, `regions`, `cities`, `districts` | **read only** by every parser | startup lookups |

---

## 3. Prerequisites

* Python 3.12 on PATH (`python --version` → 3.12.10 here).
* PostgreSQL 18 on `localhost:5432` with the `allvart` database and the `postgres`
  superuser. That is the Laravel dev database — `psql.exe` lives at
  `C:\Program Files\PostgreSQL\18\bin\psql.exe` and is **not** on PATH.
* No Docker and no WSL are needed or used.
* Nothing else. The sibling services on 8007/8008 are optional (see §1).

---

## 4. Setup from a clean checkout

### 4.1 One shared virtualenv

**One `.venv` at the repo root covers all twelve parsers.** The parsers import a common
set of packages and every pinned version is identical wherever it appears, so per-parser
environments would be twelve copies of the same thing.

What is *not* identical is the requirement *files*. Neither the root `requirements.txt`
nor the per-parser ones covers everything:

| File | Has | Missing |
| --- | --- | --- |
| `requirements.txt` (root) | `curl_cffi`, `psycopg2-binary` | `beautifulsoup4`, `lxml`, `openai` |
| `<parser>/requirements.txt` (9 of them) | `beautifulsoup4`, `lxml` | `curl_cffi`; `psycopg2-binary` in only 3; `openai` in only 1 |
| nowhere | — | `proxy_seller_user_api`, imported by `rieltor_ua_parser/parser.py` |

`requirements-local.txt` is the union. It changes **no** pinned version — it only adds what
is missing.

```powershell
cd D:\Allvart\Parsing
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-local.txt
```

All pins install cleanly on Python 3.12 / Windows with no source builds:
`curl_cffi 0.16.2`, `psycopg2-binary 2.9.10`, `SQLAlchemy 2.0.40`, `PyMySQL 1.1.1`,
`aiohttp 3.11.18`, `lxml 6.1.3`, `openai 2.28.0`. Only `proxy_seller_user_api 1.0.4` is
an sdist and builds a wheel locally (7 kB, pure Python, instant).

`PyMySQL` is still installed because it is pinned in every requirements file; after the
fixes in §10 nothing in this repo builds a MySQL URL any more, so it is dead weight rather
than a dependency.

### 4.2 Activation

You do not have to activate anything — calling `.\.venv\Scripts\python.exe` by absolute
path works from any directory and is what every example below does. If you prefer an
activated shell:

```powershell
D:\Allvart\Parsing\.venv\Scripts\Activate.ps1
```

### 4.3 A `.env` per parser directory

`settings.py` calls `load_dotenv()` with no argument, which looks for `.env` **in the
current working directory** — so each parser needs its own copy. Twelve identical files
have already been created from `env.example`; recreate them with the snippet in
`§4.4`. `.env` is gitignored; never commit it, it carries the Postgres password.

Three values differ from `env.example` on purpose:

* **`DATABASE_PORT=5432`.** `env.example` says `3306`, a leftover from the MySQL era;
  `settings.py` builds a `postgresql+psycopg2://` URL, so 3306 can never connect.
* **`VECTOR_API_URL` / `PHONE_API_URL` point at `127.0.0.1`, not left empty.** Both are
  equally safe — every failure is swallowed — but an empty value produces
  `MissingSchema: Invalid URL ''`, while the local URL produces
  `Connection refused ... 127.0.0.1:8008`, which tells you *which* service is down.
  The production defaults baked into the code are a public IP
  (`http://108.61.170.97/api/v1/task/`) and `http://0.0.0.0:2754/api/v1/tasks/`; both are
  now overridable from `.env`, and both are only reached if you delete the line.
* **`UPDATE_ADS=false`.** `settings.py` reads this as
  `False if os.getenv("UPDATE_ADS") == 'false' else True` — an **absent or empty** value
  means `True`, i.e. rewrite existing ads. The literal string `false` is the only thing
  that turns it off.

### 4.4 Regenerating all twelve `.env` files

```powershell
cd D:\Allvart\Parsing
$pw = (Get-Content 'C:\Herd\api.allvart\.env' | Where-Object { $_ -match '^DB_PASSWORD=' }) -replace '^DB_PASSWORD=',''
foreach ($p in (Get-ChildItem -Directory -Filter '*_parser').Name) {
@"
ENVIRONMENT=testing

DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_NAME=allvart
DATABASE_USER=postgres
DATABASE_PASSWORD=$pw

PROXY=
PROXY_SELLER_KEY=
OPEN_AI_TOKEN=
PROMPT_ID=
PROMPT_VERSION=
AGENT_JK_ID=
AGENT_OWNER_ID=
BOT_TOKEN=
API_HOST=
API_TOKEN=

UPDATE_ADS=false

VECTOR_API_URL=http://127.0.0.1:8008/api/v1/task/
PHONE_API_URL=http://127.0.0.1:8007/api/v1/tasks/
"@ | Set-Content -Path (Join-Path $p '.env') -Encoding utf8NoBOM
}
```

---

## 5. Two modes

`ENVIRONMENT` selects a config class in `settings.get_settings()`. A real environment
variable **wins over `.env`**, because `load_dotenv()` does not override what is already
set — that is how you switch modes without editing files.

### `ENVIRONMENT=testing` — SQLite sandbox

`DATABASE_URL` becomes `sqlite:///test.db` (or `test_db.sqlite3` in `100rielty_parser`
and `rieltor_ua_parser`), and `models.py` ends with

```python
if 'sqlite' in settings.DATABASE_URL:
    Base.metadata.create_all(engine)
```

so importing `models` builds all 14 tables in a throwaway file next to the parser.
Nothing can reach `allvart`. This is the mode to iterate in: import checks, reading the
model definitions, exercising pure functions. The DB file is gitignored.

`olx_parser`, `dim_ria_parser`, `lun_main_parser`, `thecapital_parser` and
`valion_parser` also set `TEST = True` here, which turns on `database.py`'s query
tracker — every SQL statement is echoed to the console.

### `ENVIRONMENT=development` — the real `allvart`

`DATABASE_URL` becomes `postgresql+psycopg2://postgres:***@localhost:5432/allvart`.
This is the **live Laravel dev database with real data** (2 470 358 rows in `offers` as of
2026-09-08). Use it for read-only inspection: confirming the models still match the
schema, looking at what a parser would read at startup, checking a specific offer.
Do not use it to run a parser.

---

## 6. Running a parser

Always `cd` into the parser's directory first — every import in the repo assumes it.

```powershell
cd D:\Allvart\Parsing\avisoua_parser
$env:ENVIRONMENT = 'testing'
D:\Allvart\Parsing\.venv\Scripts\python.exe parser.py
```

`$env:ENVIRONMENT` persists for the rest of that PowerShell session. Clear it with
`Remove-Item Env:\ENVIRONMENT` to fall back to the `.env` value.

**But do not actually run the line above against a live site** — see §8. What you should
run locally is the import check, which loads every module, builds the schema and stops
before any network call or loop:

```powershell
cd D:\Allvart\Parsing\avisoua_parser
$env:ENVIRONMENT = 'testing'
D:\Allvart\Parsing\.venv\Scripts\python.exe -c "import parser; print('OK')"
```

---

## 7. Smoke-test checklist

### 7.1 Every parser imports and builds its schema (`testing`)

Run this from each parser directory, substituting the entry module name
(`main`, `parser` or `ria_parser`):

```powershell
$env:ENVIRONMENT = 'testing'
D:\Allvart\Parsing\.venv\Scripts\python.exe -c "import database, parser; print('OK', database.engine.url.render_as_string(hide_password=True))"
```

Expected — verified for all 12:

```
100rielty_parser     main.py        OK sqlite:///D:\Allvart\Parsing\100rielty_parser\test_db.sqlite3
avisoua_parser       parser.py      OK sqlite:///test.db
bomberua_parser      parser.py      OK sqlite:///test.db
dim_ria_parser       ria_parser.py  OK sqlite:///test.db
domikua_parser       parser.py      OK sqlite:///test.db
est_ua_parser        parser.py      OK sqlite:///test.db
lun_main_parser      parser.py      OK sqlite:///test.db
obyavaua_parser      parser.py      OK sqlite:///test.db
olx_parser           main.py        OK sqlite:///test.db
rieltor_ua_parser    parser.py      OK sqlite:///D:\Allvart\Parsing\rieltor_ua_parser\test_db.sqlite3
thecapital_parser    parser.py      OK sqlite:///test.db
valion_parser        parser.py      OK sqlite:///test.db
```

This is not a trivial check. Six parsers
(`100rielty`, `avisoua`, `bomberua`, `domikua`, `est_ua`, `obyavaua`) run a **database
query at import time** — `CITIES_FOR_DUPLICATES = models.City.get_region_city_settings(region_id=10)`
sits at module level in their entry file. If the import succeeds, the connection works.

Then confirm the sandbox schema is real:

```powershell
D:\Allvart\Parsing\.venv\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect(r'D:\Allvart\Parsing\avisoua_parser\test.db'); print(sorted(r[0] for r in c.execute('select name from sqlite_master where type=\"table\"')))"
```

Expected: 14 tables —
`builders_housing_complexes, cities, contact_platforms, contacts, countries, districts,
keyword_logs, keywords, offer_logs, offer_requests, offer_similarities, offer_views,
offers, regions`.

### 7.2 Read-only query against `allvart` (`development`)

Force the Postgres session read-only first, so nothing can write even by accident. Save
this as `check.py` inside the parser directory, run it, then delete it:

```python
import sys, os
sys.path.insert(0, os.getcwd())
from sqlalchemy import event, text
import database

@event.listens_for(database.engine, "connect")
def _read_only(dbapi_conn, _):
    with dbapi_conn.cursor() as cur:
        cur.execute("SET default_transaction_read_only = on")

import models

with database.engine.connect() as c:
    print("db =", c.execute(text("select current_database()")).scalar(),
          "| read_only =", c.execute(text("show default_transaction_read_only")).scalar())

print("cities in region 10 :", len(models.City.get_region_city_settings(region_id=10)))
print("parsing regions     :", len(models.Region.get_all_cities_from_parsing_regions(country_id=1)))
```

```powershell
cd D:\Allvart\Parsing\olx_parser
$env:ENVIRONMENT = 'development'
D:\Allvart\Parsing\.venv\Scripts\python.exe check.py
```

Expected output, verified 2026-09-08 for all 12 parsers:

```
db = allvart | read_only = on
cities in region 10 : 48
parsing regions     : 24
```

`dim_ria_parser` is the exception: its `models.py` has no `City.get_region_city_settings`,
use `Region.get_all_cities_from_parsing_regions_domria(country_id=1)` instead (also 24).
Its `database.py` also runs the query tracker unconditionally, so expect several hundred
lines of SQL logging on the console for that one.

### 7.3 Schema drift

Verified 2026-09-08 across all 12 parsers: **no model column is missing from the live
database.** Every mapped table exists and every mapped column is present.

The live schema does carry columns the parsers do not map. That direction is harmless —
SQLAlchemy only selects what it maps, and every one of them is nullable or Laravel-managed:

| Table | Columns in `allvart` that no parser maps |
| --- | --- |
| `offers` | `callback`, `duplicate_group_id`, `map_position`, `price_m2`, `search_vector` |
| `cities` | `domria_id`, `latitude`, `longitude`, `lun_id`*, `rieltorua_id`* |
| `regions` | `domria_id` |
| `districts` | `domria_id` |
| `countries` | `currencies` |
| `builders_housing_complexes` | `created_at`, `updated_at`, `deleted_at`, `search_vector` |

\* `olx_parser` and `rieltor_ua_parser` *do* map `lun_id` and `rieltorua_id`;
`lun_main_parser` maps `lun_id`. The other nine map neither. This is the clearest sign of
how far the twelve `models.py` copies have drifted from each other.

---

## 8. Do not run this locally

### 8.1 Full parsing loops

Do not run any entry point against its real site. Reasons, in order of cost:

* **`100rielty_parser` and `dim_ria_parser` never stop** — `while True` with 1–15 minute
  sleeps. Started once and forgotten, they keep hitting the site and writing to `allvart`.
* **They write to the dev DB.** `bulk_create_offers`, `bulk_update_offers`,
  `log_change`, `create_similar` all commit. `UPDATE_ADS=false` limits *rewrites* of
  existing ads; it does not stop inserts.
* **Proxy traffic is billed per GB** (`100rielty`, `bomberua`, `lun_main`, `olx`,
  `rieltor_ua`).
* **OpenAI is billed per token.** `ai_repair.has_repair()` fires per listing whose text
  contains "ремонт"; `ai_agent` fires per listing in the AI-enabled property types.
* Unproxied scraping from a workstation IP gets that IP rate-limited or banned by the
  target site, which then affects production too.

**An empty `PROXY=` does not protect you.** Measured on this machine: `aiohttp` and
`requests` both treat `proxy=""` as *no proxy* and connect **directly**. The string
`"None"` (the code default in `bomberua_parser` and `est_ua_parser`) and `"root"`
(`lun_main_parser`) do fail fast with `InvalidURL`, but an empty value from `.env` does
not. The only reliable protection is not starting the loop.

### 8.2 `olx_parser`'s delete / cleanup scripts — never against `allvart`

Two remain, and **both work against `allvart` today**. Neither has a dry-run or a
confirmation prompt:

| Script | What it does | Against `allvart` |
| --- | --- | --- |
| `delete_dublicat.py` | ORM scan of **all** `offers` grouped by `(source, ad_id)`; deletes every row but the newest in each group. Touches the whole table, not a subset. | **Runs and deletes.** The most dangerous file in the repo. |
| `clear_script_duble.py` | Batched `DELETE` of duplicate `created` rows in `offer_logs`, 100 000 at a time, keeping the newest per offer. | **Runs and deletes** since the Postgres rewrite (§12). It finds nothing on clean data — there are currently 0 duplicate groups — but that is the data's state, not a guard. |

The other two — `delete_old_records.py` and `delete_list.py` — were deleted, see §12.

One more `olx_parser` script mutates data without deleting:

* `is_realtor_script.py` — raw `UPDATE offers SET is_realtor = 1 ...` over the whole table.

And two write to shared tables over the network, one row at a time:

* `realtors_link_parser.py` — fills `contact_platforms.link` for OLX contacts that have
  none (~38 000 rows), one unproxied `olx.ua/api/v1/users/{id}` call each. Slow, chatty,
  and it hits OLX from the workstation IP.
* `notification_script.py` — polls every offer in `notifications_log` against the OLX API,
  writes `offers.price` / `deleted_at` / `is_top`, appends to `offer_logs` and POSTs to the
  Laravel app so it mails real users. **Never point it at a production `API_HOST`.**

### 8.3 Anything using paid credentials

Keep `PROXY`, `PROXY_SELLER_KEY`, `OPEN_AI_TOKEN`, `PROMPT_ID`, `AGENT_JK_ID`,
`AGENT_OWNER_ID` and `BOT_TOKEN` empty. With empty values:

* `ai_repair.py` and `ai_agent.py` still **import** (the `AsyncOpenAI` client is built at
  module level but does not validate the key), and every call site is wrapped in
  `try/except` returning a safe default — so nothing crashes, and nothing is billed.
* `send_message.py` (Telegram) posts to `.../bot/sendMessage` and logs the failure.
* `rieltor_ua_parser` refuses to start, by design.

### 8.4 Network probes that are safe

`lun_main_parser/test_pars.py`, `dim_ria_parser/test_result.py` and
`lun_main_parser/link_parser_script.py` fetch a single
page and print the parsed result. No DB, no proxy, no OpenAI. They are fine for checking
whether a site's markup has changed — one request each.

---

## 9. Divergences between the twelve parsers

The twelve directories look like copies. They are not. Byte-identical everywhere:
`currency_api.py`, `ai_repair.py`, `validate_addition_params.py`. Everything else varies.

### `settings.py` — 10 distinct versions across 12 files

Only two pairs match: `avisoua`/`domikua`, and `bomberua`/`est_ua`.

| What varies | Detail |
| --- | --- |
| `PROXY` default | `None` (`100rielty`, `olx`) / `""` (`rieltor_ua`) / the **string** `"None"` (`bomberua`, `est_ua`) / the **string** `"root"` (`lun_main`) / absent entirely (`avisoua`, `dim_ria`, `domikua`, `obyavaua`, `thecapital`, `valion`) |
| `OPEN_AI_TOKEN` | present in 11; **was missing from `thecapital_parser`** although its `ai_repair.py` reads it — see §10 |
| `BOT_TOKEN`, `API_HOST`, `API_TOKEN`, `AGENT_*`, `ALLOWED_CATEGORIES`, `SLUG_TYPE_OBJ` | `olx_parser` only |
| `PROXY_SELLER_KEY` | `olx_parser`, `rieltor_ua_parser` only |
| `TestingConfig.DATABASE_URL` | `sqlite:///test.db` (10) / `sqlite:///{BASE_DIR}/test_db.sqlite3` (`100rielty`, `rieltor_ua`) — the second form is CWD-independent, the first is not |
| `TEST` flag | set in 5 of 12; it gates `database.py`'s SQL echo |

### `database.py` — 6 distinct versions

| Variant | Parsers | Behaviour |
| --- | --- | --- |
| SQLite-aware engine + `DatabaseQueryLogger` gated on `settings.TEST` | `olx`, `lun_main`, `thecapital`, `valion` | the reference implementation |
| same, but the query logger runs **unconditionally** | `dim_ria` | hundreds of SQL lines on every run, in every mode |
| SQLite-aware engine, no logger | `bomberua`, `est_ua` | fine |
| no `connect_timeout` at all | `100rielty`, `rieltor_ua` | fine in both modes |
| `connect_timeout` passed **unconditionally** | `avisoua`, `domikua`, `obyavaua` | **was broken** under SQLite — see §10 |

Session handling also differs: `100rielty`, `olx` and `dim_ria` open a fresh session per
`db_session()` block; the other nine reuse one module-level `session` and call `.close()`
on it inside the context manager.

### `models.py` — 6 distinct versions

Five before the §12 cleanup: `olx` and `rieltor_ua` were byte-identical and now are not.
Same 14 model classes and the same 14 tables everywhere, except `olx`, which since that
cleanup has a 15th: `UserOfferTracking` on `notifications_log`, uncommented and
retargeted for `notification_script.py`. In the other eleven it is still a commented-out
block naming the wrong table. The differences otherwise are
column coverage: `olx`/`rieltor_ua` (~1250 lines) map the most, `dim_ria` (1159) the fewest, and
`dim_ria` alone drops `City.get_region_city_settings` and adds
`Region.get_all_cities_from_parsing_regions_domria`.

### Other shared modules

* `log.py` — two versions. Six parsers write a single unbounded `logs.log`; `olx`,
  `dim_ria`, `lun_main`, `rieltor_ua`, `thecapital`, `valion` use a rotating
  `logs/app.log` (5 MB × 5) **and** echo to the console.
* `vector_service.py` — identical except `olx_parser` additionally logs the payload on
  HTTP 422.
* `config.py` — exists in 9 parsers, absent in `100rielty`, `dim_ria`, `olx`.
  `lun_main` appends a `REGIONS` list (marked "not used now"), `rieltor_ua` appends a
  `city_pages` map and a newer User-Agent.
* `ai_agent.py` — in 8 parsers, 4 distinct versions.
* `location_api.py` — `olx` and `rieltor_ua` share one version, `dim_ria` has its own.

---

## 10. Changes made for local development

Eight files were modified, all minimal and all in the direction of "match what the other
parsers already do". Nothing was committed.

| File | Change | Why |
| --- | --- | --- |
| `olx_parser/settings.py` | added `PHONE_API_URL`, defaulting to the previous hardcoded `http://0.0.0.0:2754/api/v1/tasks/` | make the phone-service URL configurable |
| `olx_parser/api_phone_service.py` | uses `settings.PHONE_API_URL` instead of the literal | same |
| `avisoua_parser/database.py`, `domikua_parser/database.py`, `obyavaua_parser/database.py` | wrap `connect_timeout` in `if 'sqlite' in settings.DATABASE_URL` — the exact branch `bomberua`/`est_ua`/`olx` already have | without it `ENVIRONMENT=testing` dies with `TypeError: 'connect_timeout' is an invalid keyword argument for Connection()`; the SQLite sandbox was unusable in these three |
| `dim_ria_parser/settings.py` | `TestingConfig.DATABASE_URL` was `mysql+pymysql://test_user:db_password@mysql:3306/test_db`, now `sqlite:///test.db` like the others | `ENVIRONMENT=testing` was not a sandbox here at all — it pointed at a Docker MySQL host that does not exist locally |
| `thecapital_parser/settings.py` | added `OPEN_AI_TOKEN` | `thecapital_parser/ai_repair.py` reads `settings.OPEN_AI_TOKEN` at import; without it `parser.py` died with `AttributeError: 'TestingConfig' object has no attribute 'OPEN_AI_TOKEN'` in **every** mode |
| `rieltor_ua_parser/settings.py` | `DATABASE_URL` was still `mysql+pymysql://...`, now `postgresql+psycopg2://...` like the other 11 | it was the last parser pointing at MySQL; it could not reach `allvart` |
| `.gitignore` | added `.venv` and `logs/` | the existing file ignored `venv` but not `.venv` |

Added (untracked): `requirements-local.txt`, `.venv/`, and one `.env` per parser directory.

---

## 11. Troubleshooting

**`ModuleNotFoundError: No module named 'settings'`**
You are not in the parser's directory, or you ran a script by absolute path from
elsewhere. Python puts the *script's* directory on `sys.path`, not the CWD. `cd` into the
parser first and use a relative filename.

**`TypeError: 'connect_timeout' is an invalid keyword argument for Connection()`**
`ENVIRONMENT=testing` with a `database.py` that passes `connect_timeout` unconditionally.
Fixed in the three parsers that had it (§10); if it reappears, that file was reverted.

**`ModuleNotFoundError: No module named 'proxy_seller_user_api'`**
`rieltor_ua_parser` only. `pip install proxy_seller_user_api==1.0.4`, or reinstall
`requirements-local.txt` — it is listed in no requirements file in the repo.

**`AttributeError: ... object has no attribute 'OPEN_AI_TOKEN'`**
`thecapital_parser` with §10 reverted.

**`connection to server at "localhost", port 5432 failed`**
Either PostgreSQL is not running, or `.env` still has `DATABASE_PORT=3306` from
`env.example`.

**`OperationalError: could not translate host name "mysql"`**
`.env` is not being found — `settings.py` fell back to its Docker defaults
(`DATABASE_HOST=mysql`). You are in the wrong directory, or that parser has no `.env`.

**The parser starts but seems to do nothing, and the console fills with SQL**
`dim_ria_parser`, or any parser where `TEST = True`. That is `database.py`'s query
tracker, not an error.

**`WARNING Error during send vector api - ... 127.0.0.1:8008`**
`Photo_duplicates_M2P` is not running. Harmless — the call is fire-and-forget.

**`InvalidURL: None` / `ProxyError ... host='none'`**
`PROXY` resolved to the literal string `"None"` or `"root"` (the code defaults in
`bomberua`, `est_ua`, `lun_main`). It also means the parser tried to make a real request;
it should not have been running.

---

## 12. Dead maintenance scripts — cleaned up 2026-09-08

The eight scripts that referenced removed models, plus the two MySQL-only deletes and the
stray `test_pars.py` copy, were audited against the live `allvart` schema and the Laravel
app at `C:\Herd\api.allvart`. Three were fixed, eight were deleted. Nothing was
committed; everything is in the working tree.

### 12.1 Fixed

| File | Was | Now |
| --- | --- | --- |
| `olx_parser/models.py` | `UserOfferTracking` commented out, pointing at `notifications` | live model on **`notifications_log`**, the table Laravel's `App\Models\Parsing\ParsingNotification` uses. Laravel took `notifications` for its own notifiable records |
| `olx_parser/notification_script.py` | `models.UserOfferTracking` missing; wrote the dropped `offers.base_price` from an un-awaited coroutine; `logg.warning(a, b, c)` used positional args as a format string | reads the revived model; writes `price` + `currency` (lower-cased, as `main.py` stores it); the log call is an f-string |
| `olx_parser/realtors_link_parser.py` | `models.Contact.platform` / `.author_link` | `models.ContactPlatform.platform` / `.link`, plus a `user_id IS NOT NULL` guard. ~38 000 OLX rows still have no link |
| `olx_parser/clear_script_duble.py` | MySQL `DELETE o1 FROM … JOIN …`, a stray `;` before `LIMIT`, a self-join that matched a `created` row against a row of **any** type, and a `while True` that retried a failing statement forever | `DELETE … USING (SELECT DISTINCT … LIMIT :batch_size)`, `change_type` pinned on both sides of the join, and the loop breaks on error. Verified with `EXPLAIN` against `allvart` |

`notification_script.py` is **load-bearing**, not scratch work: it is the only caller of
`POST /api/parser/log/{log}` in this repo and in the three sibling services, and that
endpoint is what fans out price-change / deleted / is_top notifications to users. Its
change types (`price_change`, `is_top`, `deleted`) still match `NotificationTypeEnum` and
the `offer_log_change_type_enum` in the database exactly.

### 12.2 Deleted, and why

| File | Why |
| --- | --- |
| `olx_parser/complete_offer_ads.py` | copied `raw_offers` → `offers`. There is no `raw_offers` table and no mention of one anywhere in the Laravel app; the target columns it wrote (`author_id`, `author_link`, `irrelevance`, `irrelevant_users`) are gone from `offers` too |
| `olx_parser/delete_old_records.py` | half of it deleted from `RawOffer` (gone); the other half was a blanket `DELETE FROM offers WHERE created_at < now() - 90 days`. `offers` is now RANGE-partitioned by `created_at` and deliberately keeps ~16 months — 1.64 M of its 2.47 M rows are older than 90 days. Retention here is a partition drop, not a row delete |
| `olx_parser/extract_realtors.py`, `olx_parser/set_phone.py` | the export-to-JSON → fill-by-hand → import-JSON phone backfill. Superseded by `api_phone_service.add_task_to_phone()` → the `OLX_numbers_M2P` service, which owns writing `contacts` / `contact_platforms` phones and is re-queued automatically by `main.py`'s `get_or_create_contact` on every contact still missing one. `olx_parser/realtors_without_phone.json` is the leftover artefact of the last manual run and is now orphaned |
| `olx_parser/realtors_without_city.py` | filled a realtor's city from the majority city of their OLX ads, one API call per realtor. Superseded by Laravel's `contacts:backfill-cities` (`App\Services\Realtors\ContactCityBackfiller`), scheduled weekly, which does the same majority vote in one SQL statement for every platform and never touches the network |
| `olx_parser/delete_list.py` | MySQL-only duplicate delete over a hardcoded list of ~900 `ad_id`s from a past incident, and its `source = 'olx'` literal does not even exist in the `platform_enum` (values are upper-case). `delete_dublicat.py` is the general, working, dialect-neutral version of the same job |
| `est_ua_parser/migrate_phone.py` | one-off migration of `offers.contact_id` → `offers.contact_new_id` via the old `contacts` table. `contact_new_id` no longer exists (the migration finished and the column became `contact_id`), and the old table was dropped by `2026_05_22_120100_drop_legacy_realtors_and_contacts_old` |
| `thecapital_parser/test_pars.py` | a byte-identical copy of `lun_main_parser/test_pars.py`: LUN's Next.js `__next_f.push` payload, `lunstatic.net` image URLs, `source: 'LUNUA'`. thecapital.com.ua is plain server-rendered HTML with a different shape, so retargeting it would mean writing a new probe that duplicates `thecapital_parser/parser.py`. The original stays in `lun_main_parser` |

The `realtors` and `contacts_old` tables behind `Realtor` and `Contact` were dropped
deliberately on 2026-05-22 by the Laravel migration named above, which records that they
had no model and no references left. That is why those two Python models had nowhere to
map to.

### 12.3 Still broken, left alone

* **`Offer.count_authors_offers`** (all 12 `models.py`) queries `cls.author_id`, a column
  that no longer exists on `offers`. Nothing in the repo calls it, so it fails only if
  someone starts. Fixing it means touching twelve near-copies of `models.py` for dead code.
* **`olx_parser/local_db.py` + `local_models.py`** are imported by nothing but each other.
  `local_models.py` runs `Base.metadata.create_all(engine)` at import and would create a
  `local_db.sqlite3` beside the parser.
* **`env.example` ships `DATABASE_PORT=3306`** in all 12 parsers while every
  `settings.py` now builds a PostgreSQL URL. Anyone copying `env.example` verbatim gets a
  connection that cannot work.
* **`env.example` never mentions `OPEN_AI_TOKEN`, `AGENT_JK_ID`, `AGENT_OWNER_ID` or
  `PROXY_SELLER_KEY`** (the last only in `rieltor_ua_parser`'s copy), all of which
  `settings.py` reads.
