# ProfLens — Owner & Administrator Guide

**Audience:** the site owner and trusted moderators.  
**Assumes:** the production deployment from [`DEPLOYMENT.md`](DEPLOYMENT.md) is live and you have a
superuser account.  
**Last updated:** 2026-10-27

> **Read this first:** the admin is powerful and deliberately blunt. Deleting a **School** deletes its
> professors and their reviews. Deleting a **Professor** deletes all of their reviews. There is no
> undo. Prefer **reject/hide** over **delete**. Take a database backup before any bulk action.

---

## 1. Access, roles, and first login

### 1.1 URLs

Replace `proflens.kg` with your domain. If the admin path was renamed during deployment (see
`DEPLOYMENT.md` §R-10), use that prefix instead of `/admin/`.

| Page | URL |
|---|---|
| Admin login | `https://proflens.kg/admin/` |
| Admin dashboard | `https://proflens.kg/admin/` |
| Reviews | `https://proflens.kg/admin/reviews/review/` |
| Pending reviews | `https://proflens.kg/admin/reviews/review/?status__exact=pending` |
| Professors | `https://proflens.kg/admin/reviews/professor/` |
| Pending professors | `https://proflens.kg/admin/reviews/professor/?status__exact=pending` |
| Schools | `https://proflens.kg/admin/reviews/school/` |
| Tags | `https://proflens.kg/admin/reviews/tag/` |
| Reports | `https://proflens.kg/admin/reviews/report/` |
| Votes | `https://proflens.kg/admin/reviews/vote/` |
| Users | `https://proflens.kg/admin/auth/user/` |
| Groups | `https://proflens.kg/admin/auth/group/` |
| Change your password | `https://proflens.kg/admin/password_change/` |
| Public site | `https://proflens.kg/` |

### 1.2 Create the first superuser

Run this once on the server (or via the platform shell):

```bash
# Docker
docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser

# systemd / venv
cd /srv/proflens && .venv/bin/python manage.py createsuperuser
```

Use a unique username (not `admin`), a long password from a password manager, and an email you
control. Do **not** share this account. Create separate accounts for other people.

### 1.3 Roles

| Role | How it is granted | Can do |
|---|---|---|
| **Owner / superuser** | `is_superuser=True` | Everything, including deleting data, managing users, changing permissions |
| **Moderator** | `is_staff=True` + `Moderators` group | Review/professor moderation, view schools/tags/reports; no user or permission changes |
| **Read-only staff** | `is_staff=True` + view-only permissions | Inspect queues; cannot approve/reject/delete |
| **Registered user** | Public signup | Submit reviews/professors (pending), vote, report; cannot access admin |
| **Anonymous visitor** | — | Browse/search approved content; must log in to post/vote/report |

### 1.4 Create a moderator (recommended instead of sharing your account)

1. Go to **Groups → Add group** (`/admin/auth/group/add/`).
2. Name it `Moderators`.
3. Select these permissions (labels are English model names, even if the admin UI is Russian):
   - `reviews | review | Can view review`
   - `reviews | review | Can change review`
   - `reviews | review | Can delete review` *(optional; omit if you do not want deletions)*
   - `reviews | professor | Can view professor`
   - `reviews | professor | Can change professor`
   - `reviews | school | Can view school`
   - `reviews | tag | Can view tag`
   - `reviews | report | Can view report`
   - `reviews | report | Can delete report`
   - `reviews | vote | Can view vote` *(optional)*
4. **Do not** grant `auth | user` change permissions, `reviews | school` change, or any
   `permission`/`group` permissions unless the person genuinely needs them. A staff user with user
   permissions can escalate their own access.
5. Go to **Users → Add user**. Set username/email, a strong temporary password, check
   **Staff status**, leave **Superuser status** unchecked, and assign the `Moderators` group.
6. Send credentials over a secure channel and ask them to change the password at
   `/admin/password_change/` immediately.

**Note:** `is_staff` alone lets a user open the admin, but they will only see models they have
permissions for. `is_active=False` blocks login entirely.

### 1.5 Admin language

The admin follows the browser's `Accept-Language`. The public site supports `ru`, `ky`, and `en`.
Custom model names (`Review`, `Professor`, `School`, `Tag`, `Vote`, `Report`) are **not localized**
in this project, so the menu may show English names while standard Django labels and your custom
action descriptions appear in Russian. This is cosmetic; use the URLs above if a label is unclear.

