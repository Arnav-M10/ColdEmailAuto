# Professor Outreach Manager — Complete Project Specification for Codex

## 0. Purpose of This Document

You are Codex, acting as the lead software engineer, security engineer, data engineer, product designer, and QA engineer for this repository.

Your task is to build a **local, human-supervised Professor Outreach Manager** for Arnav Mittal. The application should reduce repetitive work involved in identifying suitable researchers, finding their recent publications, retrieving lawful full-text papers, analyzing those papers, creating truthful personalized outreach emails, saving those emails as Microsoft Outlook drafts, and tracking replies and follow-ups.

This is **not** a mass-emailing system.

This is **not** an autonomous sales or marketing tool.

This is **not** a system that may send messages without explicit human approval.

The application must preserve the quality of a careful paper-first outreach workflow while automating discovery, organization, retrieval, analysis, drafting, and tracking.

The project should be built incrementally. Do not attempt to implement every advanced capability in one uncontrolled pass. Start with a safe, functional MVP, test it thoroughly, and then add capabilities in clearly separated phases.

---

# 1. Non-Negotiable Product Principles

These principles override convenience, speed, and feature completeness.

## 1.1 Human approval is mandatory

The application must never send an email automatically.

The strongest technical enforcement is preferred:

- Do not request the Microsoft Graph `Mail.Send` permission.
- Do not implement a send endpoint.
- Do not include a hidden or disabled send button.
- Do not create a background sending process.
- Do not use browser automation to click Outlook’s Send button.
- Do not use SMTP.
- Do not use any workaround that sends mail indirectly.
- Do not create future-send or scheduled-send messages.
- Stop at creating a reviewable draft in the signed-in user’s Outlook mailbox.

The user will manually open Outlook, inspect the draft, and press Send.

## 1.2 No mass outreach

The system should optimize for quality, not volume.

Default limits:

- Maximum 10 newly discovered candidates per department import.
- Maximum 5 candidates approved for paper retrieval in one batch.
- Maximum 3 email drafts generated per day.
- Maximum 2 researchers from the same institution in a rolling 7-day period.
- Maximum 1 researcher from the same laboratory, center, or closely connected research group in a rolling 14-day period, unless the user explicitly overrides the warning.
- No bulk “approve all.”
- No bulk draft creation without reviewing each candidate card.

These are application safeguards. Make the limits configurable in Settings, but require an explicit warning acknowledgment to raise them.

## 1.3 Full-paper analysis before drafting

Do not draft a research-specific email from:

- a Google Scholar title list;
- an abstract alone;
- publication metadata alone;
- a news article;
- a laboratory description;
- a third-party summary;
- a search-result snippet;
- a conference title with no paper;
- citation counts;
- author keywords alone.

At least one complete, lawfully obtained paper must be parsed and analyzed before a research-specific email may reach `DRAFT_READY`.

A second paper is optional but preferred when it adds a genuinely distinct and useful connection.

If no full paper is available, mark the candidate as `NO_FULL_TEXT` and do not generate a paper-specific draft.

## 1.4 Truthfulness over persuasion

Every technical statement in an email must be traceable to the analyzed paper.

Do not embellish.

Do not claim that Arnav:

- implemented a technique he did not implement;
- understands a field at a graduate level;
- has prior experience with tools he has not used;
- reproduced a professor’s result;
- independently derived the paper’s results;
- has expertise in a specialized topic merely because it appears adjacent to his projects;
- is seeking a guaranteed publication;
- can contribute more hours than he has stated;
- can travel or relocate unless the user explicitly adds that information;
- is affiliated with an institution or laboratory beyond what is stated in his profile.

The preferred sentence may use:

> I enjoyed reading your paper...

That sentence is allowed. However, the rest of the paragraph must use accurate, concrete details extracted from the paper and must not imply unsupported mastery.

## 1.5 Never bypass access controls

The application may download only:

- open-access publisher PDFs;
- arXiv PDFs;
- institutional repository copies;
- author-hosted manuscripts;
- public preprints;
- public technical reports;
- public conference papers;
- other clearly lawful public copies.

The application must never:

- bypass a paywall;
- use stolen credentials;
- use shadow libraries;
- evade robots or access restrictions;
- exploit publisher endpoints;
- download through a user’s institutional access without explicit action and authorization;
- defeat CAPTCHA;
- rotate proxies to evade blocking;
- scrape a source that prohibits automated access;
- masquerade as a browser to circumvent restrictions.

When access is unavailable, record the DOI and metadata, flag the item, and ask the user to upload a lawful copy manually.

## 1.6 Do not scrape Google Scholar

Google Scholar may be used manually by the user as a discovery aid, but this application must not automate Google Scholar scraping.

Use supported or reasonably automation-friendly sources, such as:

- official university faculty directories;
- official faculty homepages;
- OpenAlex;
- Crossref;
- arXiv;
- ORCID;
- institutional repositories;
- publisher open-access metadata;
- NASA ADS only if the user later supplies valid API access and its terms permit the workflow.

All source adapters must respect current API terms, rate limits, and attribution requirements.

## 1.7 Official email addresses only

The system may store and use only an email address found on:

