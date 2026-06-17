# Jury Guide

Welcome to the LavBench Platform Jury Portal. As a jury member, you can monitor competitions, review submissions, assign manual points to scores, and export results.

---

## 1. Your Role and Access

### What You Can Do
- View all competitor submissions, participant code, and execution logs (stdout/stderr)
- Register competitors individually or via CSV import
- Assign manual points to competitor scores
- Export results (scores CSV, submissions ZIP, competition backups)
- Monitor cluster health and worker server status

### What You Cannot Do
- Modify task configurations or Docker environments (admin only)
- Create, edit, or delete competitions (admin only)
- Edit admin or other jury member accounts

### Double-Blind Privacy
During an active competition, **you can see competitor identities** (names, schools, demographics) while students see only pseudonyms. Identities are de-anonymized for everyone only after the competition is finalized.

### Access Restrictions
- Once a competition starts (`start_time` to `end_time`), you cannot edit competitor accounts
- You cannot register competitors after the competition has started (the admin can)
- You have no access to competitions you are not assigned to

---

## 2. Managing Competitors

### Registering Individuals
1. Go to the **Admin Panel** → **Competitor Registration** tab
2. Fill in: Name, Surname, Grade, School, City
3. Select the competition from the dropdown
4. Click **Register** — the system auto-generates a username and password
5. Share the credentials with the competitor

### CSV Bulk Import
For large groups:
1. Go to the **Admin Panel** → **Competitor Registration** tab
2. Click **Import CSV**
3. Upload a CSV file with the following columns:
```text
   name,surname,grade,school,city,challenge_id,is_anonymous
   Alice,Smith,12,High School,Sofia,1,false
   Bob,Jones,11,Academy,Plovdiv,1,false
   ```

### Resetting Passwords
- **Single user**: Admin Panel → User Management → find the user → Reset Password
- **All competitors**: Admin Panel → Competitor Registration → select challenge → Reset All Passwords

---

## 3. Monitoring the Competition

### Live Submission Tracking
The **Submissions** tab shows all submissions in real-time via SSE. For each submission you can:
- View the status (queued → running → evaluating → completed/failed)
- See the exact code cells submitted
- Read the execution logs (stdout/stderr) for debugging
- Check the scores and inference execution time

### Live Leaderboard
The **Leaderboard** tab updates in real-time as scores from the automated validation arrive.

### Cluster Health
The **Cluster** badge in the navbar shows the worker node status:
- **Green**: All workers are connected
- **Red**: Workers are disconnected
- Click for detailed specs (CPU, RAM, VRAM, concurrency)

---

## 4. Manual Scoring

### Assigning Manual Points
For tasks requiring subjective evaluation (e.g., qualitative analysis or architecture review):
1. Go to the **Leaderboard** tab
2. Find the competitor and the respective task
3. Click the score field — a manual input form opens
4. Enter a score between **0 and 100** — it saves automatically

### Constraints
- The competitor must have at least **one completed submission** for the task
- You cannot score empty entries
- Points apply per task, per competitor

### Post-Finalization Corrections
After the competition is finalized (`scores_finalized=True`):
1. Click the score on the finalized leaderboard
2. A correction modal appears — you **must provide a reason**
3. The change is logged to a permanent **AuditLog** table with your ID, the old/new score, and the justification for the correction

---

## 5. Exporting Results

### Scores CSV
Admin Panel → Competition Management → select challenge → "Download Scores CSV"
A CSV file containing the rankings, aliases (pseudonyms), real names, task scores, and total points.

### Submissions ZIP
Admin Panel → Competition Management → select challenge → "Download Submissions ZIP"
A ZIP archive of all successfully completed student notebooks as `.ipynb` files.

### Competition Backups
In Competition Management → select a challenge → "Database Backups" section.
System snapshots taken at key moments:
- **Submission Period Ended** — when the official deadline passes
- **Grace Period Ended** — when the extra submission time expires
- **Scores Finalized** — when scores are locked and de-anonymized

Each backup contains a full database SQL dump + all associated files. They can be downloaded but not deleted manually — they are removed only upon full competition deletion.