---

## 2. Daily moderation: reviews

### 2.1 The queue

1. Open **Reviews** (`/admin/reviews/review/`).
2. In the right sidebar, click **Status → pending**. Bookmark the resulting URL:
   `/admin/reviews/review/?status__exact=pending`.
3. Click the **Created at** column header to sort oldest-first. Aim to clear the queue within
   **24–48 hours**; tell users this SLA on the rules page.
4. To see a specific professor's reviews, search by their name in the search box, or open the
   professor and use the reviews link.

The dashboard does not show a pending count. Use the changelist or this command:

```bash
docker compose -f docker-compose.prod.yml exec web python manage.py shell -c \
  "from reviews.models import Review; print('pending:', Review.objects.filter(status='pending').count())"
```

### 2.2 Review checklist

Open each review and check all of the following:

- **On-topic:** about teaching, course content, grading, workload, communication, exams.
- **No personal data:** no phone numbers, addresses, social handles, photos, transcripts, student
  IDs, or private messages. Names of other students are also personal data — remove them.
- **No abuse:** no insults, threats, harassment, discrimination, sexual content, or profanity at a
  person.
- **No defamation or allegations of crime:** no accusations of corruption, harassment, or criminal
  conduct. These are high legal risk; reject and escalate.
- **No spam:** no advertising, referral links, tutoring offers, cheating services, or exam answers.
- **No impersonation/conflict:** not a professor reviewing themselves or a colleague settling a
  score; not a competitor.
- **Plausible specifics:** mentions a real course/term and concrete teaching behavior, not a generic
  rant or template.
- **No duplicate:** same author + same course + same professor (the app blocks this, but check).
- **Ratings consistent with text:** a 5/5 with a complaint is suspicious; a 1/5 with praise may be a
  mistake — edit or reject.

### 2.3 Decisions

| Situation | Action | Result |
|---|---|---|
| Meets all rules | **Approve** | Review becomes public immediately |
| Minor, fixable issue (course name, typo, formatting; no change of meaning) | **Edit + approve** | Public, corrected |
| Off-topic, insulting, personal data, defamation, spam, cheating | **Reject** | Hidden, retained for audit; can be re-approved later |
| Illegal content, credible threat, doxxing, legal request | **Reject**, then **escalate** per §9 | Hidden; preserve evidence; do not delete until advised |
| Duplicate or test entry | **Delete** | Permanently removed |

**How to approve/reject one review:** open it, change **Status** to `approved` or `rejected`, click
**Save**.

**How to moderate in bulk:**

1. Tick the checkboxes on the left of the list.
2. Choose **“Одобрить выбранные отзывы”** or **“Отклонить выбранные отзывы”** in the action dropdown.
3. Click **Go** / **Выполнить**.
4. Confirm on the next page.

> **Audit warning:** bulk actions use `queryset.update()` and **do not create Django admin
> `LogEntry` records**. The current model also has no `moderated_by`/`moderated_at`/reason fields.
> Keep a separate moderation log (a spreadsheet is fine) with: date/time, moderator, review ID,
> action, reason, and link. This matters for appeals and legal requests. A proper audit model is a
> P1 requirement in `DEPLOYMENT.md` (§6, P1-01).

### 2.4 The resubmission trap after rejection

The duplicate check counts **all** reviews by the same author for the same course and professor,
including **rejected** ones (`reviews/django_repo.py:50-53`). Consequences:

- A student whose review was rejected **cannot submit a corrected review** for that course while the
  rejected row exists.
- If the rejection was for a fixable issue and you want to allow a resubmission, **delete the
  rejected review** (after saving a copy if needed) or **edit and approve** it instead.
- If you reject for spam/abuse, leaving the row is fine; it also prevents the same account from
  re-posting the same course review.

### 2.5 What the author sees

- On submit: “Отзыв отправлен на модерацию. Спасибо!”
- There is **no author dashboard**, no “my reviews” page, and no email notification on
  approve/reject. Users cannot see their pending review. If someone asks, search the admin by their
  email/username and the review text.
- If you need to notify authors, do it manually by email. Automated notifications require code
  (P1).

---

## 3. Reports (“Пожаловаться”)

### 3.1 Where they are

