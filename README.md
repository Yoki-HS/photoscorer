# 📸 PhotoScorer

An AI-powered photo scoring and management tool built with Streamlit and Google Gemini.

## Features

- **AI Scoring** — Automatically evaluate and rank photos using Google Gemini
- **Custom Tags** — Define your own tags or let the AI generate them freely
- **History** — Browse past evaluations
- **Search** — Find photos by tags or scores
- **Chat** — Ask about a single photo, or about a whole scoring run (or your entire history) at once to get overall trends and advice
- **User Authentication** — Secure login with per-user session management
- **Supabase Backend** — Cloud database for persistent storage

## Demo

> Supports JPG, JPEG, PNG, WebP, HEIC, BMP, TIFF

## Requirements

- Python 3.9+
- [Google Gemini API key](https://aistudio.google.com/app/apikey)
- [Supabase](https://supabase.com) project (for auth and history storage)

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/Yoki-HS/photoscorer.git
cd photoscorer
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure secrets

Create `.streamlit/secrets.toml`:

```toml
GEMINI_API_KEY = "AIza..."

[supabase]
url = "https://your-project.supabase.co"
key = "your-anon-key"
```

> The Gemini API key is read from secrets only; users are never asked for a key. On Streamlit Community Cloud, add the same values under the app's **Settings → Secrets**.

### 4. Run the app

```bash
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

## Usage

1. Log in with your credentials
2. Go to the **Scoring** page
3. Enter the path to a folder of photos
4. (Optional) Enable custom tags in the sidebar
5. Click **Start Scoring** — results appear as a ranked list

## Models

| Model | Role | Approx. cost per photo |
|-------|------|------------------------|
| `gemini-3.8-flash` | Default for scoring, tags, search and chat | ~$0.0015 (doubles from 2027-01-01) |
| `gemini-4-hydrogen` | Optional; slightly wider score spread | ~$0.006 |

Chosen from a comparison of six models (Nov 2026, 10 photos × 2 runs). 3.8-flash and 4-hydrogen ranked photos almost identically (Spearman 0.88) and both match the prompt's strict scale; the lite models scored more generously with a narrower spread. `gemini-2.5-flash` shuts down on 2026-12-01.

## Speed

- Thinking is kept to the minimum each model allows, images are read at medium resolution and the response is forced into JSON.
- Photos are scored in parallel (up to 20 at once), spaced to stay under the requests-per-minute (RPM) limit set in the sidebar (default 900). If the API still returns 429, the app waits for the delay the API asks for and resumes.
- Photos you have already scored (same image bytes) are not sent again: their previous result is reused. Tick "re-score" in the sidebar to force a new evaluation.

## Keeping Supabase awake

Free Supabase projects are paused after a period of inactivity. The workflow `.github/workflows/supabase-keepalive.yml` sends one light read query every 3 days. To enable it, add two repository secrets under **Settings → Secrets and variables → Actions**:

- `SUPABASE_URL`
- `SUPABASE_KEY`

Use the same values as in `.streamlit/secrets.toml`, then run the workflow once from the **Actions** tab to check it. Note that GitHub disables scheduled workflows in a repository with no commits for 60 days; if that happens, re-enable it from the Actions tab.

## Limitations

- Rate limits depend on your project's tier; check them on the Rate Limit page in Google AI Studio and set the RPM in the sidebar a little below it.
- Skipping only works for photos scored after this feature was added (older results have no file hash).

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | [Streamlit](https://streamlit.io) |
| AI | [Google Gemini](https://deepmind.google/technologies/gemini/) |
| Database | [Supabase](https://supabase.com) |
| Image processing | [Pillow](https://python-pillow.org) |

## License

MIT — see [LICENSE](LICENSE)
