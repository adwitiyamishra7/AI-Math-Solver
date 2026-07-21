# Project Context (Saved)

Last updated: 2026-03-09

## Goal
Handwritten math solver app with:
- Frontend draw area (mouse now, CV later)
- Flask app server on port 5000
- Gemini backend server on port 6001

## Current Working Setup
- App URL: `http://127.0.0.1:5000`
- Gemini health: `http://127.0.0.1:6001/health`
- Gemini root info: `http://127.0.0.1:6001/`

## Main Code Changes Done
- Added mouse drawing + `Solve Drawing` and `Clear Drawing`.
- Added backend routes in `app.py`:
  - `POST /api/solve`
  - `POST /api/clear`
  - `GET /api/status`
- Made CV mode optional with `ENABLE_CV` env flag.
- Reduced CV solve spam (thumb-up edge trigger only).
- Gemini server moved from port 6000 to 6001 (browser-safe).
- Added `/health` endpoint in `gemini_server.py`.
- Added clearer Gemini error messages.
- `.env` loading now uses override to avoid stale shell env values.

## Current Blocker
Google Gemini key/account side issues:
- Seen errors: `API_KEY_INVALID` and quota errors (`limit: 0`).
- This is not app UI/server routing now; it is API key/project config/quota.

## Required Google-Side Fixes
For the exact project that owns the key:
1. Enable `generativelanguage.googleapis.com`.
2. Check API key restrictions (for testing: no API restriction).
3. Ensure key is valid and active (fresh key if needed).
4. Confirm quota/rate limits are not zero for chosen model.

## Local Env Expected
In `.env`:
- `GEMINI_API_KEY=...`
- `API_KEY=...`
- `GEMINI_SERVER_HOST=127.0.0.1`
- `GEMINI_SERVER_PORT=6001`
- `GEMINI_SERVER_URL=http://127.0.0.1:6001/solve`

## Restart Sequence
1. `python gemini_server.py`
2. Verify `/health`
3. `python app.py`
4. Draw and click Solve

## Next Session Quick Start
Say: "project"
Then load this file and continue from Google key/quota verification.