`/admin/reviews/report/` lists every report: **review**, **user**, **created_at**. Click the review
link to open it in the review editor.

There is **no reason field** and no “resolved” status in the current model. You must infer the
problem from the review and the reporter's history. This is a known gap (P1-02); until it is fixed,
keep notes externally.

### 3.2 Handling a report

1. Open **Reports**, click the **Created at** column to sort oldest-first. Treat the oldest open
   reports first.
2. Click the review; read it against the §2.2 checklist.
3. Decide:
   - **No violation:** leave the review approved, reset **Reported** to `0` on the review, and delete
     the report row (or keep it for records; see below).
   - **Violation:** set the review to **rejected** (hidden immediately). For serious abuse, also
     deactivate the author.
   - **Illegal/threatening:** hide, preserve a copy, escalate (§9). Do not delete evidence yet.
4. The **Reported** counter is denormalized. Deleting a `Report` row does **not** decrement it;
   deleting a `Vote` does **not** decrement `helpful`/`not_helpful`. Reset the counters manually on
   the review form, or recompute all counters with the shell snippet in §10.4.
5. If you delete the report rows, the same user can report the review again (the unique constraint
   is on `review + user`). That is usually fine; if abuse of the report button is the problem,
   deactivate the reporter.

### 3.3 Reports are not automatic takedowns

A report does not hide a review. Only a moderator changing **Status** to `rejected` hides it. Set a
target: acknowledge reports within 24 hours and resolve within 72 hours.

---

## 4. Professors

### 4.1 Pending submissions

Public users submit new professors through **“Добавить преподавателя”**; these arrive as
`pending` and are invisible on the public site.

1. Open `/admin/reviews/professor/?status__exact=pending`.
2. Verify:
   - **School** is correct.
   - **First name / Last name** spelling (use the form used by the university; be consistent).
   - **Department** and **Title** are plausible (`профессор`, `доцент`, `старший преподаватель`,
     `преподаватель`).
   - The person is a real current/former instructor, not a test or a prank.
   - No duplicate: search the last name and school first.
3. Approve via the action **“Одобрить выбранных преподавателей”**, or open the record and set
   **Status → approved**.
4. There is **no bulk reject action** for professors. To reject, open the record, set
   **Status → rejected**, and save. The row stays for audit and is hidden publicly.

> Approving a professor does **not** approve their reviews. Reviews are moderated independently;
> a professor page can be public with zero visible reviews.

### 4.2 Adding a professor directly (trusted)

Use `/admin/reviews/professor/add/` when you have verified the person yourself. Fields:

- **School** — required.
- **First name**, **Last name** — required, max 40 chars each.
- **Slug** — **required and must be unique**. It is **not** auto-filled for professors (unlike
  Schools). Use lowercase Latin transliteration with hyphens, e.g. `aibek-toktogulov`. If you leave
  it empty, the form will not save. Avoid changing it after the page is public — the public URL is
  `/professors/<slug>/` and old links will 404.
- **Department** — required, max 80 chars.
- **Title** — required; the admin field is free text, so enter one of the four canonical public
  values: `профессор`, `доцент`, `старший преподаватель`, `преподаватель`. (The public form limits
  users to those four; the admin does not.)
- **Status** — defaults to `approved` in the admin. For user submissions, use `pending`; for a
  trusted manual entry, `approved` is fine.
- **Created by** — optional; set it if you are entering on someone's behalf.

If you get a duplicate error, a professor with the same first/last name already exists **at that
school** (case-sensitive DB constraint plus a case-insensitive check in the repository). Search and
edit the existing record instead of creating a second one.

### 4.3 Editing and deleting

- Edit spelling, department, title freely; changing the **slug** breaks existing links.
- **Rejecting** hides the professor (`/professors/<slug>/` returns 404) and removes them from search.
- **Deleting** a professor **permanently deletes all of their reviews**, votes, and reports
  (`on_delete=CASCADE`). Do this only for test/spam records, after a backup. Prefer `rejected`.
- If a professor changes school, create the correct school and edit the FK; reviews stay attached to
  the professor. If you instead create a new professor at the new school, the old reviews remain on
  the old record.

### 4.4 Professor complaints, corrections, and right of reply

There is no claim/response feature in the product. Until one is built:

1. Verify the requester's identity (university email or another credible channel).
2. If a review contains a factual error, edit the specific sentence only if the correction is
   uncontroversial; otherwise reject the review and ask for a corrected submission (remember §2.4).
3. If the complaint is about tone/opinion, explain the content policy; do not remove a legitimate
   opinion.
4. If it is a legal threat, follow §9: hide pending review, preserve evidence, involve counsel.
5. Keep a written record of every request and decision. Set an internal SLA (e.g. 5 business days).

---

## 5. Schools, cities, and tags

### 5.1 Schools

- Add at `/admin/reviews/school/add/`: **Name**, **City**, **Slug**.
- The slug auto-populates from the name (Unicode is allowed for this model). Verify it is what you
  want; the public URL is `/schools/<slug>/`.
- **City** is free text and drives the city filter. Use one canonical spelling per city
  (`Бишкек`, `Ош`, …). `Бишкек` and `бишкек` become two filter entries.
- Changing a school's **name** does not update its slug. Changing the slug breaks existing links.
- **Deleting a school cascades to all professors and reviews.** Never delete a school that has real
  content; reject/hide it or merge records manually.

### 5.2 Tags

- Tags live at `/admin/reviews/tag/`. They appear on review cards and in the top-tags summary.
- The public review form only offers the curated list in `reviews/repository.py` (`TAGS`). **Adding
  a Tag in the admin does not add it to the public form**; that requires a code change and deploy.
- You can attach any existing tag to a review in the admin via the tag widget, even if it is not in
  the public list. Use this sparingly; it can create inconsistent taxonomy.
- Deleting a tag removes it from all reviews (M2M), but the reviews remain.
- Do not add tags that encode protected traits, allegations of crime, or personal information.

### 5.3 Titles and grades

The **title** choices and the public **grade** choices are hard-coded in
`reviews/forms.py` / `reviews/repository.py`. Admin can type any grade string on a review, but the
public form will not offer it. To change these vocabularies, request a code change.

---

## 6. Users and accounts

### 6.1 Find a user

`/admin/auth/user/` → search by username or email. The username **is** the email address at signup.
Changing the **email** field later does not change the username (login identifier); change both if
the person needs a new login. Ensure the new username/email is unique.

### 6.2 Reset a password

There is no self-service password reset yet. To help a locked-out user:

1. Open the user in admin.
2. Click **Change password** (link near the password field).
3. Set a strong temporary password.
4. Send it over a secure channel and ask the user to change it at `/admin/password_change/`
   (staff) — regular users cannot access that page, so they will need to keep the temporary
   password until a reset flow is built. This is a strong reason to prioritize R-08.

### 6.3 Deactivate vs delete

| Action | Effect |
|---|---|
| **Deactivate** (`is_active=False`) | User cannot log in; their reviews/votes/reports remain. Reversible. **Preferred** for abuse. |
| **Delete** | User row removed; `Review.author` becomes `NULL` (reviews stay public); their `Vote` and `Report` rows are deleted; review `helpful`/`reported` counters are **not** recomputed. Irreversible. |

Prefer deactivation. If you must delete for a privacy request, decide separately whether the review
content itself must be removed (it may still be personal data). Document the request and action.

### 6.4 Grant/revoke moderator access

- Grant: check **Staff status**, add to `Moderators`, keep **Superuser status** off. Save.
- Revoke: uncheck **Staff status**, remove from the group, or set `is_active=False`. Do this on the
  person's last day, not later.
- Review the staff list monthly. A stale staff account is an incident waiting to happen.

### 6.5 Superuser hygiene

- Keep 1–2 superusers, both with 2FA and unique passwords.
- Never use the superuser for daily moderation; use a moderator account.
- If a superuser leaves, rotate the password, remove the account, and rotate `SECRET_KEY` if there
  is any doubt about session compromise.

---

## 7. Content policy quick reference

The public rules page (`/rules/`) states: reviews are only about studying; no insults, threats,
discrimination, personal data, or illegal content; moderation applies; violations lead to removal
and blocking. Apply these consistently.

