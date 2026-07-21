# gemini_server.py

import base64
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import hashlib
import json
import os
import re
import time

from flask import Flask, jsonify, request
import google.generativeai as genai

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        dotenv_path = kwargs.get("dotenv_path") or ".env"
        override = kwargs.get("override", True)
        if not os.path.exists(dotenv_path):
            return False

        with open(dotenv_path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if override or key not in os.environ:
                    os.environ[key] = value
        return True


# =====================
# LOAD ENV
# =====================
env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=env_path, override=True)

GEMINI_SERVER_HOST = os.getenv("GEMINI_SERVER_HOST", "127.0.0.1")
GEMINI_SERVER_PORT = int(os.getenv("GEMINI_SERVER_PORT", "6001"))

api_key = os.getenv("GEMINI_API_KEY") or os.getenv("API_KEY")
api_key_source = "GEMINI_API_KEY" if os.getenv("GEMINI_API_KEY") else "API_KEY"
if not api_key:
    raise RuntimeError("Missing API key. Set GEMINI_API_KEY (or API_KEY) in your environment/.env file.")

genai.configure(api_key=api_key)

KNOWN_MODEL_FALLBACKS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash-001",
    "gemini-2.0-flash-lite-001",
]


def _dedupe_keep_order(items):
    seen = set()
    result = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def discover_generate_content_models():
    try:
        available = []
        for model_info in genai.list_models():
            methods = getattr(model_info, "supported_generation_methods", []) or []
            if "generateContent" in methods:
                available.append(model_info.name.replace("models/", ""))

        # Prefer flash models, then the rest.
        available.sort(key=lambda name: (0 if "flash" in name.lower() else 1, name.lower()))
        return available
    except Exception:
        return []


def build_model_candidates():
    preferred = os.getenv("GEMINI_MODEL", "").strip()
    extra = [
        m.strip()
        for m in os.getenv("GEMINI_MODEL_FALLBACKS", "").split(",")
        if m.strip()
    ]
    # Avoid model-list API calls during startup so the server can boot even
    # when keys/network are temporarily invalid.
    return _dedupe_keep_order([preferred] + extra + KNOWN_MODEL_FALLBACKS)


def is_model_not_available_error(error):
    message = str(error).lower()
    signatures = [
        "is not found for api version",
        "is not supported for generatecontent",
        "model not found",
        "404",
    ]
    return any(sig in message for sig in signatures)


def is_quota_or_rate_limit_error(error):
    message = str(error).lower()
    signatures = [
        "429",
        "quota",
        "resource_exhausted",
        "resource has been exhausted",
        "rate limit",
        "too many requests",
    ]
    return any(sig in message for sig in signatures)


MODEL_CANDIDATES = build_model_candidates()
active_model = None
active_model_name = None
SOLVE_CACHE_TTL_SECONDS = int(os.getenv("SOLVE_CACHE_TTL_SECONDS", "300"))
GEMINI_REQUEST_TIMEOUT_SECONDS = int(os.getenv("GEMINI_REQUEST_TIMEOUT_SECONDS", "45"))
GEMINI_EXECUTOR = ThreadPoolExecutor(max_workers=int(os.getenv("GEMINI_WORKERS", "2")))
solve_cache = {}

app = Flask(__name__)


def masked_key_tail(value):
    if not value:
        return ""
    if len(value) <= 8:
        return value
    return f"{value[:4]}...{value[-4:]}"


def extract_retry_seconds(message):
    patterns = [
        r"retry_delay\s*\(\s*seconds:\s*(\d+)\s*\)",
        r"retry in\s*(\d+)\s*s",
        r"try again in\s*(\d+)\s*s",
    ]
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if not match:
            continue
        try:
            return int(match.group(1))
        except ValueError:
            continue
    return None


def cleanup_expired_cache(now_ts):
    expired_keys = [
        key
        for key, value in solve_cache.items()
        if now_ts - value.get("ts", 0) > SOLVE_CACHE_TTL_SECONDS
    ]
    for key in expired_keys:
        solve_cache.pop(key, None)


def parse_model_json(text):
    cleaned = (text or "").strip()
    if not cleaned:
        return None

    # Gemini may wrap JSON in markdown code fences.
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE | re.DOTALL).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                return None
        return None


def generate_content_with_timeout(model, payload):
    future = GEMINI_EXECUTOR.submit(
        model.generate_content,
        payload,
        request_options={"timeout": GEMINI_REQUEST_TIMEOUT_SECONDS},
    )
    try:
        return future.result(timeout=GEMINI_REQUEST_TIMEOUT_SECONDS)
    except FutureTimeoutError:
        raise TimeoutError(
            f"Gemini request timed out after {GEMINI_REQUEST_TIMEOUT_SECONDS} seconds. "
            "Check internet access, API key restrictions, and Gemini quota."
        )


# =====================
# SOLVE ENDPOINT
# =====================
@app.route("/", methods=["GET"])
def root():
    return jsonify(
        {
            "ok": True,
            "service": "gemini_server",
            "message": "Server is running. Use POST /solve or GET /health.",
            "endpoints": ["/solve", "/health"],
        }
    )


