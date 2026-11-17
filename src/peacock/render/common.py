"""Préparation commune des vues : arbre d'instances, états par test, arêtes filtrées, palette."""
from __future__ import annotations

from dataclasses import dataclass

from ..resolve.uvm_kb import ROLE_COLORS

ROLE_ORDER = ["test", "env", "reg_block", "agent", "virtual_sequencer", "sequencer", "driver", "monitor",
              "ref_model", "predictor", "scoreboard", "subscriber", "fifo", "component"]
DEFAULT_LAYERS = ("tlm", "seq", "vif")
ALL_LAYERS = ("tlm", "seq", "vif", "cfg", "handle")
INACTIVE = {"fill": "#f0f0f0", "stroke": "#bdbdbd", "font": "#9e9e9e"}
COND_STROKE = "#d35400"
PROTO_COLOR = {
    "analysis": "#2471a3",
    "seq_item": "#ca6f1e",
    "handle": "#7d3c98",
    "vif": "#8e44ad",
    "seq": "#27ae60",
    "cfg": "#16a085",
    "get_peek": "#2980b9",
}


STIM_ID = "stim:test"


def color_of(role: str) -> str:
    return ROLE_COLORS.get(role, "#ececec")


def safe(s: str) -> str:
    return s.replace('"', "'").replace("\\", "/")


@dataclass
class Edge:
    src: str
    dst: str
    label: str
    protocol: str
    active: bool
    conditional: bool
    kind: str = "flow"


