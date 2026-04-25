import base64
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from config_loader import config
from logger import setup_logger
from utils import ensure_dir, load_json, save_json

logger = setup_logger(__name__)


def _request(method: str, url: str, **kwargs) -> requests.Response:
    attempts = int(config.get("transcription.api_retry_attempts", 3))
    delay = float(config.get("transcription.api_retry_delay_seconds", 2.0))
    kwargs.setdefault("timeout", float(config.get("transcription.api_timeout_seconds", 900)))
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.request(method, url, **kwargs)
            if resp.status_code < 500:
                return resp
            last_error = RuntimeError(f"HTTP {resp.status_code}: {resp.text[:500]}")
        except Exception as e:
            last_error = e
        if attempt < attempts:
            logger.warning(f"Tentativa API {attempt}/{attempts} falhou: {last_error}. Tentando novamente...")
            time.sleep(delay * attempt)
    if last_error:
        raise last_error
    raise RuntimeError("Falha desconhecida na chamada de API.")


def _file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _cache_key(audio_path: str, provider: str, model: str, language: Optional[str]) -> str:
    payload = {
        "audio_sha256": _file_sha256(audio_path),
        "provider": provider,
        "model": model,
        "language": language or "auto",
        "word_timestamps": bool(config.get("transcription.word_timestamps", True)),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_cached_transcription(audio_path: str, provider: str, model: str, language: Optional[str]) -> Optional[Dict[str, Any]]:
    if not config.get("transcription.cache_enabled", True):
        return None
    cache_dir = Path(config.get("paths.transcription_cache_dir", "cache/transcriptions"))
    ensure_dir(str(cache_dir))
    path = cache_dir / f"{_cache_key(audio_path, provider, model, language)}.json"
    if path.is_file():
        logger.info(f"Reaproveitando transcricao em cache: {path}")
        return load_json(str(path))
    return None


def save_cached_transcription(audio_path: str, provider: str, model: str, language: Optional[str], data: Dict[str, Any]) -> None:
    if not config.get("transcription.cache_enabled", True):
        return
    cache_dir = Path(config.get("paths.transcription_cache_dir", "cache/transcriptions"))
    ensure_dir(str(cache_dir))
    path = cache_dir / f"{_cache_key(audio_path, provider, model, language)}.json"
    save_json(data, str(path))


def get_provider_name() -> str:
    return str(config.get("transcription.provider", "local_whisper")).strip().lower()


def get_provider_model(provider: str) -> str:
    if provider == "openai":
        return config.get("transcription.openai.model", config.get("transcription.api_model", "whisper-1"))
    if provider == "deepgram":
        return config.get("transcription.deepgram.model", "nova-3")
    if provider == "assemblyai":
        return config.get("transcription.assemblyai.model", "universal-2")
    if provider == "google":
        return config.get("transcription.google.model", "latest_long")
    if provider == "local_faster_whisper":
        return config.get(
            "transcription.faster_whisper.model",
            config.get("models.faster_whisper.size", "large-v3-turbo"),
        )
    return config.get("models.whisper.size", "medium")


def transcribe_external(audio_path: str, provider: str, language: Optional[str] = None) -> Dict[str, Any]:
    provider = provider.strip().lower()
    model = get_provider_model(provider)
    cached = load_cached_transcription(audio_path, provider, model, language)
    if cached is not None:
        return cached

    if provider == "openai":
        data = _transcribe_openai(audio_path, model, language)
    elif provider == "deepgram":
        data = _transcribe_deepgram(audio_path, model, language)
    elif provider == "assemblyai":
        data = _transcribe_assemblyai(audio_path, model, language)
    elif provider == "google":
        data = _transcribe_google(audio_path, model, language)
    else:
        raise ValueError(f"Provedor de transcricao desconhecido: {provider}")

    data["provider"] = provider
    data["model"] = model
    save_cached_transcription(audio_path, provider, model, language, data)
    return data


def list_available_models(provider: str, api_key: Optional[str] = None) -> List[str]:
    """Busca modelos disponiveis para o provedor de transcricao.

    Alguns provedores nao oferecem um endpoint publico simples para listar
    somente modelos de STT; nesses casos retornamos a lista conhecida e mantida
    no app.
    """
    provider = (provider or "local_whisper").strip().lower()
    fallback = {
        "local_whisper": ["tiny", "base", "small", "medium", "large", "large-v3-turbo", "turbo"],
        "local_faster_whisper": ["tiny", "base", "small", "medium", "large-v2", "large-v3", "large-v3-turbo", "turbo"],
        "openai": ["whisper-1", "gpt-4o-transcribe", "gpt-4o-mini-transcribe"],
        "deepgram": ["nova-3", "nova-2", "enhanced", "base"],
        "assemblyai": ["universal-3-pro", "universal-2"],
        "google": ["latest_long", "latest_short", "video", "phone_call", "default"],
    }

    if provider in ("local_whisper", "local_faster_whisper"):
        return fallback[provider]
    if config.get("app.offline_mode", False):
        return fallback.get(provider, [])
    if provider == "openai":
        key = api_key or os.environ.get("OPENAI_API_KEY") or config.get("transcription.openai.api_key", None)
        if not key:
            raise RuntimeError("Informe a chave OpenAI ou defina OPENAI_API_KEY.")
        resp = _request(
            "GET",
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=60,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Falha ao listar modelos OpenAI ({resp.status_code}): {resp.text[:500]}")
        ids = sorted({m.get("id", "") for m in resp.json().get("data", []) if m.get("id")})
        audio_ids = [
            mid for mid in ids
            if "transcribe" in mid.lower() or mid == "whisper-1"
        ]
        return audio_ids or fallback[provider]
    if provider == "deepgram":
        headers = {}
        key = api_key or os.environ.get("DEEPGRAM_API_KEY") or config.get("transcription.deepgram.api_key", None)
        if key:
            headers["Authorization"] = f"Token {key}"
        resp = _request("GET", "https://api.deepgram.com/v1/models", headers=headers, timeout=60)
        if resp.status_code >= 400:
            raise RuntimeError(f"Falha ao listar modelos Deepgram ({resp.status_code}): {resp.text[:500]}")
        raw_models = resp.json().get("stt", []) or []
        models = []
        for item in raw_models:
            canonical = item.get("canonical_name")
            architecture = item.get("architecture")
            name = item.get("name")
            for candidate in (canonical, architecture, name):
                if candidate and candidate not in models:
                    models.append(candidate)
        return models or fallback[provider]

    return fallback.get(provider, [])


def normalize_words(words: List[Dict[str, Any]], offset: float = 0.0) -> List[Dict[str, Any]]:
    normalized = []
    for item in words or []:
        word = (item.get("word") or item.get("text") or item.get("punctuated_word") or "").strip()
        if not word:
            continue
        start = _to_seconds(item.get("start", item.get("startTime", item.get("start_offset", 0.0)))) + offset
        end = _to_seconds(item.get("end", item.get("endTime", item.get("end_offset", start)))) + offset
        if end < start:
            end = start
        out = {"word": word, "start": float(start), "end": float(end)}
        if "confidence" in item and item.get("confidence") is not None:
            out["confidence"] = item.get("confidence")
        if "speaker" in item and item.get("speaker") is not None:
            out["speaker"] = item.get("speaker")
        normalized.append(out)
    return normalized


def result_to_pipeline_chunk(result: Dict[str, Any], audio_path: str, start: float, end: float) -> Dict[str, Any]:
    words = normalize_words(result.get("words", []), offset=start)
    transcript = (result.get("transcript") or result.get("text") or "").strip()
    if not transcript and words:
        transcript = " ".join(w["word"] for w in words)
    return {
        "chunk": audio_path,
        "transcript": transcript,
        "transcript_en": "",
        "words": words,
        "start": start,
        "end": end,
        "provider": result.get("provider", ""),
        "model": result.get("model", ""),
        "language": result.get("language", ""),
    }


def _env_or_config(config_key: str, env_key: str) -> str:
    value = os.environ.get(env_key) or config.get(config_key, None)
    if not value:
        raise RuntimeError(f"Configure {config_key} no config.yaml ou a variavel {env_key}.")
    return str(value)


def _to_seconds(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text.endswith("s"):
        text = text[:-1]
    try:
        return float(text)
    except ValueError:
        return 0.0


def _transcribe_openai(audio_path: str, model: str, language: Optional[str]) -> Dict[str, Any]:
    api_key = _env_or_config("transcription.openai.api_key", "OPENAI_API_KEY")
    url = config.get("transcription.openai.url", "https://api.openai.com/v1/audio/transcriptions")
    headers = {"Authorization": f"Bearer {api_key}"}
    data = {
        "model": model,
        "response_format": "verbose_json",
        "timestamp_granularities[]": "word",
    }
    if language and language != "auto":
        data["language"] = language
    prompt = config.get("transcription.prompt", None)
    if prompt:
        data["prompt"] = prompt

    logger.info(f"Transcrevendo via OpenAI ({model})...")
    with open(audio_path, "rb") as f:
        resp = _request("POST", url, headers=headers, data=data, files={"file": f})
    if resp.status_code >= 400:
        raise RuntimeError(f"OpenAI transcription falhou ({resp.status_code}): {resp.text[:1000]}")
    raw = resp.json()
    return {
        "transcript": raw.get("text", ""),
        "language": raw.get("language", language or ""),
        "words": normalize_words(raw.get("words", [])),
        "raw_provider_response": raw if config.get("transcription.keep_raw_response", False) else None,
    }


def _transcribe_deepgram(audio_path: str, model: str, language: Optional[str]) -> Dict[str, Any]:
    api_key = _env_or_config("transcription.deepgram.api_key", "DEEPGRAM_API_KEY")
    params = {
        "model": model,
        "smart_format": "true",
        "punctuate": "true",
        "paragraphs": "true",
    }
    if config.get("transcription.deepgram.diarize", False):
        params["diarize"] = "true"
    if language and language != "auto":
        params["language"] = language
    elif config.get("transcription.deepgram.detect_language", True):
        params["detect_language"] = "true"

    logger.info(f"Transcrevendo via Deepgram ({model})...")
    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "audio/wav",
    }
    with open(audio_path, "rb") as f:
        resp = _request(
            "POST",
            "https://api.deepgram.com/v1/listen",
            params=params,
            headers=headers,
            data=f,
            timeout=900,
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"Deepgram transcription falhou ({resp.status_code}): {resp.text[:1000]}")
    raw = resp.json()
    channel = (((raw.get("results") or {}).get("channels") or [{}])[0])
    alt = (channel.get("alternatives") or [{}])[0]
    words = []
    for item in alt.get("words", []) or []:
        words.append({
            "word": item.get("punctuated_word") or item.get("word"),
            "start": item.get("start", 0.0),
            "end": item.get("end", 0.0),
            "confidence": item.get("confidence"),
            "speaker": item.get("speaker"),
        })
    return {
        "transcript": alt.get("transcript", ""),
        "language": ((raw.get("results") or {}).get("detected_language") or language or ""),
        "words": normalize_words(words),
        "raw_provider_response": raw if config.get("transcription.keep_raw_response", False) else None,
    }


def _transcribe_assemblyai(audio_path: str, model: str, language: Optional[str]) -> Dict[str, Any]:
    api_key = _env_or_config("transcription.assemblyai.api_key", "ASSEMBLYAI_API_KEY")
    base_url = config.get("transcription.assemblyai.url", "https://api.assemblyai.com")
    headers = {"authorization": api_key}

    logger.info("Enviando audio para AssemblyAI...")
    with open(audio_path, "rb") as f:
        upload = _request("POST", f"{base_url}/v2/upload", headers=headers, data=f)
    if upload.status_code >= 400:
        raise RuntimeError(f"AssemblyAI upload falhou ({upload.status_code}): {upload.text[:1000]}")
    audio_url = upload.json()["upload_url"]

    payload = {
        "audio_url": audio_url,
        "punctuate": True,
        "format_text": True,
    }
    if model:
        payload["speech_models"] = [model]
    if language and language != "auto":
        payload["language_code"] = language
    else:
        payload["language_detection"] = True
    if config.get("transcription.assemblyai.speaker_labels", False):
        payload["speaker_labels"] = True

    create = _request("POST", f"{base_url}/v2/transcript", headers=headers, json=payload, timeout=120)
    if create.status_code >= 400:
        raise RuntimeError(f"AssemblyAI create falhou ({create.status_code}): {create.text[:1000]}")
    transcript_id = create.json()["id"]

    poll_interval = float(config.get("transcription.assemblyai.poll_interval", 3.0))
    while True:
        status = _request("GET", f"{base_url}/v2/transcript/{transcript_id}", headers=headers, timeout=120)
        if status.status_code >= 400:
            raise RuntimeError(f"AssemblyAI poll falhou ({status.status_code}): {status.text[:1000]}")
        raw = status.json()
        if raw.get("status") == "completed":
            break
        if raw.get("status") == "error":
            raise RuntimeError(f"AssemblyAI transcription falhou: {raw.get('error')}")
        logger.info(f"AssemblyAI status: {raw.get('status')}")
        time.sleep(poll_interval)

    words = []
    for item in raw.get("words", []) or []:
        words.append({
            "word": item.get("text"),
            "start": (item.get("start") or 0) / 1000.0,
            "end": (item.get("end") or 0) / 1000.0,
            "confidence": item.get("confidence"),
        })
    return {
        "transcript": raw.get("text", ""),
        "language": raw.get("language_code", language or ""),
        "words": normalize_words(words),
        "raw_provider_response": raw if config.get("transcription.keep_raw_response", False) else None,
    }


def _transcribe_google(audio_path: str, model: str, language: Optional[str]) -> Dict[str, Any]:
    api_key = os.environ.get("GOOGLE_API_KEY") or config.get("transcription.google.api_key", None)
    if not api_key:
        raise RuntimeError("Configure transcription.google.api_key ou GOOGLE_API_KEY para usar Google STT.")

    with open(audio_path, "rb") as f:
        content = base64.b64encode(f.read()).decode("ascii")
    lang = language if language and language != "auto" else config.get("transcription.google.language_code", "en-US")
    payload = {
        "config": {
            "languageCode": lang,
            "enableWordTimeOffsets": True,
            "model": model,
        },
        "audio": {"content": content},
    }
    url = f"https://speech.googleapis.com/v1/speech:recognize?key={api_key}"
    logger.info(f"Transcrevendo via Google Speech-to-Text ({model})...")
    resp = _request("POST", url, json=payload)
    if resp.status_code >= 400:
        raise RuntimeError(f"Google STT falhou ({resp.status_code}): {resp.text[:1000]}")
    raw = resp.json()
    words = []
    transcripts = []
    for result in raw.get("results", []) or []:
        alt = (result.get("alternatives") or [{}])[0]
        if alt.get("transcript"):
            transcripts.append(alt["transcript"])
        for item in alt.get("words", []) or []:
            words.append({
                "word": item.get("word"),
                "start": item.get("startTime", "0s"),
                "end": item.get("endTime", "0s"),
                "confidence": alt.get("confidence"),
            })
    return {
        "transcript": " ".join(transcripts).strip(),
        "language": lang,
        "words": normalize_words(words),
        "raw_provider_response": raw if config.get("transcription.keep_raw_response", False) else None,
    }
