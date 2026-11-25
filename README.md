# Silent Space Cafe

PythonAnywhere staging and manual CI-gated releases: see [deploy/PYTHONANYWHERE.txt](deploy/PYTHONANYWHERE.txt). Preparation only; host deployment remains manual.

**Standing design rule:** all customer-facing pages use the homepage's shared ivory header and espresso footer, including identical typography, spacing, navigation, bag control and reservation button. Page mockups do not override this rule. Header/footer changes belong in the shared layout/styles and must apply everywhere. This rule is recorded in `AGENTS.md` and the local design skill. Earlier references below to page-specific espresso headers describe superseded design iterations.

Django 5.2, SQLite, Django templates, local CSS and vanilla JavaScript. Timezone: Asia/Karachi. Prices: PKR.

## Final acceptance testing

Run these checks from the project directory in PowerShell:

```powershell
cd "D:\Silent Space"
.\venv\Scripts\python.exe manage.py check
.\venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\venv\Scripts\python.exe manage.py migrate --check
.\venv\Scripts\python.exe manage.py test
# Browser checks require optional Playwright and installed Chrome.
.\venv\Scripts\python.exe -m pip install playwright
.\venv\Scripts\python.exe tools/check_staff.py
.\venv\Scripts\python.exe -u tools/check_acceptance.py --check-windows-scheduler
```

The final acceptance runner uses an isolated temporary SQLite database, a private server on port 8002, disposable staff/viewer/customer accounts and an explicitly configured loopback SMTP inbox, `acceptance@silent-space.test`. The capture server accepts only that recipient. It never uses real staff recipients or SMTP credentials. Its controlled reminder clock runs only in private worker subprocesses; live reminder settings and records are unchanged.

It checks QR SVG export and its URL, phone-sized dine-in checkout, matching receipt/table/reference in the dashboard, receipt of the New Order message over SMTP, completion on the customer receipt, disabled QR blocking, reservation approval/Upcoming/reminder/cancellation/rebooking, one unattended-order reminder, acted-on skips, SMTP outage/exhaustion/recovery, overlapping command processes, permissions/CSRF and favicon responses.

With `--check-windows-scheduler`, it attempts to create a temporary one-minute repeating Windows task, waits for the worker's success marker and SMTP delivery, then removes the task. Registration or execution failure is reported as unverified. This probe does not verify logged-out execution under a production service account. Production scheduling instructions are below.

Evidence: `artifacts/acceptance-results.json`, `artifacts/acceptance-*.png` and the synthetic `artifacts/acceptance-new-order.eml`. The exported demo QR is an artifact for a temporary database/server that is deleted afterwards; export a fresh QR for the actual cafe. The runner fingerprints real order, booking, menu and location records before/after and removes its temporary services/data.

No physical phone, external SMTP credentials or explicitly designated external test inbox were available for the acceptance run. Physical camera scanning, print quality, LAN/firewall access, external inbox/spam delivery and logged-out production scheduling remain separate deployment checks. Live email checks must use a dedicated test inbox as the only `STAFF_NOTIFICATION_RECIPIENTS` value; do not assume an owner or customer address is a test destination. SMTP acceptance alone does not prove inbox delivery.

Before deployment: configure a strong `SECRET_KEY`, `DJANGO_DEBUG=False`, real `ALLOWED_HOSTS`, HTTPS `SITE_BASE_URL`, SMTP credentials and an authorized sender, staff recipients, service-account scheduling, and backed-up persistent database storage. Use a production application server and serve collected static files; Django `runserver` is for development.

```powershell
.\venv\Scripts\python.exe manage.py collectstatic --noinput
.\venv\Scripts\python.exe manage.py check --deploy
```

Review deployment-check output against the actual HTTPS/reverse-proxy setup. These commands alone do not establish production readiness. Verify backups/persistence, public staff links, permissions, actual test-inbox receipt and recurring task execution under the deployment account.

The final run passed standard Django checks and migration checks, all 38 automated tests, the isolated acceptance journey, and a real temporary Windows scheduler execution with local SMTP delivery. The production `check --deploy` reported five configuration warnings: `security.W004` (HSTS), `security.W008` (HTTPS redirect), `security.W009` (weak/development secret), `security.W012` (secure session cookie), and `security.W016` (secure CSRF cookie). Configure a long random `SECRET_KEY` through the existing environment setting. Set `SECURE_HSTS_SECONDS`, `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE` and `CSRF_COOKIE_SECURE` in the deployment settings after establishing HTTPS; these four security settings currently use Django defaults and are not read from `.env`. Confirm any trusted reverse-proxy SSL header configuration against the actual deployment. Do not enable HTTPS-only behavior on the local HTTP demo merely to silence the warnings.

## Run in PowerShell

```powershell
cd "D:\Silent Space"
# For a fresh checkout only:
py -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
# Edit .env before enabling SMTP. Never overwrite an existing configuration.
.\venv\Scripts\python.exe manage.py migrate
.\venv\Scripts\python.exe manage.py seed_menu
.\venv\Scripts\python.exe manage.py check
$env:DJANGO_DEBUG = "True"
.\venv\Scripts\python.exe manage.py runserver
```

Open http://127.0.0.1:8000/. Activating the virtual environment is optional.

`DJANGO_DEBUG` controls Django debug mode and takes precedence over legacy `DEBUG`. Use `DJANGO_DEBUG=True` locally and `DJANGO_DEBUG=False` in production. This avoids inherited variables such as `DEBUG=release` overriding the local `.env` setting and disabling runserver static assets. Existing deployments that only set `DEBUG` remain supported. Production still requires collected static files served by the web server.

## Design and scope

The old mockups in `design-references/` are retired. The thesis proposal guides the cafe concept. Invoke `$silent-space-design` in future phases; its instructions are in `.agents/skills/silent-space-design/SKILL.md`.

The storefront uses active `menu.MenuItem` records ordered by display order. `seed_menu` creates missing approved items by unique slug and never overwrites existing prices, descriptions, order or active status. The initial seed values live in `menu/seed_data.py`.

