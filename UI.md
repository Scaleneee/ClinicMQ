# ClinicMQ: UI Design Brief

Design brief for the ClinicMQ web app.
Use it to build editable screen designs.

---

## 1. Product

- Clinic management system with an online queue.
- One small clinic, one doctor per session.
- Sessions: **Morning** 9:00 AM–1:00 PM, **Night** 6:00 PM–10:00 PM.
- Four roles: **Patient**, **Nurse**, **Doctor**, **Admin**.
- Patients mostly use a phone. Staff mostly use a desktop.

---

## 2. Visual style

### Mood
- Black and white. Calm. Clinical. Like a printed document.
- Lots of white space.
- Colour is used **only for status**: red, green, yellow.
- No gradients, shadows or illustrations.

### Colours
| Token | Hex | Use |
|---|---|---|
| Ink | `#111111` | Text, primary buttons |
| Ink soft | `#3A3A3A` | Secondary headings |
| Muted | `#6F6F6F` | Labels, hints |
| Line | `#E7E7E7` | Borders, dividers |
| Paper | `#FFFFFF` | Page background |
| Wash | `#F7F7F5` | Hover, empty states |
| Red | `#C0392B` / wash `#FBEEEC` | Act now, error, danger |
| Green | `#2F7D4F` / wash `#EBF5EE` | Done, OK, success |
| Yellow | `#D9A400` / wash `#FDF6DD` | Waiting, warning |

### Type
- Font: **Times New Roman** (fallback: Georgia, serif).
- Body: 17px.
- Page title: 40px, regular weight.
- Section heading: 20px, bold.
- Eyebrow label: 15px, muted, sentence case.
- Numbers use tabular figures so columns line up.

### Spacing and shape
- Base unit: 8px.
- Page top padding: 40px. Gap between sections: 48px.
- Corner radius: 8px.
- Borders: 1px Line colour.
- Container max width: 1200px.
- Narrow pages (patient, auth): 560px, centred.

### Icons
- Bootstrap Icons, outline style, 16–20px.
- Every icon sits beside a text label.

### Brand
- Wordmark "ClinicMQ" in Times New Roman, with a small **red dot** after it.

---

## 3. Components

### Buttons
| Type | Look | Use |
|---|---|---|
| Primary | Black fill, white text | Main action, one per screen |
| Secondary | White, grey border, black text | Other actions |
| Success | Green fill | Check in, Complete, Record payment |
| Danger | Red outline | Delete, Cancel, Void, No show |
| Quiet danger | Red text only | Cancel inside table rows |

Sizes: small (32px), normal (40px), large (52px, for patient and doctor actions).

### Status badge
Pill shape, with a small dot before the label.

| Status | Label | Style |
|---|---|---|
| WAITING | Not arrived | Yellow wash |
| CHECKED_IN | Checked in | Green wash |
| SKIPPED | Skipped | Yellow outline |
| CALLED | Called | Solid red, pulsing |
| IN_CONSULTATION | With doctor | Solid black |
| COMPLETED | Completed | Grey |
| MISSED | Missed | Red outline |
| CANCELLED / EXPIRED | Cancelled / Expired | Light outline, muted |
| UNPAID | Unpaid | Yellow wash |
| PAID | Paid | Green wash |
| VOID | Void | Grey |
| Low stock | Low stock | Yellow wash |
| Expiring soon | Expiring soon | Red outline |
| Out of stock | Out of stock | Solid red |
| Active / Inactive | Active / Inactive | Green wash / light |

### Other pieces
- **Stat card**: eyebrow label, big number (32px), small note, optional icon at the top right. The whole card is clickable.
- **Card**: white, 1px border, 8px radius, optional header row (title left, small link right).
- **Table**: no vertical lines, light row dividers, muted header text, hover row in Wash.
- **Form field**: label above, 44px input, hint below in muted text, error below in red.
- **Alert / message**: full width, thin coloured left border, dismiss (×) on the right.
- **Banner**: large coloured box for urgent patient messages (red = your turn, yellow = come now).
- **Empty state**: centred icon, one line of text, optional button.
- **Confirm modal**: title, one sentence, Cancel (secondary) and a danger confirm button.
- **Search bar**: input with a search icon, plus a Search button.
- **Pagination**: "Page 1 of 3", Previous / Next.
- **Live dot**: small pulsing green dot with the text "Live · updates every 5 seconds".
- **Late check-in tag**: small yellow text tag next to a name.