| Content | Decision |
|---|---|
| Teaching quality, grading fairness, workload, communication | Approve |
| Course name typo / formatting / wrong term | Edit, then approve |
| Harsh but civil criticism of teaching | Approve |
| Personal insult, mockery of appearance/speech/identity | Reject; repeat → deactivate |
| Phone, address, social handle, photo, transcript, student ID | Reject; delete the data; warn/ban |
| Accusation of corruption, crime, or sexual misconduct | Reject; preserve; escalate to counsel |
| Threat of violence | Hide immediately; preserve; contact authorities; notify the target |
| Advertising, tutoring, referral links, cheating/exam answers | Reject; delete; ban |
| Off-topic personal life/rumor | Reject |
| Duplicate/test entry | Delete |
| Professor reviewing self/colleague, or a competitor | Reject |
| Legally mandated takedown | Hide; preserve; escalate; do not delete until counsel advises |

**Tone:** reject the content, not the person, on first minor offense. Escalate repeat behavior.
Never edit a review to change its meaning; only fix form (spelling, course name, formatting).

---

## 8. Routine operating calendar

### Daily (10–20 minutes)

- [ ] Clear pending reviews oldest-first.
- [ ] Clear pending professors.
- [ ] Triage reports.
- [ ] Check alert inbox (Sentry/uptime/5xx).
- [ ] Confirm the site loads and login works (spot check).

### Weekly

- [ ] No pending item older than 48 hours (or document why).
- [ ] No duplicate professors/schools; merge/edit.
- [ ] Reported counters make sense; reset handled ones.
- [ ] Backups succeeded; disk usage < 80%.
- [ ] Review admin logins and new staff accounts.
- [ ] Skim user feedback/translation issues.

### Monthly

- [ ] Restore a backup into staging (or at least verify the dump is readable).
- [ ] Review staff/moderator list; remove inactive access.
- [ ] Apply dependency/security updates; run `check --deploy` and tests.
- [ ] Audit a sample of approved reviews for policy drift.
- [ ] Process privacy/deletion/correction requests; update the log.
- [ ] Review metrics: pending age, approval rate, reports per 100 reviews, spam accounts.

### Quarterly

- [ ] Legal/policy review; update Terms/Privacy/Content Policy.
- [ ] Verify TLS/HSTS/renewal and firewall rules.
- [ ] Tabletop a takedown/breach/spam-wave scenario.
- [ ] Re-train moderators; refresh this guide.

---

## 9. Emergencies

### 9.1 Spam or brigading wave

1. **Do not approve anything in bulk.** Reject the batch; keep evidence.
2. Deactivate obvious spam accounts (`is_active=False`).
3. Block the source IP/ASN at Caddy/Cloudflare (temporary).
4. Close registration if the kill switch exists (`REGISTRATION_OPEN=False` + restart). If it does not
   exist yet, ask for the code change; meanwhile block at the edge.
5. Enable/raise CAPTCHA and rate limits.
6. Post a short status note if the public site is affected.
7. After the wave: review how accounts got through; tighten signup; document.

### 9.2 Doxxing, threat, or harassment

1. Set the review to **rejected** (hides it immediately).
2. Preserve a copy: screenshot + database row (do not delete yet).
3. Deactivate the author; preserve their account data for investigation.
4. If there is a credible threat of violence, contact local authorities and notify the target
   according to your policy and legal advice.
5. Record time, reviewer, actions, and evidence location.

### 9.3 Legal takedown / defamation complaint

1. Acknowledge receipt within your published SLA.
2. Hide the content (rejected) while reviewing; do not delete.
3. Preserve the review, author, timestamps, and reports.
4. Escalate to counsel; follow their instruction on disclosure/removal.
5. Respond to the complainant in writing; keep the correspondence.
6. Update the moderation log.

### 9.4 Account or admin compromise

1. Reset the affected password; deactivate the account.
2. Rotate `SECRET_KEY` (invalidates all sessions), then `python manage.py clearsessions`.
3. Rotate DB and SMTP credentials if they may be exposed; update `.env`; restart.
4. Review `LogEntry` and access logs for changes; preserve logs.
5. Notify affected users if personal data was accessed, per legal advice.
6. Check for rogue staff/superuser accounts and unknown permissions.

### 9.5 Data breach

1. Contain: revoke credentials, isolate the service, preserve logs.
2. Assess: what data (emails, reviews, votes), how many users, time window.
3. Notify counsel/owner; follow applicable breach-notification law.
4. Communicate truthfully to users; do not speculate.
5. Post-incident: rotate secrets, patch the cause, update the runbook.

