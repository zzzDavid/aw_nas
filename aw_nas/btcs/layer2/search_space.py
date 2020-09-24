"""
A 2-layer search space, with one macro and micro search space implementaion.
Macro: Stagewise densely-connected macro search space.
Micro: Possibly densely-connected micro search space.
"""

import os
import re
import copy
import random
import collections
from collections import namedtuple

import numpy as np

from aw_nas.common import SearchSpace, genotype_from_str
from aw_nas.rollout.base import BaseRollout
from aw_nas.utils.exception import expect, ConfigException

class Layer2Rollout(BaseRollout):
    NAME = "layer2"
    supported_components = [("trainer", "simple"), ("evaluator", "mepa")]

    def __init__(self, macro_rollout, micro_rollout, search_space, candidate_net=None):
        super(Layer2Rollout, self).__init__()

        self.macro = macro_rollout
        self.micro = micro_rollout
        self.search_space = search_space
        self.candidate_net = candidate_net
        self._perf = collections.OrderedDict()
        self._genotype = None

    def set_candidate_net(self, c_net):
        self.candidate_net = c_net

    @property
    def genotype(self):
        if self._genotype is None:
            self._genotype = self.search_space.genotype((self.macro, self.micro))
        return self._genotype

    def plot_arch(self, filename, label="", edge_labels=None, plot_format="pdf"):
        return self.search_space.plot_arch(self.genotype, filename=filename, label=label,
                                           edge_labels=edge_labels, plot_format=plot_format)

    def __eq__(self, other):
        return self.macro == other.macro and self.micro == other.micro


class Layer2SearchSpace(SearchSpace):
    """
    A 2-layer container search space.

    * 1st layer: Macro search space
          **Configs**:
          * cell layout
          **Search space**:
          * possible connections between cell nodes in each stage
           (assume no skip connections between stages)

    * 2st layer: Micro search space
          **Configs**:
          * how many nodes
          * concat/add at output node, if concat, need a 1x1 conv to align the width
          **Search space**:
          * connection between nodes (similar with NAS-Bench-201 and RobNAS)
          * op on each connection (support multiple op on one connection)
          * TODO: op width
          **Restriction**:
          1 input node, 1 output node; this is for the ease of macro connection search
          if allow multiple input nodes, the macro search space will be enlarged a lot,
          and we currently do not consider that.
    """
    NAME = "layer2"

    def __init__(self,
                 macro_search_space_type="macro-stagewise",
                 macro_search_space_cfg={},
                 micro_search_space_type="micro-dense",
                 micro_search_space_cfg={},
                 schedule_cfg=None
    ):
        super(Layer2SearchSpace, self).__init__(schedule_cfg)
        self.macro_search_space = SearchSpace.get_class_(macro_search_space_type)(
            **macro_search_space_cfg)
        self.micro_search_space = SearchSpace.get_class_(micro_search_space_type)(
            **micro_search_space_cfg)
        expect(self.macro_search_space.num_cell_groups == self.micro_search_space.num_cell_groups,
               "Macro/Micro search space expect the same cell group configuration, "
               "get {}/{} instead.".format(self.macro_search_space.num_cell_groups,
                                           self.micro_search_space.num_cell_groups),
               ConfigException)

    def random_sample(self):
        macro_r = self.macro_search_space.random_sample()
        micro_r = self.micro_search_space.random_sample()
        return Layer2Rollout(macro_r, micro_r, self)

    def genotype(self, arch):
        """Convert arch (controller representation) to genotype (semantic representation)"""
        macro_r, micro_r = arch
        return (macro_r.genotype, micro_r.genotype)

    def rollout_from_genotype(self, genotype):
        """Convert genotype (semantic representation) to arch (controller representation)"""
        macro_g, micro_g = genotype
        macro_g = self.macro_search_space.rollout_from_genotype(macro_g)
        micro_g = self.micro_search_space.rollout_from_genotype(micro_g)
        return Layer2Rollout(macro_g, micro_g, self)

    def plot_arch(self, genotypes, filename, label, **kwargs):
        macro_g, micro_g = genotypes
        fnames = []
        fnames += self.macro_search_space.plot_arch(
            macro_g, os.path.join(filename, "macro"), label, **kwargs)
        fnames += self.micro_search_space.plot_arch(
            micro_g, os.path.join(filename, "micro"), label, **kwargs)
        return fnames

    def distance(self, arch1, arch2):
        raise NotImplementedError()

    @classmethod
    def supported_rollout_types(cls):
        return ["layer2"]

    def mutate(self, rollout, **mutate_kwargs):
        mutate_macro_prob = mutate_kwargs.get("mutate_macro_prob", 0.2)
        new_rollout = copy.deepcopy(rollout)
        if np.random.random() < mutate_macro_prob:
            # mutate in macro search space
            new_rollout.macro = self.macro_search_space.mutate(new_rollout.macro)
        else:
            # mutate in micro search space
            new_rollout.micro = self.micro_search_space.mutate(new_rollout.micro)
        return new_rollout

    def genotype_from_str(self, genotype_str):
        match = re.search(r"\((.+Genotype\(.+\)), (.+Genotype\(.+\))\)", genotype_str)
        macro_genotype_str = match.group(1)
        micro_genotype_str = match.group(2)
        return (genotype_from_str(macro_genotype_str, self.macro_search_space),
                genotype_from_str(micro_genotype_str, self.micro_search_space))

