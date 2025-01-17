"""Unit tests for //experimental/compilers/reachability:control_flow_graph."""
import sys
import typing

import networkx as nx
import pytest
from absl import app
from absl import flags

from experimental.compilers.reachability import control_flow_graph


FLAGS = flags.FLAGS


def test_ControlFlowGraph_IsReachable_reachable():
  """Test reachable node."""
  g = control_flow_graph.ControlFlowGraph()
  g.add_edge(0, 1)
  assert g.IsReachable(0, 1)


def test_ControlFlowGraph_IsReachable_indirectly_reachable():
  """Test indirectly reachable node."""
  g = control_flow_graph.ControlFlowGraph()
  g.add_edge(0, 1)
  g.add_edge(1, 2)
  assert g.IsReachable(0, 2)


def test_ControlFlowGraph_IsReachable_unreachable():
  """Test unreachable node."""
  g = control_flow_graph.ControlFlowGraph()
  g.add_edge(0, 1)
  assert not g.IsReachable(1, 0)


def test_ControlFlowGraph_IsReachable_non_existent_node_raises_error():
  """Test that error is raised if node is not in graph."""
  g = control_flow_graph.ControlFlowGraph()
  with pytest.raises(nx.exception.NetworkXError):
    g.IsReachable(1, 0)


# TODO(cec): Add more tests for IsReachable using common real-world graphs,
# e.g. for loop.


def test_ControlFlowGraph_Reachables_empty_graph():
  """An empty graph has no reachables."""
  g = control_flow_graph.ControlFlowGraph()
  assert list(g.Reachables(0)) == []


def test_ControlFlowGraph_Reachables_simple_graph():
  """An empty graph has no reachables."""
  g = control_flow_graph.ControlFlowGraph()
  # Graph:
  #
  #   A  ->  B  ->  C
  g.add_edge(0, 1)
  g.add_edge(1, 2)
  assert list(g.Reachables(0)) == [False, True, True]
  assert list(g.Reachables(1)) == [False, False, True]
  assert list(g.Reachables(2)) == [False, False, False]


def test_ControlFlowGraph_Reachables_back_edge():
  """Test reachability with a back edge in the graph."""
  g = control_flow_graph.ControlFlowGraph()
  # Graph:
  #
  #   A  ->  B  ->  C
  #   ^      |
  #   +------+
  g.add_edge(0, 1)
  g.add_edge(1, 0)
  g.add_edge(1, 2)
  # FIXME(cec): I don't belive these values.
  assert list(g.Reachables(0)) == [False, True, True]
  assert list(g.Reachables(1)) == [True, False, True]
  assert list(g.Reachables(2)) == [False, False, False]


def test_ControlFlowGraph_validate_empty_graph():
  """Test that empty graph is invalid."""
  g = control_flow_graph.ControlFlowGraph()
  with pytest.raises(control_flow_graph.NotEnoughNodes) as e_ctx:
    g.ValidateControlFlowGraph()
  assert str(e_ctx.value) == "Graph has 0 nodes"
  assert not g.IsValidControlFlowGraph()


def test_ControlFlowGraph_validate_one_node():
  """Test that empty graph is invalid."""
  g = control_flow_graph.ControlFlowGraph()
  g.add_node(0, name='A')
  with pytest.raises(control_flow_graph.NotEnoughNodes) as e_ctx:
    g.ValidateControlFlowGraph()
  assert str(e_ctx.value) == "Graph has 1 nodes"
  assert not g.IsValidControlFlowGraph()


def test_ControlFlowGraph_IsValidControlFlowGraph_disconnected_graph():
  """A disconnected graph is not valid."""
  g = control_flow_graph.ControlFlowGraph()
  g.add_node(0, name='A', entry=True)
  g.add_node(1, name='B', exit=True)
  with pytest.raises(control_flow_graph.UnconnectedNode) as e_ctx:
    g.ValidateControlFlowGraph()
  assert str(e_ctx.value) == "Unconnected node 'A'"
  assert not g.IsValidControlFlowGraph()


def test_ControlFlowGraph_IsValidControlFlowGraph_invalid_degrees():
  """Test that a graph where two nodes could be fused is invalid."""
  g = control_flow_graph.ControlFlowGraph()
  # Graph:
  #
  #      A --> B --> C
  g.add_node(0, name='A', entry=True)
  g.add_node(1, name='B')
  g.add_node(2, name='C', exit=True)
  g.add_edge(0, 1)
  g.add_edge(1, 2)
  with pytest.raises(control_flow_graph.InvalidNodeDegree) as e_ctx:
    g.ValidateControlFlowGraph()
  assert str(e_ctx.value) == "outdegree(A) = 1, indegree(B) = 1"
  assert not g.IsValidControlFlowGraph()