### 9.6 Site down

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=200 web
docker compose -f docker-compose.prod.yml logs --tail=200 caddy
curl -sS https://proflens.kg/healthz
curl -sS https://proflens.kg/readyz
df -h
```

- `web` restarting: read logs for a missing env var, migration error, or DB connection failure.
- `readyz` 503: database down/unreachable; check `db` health and credentials.
- 502 from Caddy: `web` is unhealthy; fix it or roll back.
- Disk full: prune old images/backups/logs; never delete the live DB volume.

### 9.7 Accidental mass deletion

1. Stop writes/maintenance mode if possible.
2. Identify the deletion time and scope from `LogEntry`/logs.
3. Restore the latest backup into a **new** database; compare.
4. Copy back only the lost rows if feasible; otherwise schedule a maintenance-window restore.
5. Document the cause and add a guard (confirmation, permission removal, backup).

---

## 10. Backups and maintenance tasks

### 10.1 Manual backup (before any bulk action)

```bash
cd /srv/proflens
docker compose -f docker-compose.prod.yml exec -T db \
  sh -c 'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' > "backup-$(date +%F-%H%M).dump"
```

Store off-host, encrypted. Test that the dump is readable:

```bash
cat backup.dump | docker compose -f docker-compose.prod.yml exec -T db sh -c 'pg_restore --list' | head
```

### 10.2 Restore (into staging or an empty DB; destructive)

```bash
# Example only: target must be an empty/staging database, never the live DB without a window.
cat backup.dump | docker compose -f docker-compose.prod.yml exec -T db \
  sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists'
```

### 10.3 Routine commands

```bash
# Apply migrations (release step)
docker compose -f docker-compose.prod.yml exec web python manage.py migrate --noinput

# Collect static after template/CSS changes
docker compose -f docker-compose.prod.yml exec web python manage.py collectstatic --noinput

# Compile translations after .po changes
docker compose -f docker-compose.prod.yml exec web python manage.py compilemessages

# Check production configuration
docker compose -f docker-compose.prod.yml exec web python manage.py check --deploy

# Restart the app only
docker compose -f docker-compose.prod.yml up -d web

# Logs
docker compose -f docker-compose.prod.yml logs -f --tail=100 web
```

### 10.4 Recompute denormalized counters

Use only when counts drift after deleting votes/reports (back up first):

```bash
docker compose -f docker-compose.prod.yml exec web python manage.py shell -c "
from reviews.models import Review
for r in Review.objects.all():
    r.helpful = r.votes.filter(helpful=True).count()
    r.not_helpful = r.votes.filter(helpful=False).count()
    r.reported = r.reports.count()
    r.save(update_fields=['helpful','not_helpful','reported'])