The session-backed bag supports adding, increasing, decreasing and removing through CSRF-protected POST forms, including without JavaScript. It stores IDs and quantities only, uses current database prices, removes unavailable items with a notice, and caps each line at 99. Decreasing a quantity of one removes that line. Header count is the total quantity. Dine-in checkout requires an enabled service QR. Reservation requests appear in Django Admin.

Open the homepage, use a menu card's + button, then adjust quantities on `/orders/bag/`. Refresh to verify persistence. Create staff access with `.\venv\Scripts\python.exe manage.py createsuperuser`, then open `/admin/` to edit menu prices, display order and active status. Staff changes are reflected on the next page request.

Run the focused tests with `.\venv\Scripts\python.exe manage.py test orders`. Optional browser checks require `pip install playwright` in the virtual environment and installed Chrome. Run the site on port 8001 and execute `tools/check_phase2.py`.



SQLite, local development defaults and the fallback secret key are for development. Set SECRET_KEY, DJANGO_DEBUG and ALLOWED_HOSTS through environment variables for deployment.

## Photography and reservations

The hero photograph is illustrative. Source: [Unsplash image](https://images.unsplash.com/photo-1554118811-1e0d58224f24). Replace `static/images/concept-cafe.jpg` with an approved interior photograph and update the alt text and caption in `templates/core/partials/hero.html`. The proposal did not supply a usable cafe logo.

Requests submitted through the homepage or Book a Table are stored as pending review and visible in the staff dashboard and Django Admin. The site uses Pakistan Standard Time. Staff can approve or reject pending requests and cancel approved reservations. Customer status links reflect the decision. Staff email notifications and reminders are implemented; online payment and physical focus indicators remain outside this demo.

## Dine-in and booking demo (PowerShell)

```powershell
cd "D:\Silent Space"
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe manage.py migrate
.\venv\Scripts\python.exe manage.py seed_menu
.\venv\Scripts\python.exe manage.py seed_demo_workflows
.\venv\Scripts\python.exe manage.py createsuperuser
.\venv\Scripts\python.exe manage.py export_location_qr "Demo Table 01" "http://127.0.0.1:8000" "demo-table-01.svg"
$env:DJANGO_DEBUG = "True"
.\venv\Scripts\python.exe manage.py runserver
```

Use an existing staff login instead of creating another account if one exists. The QR export prints the scan URL for desktop testing and writes a printable SVG. Pick a new output name on repeat exports.

The demo seed adds missing records only. **10:00-18:00 PKT daily**, **6 Quiet Corner / 4 Reading Zone / 1 Solo Space seats**, and **Demo Table 01 / Demo Reading Zone** are demo configuration. Edit Booking hours, Zone capacities and Service locations in Admin. A missing weekday or zone is closed. Bookings start on the hour, last one hour and are checked again at approval. Pending requests do not hold capacity. Existing reservation rows retain their original details and receive unique references with pending status.

For a phone on the same network, replace loopback with the PC's LAN IP when exporting the QR. For example, if the PC is 192.168.1.25, set `$env:ALLOWED_HOSTS = "127.0.0.1,localhost,192.168.1.25"` and run `.\venv\Scripts\python.exe manage.py runserver 0.0.0.0:8000`. Export with `http://192.168.1.25:8000` and a new SVG filename. Allow local network access on port 8000 if prompted.

Print or display the SVG and scan it with the phone camera. Add a menu item, review the service location in checkout and place the order. Save the receipt URL to follow its status. In `/staff/orders/`, search the exact reference, match the table/zone, then use **Start preparing** and **Mark completed**. Reload the original phone receipt and verify Completed. Run the notification worker and verify the New Order message in the explicitly configured test inbox. Admin offers the same transitions. In Reservations, approve or reject a pending request; approved bookings appear in Upcoming. Customers should save the reservation status URL.

For the disabled-QR check, export a demo location while enabled, then disable it in Admin and scan the same existing QR. The customer should see Service location unavailable and be unable to place a new order there. The export command refuses disabled locations and refuses to overwrite an existing output filename. Re-enable only your demo location afterwards. Without a phone, opening the exported URL tests routing and ordering but does not verify physical scanning, print quality or LAN reachability. The loopback address is reachable only on the PC; use the actual LAN address for a phone. Set `SITE_BASE_URL` to that reachable origin while testing authenticated email links. Book exchange, loyalty and focus lights remain concept content.

## Phase 3: cancellations and staff notifications

Existing orders, reservation records and UUID customer links are retained. No seed or reset is required. In Admin > Reservation requests, select an Approved reservation and use **Cancel selected approved reservations**. The action requires change permission, accepts an optional internal cancellation reason, records the cancellation time, and has no effect on repeat cancellation. Cancelled reservations no longer consume capacity. The customer status page shows Cancelled and does not expose the internal reason. Approval still rechecks booking hours and capacity.

Only QR dine-in orders currently exist; there is no pickup workflow or pickup time. New orders queue one event after their line snapshots are saved, in the same database transaction. Repeat checkout returns the same order without enqueueing again. New reservation requests similarly queue an event in their save transaction. SMTP runs only in the worker, so a mail outage cannot undo an order or reservation. Existing historical records do not receive new-submission emails; eligible existing records can receive reminders.

### Windows setup and manual processing

```powershell
cd "D:\Silent Space"
.\venv\Scripts\python.exe -m pip install -r requirements.txt
# Fresh configuration only: copy the example if .env does not already exist.
if (!(Test-Path .env)) { Copy-Item .env.example .env }
# Edit .env, especially STAFF_NOTIFICATION_RECIPIENTS and SITE_BASE_URL.
.\venv\Scripts\python.exe manage.py migrate
.\venv\Scripts\python.exe manage.py check
.\venv\Scripts\python.exe manage.py test
.\venv\Scripts\python.exe manage.py process_notifications --limit 100
```

The default console backend prints messages in the worker terminal. Automated tests explicitly use Django's in-memory backend. For SMTP set `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend` and supply provider credentials in the ignored `.env` or process environment. Do not commit real credentials. Django's backends and SMTP settings are documented at https://docs.djangoproject.com/en/5.2/topics/email/.

| Variable | Default / purpose |
| --- | --- |
| STAFF_NOTIFICATION_RECIPIENTS | Empty; required comma-separated staff addresses. Missing recipients cause a recorded delivery failure. |
| SITE_BASE_URL | http://127.0.0.1:8000; production HTTPS origin used for authenticated Admin links. |
| EMAIL_BACKEND | django.core.mail.backends.console.EmailBackend; use smtp.EmailBackend in production with the full Django path. |
| DEFAULT_FROM_EMAIL | cafe@example.test; replace with an authorized sender. |
| EMAIL_HOST / EMAIL_PORT | Empty / 587; provider host and port. |
| EMAIL_HOST_USER / EMAIL_HOST_PASSWORD | Empty; SMTP credentials. |
| EMAIL_USE_TLS / EMAIL_USE_SSL | True / False; select the provider's mode, never both True. |
| EMAIL_TIMEOUT | 30 seconds per blocking SMTP operation. |
| ORDER_REMINDER_MINUTES | 10 minutes after placement, only while Received. |
| RESERVATION_REMINDER_MINUTES | 60 minutes before the start, only while Approved and still in the future. |
| NOTIFICATION_MAX_ATTEMPTS | 3 attempts per automatic delivery cycle. |
| NOTIFICATION_RETRY_SECONDS | 60 seconds; exponential retry delay (60, 120, ...). |

Times in messages display Asia/Karachi (PKT). A reminder is generated on the first worker run after its threshold; reservation reminders are skipped if the scheduler misses the entire remaining future window. Eligibility is checked again before each delivery/retry, so acted-on orders and cancelled/past reservations are skipped. Staff should operate in Admin; manually editing status in the database is outside the workflow.

### Schedule every minute

Run on the deployment host with access to the same database and environment as the web app. On Windows, in PowerShell (adjust paths for the production checkout):

```powershell
$action = New-ScheduledTaskAction -Execute 'D:\Silent Space\venv\Scripts\python.exe' -Argument '"D:\Silent Space\manage.py" process_notifications --limit 100' -WorkingDirectory 'D:\Silent Space'
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
$taskSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable
Register-ScheduledTask -TaskName 'SilentSpaceNotifications' -Action $action -Trigger $trigger -Settings $taskSettings -Description 'Process Silent Space staff emails every minute'
Start-ScheduledTask -TaskName 'SilentSpaceNotifications'
Get-ScheduledTaskInfo -TaskName 'SilentSpaceNotifications'
```

Configure the task to run under the deployment service account whether logged on or not using Task Scheduler. Enter account credentials through the Windows UI, never source files. Verify its database/environment permissions, run history, LastTaskResult = 0, actual test-inbox receipt and continuing one-minute triggers. Creating a trigger or manually invoking the command does not establish logged-out production scheduling. Alternatively, Linux cron (adjust checkout paths):

```cron
* * * * * cd /srv/silent-space && /srv/silent-space/venv/bin/python manage.py process_notifications --limit 100 >> /var/log/silent-space-notifications.log 2>&1
```

Unique database event keys prevent duplicate enqueueing. Each delivery uses an atomic pending-to-processing claim; overlapping commands cannot claim the same job. Batches default to 100; monitor backlog and tune `--limit` for volume. A process crash after claiming intentionally leaves the job Processing rather than automatically risking concurrent delivery. Review Failed and Processing records in Admin > Notifications, including attempts, claim time and last error. Stop all workers and confirm an interrupted worker is dead before using **Retry reviewed failed/interrupted deliveries**. This explicit staff action starts a fresh bounded retry cycle; it can duplicate an already accepted message.

SMTP cannot guarantee exactly-once delivery: the provider may accept a message before the application records success (or before a connection error is returned). Automatic retries or manual recovery can then send a duplicate. Database claims guard competing workers, not this provider acknowledgement gap. An action by staff during an in-flight send may also race with that reminder.

Real SMTP verification remains a deployment step: verify credentials, TLS/SSL, sender authorization, actual owner inbox delivery/spam placement, public HTTPS Admin links and a scheduled run under the production account. Console/in-memory tests cannot verify these.

## Phase 4: staff workspace

Open **http://127.0.0.1:8000/staff/** and sign in with an existing active staff account. The branded login is `/staff/login/`. Django Admin remains at `/admin/`; its sessions also work in the dashboard. No additional dependencies, database reset, migration or seed data is needed for Phase 4.

```powershell
cd "D:\Silent Space"
.\venv\Scripts\python.exe manage.py migrate
.\venv\Scripts\python.exe manage.py check
.\venv\Scripts\python.exe manage.py test
.\venv\Scripts\python.exe manage.py runserver
```

If a development server is running with `--noreload`, restart it to load Phase 4.

- **Overview:** oldest Received orders first, Preparing count, remaining Approved arrivals today, Pending requests, failed email count, and the next future Approved reservation. Summary cards open matching filtered lists. Restricted model data is not queried or shown.
- **Orders:** live dine-in queue, status filters, UUID/reference or location search, 25-row pagination, details and conditional transitions. Polls every 20 seconds while idle. Form edits, focus inside a form or queue, hidden tabs and in-flight interactions defer automatic refresh. Refresh queue updates just the results and keeps keyboard focus; ordinary GET navigation and POST actions also work without JavaScript. Completed orders show Closed rather than a growing wait. There is currently no pickup workflow or order-note collection.
- **Reservations:** Today includes all statuses on the local date; Upcoming includes future Approved reservations; Pending and Cancelled have dedicated filters. Details include contact information and special requests. Approve, reject and cancel use the same shared service as Admin, including approval capacity checks and repeat-safe cancellation.
- **Menu & QR:** permission-aware shortcuts to the existing Admin menu prices/availability and service-location editors.
- **Notifications:** recent delivery records, attempt counts, latest attempt/queue/sent times, errors and status filtering. Failed deliveries can be queued for a fresh bounded retry cycle. Pending, Processing, Sent and Skipped records cannot be retried from the dashboard. Interrupted Processing jobs require stopped-worker confirmation in Admin. Retrying does not send synchronously; continue running the Phase 3 worker.

### Staff permissions

In Admin > Users or Groups, grant the existing model permissions appropriate to each role. `is_staff` and an active account are required throughout `/staff/`. A model's **view** or **change** permission grants read access, matching Django Admin; its **change** permission is required for every state-changing action. Superusers retain their existing access.

| Workspace | Model permissions (app.model) |
| --- | --- |
| Orders | orders.view_dineinorder / orders.change_dineinorder |
| Reservations | bookings.view_reservationrequest / bookings.change_reservationrequest |
| Notifications | notifications.view_notification / notifications.change_notification |
| Menu editor | menu.view_menuitem / menu.change_menuitem |
| QR location editor | orders.view_servicelocation / orders.change_servicelocation |

Staff without a model's permissions cannot open its list, detail, fragment endpoint or action. Non-staff accounts receive 403 even when authenticated. Anonymous visitors go to the staff login, which rejects non-staff credentials. All actions and logout require POST and CSRF; dashboard data responses are marked non-cacheable. Existing customer UUID status and receipt links remain available on their original routes.

Transitions live in `orders/services.py` and `bookings/services.py`; delivery retry rules live in `notifications/services.py`. Both Admin and the dashboard call these shared services. Processing recovery in Admin now requires checking **All workers stopped**; ordinary retries only affect Failed jobs. SMTP acknowledgement ambiguity and bounded delivery retries are unchanged.

### Browser review

```powershell
# Requires the existing optional Playwright installation and installed Chrome.
.\venv\Scripts\python.exe tools/check_staff.py
```

The script creates a temporary SQLite database, runs its own server on port 8001, and uses disposable staff/viewer/customer accounts. It never seeds the real cafe database or sends email. It checks 390px, 768px and 1440px layouts, queue search, order transitions, reservation approval/cancellation, notification retry, Admin editing access, limited/non-staff access, focus-safe automatic/manual queue updates, keyboard navigation, valid/invalid reservation submissions and a no-JavaScript storefront bag regression. Screenshots are saved as `artifacts/phase4-*.png`. The temporary server and database are removed afterwards.

The customer and staff templates declare the branded `static/images/favicon.svg`. Browsers requesting the conventional `/favicon.ico` path are redirected to the same asset, resolving the audit's browser-tab 404. Serve collected static assets in production.

## Editorial homepage redesign

The supplied editorial homepage image guides the warm ivory/espresso/olive/brass palette, serif typography, split hero, square image cards, booking banner and footer. The local `DOC-20260803-WA0013.docx` proposal was read for cafe context. Its feature descriptions are treated as concept evidence, not implementation instructions or proof of operating amenities.

The homepage order is hero -> Quiet Corner/Reading Zone/Solo Space -> cafe experience -> curated live menu -> olive reservation banner -> full reservation form -> useful footer links. The cafe experience preserves the mini library, book exchange, charging-point concept and quiet etiquette. Proposed focus lights and loyalty rewards remain explicitly labelled concept features. No unverified address, opening hours or contact details were invented.

The full working homepage reservation form remains at `#book-a-table`; hero/header/banner reservation buttons now open the dedicated page through `core:booking`. Dedicated booking, menu, story, spaces and bag routes remain available. The original `#quiet-zones`, `#our-story`, `#menu`, `#ordering-note` and `#book-a-table` anchors are preserved. Zone reservation links preselect a valid zone on the dedicated booking page without changing POST validation. QR service-location notices, POST/CSRF bag actions, bag counts, booking errors and customer status links remain intact.

The three-item preview selects active Classic Cappuccino, Rose Latte and Waffle Sandwich records when available, with active items in database display order filling empty slots. Names, descriptions and prices remain live database data. The full menu is not restricted to the preview. The staff dashboard and notification workflows are outside this visual change.

The existing cafe photo is reused. Six separate, optimized illustrative zone/menu assets and their provenance are documented in `static/images/editorial/README.md`. The mockup is not used as a flattened page image.

```powershell
.\venv\Scripts\python.exe manage.py check
.\venv\Scripts\python.exe manage.py test
# Optional Playwright + installed Chrome; isolated database/server on port 8003.
.\venv\Scripts\python.exe -u tools/check_homepage.py
```

Browser review writes desktop/tablet/phone screenshots to `artifacts/homepage-editorial-1440.png`, `artifacts/homepage-editorial-768.png`, and `artifacts/homepage-editorial-390.png`, with results in `artifacts/homepage-editorial-checks.json`. It checks images, fragment targets, primary links, bag persistence, QR table context, no-JavaScript behavior, keyboard navigation, live menu edits and invalid/valid reservation feedback. It uses a temporary database and sends no email.

Redesign verification passed: 42 automated Django tests, standard system checks, no pending model migrations, and browser review at 390px, 768px and 1440px. The tested palette pairs meet WCAG AA text contrast: body/ivory 15.08:1, muted text/card 5.55:1, button text/olive 8.87:1, footer text/espresso 9.86:1, and input labels/form 15.89:1. The ivory-page focus outline contrast is 5.40:1. These are checks of the specified palette pairs, not a complete automated accessibility audit.

Source files changed for the redesign: `templates/base.html`; `templates/core/home.html`; `templates/core/partials/hero.html`, `zones.html`, `story.html`, `menu.html`, `booking.html`; `static/css/editorial.css`; `core/views.py`; `core/templatetags/__init__.py` and `cafe_images.py`; `bookings/views.py` (validated GET zone preselection only); `core/tests.py`; `tools/check_homepage.py`; this README; and the six WebP images plus provenance README under `static/images/editorial/`. Existing URL names, database schema, staff views/styles, notification services and order workflow code were not changed.

## Product menu and photo controls

The full public menu is **http://127.0.0.1:8000/menu/**. It uses the homepage's shared ivory header and espresso footer, photo cards, a three/two/one-column responsive grid, live names/prices/display order/availability, and the reservation banner. QR arrivals use the same menu and retain their service location. The homepage preview also uses uploaded product photos when present.

Apply the additive photo migration without deleting or reseeding existing records:

```powershell
cd "D:\Silent Space"
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe manage.py migrate
.\venv\Scripts\python.exe manage.py check
.\venv\Scripts\python.exe manage.py test
# Restart a server running with --noreload after the upgrade.
$env:DJANGO_DEBUG = "True"
.\venv\Scripts\python.exe manage.py runserver
```

Pillow 13.x is now a declared dependency for Django ImageField decoding and validation. Migration `menu/0002_menuitem_image_menuitem_image_alt_and_more.py` adds optional `image` and `image_alt` fields; old items receive blank values and keep their IDs, slugs, names, descriptions, prices, active flags and display order. Order history is not migrated or rewritten. No seed command is needed for this upgrade.

Staff can open **/staff/catalogue/** for a branded thumbnail list with name/slug search, availability filtering, prices, display order and direct item links. All editing remains in **/admin/menu/menuitem/**. Users need an active staff account plus menu view or change permission to read the list. Change permission is required to edit; add permission is required to create items. View-only staff receive read-only Admin pages.

In Admin, open an item to upload/replace its photo, enter meaningful alt text, edit its description and price, reorder it, or change **Available / visible**. The list includes photo thumbnails, editable price/status/order, name search and a status filter. The edit page includes the current photo preview. Clearing an uploaded photo restores its illustrative default or neutral placeholder. Replacements use unique filenames; old files are not automatically deleted. Apply a reviewed storage-retention policy for unused files.

Uploads accept real single-frame JPEG, PNG or WebP images, at most **5 MB** and **20 megapixels**. SVG, GIF, unsupported/corrupt files, oversized files and animated images are rejected. Alt text is required when a photo is present. Validation errors return to the same Admin form. Upload validation is shared with model validation; unrelated edits do not require re-reading existing stored photos.

The six original slugs receive separate illustrative defaults, not copied prices or seed updates. Bubble Shot's actual serving is unverified, so its stock iced-coffee photo is explicitly marked **Illustrative serving**. Orange Malt and Hot Double Chocolate use separate generated illustrative images. New or old items without an uploaded photo or a matching default use a neutral cup placeholder. Image provenance is documented in `static/images/editorial/README.md`.

The existing `active` flag remains the single visibility/availability rule: disabling hides an item from the public menu and prevents additions; unavailable items already in bags are removed with feedback. Checkout still rechecks current availability and prices. Past orders keep their saved item names, quantities, unit prices and totals, regardless of later menu edits.

### Uploaded media in development and production

`MEDIA_URL` defaults to `/media/`; `MEDIA_ROOT` defaults to the project's `media` directory. Both may be set through the environment. The ignored `media/` directory holds uploaded files under `menu/products/` with unique filenames. With `DJANGO_DEBUG=True`, the existing Django URL configuration serves these files for local testing.

For production, configure `MEDIA_ROOT` as persistent, writable storage outside disposable releases, and serve `MEDIA_URL` through IIS, Nginx, Caddy, or a separately configured object-storage backend/CDN. `DJANGO_DEBUG=False` deliberately does not serve uploads through Django's development helper. Serve correct image MIME types, disable script execution in the media directory, and use `X-Content-Type-Options: nosniff`. Allow enough request-body capacity for the 5 MB photo plus multipart form data (for example, an 8 MB proxy limit). Back up media together with the database. `collectstatic` collects illustrative/default assets but **does not collect uploaded product photos**. Database records reference media filenames; losing the media volume will break those uploaded-photo URLs.

```powershell
# Example persistent location; grant the application account write access.
$env:MEDIA_ROOT = 'D:\SilentSpaceMedia'
$env:MEDIA_URL = '/media/'
# Configure the production web server to serve /media/ from that directory.
.\venv\Scripts\python.exe manage.py collectstatic --noinput
```

Focused checks and browser acceptance:

```powershell
.\venv\Scripts\python.exe manage.py test menu
.\venv\Scripts\python.exe -u tools/check_menu.py
```

The browser runner uses a temporary database, separate temporary uploaded-media directory and private server on port 8004. It never changes real menu/order records or sends email. It tests public/staff screens at 390/768/1440px, keyboard Add to bag, uploads/replacements/alt text, price/order/visibility changes, the unchanged historical price, QR table retention, unavailable bag cleanup, image-less/new items, invalid-upload feedback and staff permissions. Screenshots: `artifacts/menu-public-*.png`, `artifacts/menu-staff-*.png`, and `artifacts/menu-admin-photo-preview.png`; results: `artifacts/menu-checks.json`.

This menu upgrade passed all 49 automated tests, Django checks, migration consistency checks, dependency checks, and the browser acceptance above. The additive migration was applied to the project database; a before/after comparison confirmed unchanged existing menu values, order/line records and service locations. No seed command or reset was run.

Changed source files: `menu/models.py`, `menu/admin.py`, `menu/validators.py`, `menu/presentation.py`, `menu/migrations/0002_menuitem_image_menuitem_image_alt_and_more.py`, `menu/tests.py`, `core/templatetags/cafe_images.py`, `core/tests.py` (neutral-fallback expectation), `templates/core/menu.html`, `templates/core/partials/menu.html` (uploaded-image resolver), `static/css/editorial.css`, `static/css/staff.css`, `staff_portal/views.py`, `templates/staff/catalogue.html`, `silent_space/settings.py`, `requirements.txt`, `.env.example`, `tools/check_menu.py`, this README and image provenance notes. Added assets: `static/images/product-placeholder.svg` and the Bubble Shot, Orange Malt and Hot Double Chocolate WebP defaults under `static/images/editorial/`.

## Reservation page and available times

Open **http://127.0.0.1:8000/book-a-table/** (`core:booking`). Homepage and menu reservation buttons use this existing route. The editorial reservation page shares the homepage's ivory header and espresso footer, ivory palette, brass details and olive controls. Desktop shows the existing illustrative seating photograph and space guide beside the form; at phone/tablet widths the form comes first. The homepage form and old section anchors remain available.

Choose a date, party size and seating zone. The available-time select refreshes through the read-only `/bookings/availability/` endpoint using the shared booking rules in Asia/Karachi. Requests are one hour and start on the hour; configured hours, elapsed times and Approved capacity determine the choices. Solo Space permits exactly one guest, including at staff approval. Missing hours, closed zones and full selections return a helpful empty-state message. Pending requests do not hold seats.

Without JavaScript, enter the selection and press **Check available times**, then choose a returned time and submit. This check creates no reservation or notification, does not require name/contact details yet, and preserves entered details. The normal submit validates the selection and contact data again, obtains the same zone lock used by staff approval, and checks current capacity once more. An unavailable/stale slot returns inline feedback with details and alternatives retained.

Date, guests, zone, available time, name and phone are required. Special request and email are optional; existing email addresses remain unchanged in their staff records. Staff email notifications and reminders remain intact. This change does not introduce customer confirmation emails: customers must save their private status link and wait for the cafe's approval. The page explains Send your request, Check your booking status and Arrive a few minutes early once approved.

New requests receive a unique database submission key and a session-bound signed form token. Repeated submission returns the original UUID reference/status link and does not enqueue another notification, including after approval/cancellation. Already-saved tokens remain replayable in the same valid browser session after the form-creation window; unsent forms expire after 24 hours and return a refreshed token while retaining details. Loading a new booking page starts a new request. Old open forms/direct clients without a token use a server-side session key for sequential retry protection. All currently rendered forms carry signed tokens and the database unique key guards concurrent duplicate inserts. Existing reservations get a nullable key without rewriting their references or statuses.

Staff continue to approve/reject/cancel using the existing dashboard and Admin services. Approval still rechecks hours/capacity, cancellation releases seats while retaining its time/internal reason, and the same customer status URL shows the decision. Private status links expose status without a login and should be saved/shared carefully.

```powershell
cd "D:\Silent Space"
.\venv\Scripts\python.exe manage.py migrate
.\venv\Scripts\python.exe manage.py check
.\venv\Scripts\python.exe manage.py test
.\venv\Scripts\python.exe -u tools/check_reservations.py
# Restart a development server running with --noreload.
```

Migration `bookings/0004_reservationrequest_submission_key_and_more.py` adds a nullable unique submission key and makes email optional. No seed/reset or new dependency is required. The browser runner uses a temporary database/server on port 8005 and in-memory staff email; it never modifies real reservations or sends external email. It exercises desktop/phone/tablet ordering and layout, dynamic availability, closed/past/full selections, Solo Space, duplicate requests, matching staff/customer references, one queued notification, approval/Upcoming, cancellation/released capacity, retained error details and no-JavaScript submission. Screenshots: `artifacts/reservation-page-390.png`, `reservation-page-768.png`, `reservation-page-1440.png`; report: `artifacts/reservation-checks.json`. External SMTP inbox delivery is not verified by these tests.

Changed files for this stage: `bookings/availability.py`, `forms.py`, `models.py`, `views.py`, `urls.py`, `submissions.py`, `tests.py`, migration `0004`; `core/views.py`; `templates/core/booking.html`, `request_status.html`, `home.html`, `partials/booking.html`, `partials/booking_form.html`, `partials/hero.html`; `templates/base.html`; `templates/staff/reservation_detail.html` (optional email fallback); `static/css/editorial.css`, `static/css/reservations.css`, `static/js/reservations.js`; the relevant regression tests and browser helpers/runners; this README. Staff workflow services, notification delivery rules, order history and existing URL names are preserved.

Final reservation-stage verification passed: all 60 automated tests, Django system checks, migration consistency/no-pending-migration checks, reservation browser acceptance at 390/768/1440px, and the maintained homepage browser regression checks. Migration application included a before/after comparison of original reservation fields/references plus order/menu data. Tests use isolated records; email delivery is verified only with Django's in-memory backend, not an external SMTP inbox. The local `/book-a-table/` page returned HTTP 200 after restarting the development server, and an invalid availability request returned HTTP 400 as expected.

## Spaces and the reservation flow

Open **http://127.0.0.1:8000/spaces/**. The existing named route `core:zones` now resolves to this page, so navigation/footer links use it automatically. The homepage's Explore the spaces button also opens it. Old `/quiet-zones/` links permanently redirect, preserving query strings; `#quiet-zones` remains a valid fragment target. Useful homepage space previews and their booking links remain available.

The page reuses the homepage's identical shared header/footer under the standing design rule. Its content follows the supplied Spaces reference: split hero, three alternating photo/text rows, guest-facing space descriptions, quiet etiquette/book-exchange copy and the olive reservation banner. On phones, each photo stacks with its own description and link. It reuses the existing separate cafe/Quiet Corner/Reading Zone/Solo Space assets; they are illustrative and replaceable, with provenance in `static/images/editorial/README.md`.

Each Reserve this space link uses `core:booking` and the real `ReservationRequest.Zone` identifier: `quiet`, `reading` or `solo`. The general Reserve a seat link has no zone query. Guests may change the selection; available times continue using the shared date, party size, PKT opening-hour and capacity rules. Solo Space remains one guest.

The existing capacity configuration defines active zones: a known zone with a positive **Zone capacity** is active; zero seats or a missing capacity row closes it. A missing, invalid or inactive URL zone is ignored on GET, and the normal form offers active zones only. POSTs targeting a now-inactive zone are rejected with retained contact details. An active zone with no available times remains selectable/preselected and shows the existing no-times message; guests can change the date or zone. Closing a zone does not delete or cancel its existing reservations or status links.

To try locally:

```powershell
cd "D:\Silent Space"
.\venv\Scripts\python.exe manage.py check
.\venv\Scripts\python.exe manage.py test
$env:DJANGO_DEBUG = "True"
.\venv\Scripts\python.exe manage.py runserver
```

No new dependency, migration, seed or reset is required. Use existing Admin configuration to ensure the desired zones have positive seats and the chosen weekday has Booking hours. Open `/spaces/`, follow each space link, choose a future date and time, and submit. Save the reference/private status URL. Sign in to `/staff/` with an authorized existing staff account; in Reservations > Pending, find that reference and verify its zone. For an inactive-zone check on a **demo configuration**, temporarily set one Zone capacity to zero, open its link and verify the selection is blank and omitted from choices; restore its original capacity afterwards. A two-guest Solo request should show the one-guest message and cannot be saved.

```powershell
# Optional installed Playwright + Chrome; private server on port 8006.
.\venv\Scripts\python.exe -u tools/check_spaces.py
```

Verification passed: all 65 automated tests, system checks, no model changes/pending migrations, Spaces browser checks at 390/768/1440px and the maintained homepage browser regression. Browser checks cover identical shared-shell styles, separate images/crops, alternating/stacked layout, each preselected link, changing zones, general unselected entry, mobile navigation, keyboard access, a completed Reading Zone request with matching customer/staff reference, approval, inactive/invalid handling, Solo rejection, full-zone feedback, alternative dates, legacy redirects and no-JavaScript availability. Fixtures use a temporary database, leave real business records unchanged and send no external email. Physical-device/browser coverage and external SMTP delivery were not verified in this stage.

Screenshots: `artifacts/spaces-page-390.png`, `spaces-page-768.png`, `spaces-page-1440.png`, `spaces-booking-customer-reference.png` and `spaces-booking-staff-reference.png`. Report: `artifacts/spaces-checks.json`.

Changed files: `core/urls.py`, `core/views.py`, `core/spaces.py`, `core/tests.py`; `bookings/availability.py`, `bookings/forms.py`, `bookings/views.py`, `bookings/tests.py`; `templates/core/zones.html`, `templates/core/partials/hero.html`, `templates/base.html` (stylesheet include only); `static/css/spaces.css`; `tools/check_spaces.py`, `tools/check_homepage.py`; this README. Header/footer markup and styling, reservation records/references, staff workflow services and notification rules were not changed.

## Bag, delivery, pickup and payments

Open **http://127.0.0.1:8000/orders/bag/** after adding items from the menu. The bag now has product thumbnails, quantity/removal controls, server-priced order totals, delivery/pickup details and payment selection. It uses the homepage's identical ivory header and shared espresso footer; the checkout mockup's different header does not override the standing design rule. Checkout stacks at phone widths. Existing separate product assets (including their neutral fallback) are reused; no new illustrative photos were generated.

QR guests keep their scanned table/zone and use Review dine-in order. Regular guests can choose Delivery or Pickup. There was no existing pickup scheduling workflow, so pickup has no date/time selector or promised collection time. Delivery fields and fees are omitted for pickup. Without JavaScript, select the fulfilment/area and use **Update fees & payment options**, then place the order. JavaScript updates the fee/total and applicable methods immediately. The server always validates current products, prices, enabled areas and payment methods again. If a fee changed since review, guests see the new total and must submit again. Disabled areas and unserved area identifiers cannot be ordered from; staff must configure actual service areas before delivery is usable. No fictitious delivery areas were seeded.

Configuration in Django Admin (authorized model permissions required):

- **Orders > Delivery areas**: `/admin/orders/deliveryarea/`. Add real area names, PKR fees and Enabled status. Fees must be nonnegative. Disabling an area preserves past orders.
- **Orders > Payment methods**: `/admin/orders/paymentmethod/`. Edit Enabled, Delivery, Pickup, Dine in, receiver account, transfer instructions and display order. **JazzCash** starts with receiver **03249233487**, editable here. **Easypaisa** starts disabled with no receiver; supply the receiver and enable the desired fulfilment types. COD is delivery-only; cash at pickup/cafe is pickup/dine-in only. Manual methods without receiver accounts and unconfigured card payments stay hidden.
- **Orders > Dine in orders**: `/admin/orders/dineinorder/` is the existing shared order ledger, now including all three fulfilment types. It retains historical references and line-price snapshots. Existing rows default to Dine-in; their original columns/records are preserved.
- **Staff > Orders**: `/staff/orders/`. Filter by fulfilment or Pending payment verification, open the reference and review address, fee, total, method, status and submitted transaction reference. Give reviewers both order view permission and the new **Can verify order payments** permission under Admin > Authentication and Authorization > Users/Groups. The **Verify manual payment** button and equivalent Admin action call the same service and record the staff user/time once. Viewing/changing order service status alone does not grant payment verification. Service status and payment status remain separate.

The order is saved and assigned its reference before transfer instructions appear. The private receipt shows the exact saved amount, saved receiver/instructions and a copy button. Submitting a transaction reference changes payment to **Pending verification**; the browser cannot mark it Paid. A repeated reference submission cannot overwrite an existing reference or reviewed payment. Corrections require contacting staff. Staff must check the receiver account before verifying. Cash orders remain Awaiting payment; the manual-transfer verification action does not mark cash collected. Checkout submission keys and unique notification events prevent duplicate order/new-order jobs. Every fulfilment type queues the same owner email with reference, items, fulfilment, total and current payment status. SMTP failures remain isolated in the existing retry queue.

### Optional hosted card checkout

A Stripe Checkout adapter is included. It is disabled initially, and no merchant keys were present during implementation. It requires an eligible Stripe merchant account that can accept PKR; do not assume a Pakistan-based business is eligible for Stripe onboarding. Confirm merchant/country/currency eligibility with the provider before enabling. See [Stripe availability](https://stripe.com/global), [Checkout Session API](https://docs.stripe.com/api/checkout/sessions/create) and [webhook setup](https://docs.stripe.com/events/set-up-events).

Set `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` in the deployment environment, set `SITE_BASE_URL` to the public HTTPS origin, and enable Card in Admin for the desired fulfilment types. No extra Python dependency is required. Register the HTTPS webhook:

```text
https://YOUR-CAFE-DOMAIN/orders/payments/stripe/webhook/
```

Subscribe to `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `checkout.session.async_payment_failed` and `checkout.session.expired`. Use matching test keys/webhook secrets for sandbox testing; never use live cards in local acceptance. The server creates a hosted session using the saved order total in PKR minor units and an order-specific Stripe idempotency key. Only Stripe hosts card entry. The receipt return URL does not mark payment paid. The webhook verifies the raw-body signature and five-minute timestamp tolerance, event uniqueness, saved session, order reference/metadata, amount, currency and live/test mode. Only a matching paid success event applies payment once. Unpaid/failed/expired events do not mark Paid. An expired hosted session is not silently replaced: contact staff to reconcile the saved order. Gateway outages retain the unpaid order and allow retry from its private receipt. Keep pending/unpaid orders under staff review. No refund or automatic cash-collection workflow is included in this stage.

### Windows setup and verification

```powershell
cd "D:\Silent Space"
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe manage.py migrate
.\venv\Scripts\python.exe manage.py check
.\venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\venv\Scripts\python.exe manage.py test
# If you do not already have a staff account:
.\venv\Scripts\python.exe manage.py createsuperuser
.\venv\Scripts\python.exe manage.py runserver
# Process configured owner email/reminders; existing scheduler instructions above still apply:
.\venv\Scripts\python.exe manage.py process_notifications
# Optional browser acceptance (installed Playwright + Chrome):
.\venv\Scripts\python.exe tools/check_checkout.py
```

Migrations `orders/0002`, `0003` and `0004` are additive/compatible with existing order records. The defaults migration uses get-or-create and never replaces configured payment values. Do not reset/reseed the database. Continue serving uploaded menu photos from persistent MEDIA_ROOT through your production web server/CDN, as described above. SMTP settings, recipients and minute-based notification scheduling use the existing environment configuration; no live email was sent in this stage.

Checkout files changed: `orders/models.py`, `forms.py`, `customer_checkout.py`, `checkout.py`, `payments.py`, `views.py`, `services.py`, `admin.py`, `urls.py`, migrations `0002`-`0004`, `test_checkout.py`; `staff_portal/views.py`, `urls.py`, `tests.py` (fixed a clock-dependent reservation test); `notifications/services.py`; `templates/orders/bag.html`, `checkout.html`, `receipt.html`, `templates/staff/orders.html`, `order_detail.html`, `partials/order_queue.html`, `templates/base.html` (shared checkout asset includes only); `static/css/checkout.css`, `static/js/checkout.js`; `silent_space/settings.py`, `.env.example`; `tools/check_checkout.py` and existing bag-subtotal browser assertions in `check_homepage.py`, `check_menu.py`, `check_phase2.py`, `check_multipage.py`; this README.

Final checkout verification: Django system checks, migration consistency and no-pending-migration checks passed; all **76 automated tests** passed. Isolated browser acceptance passed at **390/768/1440px**, including shared header/footer parity, images, no horizontal overflow, keyboard focus, live area fee changes, delivery/JazzCash receipt and staff verification, no-JavaScript pickup, and QR seat retention. The runner also migrated a nonempty legacy order/line fixture and confirmed that its reference, status and prices survived. Real database records were unchanged by acceptance fixtures. Screenshots: `artifacts/checkout-390.png`, `checkout-768.png`, `checkout-1440.png`; machine-readable report: `artifacts/checkout-acceptance.json`. Gateway API success, signature/amount checks, duplicate events and outage handling were tested with controlled local mocks. Live merchant sandbox/card success/failure, external SMTP inbox receipt and physical phone scanning remain unverified.
The maintained homepage browser regression also passed at 390/768/1440px: navigation, images/anchors, bag persistence/quantity controls, QR location, booking feedback and no-JavaScript behavior. The local development server was restarted with the updated checkout and returned HTTP 200 for home, bag, menu and staff login.

## Review a pending reservation

In Django Admin, open Bookings > Reservation requests > the reservation. In the staff dashboard, open Reservations > the reservation. Staff with change permission can select Approve or Reject in Change status and click Save; Leave pending makes no change. Both interfaces use the existing capacity-checked transition service. Already-processed requests cannot be overwritten by a stale form. Cancel approved bookings using the existing dashboard cancellation action or Admin bulk cancellation action.

The original private guest URL reads the saved status on every refresh and is marked no-store. Internal cancellation reasons are never shown there. No schema migration is required. Regression coverage is in bookings/test_detail_review.py; run `python manage.py test bookings staff_portal`.

## Manual transfer payment review

Open Admin > Orders > Dine in orders > the delivery/pickup order, verify the amount and submitted reference against the saved receiving account, then choose Approve payment or Reject payment under Change payment status and click Save. The staff dashboard has the same control under Orders > the order. The account needs Can verify order payments plus order view access (and change access for the Admin save form). Fulfilment actions require order change permission.

Payment decisions reuse the saved payment status, verified_by and verified_at; only pending submitted manual transfers can change. Repeated/stale decisions do not overwrite the original audit stamp or enqueue notifications. Guest receipts are no-store and show separate PAYMENT and ORDER sections. Internal notes and decision audit fields remain private.

After approval, choose Start preparing, then Mark out for delivery or Mark ready for pickup. Use Mark delivered or Mark collected after handoff. Admin provides the equivalent bulk actions from the order list. Unapproved JazzCash/Easypaisa delivery/pickup orders cannot be dispatched or completed. Existing cash/card and QR dine-in rules remain supported. Easypaisa still needs an enabled payment-method configuration with a real receiving account before customers can select it; browser tests configure a synthetic receiver only in their temporary database.

Run `python manage.py migrate` for orders migration 0005. Verify with `python manage.py test` and `python tools/check_checkout.py`; the latter uses temporary data and verifies legacy history, JazzCash delivery, Easypaisa pickup and QR dine-in without sending real payments.
