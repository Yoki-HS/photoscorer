# 📸 PhotoScorer

An AI-powered photo scoring and management tool built with Streamlit and Google Gemini.

## Features

- **AI Scoring** — Automatically evaluate and rank photos using Google Gemini
- **Custom Tags** — Define your own tags or let the AI generate them freely
- **History** — Browse past evaluations
- **Search** — Find photos by tags or scores
- **Chat** — Conversational interface about your photo collection
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

> You can also enter the Gemini API key manually in the sidebar at runtime.

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

## Speed

- Thinking is turned off for scoring and the response is forced into JSON, so each photo takes ~3 s instead of ~12 s (gemini-2.5-flash, measured on 10 MB JPEGs).
- Requests are spaced to stay under your requests-per-minute (RPM) limit, set in the sidebar. If the API still returns 429, the app waits for the delay the API asks for and resumes.
- Photos you have already scored (same image bytes) are not sent again: their previous result is reused. Tick "re-score" in the sidebar to force a new evaluation.

## Limitations

- On the free Gemini tier, throughput is capped by your RPM limit (e.g. 10 RPM → ~5 min for 50 new photos). Check your current limits in Google AI Studio.
- gemini-2.5-flash-lite is faster and has a higher free-tier limit, but it tends to score more generously.
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