@app.route("/solve", methods=["POST"])
def solve():
    global active_model
    global active_model_name
    global MODEL_CANDIDATES

    data = request.json or {}
    image_b64 = data.get("image")

    if not image_b64:
        return jsonify({"error": "No image provided"}), 400

    image_bytes = base64.b64decode(image_b64)
    image_hash = hashlib.sha256(image_bytes).hexdigest()
    now_ts = time.time()
    cleanup_expired_cache(now_ts)
    cached = solve_cache.get(image_hash)
    if cached is not None:
        return jsonify(cached["result"])

    prompt = """
You are a math solving AI.

Read the handwritten equation from the image and return ONLY valid JSON in this format:

{
 "problem": "...",
 "solution_type": "Equation / Arithmetic / Algebra / Graph",
 "solution_text": "step by step solution",
 "plottable_equation": ""
}

Do NOT return markdown.
Do NOT return explanation outside JSON.
"""

    try:
        payload = [
            prompt,
            {
                "mime_type": "image/png",
                "data": image_bytes,
            },
        ]

        response = None
        last_model_error = None
        tried = []

        # Fast path: reuse active model if one already worked before.
        if active_model is not None:
            tried.append(active_model_name or "(active)")
            try:
                response = generate_content_with_timeout(active_model, payload)
            except Exception as e:
                last_model_error = e
                if isinstance(e, TimeoutError):
                    raise
                elif is_model_not_available_error(e) or is_quota_or_rate_limit_error(e):
                    active_model = None
                    active_model_name = None
                else:
                    raise

        # Fallback path: try candidate models until one works.
        if response is None:
            for model_name in MODEL_CANDIDATES:
                if model_name in tried:
                    continue
                tried.append(model_name)
                try:
                    candidate = genai.GenerativeModel(model_name)
                    response = generate_content_with_timeout(candidate, payload)
                    active_model = candidate
                    active_model_name = model_name
                    break
                except Exception as e:
                    if isinstance(e, TimeoutError):
                        raise
                    elif is_model_not_available_error(e) or is_quota_or_rate_limit_error(e):
                        last_model_error = e
                        continue
                    raise

        # One refresh pass in case models changed after startup.
        if response is None:
            refreshed = discover_generate_content_models()
            if refreshed:
                MODEL_CANDIDATES = _dedupe_keep_order(MODEL_CANDIDATES + refreshed)
                for model_name in refreshed:
                    if model_name in tried:
                        continue
                    tried.append(model_name)
                    try:
                        candidate = genai.GenerativeModel(model_name)
                        response = generate_content_with_timeout(candidate, payload)
                        active_model = candidate
                        active_model_name = model_name
                        break
                    except Exception as e:
                        if isinstance(e, TimeoutError):
                            raise
                        elif is_model_not_available_error(e) or is_quota_or_rate_limit_error(e):
                            last_model_error = e
                            continue
                        raise

        if response is None:
            tried_models = ", ".join(tried) or ", ".join(MODEL_CANDIDATES) or "(none)"
            if last_model_error:
                raise RuntimeError(f"{last_model_error}. Tried models: {tried_models}")
            raise RuntimeError(f"No working Gemini model found. Tried models: {tried_models}")

        text = (response.text or "").strip()
        result_json = parse_model_json(text)
        if result_json is None:
            result_json = {
                "problem": "Could not parse AI response",
                "solution_type": "Error",
                "solution_text": text,
                "plottable_equation": "",
            }

        solve_cache[image_hash] = {"ts": now_ts, "result": result_json}
        return jsonify(result_json)

    except Exception as e:
        message = str(e)
        message_l = message.lower()
        if "api_key_invalid" in message_l or "api key expired" in message_l or "api key not valid" in message_l:
            message = (
                "Gemini API key is invalid or expired. Generate a new key in Google AI Studio, "
                "update GEMINI_API_KEY (or API_KEY) in .env, then restart gemini_server.py."
            )
        elif "429" in message_l or "quota" in message_l:
            retry_seconds = extract_retry_seconds(str(e))
            if "limit: 0" in message_l or "limit is 0" in message_l:
                message = (
                    "Gemini API free-tier quota is 0 for this Google project/key, so a fresh key will still fail. "
                    "Create/select a Google AI Studio project with Gemini API quota or enable billing for this project."
                )
            elif api_key.startswith("AQ."):
                message = (
                    "Gemini API quota was rejected for this AQ auth key/project. "
                    "Check Google AI Studio rate limits for this project or enable billing."
                )
            else:
                message = "Quota exceeded for Gemini API. Check plan/billing and model rate limits for this project."
            if retry_seconds is not None:
                message += f" Retry after about {retry_seconds} seconds."
            message += f" Raw Gemini message: {str(e)[:700]}"

        return jsonify(
            {
                "problem": "Gemini Error",
                "solution_type": "Error",
                "solution_text": message,
                "plottable_equation": "",
            }
        )


@app.route("/health", methods=["GET"])
def health():
    return jsonify(
        {
            "ok": True,
            "pid": os.getpid(),
            "env_path": env_path,
            "api_key_source": api_key_source,
            "api_key_masked": masked_key_tail(api_key),
            "active_model": active_model_name,
            "model_candidates_count": len(MODEL_CANDIDATES),
        }
    )


# =====================
# RUN SERVER
# =====================
if __name__ == "__main__":
    app.run(host=GEMINI_SERVER_HOST, port=GEMINI_SERVER_PORT)