- an official university faculty page;
- an official university directory;
- an official laboratory or institute page;
- the corresponding-author line of a paper, when the affiliation is consistent;
- the researcher’s official professional homepage hosted by the institution;
- ORCID or another official profile where the address is explicitly public and current.

Never guess an address using patterns such as `first.last@university.edu`.

Never use commercial email-enrichment services.

Never use private personal addresses unless the researcher publicly designates that address for professional contact.

Every stored email must include:

- source URL;
- retrieval timestamp;
- source type;
- confidence level;
- verification status.

If no official email is found, mark `NO_VERIFIED_EMAIL` and do not create an Outlook draft.

## 1.8 Privacy by design

This is a local application intended for one user.

The application must minimize retained data.

Do not store:

- Outlook passwords;
- Microsoft account passwords;
- raw access tokens in the database;
- full mailbox contents;
- unrelated emails;
- contacts not needed for the workflow;
- sensitive personal information about professors;
- inferred demographic attributes;
- home addresses;
- personal phone numbers;
- family details;
- political, religious, medical, or other sensitive profile information.

Store only professional, publicly available information relevant to research outreach.

## 1.9 Explain uncertainty

The system must label extracted conclusions as one of:

- `EXPLICIT`: directly stated in the paper.
- `STRONG_INFERENCE`: strongly implied by methods/results but not stated verbatim.
- `SPECULATIVE`: plausible idea that is not established by the paper.

Only `EXPLICIT` content should normally appear as factual paper description in the email.

`STRONG_INFERENCE` may be used internally to assess possible contribution areas, but must be worded cautiously.

`SPECULATIVE` content must never appear in the email as fact.

---

# 2. User Profile and Ground Truth

Create a structured profile file at:

```text
data/arnav_profile.yaml
```

Populate it initially with the following facts.

## 2.1 Identity and affiliation

```yaml
name: Arnav Mittal
email: ArnavMittal@my.unt.edu
status: Incoming Student
program: Texas Academy of Mathematics and Science
institution: University of North Texas
preferred_signoff: |
  Sincerely,
  Arnav Mittal
  Incoming Student, TAMS
  University of North Texas
  ArnavMittal@my.unt.edu
```

## 2.2 Outreach preferences

```yaml
email_preferences:
  paragraph_count: 2
  target_word_count_min: 105
  target_word_count_max: 145
  preferred_opening_phrase: "I enjoyed reading your paper"
  concise_subject: true
  no_transactional_language: true
  no_publication_request: true
  broad_contribution_ask: true
  attach_resume: true
  attach_portfolio: true
  attachment_mode: automatic_and_mandatory
  vocabulary_level: very_simple_everyday_english
  preferred_interest_word: intrigued
  avoid_phrase: very interesting
  personalization_required: true
```

## 2.3 Research portfolio

### Project A — Regge spectral geometry and random matrix theory

Use only claims supported by Arnav’s actual portfolio document when it is imported. The current high-level description is:

- Regge calculus and piecewise-linear geometry.
- Curvature represented through deficit angles.
- Flat, perturbed, and conical triangulated surfaces.
- Weighted graph or Laplace–Beltrami-type operators.
- Eigenvalues and eigenvectors.
- Spectral gaps, heat traces, spectral dimension, and spacing statistics.
- Poisson and Wigner–Dyson comparisons.
- Curvature-dependent spectral signatures.
- Mathematica-based computational work.
- Numerical visualization and interactive analysis.

### Project B — Parker Solar Probe magnetic-field analysis

Current high-level description:

- Parker Solar Probe FIELDS time-series analysis.
- Persistent homology and Vietoris–Rips complexes.
- Magnetic-field vectors mapped to the unit sphere.
- Topological intermittency index derived from H1 persistence.
- Comparison with partial variance of increments.
- Bootstrap-based analysis.
- Scientific Python tooling.
- Numerical, statistical, and visualization workflow.

### Project C — Asteroid orbit determination and uncertainty

Current high-level description:

- Astrometric imaging and plate reduction.
- Gauss orbit determination.
- Iterative light-time correction.
- Comparison with JPL Horizons.
- Six-dimensional covariance.
- Monte Carlo orbital clones.
- Nonlinear Earth and Mars MOID calculations.
- Numerical convergence and sensitivity analysis.
- Python visualization.

### Project D — VARA and stochastic optimization

Current high-level description:

- Jensen-gap analysis.
- Convex operating costs.
- Probabilistic demand modeling.
- Physics-informed convex modeling.
- Stochastic model-predictive-control concepts.
- Variance penalties.
- Sample-average approximation.
- Numerical optimization and uncertainty.

## 2.4 Tools

The system may mention only tools confirmed by the profile or uploaded portfolio:

- Python
- NumPy
- SciPy
- Pandas
- Matplotlib
- Mathematica
- numerical simulation
- statistical analysis
- scientific visualization

Do not automatically claim:

- C++
- CUDA
- HIP
- MPI
- PyTorch
- TensorFlow
- JAX
- high-performance-computing cluster experience
- general relativity expertise
- particle-in-cell code experience
- telescope image-pipeline experience
- weak-lensing expertise