---

## 4. Layout

### Navbar (all signed-in pages)
- Left: ClinicMQ wordmark.
- Middle: menu links (icon + text), depending on role.
- Right: user button "Full name [Role]" that opens a menu with **Logout**.
- Active link: black text with an underline. Others: muted.
- Mobile: hamburger, menu drops down.

| Role | Menu |
|---|---|
| Patient | Home · Get number · My queue · My visits · My bills · Profile |
| Nurse | Dashboard · Queue board · Walk-in · Patients · Medicine · Dispense · Billing |
| Doctor | Dashboard · Doctor console · Consultations · Patients · Medicine |
| Admin | Dashboard · Staff · Schedules · Patients · Medicine · Billing · Sales summary |

### Page header (every page)
- Eyebrow (date or back link) → page title → muted subtitle.
- Primary actions are aligned right on desktop and stack below on mobile.

### Footer
- One muted line: "ClinicMQ · Clinic Management System with Online Queue".

### Breakpoints
- Mobile 375px, tablet 768px, desktop 1280px.
- Design each screen at **1280px** and patient screens also at **375px**.

---

## 5. Screens

Format: **purpose → layout → states**.

### 5.1 Account

**Login**
- Centred card, 420px wide. Wordmark on top.
- Fields: Username, Password, "Remember me" checkbox.
- Primary button: Log in. Links: Forgot password, Register.
- States: wrong password (red message above the fields).

**Register (patient)**
- Same card style, wider (560px).
- Fields: IC number (`######-##-####`), Full name, Gender (M/F), Date of birth, Phone (`01X-XXXXXXX`), Email, Password, Confirm password.
- States: field errors.

**Forgot password / Email sent / Set new password / Password changed**
- Same card. One message and one action each.

**403 / 404**
- Centred: big number "403" or "404", one line, "Back to dashboard" button.

### 5.2 Dashboards

**Patient home** (mobile first)
- Greeting: "Good morning, Siti".
- Big ticket card if the patient has a number: queue number, status badge, ahead count, "View my queue" button.
- Without a ticket: empty state with a "Get queue number" button.
- Links below: My visits, My bills.

**Nurse dashboard**
- Header: date, "Welcome, Nurse Farah". Buttons: Walk-in (primary), Queue board.
- Session strip: "Morning session · Dr. Aisyah · Online numbers open until 12:30 PM".
- 4 stat cards: Today's queue · Checked in · To dispense · Low stock.
- Two columns:
  - Left (wide): "Next in line" table (Place, No., Patient, Checked in, Status).
  - Right: "Stock alerts" list and "Unpaid bills" list.

**Doctor dashboard**
- 4 stat cards: Waiting · Seen today · Avg. consult time · My next shift.
- "Open doctor console" primary button.
- Recent consultations table.

**Admin dashboard**
- 4 stat cards: Patients today · Revenue today · Unpaid bills · Low stock.
- This week's roster preview (7 columns).
- Recent bills table.

### 5.3 Queue

**Get number (patient)**
- Narrow page. Session card: session name, doctor on duty, people waiting, estimated wait.
- Big primary button: "Get queue number".
- States: open · closed (online cut-off passed, grey card with message) · already has a number (link to My queue).

**My queue (patient, live)** ⭐ most important screen
- Narrow page, mobile first.
- Top row: live dot text (left), "How the queue works" link (right).
- Centre: eyebrow "Your number", **giant number "012"** (120px), status badge, "Morning session · Dr. Aisyah".
- 3-column stat card: Now serving · Ahead · Est. wait.
- Action area changes with the status:
  - **Not arrived**: "Check in when you arrive" with a QR icon and a Check in button.
  - **Checked in**: "You're in line" with your place, e.g. "5th".
  - **3 or fewer ahead**: yellow banner "Please come to the clinic now".
  - **Called**: full-width **red pulsing banner** "It's your turn. Please go to the consultation room."
  - **With doctor**: black badge, calm text.
  - **Skipped / Missed**: red outline message plus a "Check in again" button.
  - **Completed**: green tick, "See you again", links to visit and bill.
  - **Cancelled / Expired**: number struck through and muted, "Get a new number" button.
