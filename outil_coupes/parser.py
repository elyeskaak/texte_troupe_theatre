"""
Parser de textes de théâtre (docx/pdf/txt) -> liste de blocs classifiés.

Chaque bloc : {
    "text": str,
    "bold": bool,          # majorité du texte en gras (docx) / police Bold (pdf)
    "italic": bool,
    "kind": "act" | "scene" | "speaker" | "stage_direction" | "dialogue" | "unknown"
    "speaker_name": str or None   # rempli si kind == "speaker"
    "scene_chars": list[str] or None  # rempli si kind == "scene" et personnages listés en tête
}
"""
import re
import sys

ACT_RE = re.compile(r'^\s*(ACTE|Acte)\s+([IVXLCDM]+|\d+)', re.UNICODE)
SCENE_RE = re.compile(r'^\s*(SC[ÈE]NE|Sc[èe]ne)\s+([IVXLCDM]+|\d+)\s*[\.\-–—:]?\s*(.*)$', re.UNICODE)

# Un tag de personnage : 1 à 4 mots, essentiellement en majuscules, pas de verbe/ponctuation de phrase
SPEAKER_CANDIDATE_RE = re.compile(r"^[A-ZÀÂÄÉÈÊËÎÏÔÖÙÛÜÇ][A-ZÀÂÄÉÈÊËÎÏÔÖÙÛÜÇ0-9'\-\s\.]{0,45}$")

STAGE_DIRECTION_HINTS = re.compile(
    r'\b(entre|entrent|sort|sortent|sortant|entrant|à part|bas|haut|seul|seule|ensemble)\b',
    re.IGNORECASE
)


def normalize_name(name: str) -> str:
    name = name.strip().rstrip('.').strip()
    name = re.sub(r'\s+', ' ', name)
    return name.upper()


def looks_like_speaker_tag(line: str, bold: bool, italic: bool) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 45:
        return False
    if ACT_RE.match(stripped) or SCENE_RE.match(stripped):
        return False
    # doit être majoritairement en majuscules (au moins 60% des lettres)
    letters = [c for c in stripped if c.isalpha()]
    if not letters:
        return False
    upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
    if upper_ratio < 0.8:
        return False
    if not SPEAKER_CANDIDATE_RE.match(stripped):
        return False
    word_count = len(stripped.split())
    if word_count > 4:
        return False
    # une didascalie en majuscules type "(ILS SORTENT)" ne doit pas être prise pour un nom
    if stripped.startswith('(') or stripped.endswith(')'):
        return False
    return True


def looks_like_stage_direction(line: str, italic: bool) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith('(') and stripped.endswith(')'):
        return True
    if italic and len(stripped.split()) <= 25:
        return True
    return False


def classify_line(text, bold, italic):
    stripped = text.strip()
    if not stripped:
        return None

    m_act = ACT_RE.match(stripped)
    if m_act:
        return {"text": stripped, "bold": bold, "italic": italic, "kind": "act",
                "speaker_name": None, "scene_chars": None}

    m_scene = SCENE_RE.match(stripped)
    if m_scene:
        remainder = m_scene.group(3).strip(' .-–—')
        scene_chars = None
        if remainder:
            # ex: "ALCESTE, PHILINTE" ou "Alceste, Philinte"
            parts = re.split(r'[,;]| et ', remainder)
            candidates = [normalize_name(p) for p in parts if p.strip()]
            # ne garder que si ça ressemble vraiment à une liste de noms courts
            if candidates and all(len(c.split()) <= 4 and len(c) <= 30 for c in candidates):
                scene_chars = candidates
        return {"text": stripped, "bold": bold, "italic": italic, "kind": "scene",
                "speaker_name": None, "scene_chars": scene_chars}

    if looks_like_speaker_tag(stripped, bold, italic):
        return {"text": stripped, "bold": bold, "italic": italic, "kind": "speaker",
                "speaker_name": normalize_name(stripped), "scene_chars": None}

    if looks_like_stage_direction(stripped, italic):
        return {"text": stripped, "bold": bold, "italic": italic, "kind": "stage_direction",
                "speaker_name": None, "scene_chars": None}

    return {"text": stripped, "bold": bold, "italic": italic, "kind": "dialogue",
            "speaker_name": None, "scene_chars": None}


def extract_docx_blocks(path):
    from docx import Document
    doc = Document(path)
    blocks = []
    for para in doc.paragraphs:
        text = para.text
        if not text.strip():
            continue
        runs = para.runs
        if runs:
            bold_chars = sum(len(r.text) for r in runs if r.bold)
            italic_chars = sum(len(r.text) for r in runs if r.italic)
            total_chars = sum(len(r.text) for r in runs) or 1
            bold = bold_chars / total_chars > 0.6
            italic = italic_chars / total_chars > 0.6
        else:
            bold = False
            italic = False
        block = classify_line(text, bold, italic)
        if block:
            blocks.append(block)
    return blocks


def extract_pdf_blocks(path):
    import pdfplumber
    blocks = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            words = page.extract_words(extra_attrs=["fontname"])
            # regrouper approximativement par ligne (top proche)
            lines = {}
            for w in words:
                key = round(w['top'])
                lines.setdefault(key, []).append(w)
            for key in sorted(lines.keys()):
                line_words = sorted(lines[key], key=lambda w: w['x0'])
                text = ' '.join(w['text'] for w in line_words)
                fontnames = [w.get('fontname', '') for w in line_words]
                bold = any('Bold' in f for f in fontnames) and \
                       sum('Bold' in f for f in fontnames) / max(len(fontnames), 1) > 0.6
                italic = any(('Italic' in f or 'Oblique' in f) for f in fontnames) and \
                         sum(('Italic' in f or 'Oblique' in f) for f in fontnames) / max(len(fontnames), 1) > 0.6
                block = classify_line(text, bold, italic)
                if block:
                    blocks.append(block)
    return blocks


def extract_txt_blocks(path):
    blocks = []
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            block = classify_line(line, bold=False, italic=False)
            if block:
                blocks.append(block)
    return blocks


def extract_blocks(path):
    if path.lower().endswith('.docx'):
        return extract_docx_blocks(path)
    elif path.lower().endswith('.pdf'):
        return extract_pdf_blocks(path)
    else:
        return extract_txt_blocks(path)


if __name__ == '__main__':
    blocks = extract_blocks(sys.argv[1])
    for b in blocks[:80]:
        print(b['kind'], '|', b.get('speaker_name') or '', '|', b['text'][:60])