A paper may involve those tools, but that does not mean Arnav has used them.

## 2.5 Documents

Expected local files:

```text
assets/arnav_resume.pdf
assets/arnav_research_portfolio.pdf
```

The application must provide an onboarding screen to locate or upload them.

Record hashes of the documents so the app can detect changes and re-index the profile when the files are replaced.

---

# 3. Intended User Workflow

The workflow must be explicit, reviewable, and reversible.

## 3.1 Candidate discovery

1. User enters one official department or research-group URL.
2. Application retrieves the page with an identifiable user agent.
3. Application extracts likely faculty/researchers.
4. Application displays the extracted list before saving.
5. User approves which names should be screened.
6. Application verifies titles, affiliations, research areas, and official emails.
7. Application checks for duplicates and prior contact.
8. Application calculates a transparent fit score.
9. User decides whether to shortlist a candidate.

## 3.2 Publication discovery

1. For a shortlisted candidate, query supported metadata sources.
2. Verify author identity using affiliation, ORCID, homepage, and coauthor patterns.
3. Retrieve recent publications, normally from the last five years.
4. Exclude obvious consortium-only or incidental-authorship papers unless they are clearly central to the researcher’s work.
5. Score papers for connection to Arnav’s actual portfolio.
6. Display the best 1–3 candidates with explanations.
7. User approves one or two papers for retrieval.

## 3.3 Full-text retrieval

1. Resolve DOI, arXiv ID, and open-access locations.
2. Download only from lawful public sources.
3. Validate content type and file signature.
4. Enforce file-size limits.
5. Compute SHA-256 hash.
6. Parse the full PDF.
7. If parsing confidence is low, flag it for manual upload or review.
8. Store the original PDF in a structured local folder.

## 3.4 Paper analysis

For each approved paper, extract:

- bibliographic information;
- author position;
- corresponding author if stated;
- research question;
- motivation;
- primary methods;
- datasets;
- software or computational tools explicitly mentioned;
- major equations or mathematical structures;
- validation strategy;
- principal results;
- limitations;
- future-work statements;
- plausible contribution categories;
- relationship to Arnav’s portfolio;
- risk of overclaiming;
- confidence score;
- page references or text spans supporting each point.

The paper analysis must be saved before email drafting.

## 3.5 Draft generation

The system creates a proposed draft using:

- one precise technical detail from the strongest paper;
- optionally one detail from a second paper;
- one or two truly relevant Arnav projects;
- a broad contribution statement;
- the approved signoff.

The system must show:

- the draft;
- supporting evidence for each paper-specific sentence;
- which user-profile facts were used;
- warnings;
- word count;
- similarity to prior drafts;
- same-group warning;
- prior-contact warning.

The user must explicitly click `Approve for Outlook Draft`.

## 3.6 Outlook draft creation

After approval:

1. Authenticate using delegated Microsoft identity.
2. Create a draft in the signed-in user’s mailbox.
3. Add recipient, subject, body, resume, and portfolio.
4. Save the returned Outlook message ID.
5. Mark the candidate `OUTLOOK_DRAFT_CREATED`.
6. Display a link or clear instruction to open the draft in Outlook.
7. Do not send.

## 3.7 Sent and reply tracking

The safest first version should rely on manual status updates.

A later version may read only narrowly scoped mailbox data required to match outreach threads.

It may:

- detect that a matching draft was sent manually;
- detect a reply in that thread;
- classify reply type;
- suggest a response;
- create a response draft after explicit approval.

It must never reply automatically.

---

# 4. Scope and Delivery Phases

Do not build everything at once.

## Phase 0 — Repository foundation

Deliver:

- project structure;
- README;
- environment configuration;
- local database;
- linting;
- formatting;
- tests;
- secure defaults;
- logging;
- basic UI shell;
- data migrations;
- sample data;
- `.gitignore`;
- secret scanning configuration;
- contributor instructions;
- `AGENTS.md`.

Exit criteria:

- application starts locally;
- database initializes;
- tests pass;
- no secret is committed;
- UI loads;
- health check succeeds.

## Phase 1 — Safe manual tracker

Deliver:

- Arnav profile;
- asset management;
- contacted-person CSV import;
- candidate CRUD;
- manual paper upload;
- manual paper-analysis record;
- manual email drafting;
- status tracking;
- duplicate detection;
- follow-up calculator;
- no external crawling yet;
- no Outlook integration yet.

Exit criteria:

- a candidate can be entered manually;
- an uploaded PDF is stored safely;
- analysis can be generated;
- a draft can be reviewed;
- the candidate history is auditable.

## Phase 2 — Controlled candidate discovery

Deliver:

- one-URL-at-a-time official department-page import;
- HTML retrieval;
- candidate extraction;
- user review before persistence;
- source provenance;
- title and affiliation verification;
- official email extraction;
- duplicate detection;
- transparent scoring.

Exit criteria:

- importer works on at least five structurally different official university pages;
- false positives can be rejected before saving;
- no guessed emails;
- rate limiting and robots handling are implemented;
- extraction failures are graceful.

## Phase 3 — Publication metadata and identity resolution

Deliver:

- OpenAlex integration;
- Crossref integration;
- optional ORCID integration;
- author identity disambiguation;
- recent-publication retrieval;
- paper scoring;
- consortium/minor-author warning;
- metadata provenance.

Exit criteria:

- author mismatches are caught in tests;
- ambiguous identities require manual review;
- publication metadata is deduplicated by DOI/arXiv/title fingerprint;
- API failures do not corrupt state.

## Phase 4 — Lawful open-access retrieval and PDF analysis

Deliver:

- arXiv retrieval;
- open-access URL resolution;
- safe PDF downloader;
- PDF parser;
- text quality assessment;
- structured analysis;
- evidence spans/page references;
- confidence labels;
- manual-upload fallback.

Exit criteria:

- no draft can be created without a successfully analyzed full paper;
- malformed or non-PDF downloads are rejected;
- each factual paper claim has evidence;
- inaccessible papers are clearly marked.

## Phase 5 — Outlook draft integration

Deliver:

- Microsoft delegated authentication;
- least-privilege scope;
- draft creation;
- attachments;
- token storage using OS keychain where feasible;
- token revocation/logout;
- clear error handling;
- audit logging without message-body leakage.

Exit criteria:

- app can create a draft;
- app cannot send;
- `Mail.Send` is absent;
- tokens are not stored in SQLite or logs;
- user can disconnect the account.

## Phase 6 — Reply and follow-up assistance

Deliver:

- optional sent-message matching;
- optional thread-reply detection;
- reply classification;
- follow-up date suggestions;
- response-draft suggestions;
- no automatic replies.

Exit criteria:

- mailbox access is narrow;
- unrelated mail is not persisted;
- reply classification is reviewable;
- automatic sending remains impossible.

---

# 5. Recommended Technical Architecture

Prefer a maintainable, understandable stack over unnecessary complexity.

## 5.1 Backend

Use:

- Python 3.12 or later.
- FastAPI.
- Pydantic v2.
- SQLAlchemy 2.x.
- Alembic.
- SQLite for local MVP.
- httpx for HTTP.
- tenacity for bounded retry logic.
- structured logging.
- pytest.
- Ruff.
- mypy or pyright.
- Bandit.
- pip-audit or equivalent dependency scanning.

Do not introduce Celery, Redis, Kafka, Kubernetes, or cloud infrastructure in the MVP.

For long-running jobs, use a simple local job table and background worker process. Ensure jobs are resumable and idempotent.

## 5.2 Frontend

Preferred options:

- FastAPI with Jinja2 and HTMX for a simple local application; or
- React with TypeScript if the UI requirements justify it.

Favor server-rendered pages for the first version because they reduce complexity.

The UI must be clear, professional, and information-dense without looking like a mass-marketing platform.

## 5.3 Database

Use normalized tables for:

- candidates;
- institutions;
- affiliations;
- sources;
- email addresses;
- publications;
- author-publication relationships;
- paper files;
- paper analyses;
- evidence items;
- fit scores;
- email drafts;
- outreach events;
- Outlook message references;
- replies;
- follow-up tasks;
- exclusion rules;
- audit events;
- jobs.

Use UTC timestamps internally.

Use soft deletion for most user data so accidental deletion can be reversed.

Provide an explicit purge action for permanent deletion.

## 5.4 File storage

Use:

```text
data/
  outreach.db
  exports/
  cache/
papers/
  <candidate_slug>/
    <year>_<paper_slug>_<sha8>.pdf
assets/
  arnav_resume.pdf
  arnav_research_portfolio.pdf
logs/
```

Do not store downloaded content outside the project’s controlled directories.

Never allow a remote filename to determine a path directly.

Sanitize filenames and defend against path traversal.

## 5.5 AI provider boundary

Create interfaces for paper analysis and draft generation. Do not hard-code the application around one model name.

Model names and API parameters must be configurable.

Use structured JSON outputs validated by Pydantic.

When validation fails, retry only a small bounded number of times.

Do not silently accept malformed output.

Do not send Outlook tokens, unrelated mailbox content, or unnecessary personal data to the model.

---

# 6. Core Data Model

Implement entities for Candidate, Institution, EmailAddress, Publication, Authorship, PaperFile, PaperAnalysis, EvidenceItem, Draft, OutreachEvent, FollowUpTask, AuditEvent, and Job.

Candidate statuses:

```text
DISCOVERED
SCREENING
SCREENED
SHORTLISTED
PAPERS_FOUND
PAPER_RETRIEVAL_PENDING
PAPER_ANALYZED
DRAFT_READY
OUTLOOK_DRAFT_CREATED
SENT
REPLIED
DECLINED
FOLLOW_UP_DUE
CLOSED
SKIPPED
NO_VERIFIED_EMAIL
NO_FULL_TEXT
DUPLICATE
```

Transitions must be validated. Do not allow arbitrary jumps that bypass safety checks.

Every EvidenceItem must include:

```text
claim
evidence_text
page_number
section_name
classification
confidence
```

Classification:

```text
EXPLICIT
STRONG_INFERENCE
SPECULATIVE
```

Every Draft must include:

```text
candidate_id
subject
body_text
body_html
word_count
generation_version
approved_by_user
approved_at
outlook_message_id
created_at
updated_at
```