- Bottom: "Cancel my number" (quiet danger), which opens a confirm modal.

**Check in (QR)**
- Narrow. Message "You're checked in", number, place in line.

**Queue board (nurse)**
- Header: "Queue board", subtitle with session, doctor and **Now serving 008**. Buttons: Walk-in, TV board.
- Filter pills: All 24 · Not arrived · Checked in · Called · With doctor · Skipped · Missed · Completed · Cancelled.
- Table: Place · No. · Patient (+ Late check-in tag) · Source (Online/Walk-in) · Checked in · Status · Actions (Check in, Cancel).
- The "With doctor" row is highlighted grey.
- Footer note with live dot: "Refreshes every 10 seconds".
- States: filtered · empty.

**Walk-in (nurse)**
- Two steps on one page:
  1. Search a patient by IC or name; results appear as cards.
  2. Selected patient card → "Issue number" primary button.
- "New patient" link opens the add-patient form.
- Success: big issued number "025" with a Print button.

**Doctor console** ⭐
- Header: "Doctor console", session · doctor name. Right side: 3 small stats (Waiting, Seen, Avg. time).
- Left card (wide): eyebrow "Now serving", **giant number**, status badge, patient name, "34 yrs · 900101-14-5678".
  - Called: Start (primary), No show (danger), Call again.
  - With doctor: Write notes, Complete (green).
  - Bottom: big "Call next · 009" primary button.
  - Idle: cup icon, "No one with you".
- Right card: "Next in line" list of 5 (number, name, checked-in time).

**TV board (public waiting-room screen)**
- Full screen, no navbar, 1920×1080.
- Top bar: wordmark · "Morning session · Dr. Aisyah" · clock.
- Left: "Now serving" plus a **huge number** (about 350px).
- Right: "Next in line" list: 1st 009, 2nd 010…
- Bottom bar: "Check in at the counter or scan the QR code" · "6 waiting".
- **Numbers only, never names.**

### 5.4 Patients

**Patient list**
- Search bar (IC, name, phone). "Add patient" primary.
- Table: Name · IC no. · Gender · Age · Phone · Last visit · arrow.
- States: results · search · empty · pagination.

**Patient detail**
- Header: name, IC, buttons Edit / Delete / Issue number.
- Left: details card (gender, DOB, age, phone, email, address).
- Right: today's ticket card (if any) and a visit history list.
- States: with ticket · without ticket.

**Add / Edit patient**
- Medium width form in 2 columns: IC, Full name, Gender, DOB, Phone, Email, Address (full width).
- Buttons: Save (primary), Cancel.

**Delete patient**
- Confirm page. Blocked state: "This patient has visits and cannot be deleted."

**My profile (patient)**
- Narrow form: phone, email, address. IC and name are read-only.

### 5.5 Staff and schedule (admin)

**Staff list**
- Filter pills: All · Doctors · Nurses · Admins. "Add staff" primary.
- Table: Name · Role · Specialty · Phone · Status · Actions.

**Add / Edit staff**
- Fields: Full name, Username, Email, Role, Phone, Specialty (doctor only).

**Deactivate staff**
- Confirm modal.

**Weekly roster**
- Week navigation: ‹ Prev · "3–9 Nov 2026" · Next ›.
- Grid: 7 day columns × 2 rows (Morning, Night).
- Each cell lists staff chips (Dr. / Nurse). Today's column is highlighted.
- "Add shift" primary.

**Add / Edit shift**
- Fields: Staff, Date, Session.
- Error: "Dr. Aisyah is already on duty for this session."

### 5.6 Consultations (doctor)

**Consultation list**
- Table: Date · No. · Patient · Diagnosis · MC · Billed.

**New / Edit consultation** ⭐
- Top: patient strip (name, age, IC).
- Section 1: Symptoms (textarea), Diagnosis, Notes, Consult fee (RM).
- Section 2: **Prescription** table you can add rows to:
  - Medicine (select) · Dosage · Qty · Unit price · Amount · remove ×.
  - "+ Add medicine" link. Running total at the bottom.
  - Out-of-stock medicines are disabled in the select.
- Section 3: **Medical certificate** toggle → Start date, Days (1–7), Reason.
- Sticky bottom bar: total "RM 45.00", Save (primary).

