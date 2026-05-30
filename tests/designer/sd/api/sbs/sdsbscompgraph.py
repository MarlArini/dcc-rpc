"""AI-generated (Claude Opus 4.7): fake `sd.api.sbs.sdsbscompgraph`.

SDSBSCompGraph is the compositing-graph subclass of SDGraph. The plugin
checks `isinstance(graph, SDSBSCompGraph)` to decide whether to query the
graph's default parent size (which only exists on comp graphs).
"""
from __future__ import annotations


class SDSBSCompGraph:
    """Stand-in. make_graph(is_comp_graph=True) returns an instance of this
    so isinstance() checks pass."""

    def __init__(self):
        self._package = None
        self._nodes = None
        self._output_nodes = None
        self._annotations: dict = {}
        self._input_properties: dict = {}
        self._default_parent_size = None
        self._is_comp_graph = True

    def getPackage(self):  # noqa: N802
        return self._package

    def getNodes(self):  # noqa: N802
        return self._nodes

    def getOutputNodes(self):  # noqa: N802
        return self._output_nodes

    def getAnnotationPropertyValueFromId(self, identifier: str):  # noqa: N802
        return self._annotations.get(identifier)

    def getInputPropertyValueFromId(self, identifier: str):  # noqa: N802
        return self._input_properties.get(identifier)

    def getDefaultParentSize(self):  # noqa: N802
        if self._default_parent_size is None:
            from .. import sdbasetypes
            return sdbasetypes.int2(2048, 2048)
        return self._default_parent_size