---

# 7. Candidate Discovery Rules

## 7.1 Eligible researchers

Prefer:

- assistant professors;
- associate professors;
- research professors;
- research faculty;
- postdoctoral researchers;
- advanced research scientists;
- junior group leaders;
- active faculty with computationally tractable projects.

Allow senior faculty when the fit is unusually strong, but display a lower accessibility score.

## 7.2 Subject areas

Primary:

- computational astrophysics;
- theoretical astrophysics;
- plasma astrophysics;
- numerical relativity;
- cosmology;
- gravitational lensing;
- time-domain astronomy;
- astronomical data analysis;
- computational physics;
- mathematical physics;
- spectral geometry;
- random matrix theory;
- numerical analysis;
- applied mathematics;
- scientific computing;
- topological data analysis;
- dynamical systems;
- stochastic modeling;
- optimization;
- uncertainty quantification.

## 7.3 Exclusion or warning conditions

Flag or exclude:

- wet-lab-only research;
- hardware-dependent experimental projects with no obvious computational component;
- fieldwork requiring presence;
- researchers marked emeritus with no recent activity;
- no publications in the last five years, absent a compelling reason;
- no verified current affiliation;
- no verified email;
- obvious duplicate;
- previously contacted;
- same group as a recently contacted researcher;
- paper is only a giant consortium publication and the candidate’s contribution is unclear;
- candidate’s research is outside Arnav’s background with no credible bridge;
- candidate webpage is stale or archived;
- candidate explicitly states they do not supervise external students;
- candidate is on leave and not accepting students, if publicly stated.

Never infer protected or sensitive attributes.

## 7.4 Fit scoring

Calculate individual components and show them separately.

Recommended weights:

```text
Genuine research fit                 30
Remote/computational feasibility     20
Career-stage accessibility           15
Recent research activity             15
Evidence of student mentoring        10
Institution/research environment      10
Total                               100
```

Do not present the score as objective truth.

Display score, factors, evidence, missing data, confidence, and warnings.

## 7.5 Prior-contact deduplication

Match candidates by:

1. normalized email;
2. ORCID;
3. official profile URL;
4. normalized full name plus institution;
5. fuzzy name match plus research group.

Require user confirmation for uncertain duplicates.

Import the existing contact history from CSV with preview, validation, rollback, and duplicate prevention.

---

# 8. Publication Selection Rules

Default to papers from the last five calendar years.

Prefer papers where the candidate is first author, corresponding author, senior/last author where meaningful, one of a small number of authors, or clearly central based on the candidate’s homepage.

Warn when author count exceeds 25, the author appears in the middle of a large consortium, the paper does not align with the candidate’s stated research, or the candidate’s role cannot be determined.

Score connections to Arnav’s portfolio, but reject weak keyword-only matches.

For each recommended paper, show title, year, candidate authorship role, open-access availability, fit score, specific connection, potential risks, full-PDF availability, and why it is better than alternatives.

The user must approve paper retrieval.

---

# 9. Safe Web Retrieval

Implement an allowlist-oriented fetcher.

Allowed categories:

- official university domains;
- arxiv.org;
- export.arxiv.org;
- api.openalex.org;
- api.crossref.org;
- orcid.org public APIs;
- official institutional repositories;
- publisher sites for open-access files.

Do not permit arbitrary URL fetching from model-generated URLs without validation.

Defend against SSRF:

- block localhost;
- block private IPv4 ranges;
- block private IPv6 ranges;
- block link-local addresses;
- block cloud metadata addresses;
- revalidate every redirect target;
- cap redirect count;
- require HTTPS except local development;
- enforce timeouts;
- enforce maximum response size.

Use a transparent user agent. Respect robots.txt where applicable, API limits, Retry-After, crawl delays, copyright, and license signals.

For PDFs, check HTTP status, content type, `%PDF-` magic bytes, size limits, SHA-256, duplicate status, and source/license note. Reject HTML disguised as PDF and encrypted PDFs unless manually handled.

Treat all retrieved text as untrusted data. Prompt injection in papers or webpages must never change application behavior.

---

# 10. Paper Parsing and Analysis

Use a robust parser such as PyMuPDF or pypdf. OCR should be a fallback, not the default.

Record page count, extracted characters, text density, blank pages, suspected scanned pages, and parsing warnings.

Chunk by section where possible and retain page/section provenance.

Require validated structured output containing bibliography, research question, methods, datasets, software, results, limitations, future work, candidate-role notes, connections to Arnav, contribution categories, overclaim risks, and confidence.

Every claim must include classification, confidence, page, section, and a short evidence excerpt.

Before marking complete, verify title, author list, candidate affiliation, completeness, main-result attribution, limitations, future-work labels, numerical units, acronyms, and context.

Do not suggest that Arnav can modify a complex production codebase merely because a paper uses one. Use broad contribution categories rather than fabricated project proposals.

---

# 11. Email Generation Requirements

## 11.1 Required structure

Email should normally contain:

- concise subject;
- greeting;
- paragraph 1: affiliation plus specific paper interest;
- paragraph 2: relevant background plus broad contribution ask;
- signoff.