def DFS(v, adj, visited):
    visited[v] = 1
    for new_v in np.argwhere(adj[:,v].reshape(-1)):
        if not visited[new_v]:
            DFS(new_v, adj, visited)
    return visited

class StagewiseMacroRollout(BaseRollout):
    NAME = "macro-stagewise"

    def __init__(self, arch, search_space):
        super(StagewiseMacroRollout, self).__init__()

        self.arch = arch
        self.search_space = search_space
        self.perf = collections.OrderedDict
        self._genotype = None

    def set_candidate_net(self, c_net):
        # should not corresponding to a candidate net
        raise Exception("A macro rollout only should not correpond to a candidate net")

    @property
    def genotype(self):
        if self._genotype is None:
            self._genotype = self.search_space.genotype(self.arch)
        return self._genotype

    def plot_arch(self, filename, label="", edge_labels=None, plot_format="pdf"):
        return self.search_space.plot_arch(self.genotype, filename, label=label,
                                           edge_labels=edge_labels, plot_format=plot_format)

    def __eq__(self, other):
        return all((self.arch[i] == other.arch[i]).all() for i in range(len(self.arch)))

    def ck_connect(self, verbose=False):
        all_connected = np.array([(DFS(0,arch,np.zeros(arch.shape[0]))).all() \
             for arch in self.arch])
        connected = np.array([(DFS(0,arch,np.zeros(arch.shape[0])))[-1] \
             for arch in self.arch])
        if not verbose:
            return connected.all()
        else:
            return connected, all_connected

