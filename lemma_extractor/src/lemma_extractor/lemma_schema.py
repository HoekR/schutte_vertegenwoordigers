"""Pydantic schema for structured lemma extraction.

Mirrors the Dutch XML layout of
``schutte_binnenland/output_lemmas/parsed_data_ollama_test.xml``.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class Geboorte(BaseModel):
    plaats: Optional[str] = None
    jaar: Optional[str] = None


class Opleiding(BaseModel):
    status: Optional[str] = None
    universiteit: Optional[str] = None
    inschrijfdatum: Optional[str] = None


class CarriereItem(BaseModel):
    jaar: Optional[str] = None
    positie: Optional[str] = None


class Overlijden(BaseModel):
    plaats: Optional[str] = None
    datum: Optional[str] = None


class Bewoner(BaseModel):
    jaren: Optional[str] = Field(
        default=None,
        description="Ambtsperiode / functie-regel, e.g. '1656-1687 resident'",
    )
    nummer: Optional[str] = Field(
        default=None,
        description="Schutte nr if present in text (may differ from file id)",
    )
    naam: Optional[str] = Field(
        default=None,
        description="Full name with titles as in the lemma opening line",
    )
    titel: Optional[str] = None
    geboorte: Optional[Geboorte] = None
    opleiding: Optional[Opleiding] = None
    carriere: list[CarriereItem] = Field(default_factory=list)
    overlijden: Optional[Overlijden] = None


class Huwelijk(BaseModel):
    plaats: Optional[str] = None
    maand: Optional[str] = None
    aankondiging: Optional[str] = None


class OudersEchtgenoot(BaseModel):
    vader: Optional[str] = None
    vader_titel: Optional[str] = None
    vader_carriere: list[CarriereItem] = Field(default_factory=list)
    moeder: Optional[str] = None


class Echtgenoot(BaseModel):
    naam: Optional[str] = None
    geboorte: Optional[Geboorte] = None
    huwelijk: Optional[Huwelijk] = None
    ouders: Optional[OudersEchtgenoot] = None


class Familie(BaseModel):
    vader: Optional[str] = None
    moeder: Optional[str] = None
    echtgenoot: Optional[Echtgenoot] = None


class ParsedLemma(BaseModel):
    """Structured extraction of one Schutte lemma."""

    bewoner: Bewoner
    familie: Optional[Familie] = None
    bronnen: list[str] = Field(
        default_factory=list,
        description="Bibliographic references (N.N.B.W., Van der Aa, …)",
    )


def parsed_lemma_to_xml(parsed: ParsedLemma, lemma_id: str | int) -> str:
    """Serialize to Dutch XML matching ``parsed_data_ollama_test.xml``."""

    def esc(s: str | None) -> str:
        if s is None:
            return ""
        return (
            str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    def tag(name: str, value: str | None, indent: int = 8) -> str:
        pad = " " * indent
        if value is None or value == "":
            return f"{pad}<{name} />"
        return f"{pad}<{name}>{esc(value)}</{name}>"

    def carriere_xml(items: list[CarriereItem], indent: int = 8) -> str:
        if not items:
            return ""
        pad = " " * indent
        lines = [f"{pad}<carrière>"]
        for item in items:
            lines.append(tag("jaar", item.jaar, indent + 4))
            lines.append(tag("positie", item.positie, indent + 4))
        lines.append(f"{pad}</carrière>")
        return "\n".join(lines)

    b = parsed.bewoner
    parts: list[str] = [f'<lemma lemma="{esc(str(lemma_id))}">', "    <bewoner>"]
    parts.append(tag("jaren", b.jaren, 8))
    parts.append(tag("nummer", b.nummer, 8))
    parts.append(tag("naam", b.naam, 8))
    parts.append(tag("titel", b.titel, 8))

    if b.geboorte:
        parts.append("        <geboorte>")
        parts.append(tag("plaats", b.geboorte.plaats, 12))
        parts.append(tag("jaar", b.geboorte.jaar, 12))
        parts.append("        </geboorte>")
    else:
        parts.append("        <geboorte>")
        parts.append("            <plaats />")
        parts.append("            <jaar />")
        parts.append("        </geboorte>")

    if b.opleiding:
        parts.append("        <opleiding>")
        parts.append(tag("status", b.opleiding.status, 12))
        parts.append(tag("universiteit", b.opleiding.universiteit, 12))
        parts.append(tag("inschrijfdatum", b.opleiding.inschrijfdatum, 12))
        parts.append("        </opleiding>")

    if b.carriere:
        parts.append(carriere_xml(b.carriere, 8))

    if b.overlijden:
        parts.append("        <overlijden>")
        parts.append(tag("plaats", b.overlijden.plaats, 12))
        parts.append(tag("datum", b.overlijden.datum, 12))
        parts.append("        </overlijden>")

    parts.append("    </bewoner>")

    if parsed.familie:
        f = parsed.familie
        parts.append("    <familie>")
        parts.append(tag("vader", f.vader, 8))
        parts.append(tag("moeder", f.moeder, 8))
        if f.echtgenoot:
            e = f.echtgenoot
            parts.append("        <echtgenoot>")
            parts.append(tag("naam", e.naam, 12))
            if e.geboorte:
                parts.append("            <geboorte>")
                parts.append(tag("jaar", e.geboorte.jaar, 16))
                parts.append("            </geboorte>")
            if e.huwelijk:
                parts.append("            <huwelijk>")
                parts.append(tag("plaats", e.huwelijk.plaats, 16))
                parts.append(tag("maand", e.huwelijk.maand, 16))
                parts.append(tag("aankondiging", e.huwelijk.aankondiging, 16))
                parts.append("            </huwelijk>")
            if e.ouders:
                o = e.ouders
                parts.append("            <ouders>")
                parts.append(tag("vader", o.vader, 16))
                parts.append(tag("vader_titel", o.vader_titel, 16))
                if o.vader_carriere:
                    # indent one level deeper under ouders
                    block = carriere_xml(o.vader_carriere, 16).replace(
                        "<carrière>", "<vader_carrière>"
                    ).replace("</carrière>", "</vader_carrière>")
                    parts.append(block)
                parts.append(tag("moeder", o.moeder, 16))
                parts.append("            </ouders>")
            parts.append("        </echtgenoot>")
        parts.append("    </familie>")

    if parsed.bronnen:
        parts.append("    <bronnen>")
        for item in parsed.bronnen:
            parts.append(f"        <item>{esc(item)}</item>")
        parts.append("    </bronnen>")

    parts.append("</lemma>")
    return "\n".join(parts) + "\n"
