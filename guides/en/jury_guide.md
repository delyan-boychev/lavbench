# Jury Guide

Welcome to the LavBench Platform Jury Portal. As a jury member, you can monitor competitions, review submissions, assign manual scores, and export results.

---

## 1. Your Role and Access

### What You Can Do
- View all competitor submissions, code, and execution logs
- Register competitors individually or via CSV import
- Assign manual points to competitor scores
- Export results (scores CSV, submissions ZIP, competition backups)
- Monitor cluster health and worker status

### What You Cannot Do
- Modify task configurations or Docker environments (admin only)
- Create, edit, or delete challenges (admin only)
- Edit admin or other jury member accounts

### Double-Blind Privacy
During an active competition, **you can see competitor identities** (names, schools, demographics) while students see only pseudonyms. Identities are revealed to everyone after the competition is finalized.

### Access Restrictions
- Once a competition starts (`start_time` to `end_time`), you cannot edit competitor accounts
- You cannot register competitors after the competition has started (admin can)
- You cannot access competitions you're not assigned to

---

## 2. Managing Competitors

### Registering Individuals
1. Go to **Admin Panel** → **Competitor Registration** tab
2. Fill in: Name, Surname, Grade, School, City
3. Select the competition from the dropdown
4. Click **Register** — the system auto-generates username and password
5. Share the credentials with the competitor

### CSV Bulk Import
For large groups:
1. Go to **Admin Panel** → **Competitor Registration**
2. Click **Import CSV**
3. Upload a CSV with columns:
   ```csv
   name,surname,grade,school,city,challenge_id,is_anonymous
   Alice,Smith,12,High School,Sofia,1,false
   Bob,Jones,11,Academy,Plovdiv,1,false
   ```

### Resetting Passwords
- **Single user**: Admin Panel → User Management → find user → Reset Password
- **All competitors**: Admin Panel → Competitor Registration → select challenge → Reset All Passwords

---

## 3. Monitoring the Competition

### Live Submission Tracking
The **Submissions** tab shows all submissions in real-time via SSE. For each submission you can:
- View status (queued → running → evaluating → completed/failed)
- See the exact code cells submitted
- Read execution logs for debugging
- Check scores and execution time

### Live Leaderboard
The **Leaderboard** tab updates in real-time as scores arrive.

### Cluster Health
The **Cluster** badge in the navbar shows worker status:
- **Green**: All workers connected
- **Red**: Workers disconnected
- Click for detailed worker specs (CPU, RAM, GPU, concurrency)

---

## 4. Manual Scoring

### Assigning Manual Points
For tasks requiring subjective evaluation:
1. Go to the **Leaderboard** tab
2. Find the competitor and task
3. Click the score field — a manual input opens
4. Enter a score between **0 and 100** — saves automatically

### Constraints
- Competitor must have at least **one completed submission** for the task
- You cannot score empty entries
- Points apply per task, per competitor

### Post-Finalization Corrections
After the competition is finalized (`scores_finalized=True`):
1. Click the score on the finalized leaderboard
2. A correction modal appears — you **must provide a reason**
3. The change is logged to a permanent **AuditLog** table with your ID, old/new scores, and justification

---

## 5. Exporting Results

### Scores CSV
Admin Panel → Competition Management → select challenge → "Download Scores CSV"
A CSV file with ranks, aliases, names, task scores, and totals.

### Submissions ZIP
Admin Panel → Competition Management → select challenge → "Download Submissions ZIP"
All completed student notebooks as `.ipynb` files in a ZIP archive.

### Competition Backups
In Competition Management → select a challenge → "Competition Backups" section.
Snapshots taken at key moments:
- **Submission Period Ended** — when the deadline passes
- **Grace Period Ended** — when the grace period expires
- **Scores Finalized** — when scores are locked

Each backup contains a full database dump + all files. Downloadable but not deletable — only competition deletion removes them.