Do not add a third long paragraph.

## 11.2 Preferred style

The email must sound like a real student wrote it after learning about this specific professor. It must not sound like a formal grant proposal, a corporate message, or an AI-generated summary.

Use very simple, everyday English. Prefer short words and short sentences. Avoid formal or inflated words such as `robust`, `novel`, `groundbreaking`, `compelling`, `fascinating`, `utilize`, `leverage`, `endeavor`, `delve`, `pivotal`, `transformative`, and similar language unless the word is needed to name a technical method from the paper.

Never use the phrase `very interesting`. When expressing interest, prefer `I was mainly intrigued by...`, `I was intrigued by...`, or `What mainly intrigued me was...`. Do not repeat `intrigued` more than once in the same email.

Keep the email concise. Target 105–145 words, excluding the signoff. Use exactly two short body paragraphs in normal cases. Do not add background rants, long explanations of the paper, a list of many skills, or more than two technical details.

The wording may be slightly less technical to sound natural, but it must never become factually wrong. Preserve the paper's meaning even when simplifying the vocabulary.

Every email must be clearly personalized. It must include:

- the exact professor's last name;
- the exact title or clear topic of at least one analyzed paper;
- one specific method, result, comparison, dataset, or idea from that paper;
- the one or two parts of Arnav's work that genuinely match that paper;
- contribution areas that fit the professor's actual work;
- wording that is not copied unchanged from another professor's email.

Do not use generic praise that could be sent to anyone. The first paragraph should make it obvious why this professor, rather than another professor, is being contacted.

Preferred pattern:

```text
Dear Professor [Last Name],

I am an incoming student at the Texas Academy of Mathematics and Science at the University of North Texas. I enjoyed reading your paper on [specific topic]. I was mainly intrigued by [one accurate and simply worded technical detail]. [Optional one short sentence about a second paper or related part of the professor's work.]

My recent work includes [one or two directly relevant projects]. I would be glad to help with any suitable ongoing project through [two to four realistic contribution types]. I have attached my resume and research portfolio for context.

Sincerely,
Arnav Mittal
Incoming Student, TAMS
University of North Texas
ArnavMittal@my.unt.edu
```

## 11.3 Forbidden language

Do not write language about needing a publication, publishing quickly, guarantees, exaggerated expertise, prestige, citation counts, mass outreach, demands for meetings, demands for authorship, referrals in the first email, or unsupported claims of reproduction or mastery.

## 11.4 Similarity and evidence

Compute similarity against prior drafts and warn on excessive reuse, especially within the same institution.

The review page must let the user click each technical sentence and see paper title, page, section, supporting evidence, confidence, and explicit/inference label.

## 11.5 Final validation

Before enabling approval:

- verified official email exists;
- no prior-contact block;
- at least one full paper analyzed;
- candidate identity confidence above threshold;
- word count is normally 105–145 words excluding the signoff;
- exactly two concise body paragraphs unless the user explicitly approves an exception;
- no forbidden phrase;
- no phrase `very interesting`;
- simple-vocabulary check completed;
- at least one professor-specific detail is present;
- personalization and prior-draft similarity checks completed;
- no unsupported tool or project claim;
- no `Mail.Send` capability;
- attachments exist;
- group warning resolved;
- all technical sentences have evidence.

---

# 12. Outlook Integration

Use Microsoft Graph delegated authentication for the signed-in user.

Prefer authorization code flow with PKCE. Device-code flow may be a fallback.

Use the system browser for sign-in. Never ask the user to type a Microsoft password into the app.

Initial scopes:

- `openid`
- `profile`
- `offline_access`
- `User.Read`
- `Mail.ReadWrite`

Do not request:

- `Mail.Send`
- organization-wide application permissions;
- application-only mail access;
- directory-wide read permissions;
- contacts access;
- calendar access;
- files access.

Never store tokens in plaintext in SQLite, source code, `.env`, logs, or browser local storage. Prefer OS credential storage.

Provide Disconnect Outlook and document revocation.

Create drafts with recipients, subject, body, and attachments. Store only the Graph message ID and minimum metadata locally.

The resume and research portfolio must be attached automatically to every approved first-contact draft. The user should not have to select them each time. Resolve them from the configured asset paths, verify both files exist, validate that both are PDFs, show their names and sizes on the approval screen, and block Outlook draft creation if either required file is missing or invalid. Never silently create a draft without both attachments. Do not automatically attach them to a short thank-you reply after a professor responds.

Use idempotency so repeated clicks do not create duplicate drafts.

Handle expired tokens, revoked consent, attachment errors, throttling, timeouts, invalid recipients, and deleted drafts safely.

---

# 13. Reply Classification and Follow-Up

This is a later phase.

Classify replies as positive interest, request for information, meeting request, referral, capacity decline, institution-priority decline, no relevant project, out-of-office, ambiguous, or unrelated.

A response stating that the professor must prioritize students at their own institution and lacks capacity should be classified as:

```yaml
status: DECLINED
reason: INTERNAL_STUDENT_PRIORITY_AND_CAPACITY
follow_up_recommended: false
thank_you_reply_recommended: true
```

