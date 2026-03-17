from __future__ import annotations

"""
Parse extracted text from 'other format' committee-report PDFs into a long-format
procedure table.

Input columns expected in the source CSV:
    procedure, reference, format, extracted_text

Output columns:
    procedure, committee, designation, head, value

The parser intentionally supports three structural fallbacks:
1) modern table-like procedure blocks,
2) mid-era prose procedure blocks,
3) older opinion blocks without a literal PROCEDURE heading.
"""

from typing import Dict, Iterable, List, Optional, Tuple
import re

import pandas as pd


MONTH_MAP = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

NUMBER_WORDS = {
    "zero": 0,
    "none": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

DATE_DOTTED_RE = re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{4}\b")
DATE_NAMED_RE = re.compile(
    r"\b\d{1,2}(?:\s*-\s*\d{1,2})?\s+"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"(?:\s+\d{4})?\b",
    flags=re.I,
)


# ---------------------------------------------------------------------------
# text helpers
# ---------------------------------------------------------------------------
def clean_text(text: str | None) -> str:
    if text is None:
        return ""
    text = str(text)
    text = (
        text.replace("\r", " ")
        .replace("\n", " ")
        .replace("\xa0", " ")
        .replace("\u00ad", "")
        .replace("\u2011", "-")
        .replace("\u2012", "-")
        .replace("\u2013", "–")
        .replace("\u2014", "–")
        .replace("\u2212", "–")
        .replace("<<PAGEBREAK>>", " ")
    )
    text = re.sub(r"(?<=\b\d)O(?=\b)", "0", text)
    text = re.sub(r"(?<=\b\d)O(?=\s+[A-Za-z])", "0", text)
    text = re.sub(r"(?<=\b)O(?=\d\b)", "0", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalise_procedure_text(text: str | None) -> str:
    if text is None:
        return ""
    # Preserve page boundaries before collapsing whitespace.
    text = str(text).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n\s*\n+", " <<PAGEBREAK>> ", text)
    text = clean_text(text)
    text = re.sub(r"\bO\s+P\s+I\s+N\s+I\s+O\s+N\b", "OPINION", text, flags=re.I)
    text = re.sub(r"\bC\s+O\s+N\s+T\s+E\s+N\s+T\s+S\b", "CONTENTS", text, flags=re.I)
    text = re.sub(r"\bP\s*R\s*O\s*C\s*E\s*D\s*U\s*R\s*E\b", "PROCEDURE", text, flags=re.I)
    text = re.sub(r"\bPOSITION OT THE COMMISSION\b", "POSITION OF THE COMMISSION", text, flags=re.I)
    return text


def safe_int(token: str | None) -> Optional[int]:
    if token is None:
        return None
    token = clean_text(token).lower().rstrip(":")
    if token.isdigit():
        return int(token)
    return NUMBER_WORDS.get(token)


def dedupe_keep_order(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for value in values:
        value = clean_text(value)
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


# ---------------------------------------------------------------------------
# date helpers
# ---------------------------------------------------------------------------
def normalise_date(value: str) -> str:
    value = clean_text(value)
    value = re.sub(r"(?<=\b\d)O(?=\s+[A-Za-z])", "0", value)

    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", value)
    if m:
        d, mth, y = m.groups()
        return f"{int(d)}.{int(mth)}.{int(y)}"

    m = re.fullmatch(r"(\d{1,2})\s*-\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", value)
    if m:
        d1, d2, month_name, year = m.groups()
        month_num = MONTH_MAP.get(month_name.lower())
        if month_num:
            return f"{int(d1)}-{int(d2)}.{month_num}.{int(year)}"

    m = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", value)
    if m:
        day, month_name, year = m.groups()
        month_num = MONTH_MAP.get(month_name.lower())
        if month_num:
            return f"{int(day)}.{month_num}.{int(year)}"

    return value


def extract_dates(fragment: str) -> List[str]:
    fragment = clean_text(fragment)
    if not fragment:
        return []

    dotted = [normalise_date(x) for x in DATE_DOTTED_RE.findall(fragment)]
    if dotted:
        return dedupe_keep_order(dotted)

    named_tokens = DATE_NAMED_RE.findall(fragment)
    if not named_tokens:
        return []

    years = re.findall(r"\b(\d{4})\b", fragment)
    fallback_year = years[-1] if years else None

    out: List[str] = []
    for token in named_tokens:
        token = clean_text(token)
        if not re.search(r"\b\d{4}\b", token) and fallback_year:
            token = f"{token} {fallback_year}"
        out.append(normalise_date(token))
    return dedupe_keep_order(out)


# ---------------------------------------------------------------------------
# generic row helpers
# ---------------------------------------------------------------------------
def add_row(rows: List[Dict[str, str]], procedure: str, committee: str, designation: str, head: str, value: str) -> None:
    head = clean_text(head)
    value = clean_text(value)
    committee = clean_text(committee)
    if not head or not value or not committee:
        return
    rows.append(
        {
            "procedure": procedure,
            "committee": committee,
            "designation": designation,
            "head": head,
            "value": value,
        }
    )


def split_reference_blob(reference_blob: str) -> List[str]:
    reference_blob = clean_text(reference_blob)
    if not reference_blob:
        return []
    parts = re.split(r"\s+[–-]\s+", reference_blob)
    return dedupe_keep_order(parts)


# ---------------------------------------------------------------------------
# global document metadata
# ---------------------------------------------------------------------------
def extract_global_title_and_references(text: str, procedure: str) -> Tuple[str, List[str]]:
    patterns = [
        rf"\bREPORT on (.+) \((.+?{re.escape(procedure)}.*?)\)\s+Committee on",
        rf"\bDRAFT EUROPEAN PARLIAMENT LEGISLATIVE RESOLUTION on (.+) \((.+?{re.escape(procedure)}.*?)\)\s*\(",
        rf"\bDRAFT LEGISLATIVE RESOLUTION .*? on (.+) \((.+?{re.escape(procedure)}.*?)\)\s*\(",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.I)
        if m:
            return clean_text(m.group(1)), split_reference_blob(m.group(2))
    return "", []


def extract_cover_lead_committee(text: str) -> str:
    patterns = [
        r"\bCommittee on ([A-Z][A-Za-z'’\-\s,&]+?) Rapporteur:",
        r"\bCommittee on ([A-Z][A-Za-z'’\-\s,&]+?) Rapporteur for the opinion:",
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            return clean_text(f"Committee on {m.group(1)}")
    return ""


def extract_lead_procedural_block(text: str) -> str:
    start_match = re.search(r"\bPROCEDURAL PAGE\b", text, flags=re.I)
    if start_match:
        start = start_match.start()
    else:
        m = re.search(r"\bBy letter of\b", text)
        if not m:
            return ""
        start = m.start()

    end_candidates = []
    for pat in [
        r"\bLEGISLATIVE PROPOSAL\b",
        r"\bDRAFT LEGISLATIVE RESOLUTION\b",
        r"\bA LEGISLATIVE PROPOSAL\b",
    ]:
        m = re.search(pat, text[start:], flags=re.I)
        if m:
            end_candidates.append(start + m.start())

    end = min(end_candidates) if end_candidates else len(text)
    return clean_text(text[start:end])


# ---------------------------------------------------------------------------
# opinion section detection
# ---------------------------------------------------------------------------
def extract_opinion_sections(text: str) -> List[Dict[str, str]]:
    starts: List[Dict[str, str | int]] = []

    pattern1 = re.compile(
        r"(?:\b\d{1,2}\.\d{1,2}\.\d{4}\s+)?"
        r"OPINION OF THE COMMITTEE ON\s+(.+?)\s+for the Committee on\s+(.+?)"
        r"(?=\s+on the proposal|\s+Draftsman:|\s+Rapporteur:|\s+SHORT JUSTIFICATION|\s+PROCEDURE)",
        flags=re.I,
    )
    for m in pattern1.finditer(text):
        local_tail = text[m.end(): m.end() + 500]
        if not re.search(r"Draftsman:|Rapporteur:|SHORT JUSTIFICATION|PROCEDURE|At its meeting", local_tail, flags=re.I):
            continue
        starts.append(
            {
                "start": m.start(),
                "committee": clean_text(f"Committee on {m.group(1)}"),
                "lead_committee": clean_text(f"Committee on {m.group(2)}"),
            }
        )

    pattern2 = re.compile(
        r"OPINION(?:\s*\(Rule .*?\))?\s+of the Committee on\s+(.+?)\s+for the Committee on\s+(.+?)"
        r"(?=\s+Draftsman:|\s+At its meeting|\s+on the proposal)",
        flags=re.I,
    )
    for m in pattern2.finditer(text):
        local_tail = text[m.end(): m.end() + 500]
        if not re.search(r"Draftsman:|At its meeting|PROCEDURE", local_tail, flags=re.I):
            continue
        starts.append(
            {
                "start": m.start(),
                "committee": clean_text(f"Committee on {m.group(1)}"),
                "lead_committee": clean_text(f"Committee on {m.group(2)}"),
            }
        )

    if not starts:
        return []

    deduped: List[Dict[str, str | int]] = []
    seen = set()
    for item in sorted(starts, key=lambda x: int(x["start"])):
        key = (int(item["start"]), str(item["committee"]))
        if key not in seen:
            seen.add(key)
            deduped.append(item)

    out: List[Dict[str, str]] = []
    for i, item in enumerate(deduped):
        start = int(item["start"])
        end = int(deduped[i + 1]["start"]) if i + 1 < len(deduped) else len(text)

        lead_proc_match = re.search(r"\bPROCEDURE\s*[–-]\s*COMMITTEE RESPONSIBLE\b", text[start:end], flags=re.I)
        if lead_proc_match:
            end = start + lead_proc_match.start()

        out.append(
            {
                "committee": str(item["committee"]),
                "lead_committee": str(item["lead_committee"]),
                "text": clean_text(text[start:end]),
            }
        )
    return out


# ---------------------------------------------------------------------------
# modern/table-like parsing
# ---------------------------------------------------------------------------
def extract_between(text: str, start_pat: str, end_pats: List[str]) -> str:
    start_match = re.search(start_pat, text, flags=re.I)
    if not start_match:
        return ""
    tail = text[start_match.end():]
    end_positions = []
    for pat in end_pats:
        m = re.search(pat, tail, flags=re.I)
        if m:
            end_positions.append(m.start())
    end = min(end_positions) if end_positions else len(tail)
    return clean_text(tail[:end])


def pair_name_dates(fragment: str) -> List[Tuple[str, str]]:
    fragment = clean_text(fragment)
    if not fragment:
        return []
    dates = list(DATE_DOTTED_RE.finditer(fragment))
    out: List[Tuple[str, str]] = []
    prev = 0
    for d in dates:
        name = clean_text(fragment[prev:d.start()])
        if name:
            out.append((name, normalise_date(d.group())))
        prev = d.end()
    return out


def parse_modern_procedure_block(
    block: str,
    procedure: str,
    committee: str,
    designation: str,
    fallback_title: str,
    fallback_refs: List[str],
    lead_committee_name: str = "",
) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []

    proc_block_match = re.search(r"\bPROCEDURE(?:\s*[–-]\s*COMMITTEE RESPONSIBLE)?\b", block, flags=re.I)
    if not proc_block_match:
        return rows

    proc_block = clean_text(block[proc_block_match.start():])

    title = extract_between(proc_block, r"\bTitle\b", [r"\bReferences\b", r"\bCommittee responsible\b", r"\bOpinion by\b"])
    if not title:
        title = fallback_title
    if title:
        add_row(rows, procedure, committee, designation, "Title", title)

    refs_blob = extract_between(
        proc_block,
        r"\bReferences\b",
        [r"\bDate submitted to Parliament\b", r"\bCommittee responsible\b", r"\bOpinion by\b"],
    )
    refs = split_reference_blob(refs_blob) if refs_blob else fallback_refs
    for ref in refs:
        add_row(rows, procedure, committee, designation, "References", ref)

    for d in extract_dates(extract_between(proc_block, r"\bDate submitted to Parliament\b", [r"\bCommittee responsible\b", r"\bOpinion by\b"])):
        add_row(rows, procedure, committee, designation, "Date submitted to Parliament", d)

    cr_seg = extract_between(
        proc_block,
        r"\bCommittee responsible\s+Date announced in plenary\b",
        [
            r"\bCommittees asked for opinions\s+Date announced in plenary\b",
            r"\bOpinion by\s+Date announced in plenary\b",
            r"\bNot delivering opinions\s+Date of decision\b",
            r"\bAssociated committees\s+Date announced in plenary\b",
            r"\bRapporteur\b",
            r"\bRapporteurs\b",
        ],
    )
    for value, date in pair_name_dates(cr_seg):
        resolved_value = committee if designation == "lead" and re.fullmatch(r"[A-Z]{2,6}", value) else value
        if designation == "opinion" and lead_committee_name and re.fullmatch(r"[A-Z]{2,6}", value):
            resolved_value = lead_committee_name
        add_row(rows, procedure, committee, designation, "Committee responsible", resolved_value)
        add_row(rows, procedure, committee, designation, "Date announced in plenary", date)

    cafo_seg = extract_between(
        proc_block,
        r"\bCommittees asked for opinions\s+Date announced in plenary\b",
        [
            r"\bAssociated committees\s+Date announced in plenary\b",
            r"\bNot delivering opinions\s+Date of decision\b",
            r"\bOpinion by\s+Date announced in plenary\b",
            r"\bRapporteur\b",
            r"\bRapporteurs\b",
        ],
    )
    for value, date in pair_name_dates(cafo_seg):
        add_row(rows, procedure, committee, designation, "Committees asked for opinions", value)
        add_row(rows, procedure, committee, designation, "Date announced in plenary", date)

    assoc_seg = extract_between(
        proc_block,
        r"\bAssociated committees\s+Date announced in plenary\b",
        [r"\bNot delivering opinions\s+Date of decision\b", r"\bRapporteur\b", r"\bRapporteurs\b"],
    )
    for value, date in pair_name_dates(assoc_seg):
        add_row(rows, procedure, committee, designation, "Associated committees", value)
        add_row(rows, procedure, committee, designation, "Date announced in plenary", date)

    opinion_seg = extract_between(
        proc_block,
        r"\bOpinion by\s+Date announced in plenary\b",
        [r"\bAssociated committees\s+Date announced in plenary\b", r"\bRapporteur\b", r"\bRapporteurs\b"],
    )
    for value, date in pair_name_dates(opinion_seg):
        resolved_value = committee if designation == "opinion" and re.fullmatch(r"[A-Z]{2,6}", value) else value
        add_row(rows, procedure, committee, designation, "Opinion by", resolved_value)
        add_row(rows, procedure, committee, designation, "Date announced in plenary", date)

    ndo_seg = extract_between(
        proc_block,
        r"\bNot delivering opinions\s+Date of decision\b",
        [r"\bRapporteur\b", r"\bRapporteurs\b"],
    )
    for value, date in pair_name_dates(ndo_seg):
        add_row(rows, procedure, committee, designation, "Not delivering opinions", value)
        add_row(rows, procedure, committee, designation, "Date of decision", date)

    rap_seg = extract_between(
        proc_block,
        r"\bRapporteurs?\s+Date appointed\b",
        [r"\bDiscussed in committee\b", r"\bDate adopted\b", r"\bResult of final vote\b"],
    )
    if rap_seg:
        rap_dates = list(DATE_DOTTED_RE.finditer(rap_seg))
        if rap_dates:
            first_date = rap_dates[0]
            rap_name = clean_text(rap_seg[:first_date.start()])
            rap_label = "Rapporteur for the opinion" if designation == "opinion" else ("Rapporteurs" if "," in rap_name else "Rapporteur")
            add_row(rows, procedure, committee, designation, rap_label, rap_name)
            add_row(rows, procedure, committee, designation, "Date appointed", normalise_date(first_date.group()))

    for d in extract_dates(extract_between(proc_block, r"\bDiscussed in committee\b", [r"\bDate adopted\b", r"\bResult of final vote\b", r"\bMembers present for the final vote\b"])):
        add_row(rows, procedure, committee, designation, "Discussed in committee", d)

    for d in extract_dates(extract_between(proc_block, r"\bDate adopted\b", [r"\bResult of final vote\b", r"\bMembers present for the final vote\b"])):
        add_row(rows, procedure, committee, designation, "Date adopted", d)

    vote_match = re.search(r"Result of final vote\s*\+:\s*–:\s*0:\s*(\d+)\s+(\d+)\s+(\d+)", proc_block, flags=re.I)
    if vote_match:
        pos, neg, abs_ = vote_match.groups()
        add_row(rows, procedure, committee, designation, "Result of final vote +", pos)
        add_row(rows, procedure, committee, designation, "Result of final vote –", neg)
        add_row(rows, procedure, committee, designation, "Result of final vote 0", abs_)
    else:
        vote_match2 = re.search(r"Result of final vote\s*\+:\s*–:\s*(\d+)\s+(\d+)", proc_block, flags=re.I)
        if vote_match2:
            pos, neg = vote_match2.groups()
            add_row(rows, procedure, committee, designation, "Result of final vote +", pos)
            add_row(rows, procedure, committee, designation, "Result of final vote –", neg)

    members = extract_between(
        proc_block,
        r"\bMembers present for the final vote\b",
        [r"\bSubstitutes present for the final vote\b", r"\bSubstitutes under Rule .*? present for the final vote\b", r"\bDate tabled\b"],
    )
    if members:
        add_row(rows, procedure, committee, designation, "Members present for the final vote", members)

    substitutes = extract_between(
        proc_block,
        r"\bSubstitutes present for the final vote\b",
        [r"\bSubstitutes under Rule .*? present for the final vote\b", r"\bDate tabled\b"],
    )
    if substitutes:
        add_row(rows, procedure, committee, designation, "Substitutes present for the final vote", substitutes)

    for rule_head in [
        "Substitutes under Rule 200(2) present for the final vote",
        "Substitutes under Rule 209(7) present for the final vote",
    ]:
        rule_val = extract_between(proc_block, rf"\b{re.escape(rule_head)}\b", [r"\bDate tabled\b"])
        if rule_val:
            add_row(rows, procedure, committee, designation, rule_head, rule_val)

    for d in extract_dates(extract_between(proc_block, r"\bDate tabled\b", [])):
        add_row(rows, procedure, committee, designation, "Date tabled", d)

    return rows


# ---------------------------------------------------------------------------
# prose parsing helpers
# ---------------------------------------------------------------------------
def extract_committee_list(blob: str) -> List[str]:
    if not blob:
        return []
    matches = re.findall(
        r"(?:the\s+)?(Committee on .*?)(?=(?:,\s+the\s+Committee on|\s+and\s+the\s+Committee on|\s+for their opinions|\s+are attached|\s+decided on|$))",
        blob,
        flags=re.I,
    )
    return dedupe_keep_order(matches)


def clean_member_blob(blob: str) -> str:
    blob = clean_text(blob)
    if not blob:
        return ""
    blob = blob.replace(";", ", ")
    blob = re.sub(r",\s*(chairman|chairwoman|vice-chairman|vice-chairmen|vice-chairwoman|vice-chairwomen)\b", "", blob, flags=re.I)
    blob = re.sub(r",\s*(rapporteur|draftsman)\b", "", blob, flags=re.I)
    blob = re.sub(r"\s+and\s+rapporteur\b", "", blob, flags=re.I)
    blob = re.sub(r"\s+and\s+draftsman\b", "", blob, flags=re.I)
    blob = re.sub(r"\s+", " ", blob)
    blob = re.sub(r",\s*,", ", ", blob)
    return clean_text(blob)


def count_members_in_blob(blob: str) -> int:
    """
    Count member entries in a cleaned member blob.

    Used as a fallback for old PDFs that say the vote was adopted
    unanimously but do not print explicit + / - / 0 figures.
    """
    blob = clean_member_blob(blob)
    if not blob:
        return 0

    parts = [p.strip() for p in blob.split(",")]
    count = 0
    for part in parts:
        if not part:
            continue
        lower = part.lower()
        if lower.startswith("(for ") or lower.startswith("for "):
            continue
        if lower.startswith("pursuant to rule"):
            continue
        count += 1
    return count


def extract_vote_counts_from_prose(text: str) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    patterns = [
        r"by\s+([A-Za-z0-9]+)\s+votes?\s+to\s+([A-Za-z0-9]+)(?:,?\s+with\s+([A-Za-z0-9]+)\s+abstentions?)?",
        r"by\s+([A-Za-z0-9]+)\s+votes?\s+to\s+([A-Za-z0-9]+)\.",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.I)
        if m:
            pos = safe_int(m.group(1))
            neg = safe_int(m.group(2))
            abs_ = safe_int(m.group(3)) if m.lastindex and m.lastindex >= 3 else None
            return pos, neg, abs_

    if re.search(r"\bunanimously\b", text, flags=re.I):
        members = extract_present_members_from_prose(text)
        member_count = count_members_in_blob(members)
        if member_count > 0:
            return member_count, 0, 0

    return None, None, None


def extract_present_members_from_prose(text: str) -> str:
    patterns = [
        r"The following were present for the vote:\s*(.+?)(?=\s+The opinions? of|\s+The report was tabled|\s+SHORT JUSTIFICATION|\s+Explanatory statement:|\s+I\.|\s+AMENDMENTS|\s+POSITION OF THE COMMISSION|$)",
        r"The following took part in the vote/were present for the vote:\s*(.+?)(?=\s+The opinions? of|\s+SHORT JUSTIFICATION|\s+Explanatory statement:|\s+AMENDMENTS|$)",
        r"The following took part in the vote:\s*(.+?)(?=\s+I\.|\s+Explanatory statement:|\s+AMENDMENTS|$)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.I)
        if m:
            return clean_member_blob(m.group(1))
    return ""


def extract_report_tabled_date(text: str) -> str:
    m = re.search(r"\bThe report was tabled on\s+(.+?)(?:\.|$)", text, flags=re.I)
    if not m:
        return ""
    dates = extract_dates(m.group(1))
    return dates[0] if dates else ""


def extract_rapporteur_and_appointment(text: str) -> Tuple[str, str]:
    patterns = [
        r"appointed\s+(.+?)\s+rapporteur\s+at its meeting of\s+(.+?)(?:\.|$)",
        r"appointed\s+(.+?)\s+draftsman\s+at its meeting of\s+(.+?)(?:\.|$)",
        r"Draftsman:\s*(?:Mr\s+|Mrs\s+|Ms\s+)?(.+?)\s+At its meeting of\s+(.+?)(?:\.|$)",
        r"Rapporteur:\s*(?:Mr\s+|Mrs\s+|Ms\s+)?(.+?)(?=\s+PE\b|\s+-\s+Or\.|\s+PE\s|$)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.I)
        if m:
            name = clean_text(m.group(1))
            date = ""
            if m.lastindex and m.lastindex >= 2:
                dates = extract_dates(m.group(2))
                date = dates[0] if dates else ""
            return name, date
    return "", ""


def extract_discussed_dates_from_prose(text: str) -> List[str]:
    patterns = [
        r"considered .*? at its meetings of\s+(.+?)(?:\.|$)",
        r"At its meetings of\s+(.+?)\s+it considered",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.I)
        if m:
            return extract_dates(m.group(1))
    return []


def parse_lead_procedural_page(
    procedure: str,
    committee: str,
    text: str,
    title: str,
    refs: List[str],
) -> Tuple[List[Dict[str, str]], Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    opinion_date_map: Dict[str, str] = {}

    if title:
        add_row(rows, procedure, committee, "lead", "Title", title)
    for ref in refs:
        add_row(rows, procedure, committee, "lead", "References", ref)

    m = re.search(r"\bBy letter of\s+(.+?)\s+the Commission submitted to Parliament", text, flags=re.I)
    if m:
        for d in extract_dates(m.group(1)):
            add_row(rows, procedure, committee, "lead", "Date submitted to Parliament", d)

    m = re.search(
        r"At the sitting of\s+(.+?)\s+the President of Parliament announced .*? referred this proposal to\s+(.+?)\s+as the committee responsible(?:\s+and\s+(.+?)\s+for their opinions)?",
        text,
        flags=re.I,
    )
    if m:
        announce_dates = extract_dates(m.group(1))
        announce_date = announce_dates[0] if announce_dates else ""
        committee_responsible = clean_text(re.sub(r"^the\s+", "", m.group(2), flags=re.I))
        add_row(rows, procedure, committee, "lead", "Committee responsible", committee_responsible)
        if announce_date:
            add_row(rows, procedure, committee, "lead", "Date announced in plenary", announce_date)
        for opinion_committee in extract_committee_list(clean_text(m.group(3))):
            add_row(rows, procedure, committee, "lead", "Committees asked for opinions", opinion_committee)
            if announce_date:
                add_row(rows, procedure, committee, "lead", "Date announced in plenary", announce_date)
                opinion_date_map[opinion_committee] = announce_date

    rapporteur, appointed = extract_rapporteur_and_appointment(text)
    if rapporteur:
        add_row(rows, procedure, committee, "lead", "Rapporteur", rapporteur)
    if appointed:
        add_row(rows, procedure, committee, "lead", "Date appointed", appointed)

    for d in extract_discussed_dates_from_prose(text):
        add_row(rows, procedure, committee, "lead", "Discussed in committee", d)

    pos, neg, abs_ = extract_vote_counts_from_prose(text)
    if pos is not None:
        add_row(rows, procedure, committee, "lead", "Result of final vote +", str(pos))
    if neg is not None:
        add_row(rows, procedure, committee, "lead", "Result of final vote –", str(neg))
    if abs_ is not None:
        add_row(rows, procedure, committee, "lead", "Result of final vote 0", str(abs_))

    members = extract_present_members_from_prose(text)
    if members:
        add_row(rows, procedure, committee, "lead", "Members present for the final vote", members)

    m = re.search(r"(Committee on .*?)\s+decided on\s+(.+?)\s+not to deliver an opinion", text, flags=re.I)
    if m:
        add_row(rows, procedure, committee, "lead", "Not delivering opinions", clean_text(m.group(1)))
        dates = extract_dates(m.group(2))
        if dates:
            add_row(rows, procedure, committee, "lead", "Date of decision", dates[0])

    tabled = extract_report_tabled_date(text)
    if tabled:
        add_row(rows, procedure, committee, "lead", "Date tabled", tabled)

    return rows, opinion_date_map


def parse_opinion_prose_block(
    procedure: str,
    committee: str,
    lead_committee: str,
    block: str,
    title: str,
    refs: List[str],
    opinion_announce_date: str = "",
) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []

    if title:
        add_row(rows, procedure, committee, "opinion", "Title", title)
    for ref in refs:
        add_row(rows, procedure, committee, "opinion", "References", ref)

    if lead_committee:
        add_row(rows, procedure, committee, "opinion", "Committee responsible", lead_committee)
    if opinion_announce_date:
        add_row(rows, procedure, committee, "opinion", "Date announced in plenary", opinion_announce_date)

    add_row(rows, procedure, committee, "opinion", "Opinion by", committee)
    if opinion_announce_date:
        add_row(rows, procedure, committee, "opinion", "Date announced in plenary", opinion_announce_date)

    rapporteur, appointed = extract_rapporteur_and_appointment(block)
    if rapporteur:
        add_row(rows, procedure, committee, "opinion", "Rapporteur for the opinion", rapporteur)
    if appointed:
        add_row(rows, procedure, committee, "opinion", "Date appointed", appointed)

    for d in extract_discussed_dates_from_prose(block):
        add_row(rows, procedure, committee, "opinion", "Discussed in committee", d)

    pos, neg, abs_ = extract_vote_counts_from_prose(block)
    if pos is not None:
        add_row(rows, procedure, committee, "opinion", "Result of final vote +", str(pos))
    if neg is not None:
        add_row(rows, procedure, committee, "opinion", "Result of final vote –", str(neg))
    if abs_ is not None:
        add_row(rows, procedure, committee, "opinion", "Result of final vote 0", str(abs_))

    members = extract_present_members_from_prose(block)
    if members:
        add_row(rows, procedure, committee, "opinion", "Members present for the final vote", members)

    return rows


# ---------------------------------------------------------------------------
# public interface
# ---------------------------------------------------------------------------
def parse_other_format_procedure_text(procedure: str, reference: str, extracted_text: str) -> List[Dict[str, str]]:
    if pd.isna(extracted_text) or not clean_text(extracted_text):
        return []

    text = normalise_procedure_text(extracted_text)
    title, refs = extract_global_title_and_references(text, procedure)

    rows: List[Dict[str, str]] = []
    lead_committee = ""
    opinion_date_map: Dict[str, str] = {}

    lead_block = extract_lead_procedural_block(text)
    if lead_block:
        m = re.search(r"referred this proposal to\s+(.+?)\s+as the committee responsible", lead_block, flags=re.I)
        if m:
            lead_committee = clean_text(re.sub(r"^the\s+", "", m.group(1), flags=re.I))
        if not lead_committee:
            lead_committee = extract_cover_lead_committee(text)
        if lead_committee:
            lead_rows, opinion_date_map = parse_lead_procedural_page(procedure, lead_committee, lead_block, title, refs)
            rows.extend(lead_rows)

    opinion_sections = extract_opinion_sections(text)
    for section in opinion_sections:
        opinion_committee = section["committee"]
        section_lead_committee = section.get("lead_committee") or lead_committee
        block = section["text"]

        modern_rows = parse_modern_procedure_block(
            block=block,
            procedure=procedure,
            committee=opinion_committee,
            designation="opinion",
            fallback_title=title,
            fallback_refs=refs,
            lead_committee_name=section_lead_committee,
        )
        if modern_rows:
            rows.extend(modern_rows)
            continue

        rows.extend(
            parse_opinion_prose_block(
                procedure=procedure,
                committee=opinion_committee,
                lead_committee=section_lead_committee,
                block=block,
                title=title,
                refs=refs,
                opinion_announce_date=opinion_date_map.get(opinion_committee, ""),
            )
        )

    if lead_committee:
        rows.extend(
            parse_modern_procedure_block(
                block=text,
                procedure=procedure,
                committee=lead_committee,
                designation="lead",
                fallback_title=title,
                fallback_refs=refs,
                lead_committee_name="",
            )
        )

    return rows


def expand_other_format_committee_procedure(df: pd.DataFrame) -> pd.DataFrame:
    all_rows: List[Dict[str, str]] = []
    for _, row in df.iterrows():
        all_rows.extend(
            parse_other_format_procedure_text(
                procedure=row.get("procedure", ""),
                reference=row.get("reference", ""),
                extracted_text=row.get("extracted_text", ""),
            )
        )

    out = pd.DataFrame(all_rows, columns=["procedure", "committee", "designation", "head", "value"])
    if out.empty:
        return out
    return out.drop_duplicates().reset_index(drop=True)
