"""Rendu draw.io (mxGraph) : blocs imbriqués éditables, une page par vue (référence + un par test)."""
from __future__ import annotations

import math
from xml.sax.saxutils import escape

from .common import PROTO_COLOR, View, color_of

LEAF_W, LEAF_H, PAD, HEAD, GAP = 170, 46, 14, 30, 16


def _layout(view: View, i: str, pos: dict):
    kids = view.ordered_children(i)
    if not kids:
        pos[i] = {"w": LEAF_W, "h": LEAF_H, "x": 0, "y": 0}
        return
    for k in kids:
        _layout(view, k, pos)
    area = sum((pos[k]["w"] + GAP) * (pos[k]["h"] + GAP) for k in kids)
    max_row = max(max(pos[k]["w"] for k in kids), math.sqrt(area) * 1.5)
    x = y = row_h = 0
    width = 0
    for k in kids:
        w, h = pos[k]["w"], pos[k]["h"]
        if x and x + w > max_row:
            x, y, row_h = 0, y + row_h + GAP, 0
        pos[k]["x"], pos[k]["y"] = x + PAD, y + HEAD + PAD
        x += w + GAP
        row_h = max(row_h, h)
        width = max(width, x - GAP)
    pos[i] = {"w": width + 2 * PAD, "h": y + row_h + HEAD + 2 * PAD, "x": 0, "y": 0}


def page(view: View, base_pos: dict | None = None) -> str:
    pos = base_pos or {}
    if not base_pos:
        _layout(view, view.env["root"], pos)
    cells = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']
    cid: dict[str, str] = {}

    def c(i):
        return cid.setdefault(i, f"c{len(cid) + 2}")

    def emit(i: str, parent: str):
        inst = view.by_id[i]
        st = view.style_of(inst)
        p = pos[i]
        kids = view.ordered_children(i)
        dash = "dashed=1;" if st["kind"] in ("conditional", "inactive") else ""
        style = (f"rounded=1;whiteSpace=wrap;html=1;fillColor={st['fill']};strokeColor={st['stroke']};"
                 f"fontColor={st['font']};{dash}" + ("verticalAlign=top;fontStyle=1;" if kids else ""))
        cells.append(f'<mxCell id="{c(i)}" value="{escape(view.label(inst), {chr(34): "&quot;"})}" style="{style}" vertex="1" parent="{parent}">'
                     f'<mxGeometry x="{p["x"]}" y="{p["y"]}" width="{p["w"]}" height="{p["h"]}" as="geometry"/></mxCell>')
        for k in kids:
            emit(k, c(i))

    root = view.env["root"]
    emit(root, "1")
    # --- blocs explicites : test (émetteur de séquences) et harness (interfaces / DUT)
    test_cell = "ctest"
    tstyle = (f"rounded=1;whiteSpace=wrap;html=1;fillColor={color_of('test')};strokeColor=#6c3483;fontStyle=1;")
    cells.append(f'<mxCell id="{test_cell}" value="{escape("test : " + (view.test or "(tous tests)"))}" style="{tstyle}" '
                 f'vertex="1" parent="1"><mxGeometry x="{-LEAF_W - 90}" y="{-LEAF_H - 40}" width="{LEAF_W}" height="{LEAF_H}" as="geometry"/></mxCell>')
    hcell: dict[str, str] = {}
    for k, h in enumerate(view.env.get("harness_nodes", [])):
        hid = f"h{k}"
        hcell[h["id"]] = hid
        fill, stroke = ("#d1c4e9", "#512da8") if h["kind"] == "dut" else ("#e0f2f1", "#00796b")
        cells.append(f'<mxCell id="{hid}" value="{escape(h["name"] + " : " + str(h["type"]))}" style="rounded=1;whiteSpace=wrap;html=1;'
                     f'fillColor={fill};strokeColor={stroke};" vertex="1" parent="1"><mxGeometry x="{-LEAF_W - 90}" y="{k * (LEAF_H + 20)}" '
                     f'width="{LEAF_W}" height="{LEAF_H}" as="geometry"/></mxCell>')
    # --- calques (un par type de relation) ; config et handles masqués par défaut
    layers = [("tlm", "TLM", 1), ("seq", "Séquences", 1), ("vif", "Harness / VIF", 1), ("cfg", "Config", 0), ("handle", "Handles", 0)]
    lid = {}
    for kind, name, vis in layers:
        lid[kind] = f"layer_{kind}"
        cells.append(f'<mxCell id="{lid[kind]}" value="{name}" parent="0"' + ("" if vis else ' visible="0"') + "/>")

    parents: dict[str, str | None] = {i["id"]: i["parent"] for i in view.env["instances"]}

    def is_anc(x, y):
        cur = parents.get(y)
        while cur:
            if cur == x:
                return True
            cur = parents.get(cur)
        return False

    def endpoint(i):
        if i in hcell:
            return hcell[i]
        if i in view.visible:
            return c(i)
        return None

    seen = set()
    for k, r in enumerate(view.env.get("relations", [])):
        s, d = r["src"]["inst"], r["dst"]["inst"]
        if r["kind"] not in lid:                        # 'hier' = détail de promotion de ports, non tracé
            continue
        if (s not in view.visible and s not in hcell) or (d not in view.visible and d not in hcell):
            continue
        act = r["states"][view.test] if view.test else True
        if view.hide and view.test and not act:
            continue
        if s == root and view.children(root):
            src_cell = test_cell
        else:
            src_cell = endpoint(s)
        dst_cell = endpoint(d)
        if not src_cell or not dst_cell or src_cell == dst_cell:
            continue
        if is_anc(s, d) or is_anc(d, s):
            continue
        if r["kind"] == "vif" and d in view.visible and view.children(d):
            continue
        key = (src_cell, dst_cell, r["label"], r["kind"])
        if key in seen:
            continue
        seen.add(key)
        cond = view.test is None and not all(r["states"].values())
        dash = "dashed=1;" if (r["kind"] in ("handle", "cfg") or cond or (view.test and not act)) else ""
        col = "#bdbdbd" if (view.test and not act) else PROTO_COLOR.get(r["protocol"], PROTO_COLOR.get(r["kind"], "#555555"))
        cells.append(f'<mxCell id="e{k}" value="{escape(r["label"] or "")}" style="edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;'
                     f'strokeColor={col};fontColor={col};{dash}endArrow=block;" edge="1" parent="{lid[r["kind"]]}" '
                     f'source="{src_cell}" target="{dst_cell}"><mxGeometry relative="1" as="geometry"/></mxCell>')
    return "<mxGraphModel><root>" + "".join(cells) + "</root></mxGraphModel>"


def document(arch: dict, hide_inactive: bool = False, raw: bool = False) -> str:
    tests = [None] + arch["environment"]["tests"]
    pos: dict = {}
    ref = View(arch, None, False, raw)
    _layout(ref, ref.env["root"], pos)
    pages = []
    for k, t in enumerate(tests):
        v = View(arch, t, hide_inactive, raw)
        p = pos
        if hide_inactive and t:
            p = {}
            _layout(v, v.env["root"], p)
        name = "Référence (tous tests)" if t is None else t
        pages.append(f'<diagram id="p{k}" name="{escape(name, {chr(34): "&quot;"})}">{page(v, p)}</diagram>')
    return '<?xml version="1.0" encoding="UTF-8"?>\n<mxfile host="peacock">' + "".join(pages) + "</mxfile>\n"