Default follow-up timing: 7–10 business days, maximum one follow-up, and never after an explicit decline.

The application should suggest, not automatically create or send, follow-ups.

---

# 14. Security Requirements

Document the threat model in `docs/THREAT_MODEL.md`.

Threats include malicious webpages, malicious PDFs, prompt injection, compromised APIs, accidental mass drafting, duplicate messages, leaked keys/tokens, path traversal, SSRF, SQL injection, XSS, CSRF, dependency compromise, accidental deletion, database corruption, identity mismatch, model hallucination, and overclaiming.

Provide `.env.example`, ignore `.env`, never print secrets, redact authorization headers, run secret scanning, use mocked services in tests, validate all inputs, use parameterized queries, apply CSRF protection, sanitize model output, bind to `127.0.0.1` by default, and set secure headers.

Audit important actions but do not log tokens, API keys, full email bodies by default, full paper contents, or unrelated mailbox content.

Provide encrypted export, migration backups, restore instructions, and integrity checks. Do not back up tokens with the database.

---

# 15. Ethical and Reputation Safeguards

The UI must not resemble a bulk-mail campaign system.

Do not provide mail merge, send-all, automatic sequencing, open tracking, click tracking, tracking pixels, delivery analytics, address enrichment, A/B testing, or automated follow-up chains.

Record explicit declines and block future outreach unless intentionally reopened.

Avoid contacting multiple people in a small group simultaneously. Display a relationship map based on same institution, department, recent coauthorship, research center, or shared lab page only to prevent redundant contact.

Personalization must come from real paper analysis, not generic praise.

Do not encourage Arnav to misrepresent credentials or include unnecessary personal details.

---

# 16. Product Design Requirements

Create pages for Dashboard, Candidate Discovery, Candidate Detail, Paper Review, Draft Review, Contact History, Follow-Up Tracker, and Settings.

The Draft Review page must show recipient, verified email source, subject, editable body, attachments, word count, evidence mapping, similarity warning, group warning, prior-contact warning, approval checkbox, and Create Outlook Draft button.

Approval text:

> I reviewed the recipient, technical details, wording, and attachments. Create an Outlook draft only. Do not send.

Use semantic HTML, keyboard navigation, readable contrast, clear focus states, labeled forms, and error messages tied to fields.

Visual design should be polished, restrained, and serious. Avoid excessive animation.

---

# 17. Testing Requirements

Unit tests must cover URL validation, SSRF blocking, email normalization, duplicate detection, scoring, status transitions, CSV validation, publication deduplication, author identity matching, file validation, analysis schema, forbidden phrases, word count, evidence coverage, Outlook idempotency, and follow-up calculation.

Integration tests must mock department pages, OpenAlex, Crossref, arXiv, malformed PDFs, invalid model JSON, unsupported claims, Outlook drafts, expired tokens, attachment failure, and throttling.

Security tests must cover path traversal, local-file URLs, localhost/private-IP SSRF, redirect SSRF, HTML masquerading as PDF, oversized responses, XSS, CSRF, secret redaction, duplicate-draft races, and prompt injection inside PDFs.

End-to-end tests should exercise the full mocked workflow from candidate import through draft creation and decline handling.

Quality gates: formatter, linter, type checker, tests, security scan, dependency audit, secret scan, migration test, README update, changelog update.

---

# 18. Observability and Error Handling

Use structured logs with timestamp, level, event, request_id, job_id, candidate_id, publication_id, duration, status, and error code.

Long-running jobs must have status, progress, retry count, timestamps, error code, user-readable error, safe cancellation, and idempotency key.

Retry only transient failures with exponential backoff and jitter. Do not retry authorization failures, access denials, missing resources, invalid PDFs, or explicit robots denial.

---

# 19. Configuration

Provide typed configuration with defaults for candidate limits, same-institution/group limits, draft limits, word counts, PDF size, timeouts, redirects, follow-up timing, and Outlook drafts-only mode.

Some controls must be non-disableable:

- no automatic sending;
- no `Mail.Send`;
- no guessed emails;
- no paywall bypass;
- no draft without full-paper analysis.

---

# 20. Repository Structure

Create:

```text
professor-outreach/
├── AGENTS.md
├── PROJECT_SPEC.md
├── README.md
├── CHANGELOG.md
├── SECURITY.md
├── LICENSE
├── .env.example
├── .gitignore
├── pyproject.toml
├── alembic.ini
├── app/
│   ├── main.py
│   ├── config.py
│   ├── dependencies.py
│   ├── db/
│   ├── models/
│   ├── schemas/
│   ├── services/
│   │   ├── discovery/
│   │   ├── metadata/
│   │   ├── retrieval/
│   │   ├── parsing/
│   │   ├── analysis/
│   │   ├── drafting/
│   │   ├── outlook/
│   │   ├── scoring/
│   │   └── audit/
│   ├── routes/
│   ├── templates/
│   ├── static/
│   ├── workers/
│   └── security/
├── data/
│   ├── arnav_profile.yaml
│   ├── contacted_people.csv
│   └── .gitkeep
├── assets/
│   └── .gitkeep
├── papers/
│   └── .gitkeep
├── docs/
│   ├── ARCHITECTURE.md
│   ├── THREAT_MODEL.md
│   ├── DATA_MODEL.md
│   ├── OUTLOOK_SETUP.md
│   ├── SOURCE_POLICY.md
│   └── USER_GUIDE.md
├── migrations/
├── scripts/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── security/
│   ├── e2e/
│   └── fixtures/
└── logs/
    └── .gitkeep
```

