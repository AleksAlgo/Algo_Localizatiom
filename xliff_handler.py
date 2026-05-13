"""
XLIFF 1.2 and 2.0 parser/assembler for Jerome 1.0.
Produces Segment-compatible dicts for translator.py.
"""
from __future__ import annotations
from pathlib import Path
from lxml import etree

# Namespaces
_NS12 = "urn:oasis:names:tc:xliff:document:1.2"
_NS20 = "urn:oasis:names:tc:xliff:document:2.0"


def _detect_version(root) -> str:
    ns = root.nsmap.get(None, "")
    if _NS20 in ns or root.get("version", "") == "2.0":
        return "2.0"
    return "1.2"


def extract(path: Path) -> list[dict]:
    tree = etree.parse(str(path))
    root = tree.getroot()
    ver = _detect_version(root)
    if ver == "2.0":
        return _extract_20(root)
    return _extract_12(root)


def _extract_12(root) -> list[dict]:
    ns = {"x": _NS12}
    segs = []
    seen: dict[str, int] = {}
    for tu in root.findall(".//x:trans-unit", ns):
        tid = tu.get("id", "")
        src_el = tu.find("x:source", ns)
        src = "".join(src_el.itertext()) if src_el is not None else ""
        note_el = tu.find("x:note", ns)
        ctx = {"note": note_el.text.strip()} if note_el is not None and note_el.text else {}
        # make ID unique if duplicated
        if tid in seen:
            seen[tid] += 1
            uid = f"{tid}__{seen[tid]}"
        else:
            seen[tid] = 0
            uid = tid
        segs.append({"id": uid, "text": src, "ctx": ctx})
    return segs


def _extract_20(root) -> list[dict]:
    ns = {"x": _NS20}
    segs = []
    seen: dict[str, int] = {}
    for unit in root.findall(".//x:unit", ns):
        uid = unit.get("id", "")
        for seg in unit.findall(".//x:segment", ns):
            sid = seg.get("id", uid)
            src_el = seg.find("x:source", ns)
            src = "".join(src_el.itertext()) if src_el is not None else ""
            if sid in seen:
                seen[sid] += 1
                uid_seg = f"{sid}__{seen[sid]}"
            else:
                seen[sid] = 0
                uid_seg = sid
            segs.append({"id": uid_seg, "text": src, "ctx": {}})
    return segs


def write(original_path: Path, translations: dict[str, str], out_path: Path) -> None:
    tree = etree.parse(str(original_path))
    root = tree.getroot()
    ver = _detect_version(root)
    if ver == "2.0":
        _write_20(root, translations)
    else:
        _write_12(root, translations)
    tree.write(str(out_path), xml_declaration=True, encoding="UTF-8", pretty_print=True)


def _write_12(root, translations: dict[str, str]) -> None:
    ns = {"x": _NS12}
    seen: dict[str, int] = {}
    for tu in root.findall(".//x:trans-unit", ns):
        tid = tu.get("id", "")
        if tid in seen:
            seen[tid] += 1
            uid = f"{tid}__{seen[tid]}"
        else:
            seen[tid] = 0
            uid = tid
        text = translations.get(uid) or translations.get(tid)
        if text is None:
            continue
        tgt_el = tu.find("x:target", ns)
        if tgt_el is None:
            tgt_el = etree.SubElement(tu, f"{{{_NS12}}}target")
        tgt_el.text = text
        tgt_el.set("state", "translated")


def _write_20(root, translations: dict[str, str]) -> None:
    ns = {"x": _NS20}
    seen: dict[str, int] = {}
    for unit in root.findall(".//x:unit", ns):
        uid = unit.get("id", "")
        for seg in unit.findall(".//x:segment", ns):
            sid = seg.get("id", uid)
            if sid in seen:
                seen[sid] += 1
                uid_seg = f"{sid}__{seen[sid]}"
            else:
                seen[sid] = 0
                uid_seg = sid
            text = translations.get(uid_seg) or translations.get(sid)
            if text is None:
                continue
            tgt_el = seg.find("x:target", ns)
            if tgt_el is None:
                tgt_el = etree.SubElement(seg, f"{{{_NS20}}}target")
            tgt_el.text = text
            seg.set("state", "translated")
