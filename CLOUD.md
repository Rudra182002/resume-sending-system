# Running the pipeline in the cloud

GitHub Actions runs the daily pipeline at 09:00 IST whether or not your laptop
is on. Code stays in this public repo; all state goes to a separate **private**
repo, so the job database, generated resumes and your real master resume are
never public.

## 1. Create the private state repo

New repo named `resume-pipeline-state`, **Private**, tick "Add a README".
Then clone and seed it from your local run:

```bash
git clone https://github.com/<you>/resume-pipeline-state.git ~/resume-pipeline-state
cd ~/Resume_Sending_System
./seed_state.sh ~/resume-pipeline-state
```

## 2. Create a token the workflow can push with

github.com/settings/tokens → **Fine-grained tokens** → Generate new token

- Repository access: **Only select repositories** → `resume-pipeline-state`
- Permissions → Repository permissions → **Contents: Read and write**
- Expiry: 90 days (diarise the renewal)

Copy the token.

## 3. Add secrets to THIS repo

Settings → Secrets and variables → Actions → New repository secret:

| Secret | Value |
|---|---|
| `STATE_REPO` | `<you>/resume-pipeline-state` |
| `STATE_TOKEN` | the fine-grained token |
| `ANTHROPIC_API_KEY` | your key |
| `ANTHROPIC_BASE_URL` | only if you use a non-standard endpoint |
| `LLM_MODEL` | e.g. `claude-sonnet-5` |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | from developer.adzuna.com |
| `IMAP_USER` | your Gmail address |
| `IMAP_PASS` | Gmail **app password**, not your login password |

## 4. Run it once by hand

Actions tab → **Daily job pipeline** → **Run workflow**. Watch the log; the
summary shows jobs seen, matched, queued and applied.

## 5. Pull results locally

```bash
cd ~/resume-pipeline-state && git pull
cp jobs.db ~/Resume_Sending_System/data/jobs.db
cp -r drafts/.  ~/Resume_Sending_System/output/drafts/
cp -r resumes/. ~/Resume_Sending_System/output/resumes/
cd ~/Resume_Sending_System && ./.venv/bin/python -m resume_bot dash
```

## What the cloud run will not do

`AUTO_SEND=false` and `APPLY_MODE=prepare` are hardcoded in the workflow, so it
never emails anyone and never submits a form unattended. It finds, scores,
researches, tailors and renders. Sending and submitting stay manual, on your
machine, with you looking at them.

## Cost

Free. Public repositories get unlimited Actions minutes; a run takes ~10-15.