Do not commit the database with personal data, PDFs, resume, portfolio, logs, token cache, `.env`, or exports.

---

# 21. README Requirements

The README must include exact copy-pastable commands for environment creation, dependencies, configuration, database initialization, launch, worker, tests, linting, type checking, security scanning, backup, CSV import, Outlook connection/disconnection, and troubleshooting.

Include macOS, Windows, and Linux notes where commands differ. Do not assume the user is an experienced developer.

---

# 22. AGENTS.md Requirements

Create an `AGENTS.md` instructing future Codex sessions to read `PROJECT_SPEC.md`, preserve drafts-only architecture, never add `Mail.Send`, never add automatic sending, maintain evidence traceability, run tests, update docs, avoid unrelated refactors, make small reviewable commits, protect secrets, and ask before altering policy.

---

# 23. Development Process for Codex

Before coding:

1. Inspect repository.
2. Read specification.
3. Create implementation plan.
4. Identify ambiguities.
5. State current phase.
6. Avoid later-phase work.
7. Create/update TODOs.

During coding:

- make small coherent changes;
- keep app runnable;
- add tests with each feature;
- use migrations;
- document security decisions;
- avoid premature optimization;
- install only necessary packages;
- review dependency licenses.

After coding:

1. Run formatter.
2. Run linter.
3. Run type checker.
4. Run tests.
5. Run security checks.
6. Review diff.
7. Verify no secret or private PDF is staged.
8. Update README/changelog.
9. Summarize changes, remaining work, and risks.

Do not claim completion without proof. Clearly distinguish completed, partial, stubbed, untested, and deferred work.

---

# 24. MVP Acceptance Criteria

The first usable MVP is complete only when:

1. Local app launches.
2. User profile loads.
3. Resume and portfolio paths can be configured.
4. Existing contacted CSV imports safely.
5. Candidate can be added manually.
6. Duplicate warning works.
7. Official email source can be recorded.
8. PDF can be uploaded manually.
9. PDF validation and hashing work.
10. Full text is parsed.
11. Structured analysis is created.
12. Evidence is displayed.
13. Email draft is generated in required style.
14. Unsupported claims are blocked or warned.
15. User can edit the draft.
16. User can approve it.
17. Status history is recorded.
18. No email-send functionality exists.
19. Tests pass.
20. Security documentation exists.

---

# 25. Explicitly Out of Scope Initially

Do not implement nationwide crawling, autonomous whole-web browsing, automatic sending, automatic replies, multi-user SaaS, cloud hosting, mobile app, browser extension, CRM integrations, calendar scheduling, meeting transcription, citation-graph recommendation, personality profiling, response-probability promises, open tracking, link tracking, or campaign analytics.

---

# 26. Interpretation Rules

When requirements conflict:

1. Safety and truthfulness win.
2. Human approval wins.
3. Privacy wins.
4. Official-source verification wins.
5. Full-paper evidence wins.
6. Quality wins over volume.
7. Simplicity wins over premature scale.

When uncertain, pause, record uncertainty, ask the user, do not invent, do not broaden permissions, do not send, do not guess an email, and do not claim a paper connection.

---

# 27. Initial Task

Begin with **Phase 0 and Phase 1 only**.

1. Inspect the newly created project folder.
2. Initialize Git if needed.
3. Create repository structure.
4. Create `AGENTS.md`.
5. Preserve this file as `PROJECT_SPEC.md`.
6. Create Python project configuration.
7. Build FastAPI application shell.
8. Add SQLite and Alembic.
9. Add secure configuration handling.
10. Add user-profile YAML.
11. Add a sample contacted-person CSV.
12. Implement candidate tracking.
13. Implement safe manual PDF upload.
14. Implement PDF metadata, hashing, and parsing.
15. Implement structured paper-analysis interfaces with a mock provider first.
16. Implement draft-generation interfaces with a mock provider first.
17. Build dashboard, candidate detail, paper review, and draft review pages.
18. Add status transitions and audit events.
19. Add tests.
20. Write exact local setup instructions.
21. Run everything and report results.

Do not begin live crawling, OpenAlex, Crossref, arXiv, or Outlook integration until Phase 1 is working and reviewed.

At the end of the first implementation pass, provide architecture summary, files created, exact commands, test results, UI description, known limitations, next recommended task, security review, and confirmation that no sending capability exists.

---

# 28. Final Reminder

This application exists to help Arnav send a small number of careful, truthful, paper-specific messages.

It must not become a spam engine.

It must not sacrifice accuracy for scale.

It must not send email.

It must not invent expertise.

It must not guess addresses.

It must not bypass access controls.

It must preserve a complete audit trail from source paper to technical sentence to approved Outlook draft.

Build it so the user can trust every step.