class StagewiseMacroSearchSpace(SearchSpace):
    NAME = "macro-stagewise"

    def __init__(self,
                 num_cell_groups=2,
                 cell_layout=None,
                 reduce_cell_groups=None,
                 schedule_cfg=None
    ):
        super(StagewiseMacroSearchSpace, self).__init__(schedule_cfg)

        # configuration checks
        expect(
            cell_layout is not None,
            "`cell_layout` need to be explicitly specified",
            ConfigException,
        )
        expect(
            np.max(cell_layout) == num_cell_groups - 1,
            "Max of elements of `cell_layout` should equal `num_cell_groups-1`",
            ConfigException
        )
        expect(
            reduce_cell_groups is not None,
            "`reduce_cell_groups` need to be explicitly specified",
            ConfigException,
        )

        self.num_cell_groups = num_cell_groups
        self.cell_layout = cell_layout
        self.reduce_cell_groups = reduce_cell_groups
        self.num_layers = len(cell_layout)

        # parse stages
        reduce_layer_idxes = [i_layer for i_layer, cg in enumerate(cell_layout)
                              if cg in self.reduce_cell_groups]
        _splits = reduce_layer_idxes
        if 0 not in _splits:
            _splits = [-1] + _splits
        if self.num_layers - 1 not in _splits:
            _splits.append(self.num_layers)
        stages_begin = []
        stages_end = []
        for i_stage in range(len(_splits) - 1):
            if _splits[i_stage + 1] == _splits[i_stage] + 1:
                continue
            stages_begin.append(_splits[i_stage])
            stages_end.append(_splits[i_stage + 1])
        self.stages_begin = stages_begin
        self.stages_end = stages_end
        self.stage_num = len(self.stages_begin)
        self.stage_node_nums = [stages_end[i_stage] - stages_begin[i_stage] + 1
                                for i_stage in range(self.stage_num)]
        self.idxes = [np.tril_indices(node_num, k=-1) for node_num in self.stage_node_nums]
        self.num_possible_edges = [len(idx[0]) for idx in self.idxes]

        # genotype
        self.stage_names = ["stage_{}".format(i) for i in range(self.stage_num)]
        self.genotype_type_name = "StagewiseMacroGenotype"
        self.genotype_type = namedtuple(self.genotype_type_name, self.stage_names)

    def random_sample(self):
        stage_conns = []
        for i_stage in range(self.stage_num):
            stage_conn = np.zeros((self.stage_node_nums[i_stage], self.stage_node_nums[i_stage]))
            stage_conn[self.idxes[i_stage]] = \
                        np.random.randint(low=0, high=2, size=self.num_possible_edges[i_stage])
            stage_conns.append(stage_conn)
        return StagewiseMacroRollout(stage_conns, search_space=self)

    def genotype(self, arch):
        stage_strs = []
        for i_stage, stage_arch in enumerate(arch):
            strs = ["num_node~{}".format(self.stage_node_nums[i_stage])]
            for i_node in range(1, self.stage_node_nums[i_stage]):
                strs.append("|" + "|".join([
                    str(i_input)
                    for i_input in range(0, i_node)
                    if stage_arch[i_node, i_input]
                ]) + "|")
            stage_strs.append("+".join(strs))
        return self.genotype_type(**dict(zip(self.stage_names, stage_strs)))

    def rollout_from_genotype(self, genotype):
        stage_strs = list(genotype._asdict().values())
        stage_conns = []
        for stage_str in stage_strs:
            node_strs = stage_str.strip().split("+")
            stage_node_num = int(node_strs[0].split("~")[1])
            conn_idxes = tuple(zip(*[(i_node + 1, int(i_input))
                          for i_node, node_str in enumerate(node_strs[1:])
                                    if node_str.strip("|")
                                    for i_input in node_str.strip("|").split("|")]))
            stage_conn = np.zeros((stage_node_num, stage_node_num))
            if len(conn_idxes):
                stage_conn[conn_idxes] = 1
            stage_conns.append(stage_conn)
        return StagewiseMacroRollout(stage_conns, search_space=self)

    def parse_overall_adj(self, geno_or_rollout):
        """
        node 0: stem output
        node k: cell k - 1. k = 1, ..., num_layer
        node num_layers + 1: avgpooling input
        """
        if isinstance(geno_or_rollout, tuple):
            stage_conns = self.rollout_from_genotype(geno_or_rollout).arch
        elif isinstance(geno_or_rollout, StagewiseMacroRollout):
            stage_conns = geno_or_rollout.arch
        else:
            raise TypeError("We don't do that here")

        last_node_idx = 0
        overall_adj = np.zeros((self.num_layers + 2, self.num_layers + 2))
        for i_stage, stage_conn in enumerate(stage_conns):
            # NOTE: all stages_end/stages_begin indexes should add 1 because we add a stem layer
            while last_node_idx < self.stages_begin[i_stage] + 1:
                # sequential connection
                overall_adj[last_node_idx + 1, last_node_idx] = 1
                last_node_idx += 1
            for to_, from_ in zip(*np.where(stage_conn)):
                overall_adj[self.stages_begin[i_stage] + 1 + to_,
                            self.stages_begin[i_stage] + 1 + from_] = 1
            last_node_idx = self.stages_end[i_stage] + 1
        while last_node_idx < self.num_layers:
            overall_adj[last_node_idx + 1, last_node_idx] = 1
            last_node_idx += 1
        return overall_adj

    def plot_arch(self, genotypes, filename, label, edge_labels=None, plot_format="pdf"):
        from graphviz import Digraph

        graph = Digraph(
            format=plot_format,
            body=['label="{l}"'.format(l=label), "labelloc=top", "labeljust=left"],
            edge_attr=dict(fontsize="20", fontname="times"),
            node_attr=dict(
                style="filled",
                shape="rect",
                align="center",
                fontsize="20",
                height="0.5",
                width="0.5",
                penwidth="2",
                fontname="times",
            ),
            engine="dot",
        )
        graph.body.extend(["rankdir=LR"])

        # cell node
        cell_nodes = ["cell {}\ngroup {}".format(i, self.cell_layout[i])
                      for i in range(0, self.num_layers)]
        cell_nodes = ["stem"] + cell_nodes + ["output"]
        graph.node(cell_nodes[0], fillcolor="darkseagreen2")
        graph.node(cell_nodes[-1], fillcolor="darkseagreen2")
        [graph.node(
            n, fillcolor=("palegoldenrod" \
                          if self.cell_layout[i_layer] in self.reduce_cell_groups else "lightblue"))
         for i_layer, n in enumerate(cell_nodes[1:-1])]

        overall_adj = self.parse_overall_adj(genotypes)
        for to_, from_ in zip(*np.where(overall_adj)):
            graph.edge(cell_nodes[from_], cell_nodes[to_], fillcolor="gray")

        graph.render(filename, view=False)
        return [filename + ".{}".format(plot_format)]

    def distance(self, arch1, arch2):
        raise NotImplementedError()

    @classmethod
    def supported_rollout_types(cls):
        return ["macro-stagewise"]

    def mutate(self, rollout, **mutate_kwargs):
        raise NotImplementedError()


