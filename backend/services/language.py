"""
Language detection service.
"""

from langdetect import detect, DetectorFactory

# Make results deterministic
DetectorFactory.seed = 0

SUPPORTED_LANGUAGES = {"ar", "en", "hi"}


def detect_language(text: str) -> str:
    """
    Detect the dominant language of a text snippet.
    Returns ISO 639-1 code: 'ar', 'hi', 'en', or 'mixed'.
    """
    if not text or len(text.strip()) < 50:
        return "unknown"

    try:
        lang = detect(text[:2000])  # Use first 2000 chars for speed
        return lang if lang in SUPPORTED_LANGUAGES else lang
    except Exception:
        return "unknown"