print('counters recomputed')
"
```

### 10.5 Useful moderation queries

```bash
docker compose -f docker-compose.prod.yml exec web python manage.py shell -c "
from reviews.models import Review, Professor, Report
from django.utils import timezone
from datetime import timedelta
print('pending reviews:', Review.objects.filter(status='pending').count())
print('pending professors:', Professor.objects.filter(status='pending').count())
print('reports:', Report.objects.count())
old = Review.objects.filter(status='pending', created_at__lt=timezone.now()-timedelta(hours=48)).count()
print('pending >48h:', old)
"
```

---

## 11. What you cannot do from the admin (requires a code change)

These are deliberate gaps in the current MVP; know them before promising anything to users:

- Add a new tag to the **public** review form (admin Tag additions are not offered to users).
- Change the public **title** or **grade** vocabularies.
- Close registration temporarily (no `REGISTRATION_OPEN` switch yet).
- Send email to users, or notify authors when a review is approved/rejected.
- See **why** a review was reported (no reason field), or track report resolution status.
- See an audit trail for bulk approve/reject actions.
- Offer self-service password reset or account deletion.
- Let a professor claim a profile or post a reply.
- Export data from the admin (use `dumpdata`/SQL with care, or ask for an export feature).
- Rename the admin path or add 2FA (deployment/config task).
- Add custom pages (Privacy, Terms, Takedown) without templates/routes.
- Merge duplicate schools/professors automatically.

If a user asks for one of these, say it is on the roadmap and record the request; do not improvise
with database edits unless you have a backup and a tested query.

---

## 12. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| “Отзыв отправлен…” but review is not public | Status is `pending` | Approve in `/admin/reviews/review/?status__exact=pending` |
| Professor page 404 | Professor is `pending`/`rejected` | Approve in admin; check slug |
| Footer says “Демо-данные сбрасываются при рестарте” | `REPO_BACKEND=memory` | Set `REPO_BACKEND=django`, restart; data from memory is already lost |
| Admin/site has no CSS | `collectstatic` not run / WhiteNoise missing | Run `collectstatic`; check `/static/reviews/style.css` returns 200 |
| 403 CSRF after login | HTTPS/proxy mismatch or missing `CSRF_TRUSTED_ORIGINS` | Check `SECURE_PROXY_SSL_HEADER`, `CSRF_TRUSTED_ORIGINS`, clear cookies |
| Too many redirects | `SECURE_SSL_REDIRECT=True` without proxy header | Set `SECURE_PROXY_SSL_HEADER` and ensure proxy sends `X-Forwarded-Proto: https` |
| 502 Bad Gateway | `web` container down/unhealthy | `docker compose ps`, logs, restart; check DB |
| 500 after update | Missing env var, migration, or code error | Read logs; run `check`/`migrate`; roll back if needed |
| “no such table” / DB connection refused | Migrations not applied or wrong `DATABASE_URL` | Run `migrate`; verify DB host/credentials/SSL |
| Cannot log into admin | `is_active=False`, not staff, wrong password | Fix in admin (via another superuser) or `changepassword` |
| Duplicate professor error | Existing record with same name/school | Search and edit; do not create a duplicate |
| Student cannot resubmit after rejection | Duplicate check includes rejected reviews | Delete the rejected row (with a copy) or edit+approve |
| `Reported`/`helpful` counts wrong | Denormalized counters not updated on delete | Recompute with §10.4 or edit manually |
| Vote seems not counted twice | One vote per user per review (DB unique) | Expected behavior |
| Language switch does nothing | `.mo` not compiled / cookie blocked | Run `compilemessages`; check cookie settings |
| Admin 404 | Admin path renamed or wrong host | Use the deployment's admin URL; check `config/urls.py` |
| Email not sent | SMTP not configured; no reset flow yet | Configure `EMAIL_*`; use manual password reset for now |
| Disk full | Logs/backups/images | Prune old images/logs; move backups off-host; do not delete the DB volume |

---

## 13. Owner launch checklist (first 7 days)

- [ ] Create your superuser and one moderator account; store credentials in a password manager.
- [ ] Change the admin path if it is still `/admin/`; restrict it by IP/VPN if possible.
- [ ] Load the real list of universities (admin → Schools); do not use demo `seed_kg` data.
- [ ] Disable/remove the demo footer message and any seeded fictional professors/reviews.
- [ ] Post the moderation SLA and response times on `/rules/`.
- [ ] Publish Privacy Policy, Terms, Content Policy, and a takedown contact.
- [ ] Run one full test: signup → submit review → approve → public view → vote → report → resolve.
- [ ] Verify a backup dump and a restore into staging.
- [ ] Confirm Sentry/uptime alerts reach you.
- [ ] Bookmark the pending-review and pending-professor URLs.
- [ ] Decide who moderates on weekends; set an escalation contact.
- [ ] Schedule a 30-day review of this guide and the P1 backlog.

---

## 14. Quick reference

**Approve a review:** `/admin/reviews/review/?status__exact=pending` → open → Status `approved` → Save.

**Bulk approve:** select → “Одобрить выбранные отзывы” → Go → confirm.

**Hide a review:** Status `rejected` → Save (retained, not deleted).

**Approve a professor:** `/admin/reviews/professor/?status__exact=pending` → select → “Одобрить выбранных преподавателей” → Go.

**Reports:** `/admin/reviews/report/` → open review → decide → reset `Reported` → delete report rows (optional).

**Users:** `/admin/auth/user/` → deactivate for abuse; never share the superuser.

**Backup before bulk actions:** `pg_dump -Fc` (see §10.1).

**When in doubt:** hide (`rejected`), preserve evidence, ask for a second opinion, and never delete
without a backup.

---

*This guide reflects the code at commit `5149bdd` and the current admin configuration. When the
moderation model or deployment changes, update the relevant sections. For infrastructure,
deployment, and the P0/P1 backlog, see [`DEPLOYMENT.md`](DEPLOYMENT.md).*