class DenseMicroRollout(BaseRollout):
    NAME = "micro-dense"

    def __init__(self, arch, search_space):
        super(DenseMicroRollout, self).__init__()

        self.arch = arch
        self.search_space = search_space
        self.perf = collections.OrderedDict()
        self._genotype = None  # calc when need

    def set_candidate_net(self, c_net):
        # should not corresponding to a candidate net
        raise Exception("A micro rollout only should not correpond to a candidate net")

    @property
    def genotype(self):
        if self._genotype is None:
            self._genotype = self.search_space.genotype(self.arch)
        return self._genotype

    def plot_arch(self, filename, label="", edge_labels=None, plot_format="pdf"):
        fnames = []
        for i_cell, cell_arch in enumerate(self.arch):
            fname = self.search_space.plot_cell(
                cell_arch,
                os.path.join(filename, "{}".format(i_cell)),
                label="{}cell {}".format(
                    "{} - ".format(label) if label else "", i_cell
                ),
                edge_labels=edge_labels[i_cell] if edge_labels else None,
                plot_format=plot_format,
            )
            fnames.append(("cell{}".format(i_cell), fname))
        return fnames

    def __eq__(self, other):
        return all((self.arch[i] == other.arch[i]).all() for i in range(len(self.arch)))


class DenseMicroSearchSpace(SearchSpace):
    """
    This search space currently does not consider stride, since strided cells that are
    the delimiters of stages are handled mainly in the macro search spaces.
    """
    NAME = "micro-dense"

    def __init__(self,
                 num_cell_groups=2,
                 num_init_nodes=1, # current only `num_init_nodes=1` is supported
                 num_steps=4,
                 primitives=("skip_connect", "sep_conv_3x3"),
                 concat_op="concat",
                 cellwise_cfgs=None, # support num_steps, primitives, concat_op configs?
                 schedule_cfg=None
    ):
        super(DenseMicroSearchSpace, self).__init__(schedule_cfg)

        # configuration checks
        expect(num_init_nodes == 1, "Currently only support `num_init_nodes==1`",
               ConfigException)
        expect("none" not in primitives)
        expect(concat_op in {"concat", "add"})

        self.num_cell_groups = num_cell_groups
        self.num_init_nodes = num_init_nodes
        self.num_steps = num_steps
        self.primitives = primitives
        self.cell_shared_primitives = [primitives]*self.num_cell_groups
        self.concat_op = concat_op
        self.cellwise_cfgs = cellwise_cfgs
        expect(self.cellwise_cfgs is None, "Currently only support the same cfg for each cell")

        # calc some attributes
        self.num_op_choices = len(primitives)
        self._num_nodes = self.num_steps + self.num_init_nodes
        _num_input_conns = self.num_init_nodes * (self.num_init_nodes - 1) // 2
        self.idx = np.tril_indices(self._num_nodes, k=-1)
        self.idx = (self.idx[0][_num_input_conns:], self.idx[1][_num_input_conns:])
        self.num_possible_edges = np.sum(
            self.num_init_nodes + np.arange(self.num_steps)
        )
        assert len(self.idx[0]) == self.num_possible_edges

        # genotype
        self.cell_group_names = ["cell_{}".format(i) for i in range(self.num_cell_groups)]
        self.genotype_type_name = "DenseMicroGenotype"
        self.genotype_type = namedtuple(self.genotype_type_name, self.cell_group_names)

    def _random_sample_cell_arch(self):
        arch = np.zeros((self._num_nodes, self._num_nodes, self.num_op_choices), dtype=int)
        arch[self.idx] = np.random.randint(
            low=0, high=2, size=(self.num_possible_edges, self.num_op_choices)
        ) # 0/1
        return arch

    def _random_sample_arch(self):
        return [self._random_sample_cell_arch() for _ in range(self.num_cell_groups)]

    def __getstate__(self):
        state = super(DenseMicroSearchSpace, self).__getstate__().copy()
        del state["genotype_type"]
        return state

    def __setstate__(self, state):
        super(DenseMicroSearchSpace, self).__setstate__(state)
        self.genotype_type = namedtuple(self.genotype_type_name, self.cell_group_names)

    def plot_cell(
        self, matrix, filename, label="", edge_labels=None, plot_format="pdf"):
        from graphviz import Digraph

        graph = Digraph(
            format=plot_format,
            body=['label="{l}"'.format(l=label), "labelloc=top", "labeljust=left"],
            edge_attr=dict(fontsize="20", fontname="times"),
            node_attr=dict(
                style="filled",
                shape="rect",
                align="center",
                fontsize="20",
                height="0.5",
                width="0.5",
                penwidth="2",
                fontname="times",
            ),
            engine="dot",
        )
        graph.body.extend(["rankdir=LR"])
        final_output_node = "{} ({})".format(self._num_nodes, self.concat_op)
        init_node = self.num_init_nodes
        [graph.node(str(i), fillcolor="darkseagreen2") for i in range(0, init_node)]
        [
            graph.node(str(i), fillcolor="lightblue")
            for i in range(init_node, self._num_nodes)
        ]
        graph.node(final_output_node, fillcolor="palegoldenrod")

        for to_, from_ in zip(*self.idx):
            ops = matrix[to_, from_]
            for op_idx, has_op in enumerate(ops):
                if has_op:
                    op_name = self.primitives[op_idx]
                    graph.edge(str(from_), str(to_), label=op_name, fillcolor="gray")

        # final concat edges
        for node in range(init_node, self._num_nodes):
            graph.edge(str(node), final_output_node, fillolor="gray")

        graph.render(filename, view=False)
        return filename + ".{}".format(plot_format)

    # ---- APIs ----

    def get_num_steps(self, cell_index):
        return self.num_steps if isinstance(self.num_steps, int) else self.num_steps[cell_index]

    def random_sample(self):
        """Random sample an architecture rollout from search space"""
        return DenseMicroRollout(self._random_sample_arch(), search_space=self)

    def genotype(self, arch):
        """
        Convert arch (controller representation) to genotype (semantic representation)
        For each cell, the string representation is "init_node~<init node number>" followed by
        the specifications organized by output node/step (seperated by "+").
        In the specification of each output node/step, all input connections are seperated by "|",
        and the specification of each connection is "<op primitive name>~<input node>".
        """
        cell_strs = []
        for cell_arch in arch:
            node_strs = ["init_node~{}".format(self.num_init_nodes)]
            for i_node in range(self.num_init_nodes, self._num_nodes):
                node_strs.append(
                    "|"
                    + "|".join(
                        [
                            "{}~{}".format(
                                self.primitives[i_op],
                                i_input,
                            )
                            for i_input in range(0, i_node)
                            for i_op, has_op in enumerate(cell_arch[i_node, i_input]) if has_op]
                    )
                    + "|"
                )
            cell_str = "+".join(node_strs)
            cell_strs.append(cell_str)
        return self.genotype_type(**dict(zip(self.cell_group_names, cell_strs)))

    def rollout_from_genotype(self, genotype):
        """Convert genotype (semantic representation) to arch (controller representation)"""
        cell_strs = list(genotype._asdict().values())
        arch = []
        for cell_str in cell_strs:
            node_strs = cell_str.strip().split("+")
            _geno_num_i_nodes = int(node_strs[0].split("~")[1])
            expect(
                _geno_num_i_nodes == self.num_init_nodes,
                (
                    "Search space configuration (`num_init_nodes={}` "
                    "differs from the genotype specification {})"
                ).format(self.num_init_nodes, _geno_num_i_nodes),
            )
            all_conn_ops = [
                [conn_str.split("~") for conn_str in node_str[1:-1].split("|")] \
                if node_str.strip("|") else []
                for node_str in node_strs[1:]
            ]
            all_conn_op_inds = tuple(zip(*[
                (i_node + self.num_init_nodes, int(conn_op[1]), self.primitives.index(conn_op[0]))
                for i_node, step_conn_ops in enumerate(all_conn_ops) for conn_op in step_conn_ops
            ])) # [(output_node, input_node, op_id)]: the index tuples of `arch`
            cell_arch = np.zeros((self._num_nodes, self._num_nodes, self.num_op_choices))
            cell_arch[all_conn_op_inds] = 1
            arch.append(cell_arch)
        return DenseMicroRollout(arch, search_space=self)

    def plot_arch(self, genotypes, filename, label="", edge_labels=None, **kwargs):
        return self.rollout_from_genotype(genotypes).plot_arch(
            filename, label=label, edge_labels=edge_labels, **kwargs
        )

    def distance(self, arch1, arch2):
        raise NotImplementedError()

    def mutate(self, parent):
        child = parent.arch.copy()
        change_cell_idx = random.randint(0, self.num_cell_groups - 1)
        change_node_idx = random.randint(self.num_init_nodes, self._num_nodes - 1)
        change_node_from = random.randint(0, change_node_idx - 1)
        change_op_idx = random.randint(0, self.num_op_choices - 1)
        # flip 0/1: whether this op exists
        child[change_cell_idx][change_node_idx][change_node_from][change_op_idx] = \
                  1 - child[change_cell_idx][change_node_idx][change_node_from][change_op_idx]
        return DenseMicroRollout(child, self)

    @classmethod
    def supported_rollout_types(cls):
        return ["micro-dense"]