class View:
    """Une vue de l'environnement : test=None -> schéma de référence (surensemble)."""

    def __init__(self, arch: dict, test: str | None = None, hide_inactive: bool = False, raw: bool = False,
                 layers=DEFAULT_LAYERS):
        self.layers = None if layers is None else tuple(layers)
        self.arch, self.env, self.test = arch, arch["environment"], test
        self.hide, self.raw = hide_inactive, raw
        self.by_id = {i["id"]: i for i in self.env["instances"]}
        self.kids: dict[str, list[str]] = {}
        for i in self.env["instances"]:
            if i["parent"]:
                self.kids.setdefault(i["parent"], []).append(i["id"])
        self.visible = {i["id"] for i in self.env["instances"] if self._vis(i)}

    # ----- états
    def active(self, inst: dict) -> bool:
        if self.test is None:
            return True
        return inst["states"][self.test]["active"]

    def _vis(self, inst) -> bool:
        if self.test is not None and not inst["states"][self.test]["present"] and self.hide:
            return False
        return not (self.hide and self.test is not None and not self.active(inst))

    def effective(self, inst: dict) -> str:
        if self.test is not None:
            e = inst["states"][self.test]["effective_type"]
            if e:
                return e
        return inst["declared_type"] if inst["id"] != self.env["root"] else "uvm_test"

    def label(self, inst: dict) -> str:
        if inst["id"] == self.env["root"]:
            return f"uvm_test_top : {self.test}" if self.test else "uvm_test_top"
        eff = self.effective(inst)
        decl = inst["declared_type"]
        t = eff
        if self.test is not None and inst["states"][self.test]["overridden"]:
            t = f"{eff} (override)"
        elif self.test is None and inst["overridden_in"]:
            t = f"{decl} (override*)"
        arr = " ×N" if (inst.get("array") or {}).get("unresolved") else ""
        return f"{inst['name']}{arr} : {t}"

    def role_color(self, inst) -> str:
        return color_of(inst["role"])

    def children(self, iid: str) -> list[str]:
        return [k for k in self.kids.get(iid, []) if k in self.visible]

    def roots(self) -> list[str]:
        return [self.env["root"]]

    def ordered_children(self, iid):
        ks = self.children(iid)
        return sorted(ks, key=lambda k: (ROLE_ORDER.index(self.by_id[k]["role"]) if self.by_id[k]["role"] in ROLE_ORDER
                                          else 99))

    def style_of(self, inst: dict) -> dict:
        """Style d'un nœud : active / conditional / inactive."""
        if self.test is not None and not self.active(inst):
            return {"kind": "inactive", **INACTIVE}
        return {"kind": "conditional" if (self.test is None and inst["conditional"]) else "normal",
                "fill": self.role_color(inst), "stroke": COND_STROKE if (self.test is None and inst["conditional"]) else "#555555",
                "font": "#000000"}

    # ----- arêtes
    def _is_anc(self, x: str, y: str) -> bool:
        cur = (self.by_id.get(y) or {}).get("parent")
        while cur:
            if cur == x:
                return True
            cur = (self.by_id.get(cur) or {}).get("parent")
        return False

    def relation_edges(self) -> list[Edge]:
        """Arêtes typées (tlm/seq/vif/cfg/handle) issues de `environment.relations`, avec les mêmes règles que le viewer HTML."""
        root = self.env["root"]
        harness = {h["id"] for h in self.env.get("harness_nodes", [])}
        out: list[Edge] = []
        seen = set()
        for r in self.env["relations"]:
            if r["kind"] not in self.layers:
                continue
            s, d = r["src"]["inst"], r["dst"]["inst"]
            if (s not in self.visible and s not in harness) or (d not in self.visible and d not in harness):
                continue
            act = r["states"][self.test] if self.test else True
            if self.hide and self.test and not act:
                continue
            if s == root and self.children(root):
                s = STIM_ID                                 # le test devient un bloc explicite
            if s == d or self._is_anc(s, d) or self._is_anc(d, s):
                continue
            if r["kind"] == "vif" and d in self.visible and self.children(d):
                continue
            key = (s, d, r["label"], r["kind"])
            if key in seen:
                continue
            seen.add(key)
            proto = r["protocol"] if r["protocol"] in PROTO_COLOR else r["kind"]
            out.append(Edge(s, d, r["label"] or "", proto, act, self.test is None and not all(r["states"].values()), r["kind"]))
        return out

    def extra_nodes(self) -> list[dict]:
        """Nœuds hors hiérarchie UVM : bloc test et harness (interfaces / DUT), uniquement s'ils sont reliés."""
        if self.layers is None or "relations" not in self.env:
            return []
        used = {x for e in self.edges() for x in (e.src, e.dst)}
        nodes = []
        if STIM_ID in used:
            nodes.append({"id": STIM_ID, "label": f"test : {self.test or '(tous tests)'}", "fill": color_of("test"), "stroke": "#6c3483"})
        for h in self.env.get("harness_nodes", []):
            if h["id"] in used:
                dut = h["kind"] == "dut"
                nodes.append({"id": h["id"], "label": f"{h['name']} : {h['type']}", "fill": "#d1c4e9" if dut else "#e0f2f1",
                              "stroke": "#512da8" if dut else "#00796b"})
        return nodes

    def edges(self) -> list[Edge]:
        if self.layers is not None and "relations" in self.env:
            return self.relation_edges()
        out: list[Edge] = []
        conns = self.env["connections"] if self.raw else self.env["flat_connections"]
        for c in conns:
            s, d = (c["src"] if self.raw else c["from"]), (c["dst"] if self.raw else c["to"])
            if s["inst"] not in self.visible or d["inst"] not in self.visible:
                continue
            act = c["states"][self.test] if self.test else True
            if self.hide and self.test and not act:
                continue
            cond = self.test is None and not all(c["states"].values())
            lab = c["txn"] or c["protocol"]
            out.append(Edge(s["inst"], d["inst"], lab or "", c["protocol"], act, cond))
        for l in self.env["handle_links"]:
            if l["owner"] not in self.visible or l["target"] not in self.visible:
                continue
            act = l["states"][self.test] if self.test else True
            if self.hide and self.test and not act:
                continue
            out.append(Edge(l["owner"], l["target"], l["handle"], "handle", act,
                            self.test is None and not all(l["states"].values()), "handle"))
        return out

    def edge_color(self, e: Edge) -> str:
        return "#bdbdbd" if (self.test and not e.active) else PROTO_COLOR.get(e.protocol, "#555555")

    # ----- noms de fichiers
    @property
    def tag(self) -> str:
        return self.test or "all"