def test_ControlFlowGraph_IsValidControlFlowGraph_unamed_nodes():
  """Test that all nodes in a graph must have a name."""
  g = control_flow_graph.ControlFlowGraph()
  # Graph:
  #
  #     +----> B -----+
  #     |             |
  #     |             v
  #     A             D
  #     |             ^
  #     |             |
  #     +---->   -----+
  g.add_node(0, name='A', entry=True)
  g.add_node(1, name='B')
  g.add_node(2)
  g.add_node(3, name='D', exit=True)
  g.add_edge(0, 1)
  g.add_edge(0, 2)
  g.add_edge(1, 3)
  g.add_edge(2, 3)
  with pytest.raises(control_flow_graph.MissingNodeName) as e_ctx:
    g.ValidateControlFlowGraph()
  assert str(e_ctx.value) == "Node 2 has no name"
  assert not g.IsValidControlFlowGraph()


def test_ControlFlowGraph_IsValidControlFlowGraph_duplicate_names():
  """Test that duplicate names is an error."""
  g = control_flow_graph.ControlFlowGraph()
  # Graph:
  #
  #     +----> B -----+
  #     |             |
  #     |             v
  #     A             D
  #     |             ^
  #     |             |
  #     +----> B -----+
  g.add_node(0, name='A', entry=True)
  g.add_node(1, name='B')
  g.add_node(2, name='B')
  g.add_node(3, name='D', exit=True)
  g.add_edge(0, 1)
  g.add_edge(0, 2)
  g.add_edge(1, 3)
  g.add_edge(2, 3)
  with pytest.raises(control_flow_graph.DuplicateNodeName) as e_ctx:
    g.ValidateControlFlowGraph()
  assert str(e_ctx.value) == "Duplicate node name 'B'"
  assert not g.IsValidControlFlowGraph()


def test_ControlFlowGraph_IsValidControlFlowGraph_exit_block_has_output():
  """Test that an if-else loop graph is valid."""
  g = control_flow_graph.ControlFlowGraph()
  # Graph:
  #
  #     +----> B -----+
  #     |             |
  #     |             v
  #     A<-----------+D
  #     |             ^
  #     |             |
  #     +----> C -----+
  g.add_node(0, name='A', entry=True)
  g.add_node(1, name='B')
  g.add_node(2, name='C')
  g.add_node(3, name='D', exit=True)
  g.add_edge(0, 1)
  g.add_edge(0, 2)
  g.add_edge(1, 3)
  g.add_edge(2, 3)
  g.add_edge(3, 0)
  with pytest.raises(control_flow_graph.InvalidNodeDegree) as e_ctx:
    g.ValidateControlFlowGraph()
  assert str(e_ctx.value) == "Exit block outdegree(D) = 1"
  assert not g.IsValidControlFlowGraph()


def test_ControlFlowGraph_IsValidControlFlowGraph_if_else_loop():
  """Test that an if-else loop graph is valid."""
  g = control_flow_graph.ControlFlowGraph()
  # Graph:
  #
  #     +----> B -----+
  #     |             |
  #     |             v
  #     A             D
  #     |             ^
  #     |             |
  #     +----> C -----+
  g.add_node(0, name='A', entry=True)
  g.add_node(1, name='B')
  g.add_node(2, name='C')
  g.add_node(3, name='D', exit=True)
  g.add_edge(0, 1)
  g.add_edge(0, 2)
  g.add_edge(1, 3)
  g.add_edge(2, 3)
  assert g.ValidateControlFlowGraph() == g
  assert g.IsValidControlFlowGraph()


def test_ControlFlowGraph_IsValidControlFlowGraph_while_loop():
  """Test that a while loop graph is valid."""
  g = control_flow_graph.ControlFlowGraph()
  # Graph:
  #
  #     +--------+
  #     |        |
  #     v        |
  #     A+------>B       C
  #     |                ^
  #     |                |
  #     +----------------+
  g.add_node(0, name='A', entry=True)
  g.add_node(1, name='B')
  g.add_node(2, name='C', exit=True)
  g.add_edge(0, 1)
  g.add_edge(1, 0)
  g.add_edge(0, 2)
  assert g.ValidateControlFlowGraph() == g
  assert g.IsValidControlFlowGraph()


