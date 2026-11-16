"""Klarheit auf den ersten Blick: Ist auf dem ersten Handy-Bildschirm erkennbar, für wen das Angebot ist und was verkauft wird?

Der Auditor kennt weder Schlüssel noch Anbieter. Eine von außen übergebene Funktion `judge(first_view)` beantwortet beide
Fragen mit je einem Satz und einem wörtlichen Zitat. Dieses Modul prüft jedes Zitat gegen den gesammelten Text, bildet die
Stufe und erzeugt die Befunde. Ein Zitat, das nicht im Text steht, zählt nicht. Alles, was nicht an der Seite liegt
(gesperrt, kein Text, Dienst ausgefallen), ergibt `nicht_beurteilbar` ohne Befunde und damit ohne Einfluss auf die Note.
"""
from typing import Callable

from auditor.findings import finding

MAX_LEN = 200
MIN_QUOTE = 10
NOT_ASSESSABLE_REASON = {"blocked": "blocked", "empty": "no_text"}


_TYPOGRAPHY = str.maketrans({"„": '"', "“": '"', "”": '"', "‚": "'", "‘": "'", "’": "'", "–": "-", "—": "-"})


def _norm(text: str) -> str:
    """Kleinschreibung, ohne jeden Leerraum und mit glatten Anführungszeichen und Strichen. Der gesammelte Text hat durch
    Inline-Elemente manchmal ein Leerzeichen vor dem Komma, ein Modell zitiert ohne. Das Zitat muss trotzdem lückenlos im Text stehen."""
    return "".join(text.lower().translate(_TYPOGRAPHY).split())


def _verified(entry, text_norm: str) -> dict | None:
    """Die Antwort, wenn Satz und Zitat Texte sind und das Zitat im gesammelten Text steht, sonst None."""
    if not isinstance(entry, dict):
        return None
    answer, quote = entry.get("answer"), entry.get("quote")
    if not isinstance(answer, str) or not isinstance(quote, str):
        return None
    answer, quote_norm = " ".join(answer.split()), _norm(quote)
    if not answer or len(quote_norm) < MIN_QUOTE or quote_norm not in text_norm:
        return None
    return {"answer": answer[:MAX_LEN], "quote": " ".join(quote.split())[:MAX_LEN]}


def _not_assessable(reason: str) -> dict:
    return {"stage": "nicht_beurteilbar", "reason": reason, "audience": None, "offer": None}


def _findings(audience, offer) -> list:
    if audience and offer:
        return [finding(
            "KLA-03", "POSITIV",
            "Auf dem ersten Bildschirm ist erkennbar, für wen dein Angebot ist und was du verkaufst.",
            "Besucher verstehen in Sekunden, ob sie hier richtig sind.",
        )]
    if audience or offer:
        missing = "was du verkaufst" if audience else "für wen dein Angebot ist"
        return [finding(
            "KLA-02", "MITTEL",
            f"Auf dem ersten Bildschirm ist nicht erkennbar, {missing}.",
            "Besucher entscheiden in wenigen Sekunden, ob sie bleiben. Fehlt eine der beiden Antworten, raten sie, und viele gehen.",
            f"Sag oben in der Hauptüberschrift in einem Satz, {missing}.",
        )]
    return [finding(
        "KLA-01", "HOCH",
        "Auf dem ersten Bildschirm ist nicht erkennbar, für wen dein Angebot ist und was du verkaufst.",
        "Besucher entscheiden in wenigen Sekunden, ob sie bleiben. Verstehen sie nicht sofort, ob das Angebot zu ihnen passt, springen sie ab.",
        "Sag oben in der Hauptüberschrift in einem Satz, für wen das Angebot ist und was du verkaufst, zum Beispiel: Websites für Zahnarztpraxen in Mainz.",
    )]


def run(first_view: dict | None, judge: Callable[[dict], dict | None] | None) -> dict:
    if not isinstance(first_view, dict):
        return _not_assessable("failed")
    status = first_view.get("status")
    if status != "ok":
        return _not_assessable(NOT_ASSESSABLE_REASON.get(status, "failed"))
    if judge is None:
        return _not_assessable("failed")
    try:
        answers = judge(first_view)
    except Exception:
        return _not_assessable("failed")
    if not isinstance(answers, dict):
        return _not_assessable("failed")
    text_norm = _norm(first_view.get("text") or "")
    audience = _verified(answers.get("audience"), text_norm)
    offer = _verified(answers.get("offer"), text_norm)
    stage = "klar" if audience and offer else "teilweise" if audience or offer else "unklar"
    return {"stage": stage, "reason": None, "audience": audience, "offer": offer, "findings": _findings(audience, offer)}