**Consultation detail**
- Header: date, diagnosis as the title, patient · doctor. Buttons: Download MC, Edit, Delete.
- Left: notes card; prescription table with a Dispensed / Waiting badge.
- Right: MC card; billing card (fee, medicines, bill link + status).

**Patient history**
- Vertical timeline: date, diagnosis, doctor, medicines, MC tag.

**My visits (patient)**
- The same timeline in a narrow layout.

**MC print (A5)**
- A5 portrait document: clinic name and address, "Medical Certificate", MC no., patient name and IC, dates, days, reason, doctor signature line.
- No navbar.

### 5.7 Pharmacy

**Medicine list**
- Filter pills: All · Low stock · Expiring soon · Out of stock. Search bar. "Add medicine" primary.
- Table: Name · Category · Unit · Price · Stock (e.g. "8 boxes") · Expiry · Badges · Actions (Restock, Edit).

**Add / Edit medicine**
- Fields: Name, Category, Unit, Unit price, Quantity, Reorder level, Expiry date.

**Restock**
- Small form: current stock (read-only), add quantity, new expiry date.

**Delete medicine**
- Confirm. Blocked state: "Used in prescriptions."

**Dispense list (nurse)**
- Cards or table: No. · Patient · Doctor · Items · Time · "Dispense" button.

**Dispense detail**
- Prescription items with checkboxes and stock left.
- "Mark as dispensed" (green).
- Error state: "Not enough stock for Paracetamol 500mg (need 20, have 8)."

### 5.8 Billing

**Bill list**
- Filter pills: All · Unpaid · Paid · Void. Search.
- Table: Bill no. · Date · Patient · Total · Status · Method.

**Generate bill**
- Bill preview: consultation fee line + medicine lines.
- Inputs: Discount (RM), Tax rate (%).
- Live totals: Subtotal, Discount, Tax, **Total**.
- "Create bill" primary.

**Bill detail**
- Invoice look: bill no., date, patient, item table, totals.
- Buttons by status:
  - Unpaid: Record payment (green), Void (danger).
  - Paid: Print receipt.
  - Void: shows the void reason in red.

**Record payment**
- Total due shown large.
- Method: 3 big selectable tiles (Cash · Card · E-wallet), with a black fill when selected.
- Cash: "Amount received" field plus live **Change** display.
- Error: "Amount paid is less than the total."

**Void bill**
- Reason textarea plus a danger confirm.

**Receipt print (80mm)**
- Narrow thermal receipt: clinic header, bill no., items, totals, method, paid, change, "Thank you".

**Sales summary (admin)**
- Date range picker.
- Stat cards: Revenue · Bills paid · Avg. bill · Voided.
- Table by day, plus a payment-method breakdown.
- Top medicines sold.

**My bills (patient)**
- List of bill cards: bill no., date, total, status badge, "View" link.

---

## 6. Sample data

| Item | Value |
|---|---|
| Clinic | ClinicMQ Clinic, Setapak, Kuala Lumpur |
| Today | Wednesday, 4 November 2026, 10:42 AM |
| Session | Morning · Dr. Aisyah Rahman |
| Nurse | Nurse Farah Lim |
| Admin | Admin Kumar |
| Patients | Siti Nurhaliza, Tan Wei Ming, Raj Kumar, Lim Mei Ling, Ahmad Faiz |
| Now serving | 008 |
| My number | 012 (3 ahead, 10–15 min) |
| Medicines | Paracetamol 500mg, Amoxicillin 250mg, Loratadine 10mg, Cough syrup 100ml |
| Money format | RM 12.50 |
| Queue number | 3 digits: 005, 012 |
| IC | 900101-14-5678 |
| Phone | 012-3456789 |
| Bill no. | B-20261104-001 |
| MC no. | MC-20261104-001 |

---

## 7. Rules

- Show only one primary (black) button per area.
- Use colour only for status. Never use it for decoration.
- Every status has a text label. Never rely on colour alone.
- Patient screens must work one-handed at 375px.
- Never show patient names on the TV board.
- Write labels in plain sentence case: "Get queue number", not "GET NUMBER".
- Ask before destructive actions with a confirm modal.
- Every list needs an empty state.
- Every form needs an error state.
