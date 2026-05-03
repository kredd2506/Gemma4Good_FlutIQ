# Deploying FlutIQ to Hugging Face Spaces

A single HF Space serves both the FastAPI backend and the static
frontend. One URL, no CORS, no separate frontend host.

Total time: ~10 minutes, mostly your clicks.

---

## What you need

- A free Hugging Face account (signup at https://huggingface.co/join)
- Your Google AI Studio API key already pasted into
  [openrouter.ai/settings/integrations](https://openrouter.ai/settings/integrations)
  (BYOK — required for reliable rate limits)
- Your OpenRouter API key (the `sk-or-v1-...` one already in
  `backend/.env` locally)

---

## Step-by-step

### 1. Create the Space

1. Go to https://huggingface.co/new-space
2. **Owner**: `kredd2506` (or your HF username)
3. **Space name**: `flutiq`
4. **License**: pick one (Apache 2.0 is fine for a hackathon)
5. **Select the Space SDK**: choose **Docker** → **Blank**
6. **Space hardware**: **CPU basic · 2 vCPU · 16GB · FREE**
7. **Public**
8. Click **Create Space**

You now have an empty Space at
`https://huggingface.co/spaces/kredd2506/flutiq` and a git remote at
`https://huggingface.co/spaces/kredd2506/flutiq.git`.

### 2. Add the OpenRouter secret

In the Space's web UI:

1. Click **Settings** (top-right of the Space)
2. Scroll to **Variables and secrets**
3. Click **New secret**
4. **Name**: `OPENROUTER_API_KEY`
5. **Value**: paste your `sk-or-v1-...` key
6. **Save**

The Space will rebuild automatically when secrets change.

### 3. Push the backend to the Space

The Space root must contain `Dockerfile`, `README.md` (with the HF
frontmatter), and the app. That's our `backend/` directory. Push it
as a git subtree:

```bash
# from the repo root
git remote add hf https://huggingface.co/spaces/kredd2506/flutiq

# you'll be prompted for an HF access token (not your password):
# create one at https://huggingface.co/settings/tokens
git subtree push --prefix=backend hf main
```

If the Space already had a default `README.md` from the create step,
the first push will conflict. Easiest fix: in the HF UI, delete the
default README, then re-run `git subtree push`.

Alternative if subtree push gives you trouble:

```bash
# clone the empty space repo into a sibling directory
cd ..
git clone https://huggingface.co/spaces/kredd2506/flutiq flutiq-space
cp -R Gemma4Good_FlutIQ/backend/* flutiq-space/
cp -R Gemma4Good_FlutIQ/backend/.gitignore flutiq-space/
cd flutiq-space
git add . && git commit -m "Initial deploy"
git push
```

### 4. Watch it build

Back in the Space's web UI, click the **Logs** tab. You'll see Docker
pulling `python:3.11-slim`, installing `requirements.txt`, copying the
app, and finally `Uvicorn running on http://0.0.0.0:8000`.

First build takes ~3–5 minutes. Subsequent pushes are faster (cached
pip layer).

### 5. Smoke test the live URL

```bash
curl -s https://kredd2506-flutiq.hf.space/api/health
# → {"status":"ok","openrouter_key_configured":true}
```

Then open `https://kredd2506-flutiq.hf.space/` in a browser and try
an address.

---

## Updating after the first deploy

```bash
# from the repo root
git subtree push --prefix=backend hf main
```

That's it. The Space rebuilds, downtime is ~30 seconds.

---

## Troubleshooting

**The Space says "Build failed" with a Docker error.** Check the
Logs tab. Most likely cause: a typo in `Dockerfile` or
`requirements.txt`. Fix locally, commit, push again.

**The Space builds but every assessment errors.** Check that
`OPENROUTER_API_KEY` is set in Space → Settings → Secrets, and that
the Space has been restarted since (the **Restart Space** button in
the top-right).

**`/api/health` returns `openrouter_key_configured: false`.** Same
as above — secret not visible to the running container.

**Browser console: SSE connection drops mid-assessment.** HF Spaces
free tier sleeps containers after ~48h of inactivity. First request
to a sleeping Space takes ~10s to wake. Workaround: hit `/api/health`
once before showing the user the search screen, OR pay for **Persistent
Storage** (~$0.30/day).

**You changed `index.html` and don't see the change live.** Browser
cached the previous version. Hard reload (Cmd-Shift-R) or open in
incognito.

---

## Local dev (still works exactly as before)

The bundled deploy doesn't break local dev. You have two options now:

### Option 1: bundled (what production will look like)

```bash
cd backend
set -a && source .env && set +a
.venv/bin/uvicorn app.main:app --port 8000 --reload
# open http://127.0.0.1:8000
```

One port, no separate frontend server, exactly mirrors production.

### Option 2: split (faster frontend iteration)

```bash
# Terminal A
cd backend
set -a && source .env && set +a
.venv/bin/uvicorn app.main:app --port 8000

# Terminal B (from repo root)
python3 -m http.server 5173 --directory backend/static
# open http://127.0.0.1:5173
```

The frontend's `API_URL` resolver auto-detects this case (port != 8000)
and points to `http://127.0.0.1:8000` for the API.

---

## Custom domain (optional, post-submission)

HF Spaces supports custom domains on paid tiers. For a hackathon
submission the default `*.hf.space` URL is fine and is what you'll
paste into the Kaggle writeup and YouTube video.