def test_ControlFlowGraph_IsValidControlFlowGraph_while_loop_with_exit():
  """Test that a while loop with an if branch exit is valid."""
  g = control_flow_graph.ControlFlowGraph()
  # Graph:
  #
  #     +----------------+
  #     |                |
  #     v                |
  #     A+------>B+----->C       D
  #     |        |               ^
  #     |        |               |
  #     +------->+---------------+
  g.add_node(0, name='A', entry=True)
  g.add_node(1, name='B')
  g.add_node(2, name='C')
  g.add_node(3, name='D', exit=True)
  g.add_edge(0, 1)
  g.add_edge(1, 2)
  g.add_edge(2, 0)
  g.add_edge(0, 3)
  g.add_edge(1, 3)
  assert g.ValidateControlFlowGraph() == g
  assert g.IsValidControlFlowGraph()


def test_ControlFlowGraph_IsValidControlFlowGraph_irreducible_loop():
  """Test that an irreducible graph is valid."""
  g = control_flow_graph.ControlFlowGraph()
  # Graph:
  #              +-------+
  #              |       |
  #              v       |
  #     A------->B+----->C
  #     |        |       ^
  #     |        |       |
  #     |        v       |
  #     |        D       |
  #     |                |
  #     +----------------+
  g.add_node(0, name='A', entry=True)
  g.add_node(1, name='B')
  g.add_node(2, name='C')
  g.add_node(3, name='D', exit=True)
  g.add_edge(0, 1)
  g.add_edge(1, 2)
  g.add_edge(2, 1)
  g.add_edge(1, 3)
  assert g.ValidateControlFlowGraph() == g
  assert g.IsValidControlFlowGraph()


def test_ControlFlowGraph_entry_block():
  """Test entry block."""
  g = control_flow_graph.ControlFlowGraph()
  # Graph:
  #
  #     +----> B -----+
  #     |             |
  #     |             v
  #     A             D
  #     |             ^
  #     |             |
  #     +----> C -----+
  g.add_node(0, name='A', entry=True)
  g.add_node(1, name='B')
  g.add_node(2, name='C')
  g.add_node(3, name='D', exit=True)
  g.add_edge(0, 1)
  g.add_edge(0, 2)
  g.add_edge(1, 3)
  g.add_edge(2, 3)
  assert g.entry_block == 0


def test_ControlFlowGraph_exit_block():
  """Test exit block."""
  g = control_flow_graph.ControlFlowGraph()
  # Graph:
  #
  #     +----> B -----+
  #     |             |
  #     |             v
  #     A             D
  #     |             ^
  #     |             |
  #     +----> C -----+
  g.add_node(0, name='A', entry=True)
  g.add_node(1, name='B')
  g.add_node(2, name='C')
  g.add_node(3, name='D', exit=True)
  g.add_edge(0, 1)
  g.add_edge(0, 2)
  g.add_edge(1, 3)
  g.add_edge(2, 3)
  assert g.exit_block == 3


def test_ControlFlowGraph_equal():
  """Test that equal graphs can be compared."""
  # Graph 1: A --> B
  g1 = control_flow_graph.ControlFlowGraph()
  g1.add_node(0, name='A', entry=True)
  g1.add_node(1, name='B', exit=True)
  g1.add_edge(0, 1)

  # Graph 2: A --> B
  g2 = control_flow_graph.ControlFlowGraph()
  g2.add_node(0, name='A', entry=True)
  g2.add_node(1, name='B', exit=True)
  g2.add_edge(0, 1)

  assert g1 == g2


def test_ControlFlowGraph_unequal_nodes():
  """Test that graphs with unequal nodes are not equal."""
  # Graph 1: A --> B    C
  g1 = control_flow_graph.ControlFlowGraph()
  g1.add_node(0, name='A', entry=True)
  g1.add_node(1, name='B', exit=True)
  g1.add_node(2, name='C', exit=True)
  g1.add_edge(0, 1)

  # Graph 2: A --> B
  g2 = control_flow_graph.ControlFlowGraph()
  g2.add_node(0, name='A', entry=True)
  g2.add_node(1, name='B', exit=True)
  g2.add_edge(0, 1)

  assert g1 != g2


def test_ControlFlowGraph_unequal_edges():
  """Test that graphs with unequal edges are not equal."""
  # Graph 1: A --> B
  g1 = control_flow_graph.ControlFlowGraph()
  g1.add_node(0, name='A', entry=True)
  g1.add_node(1, name='B', exit=True)
  g1.add_edge(0, 1)

  # Graph 2: B --> A
  g2 = control_flow_graph.ControlFlowGraph()
  g2.add_node(0, name='A', entry=True)
  g2.add_node(1, name='B', exit=True)
  g2.add_edge(1, 0)

  assert g1 != g2


def test_ControlFlowGraph_unequal_graph_names_are_equal():
  """Test that graph names are not used in comparison."""
  # Graph 1: A --> B
  g1 = control_flow_graph.ControlFlowGraph(name='foo')
  g1.add_node(0, name='A', entry=True)
  g1.add_node(1, name='B', exit=True)
  g1.add_edge(0, 1)

  # Graph 2: A --> B
  g2 = control_flow_graph.ControlFlowGraph(name='bar')
  g2.add_node(0, name='A', entry=True)
  g2.add_node(1, name='B', exit=True)
  g2.add_edge(0, 1)

  assert g1 == g2


def test_ControlFlowGraph_unequal_edge_data():
  """Test that edge data is used in comparison."""
  # Graph 1: A --> B
  g1 = control_flow_graph.ControlFlowGraph(name='foo')
  g1.add_node(0, name='A', exit=True)
  g1.add_node(1, name='B')
  g1.add_edge(0, 1)

  # Graph 2: A --> B
  g2 = control_flow_graph.ControlFlowGraph(name='bar')
  g2.add_node(0, name='A')
  g2.add_node(1, name='B', entry=True)
  g2.add_edge(0, 1)

  assert g1 != g2


def test_ControlFlowGraph_ToProto_FromProto_equivalency():
  """Test that conversion to and from proto preserves values."""
  g1 = control_flow_graph.ControlFlowGraph()
  # Graph:
  #
  #     +----> B -----+
  #     |             |
  #     v             v
  #     A             D
  #     ^             ^
  #     |             |
  #     +----> C -----+
  g1.add_node(0, name='A', entry=True)
  g1.add_node(1, name='B')
  g1.add_node(2, name='C')
  g1.add_node(3, name='D', exit=True)
  g1.add_edge(0, 1)
  g1.add_edge(0, 2)
  g1.add_edge(1, 3)
  g1.add_edge(2, 3)

  proto = g1.ToProto()

  g2 = control_flow_graph.ControlFlowGraph.FromProto(proto)

  assert g1 == g2

  # Graph names are not used in equality checks.
  assert g1.name == g2.name


def test_ControlFlowGraph_equivalent_hashes():
  """Test equivalent hashes, despite different graph names."""
  # Graph 1: A --> B
  g1 = control_flow_graph.ControlFlowGraph(name='foo')
  g1.add_node(0, name='A', entry=True)
  g1.add_node(1, name='B', exit=True)
  g1.add_edge(0, 1)

  # Graph 2: A --> B
  g2 = control_flow_graph.ControlFlowGraph(name='bar')
  g2.add_node(0, name='A', entry=True)
  g2.add_node(1, name='B', exit=True)
  g2.add_edge(0, 1)

  assert hash(g1) == hash(g2)


def test_ControlFlowGraph_node_name_changes_hash():
  """Test that hash depends on node name."""
  g1 = control_flow_graph.ControlFlowGraph()
  g1.add_node(0, name='A', entry=True)

  g2 = control_flow_graph.ControlFlowGraph()
  g2.add_node(0, name='B', entry=True)

  assert hash(g1) != hash(g2)


def test_ControlFlowGraph_node_attribute_changes_hash():
  """Test that hash depends on node attributes."""
  g1 = control_flow_graph.ControlFlowGraph()
  g1.add_node(0, name='A')

  g2 = control_flow_graph.ControlFlowGraph()
  g2.add_node(0, name='A', entry=True)

  assert hash(g1) != hash(g2)


def main(argv: typing.List[str]):
  """Main entry point."""
  if len(argv) > 1:
    raise app.UsageError("Unknown arguments: '{}'.".format(' '.join(argv[1:])))
  sys.exit(pytest.main([__file__, '-vv']))


if __name__ == '__main__':
  flags.FLAGS(['argv[0]', '-v=1'])
  app.run(main)
