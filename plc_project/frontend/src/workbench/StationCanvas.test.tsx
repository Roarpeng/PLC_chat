import React, { type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { ReactFlow, type ReactFlowProps } from "@xyflow/react";
import { StationCanvas } from "./StationCanvas";
import { emptyFlow, newNode, type Flow } from "./stationDesign";

vi.mock("@xyflow/react", () => ({
  ReactFlow: () => null,
  Background: () => null,
  Controls: () => null,
  Handle: () => null,
  MarkerType: { ArrowClosed: "arrowclosed" },
  Position: { Left: "left", Right: "right", Bottom: "bottom" },
  useUpdateNodeInternals: () => vi.fn(),
}));
vi.mock("./StationCanvasInspector", () => ({ CanvasInspector: () => null }));

type CanvasProps = React.ComponentProps<typeof StationCanvas>;
type Element = ReactElement<Record<string, unknown>>;

function findElement(tree: ReactNode, predicate: (element: Element) => boolean): Element | undefined {
  for (const child of React.Children.toArray(tree)) {
    if (!React.isValidElement<Record<string, unknown>>(child)) continue;
    if (predicate(child)) return child;
    const found = findElement(child.props.children as ReactNode, predicate);
    if (found) return found;
  }
}

// SSR supplies real React hooks. The captured element tree exposes the canvas
// event handlers while React Flow's DOM measurement stays outside this suite.
function canvas(overrides: Partial<CanvasProps> = {}) {
  const update = vi.fn<CanvasProps["update"]>();
  const props: CanvasProps = {
    flow: emptyFlow(), stations: [], catalog: [], selected: "", select: vi.fn(), update,
    openStation: vi.fn(), hardware: { cpu: "", network: "", modules: [], signals: [] },
    problemIds: new Set(), ...overrides,
  };
  let tree: ReactNode;
  function Render() {
    tree = StationCanvas(props);
    return tree;
  }
  renderToStaticMarkup(<Render />);
  const graph = findElement(tree, (item) => item.type === ReactFlow)!.props as ReactFlowProps;
  const surface = findElement(tree, (item) => item.props.className === "af-graph af-canvas-surface")!
    .props as React.HTMLAttributes<HTMLDivElement>;
  const screenToFlowPosition = vi.fn(({ x, y }: { x: number; y: number }) => ({ x: x - 120, y: y - 80 }));
  const fitView = vi.fn();
  graph.onInit!({ screenToFlowPosition, fitView } as unknown as Parameters<NonNullable<typeof graph.onInit>>[0]);
  return { graph, surface, update, props, screenToFlowPosition, fitView };
}

function drop(surface: React.HTMLAttributes<HTMLDivElement>, entry: string, x: number, y: number) {
  const getData = vi.fn(() => entry);
  const preventDefault = vi.fn();
  surface.onDrop!({ dataTransfer: { getData }, clientX: x, clientY: y, preventDefault } as unknown as React.DragEvent<HTMLDivElement>);
  return { getData, preventDefault };
}

function flowWithNodes(): Flow {
  return {
    start: "source", edges: [], nodes: [
      { ...newNode("start"), id: "source", position: { x: 30, y: 40 } },
      { ...newNode("done"), id: "target", position: { x: 340, y: 40 } },
      { ...newNode("done"), id: "other", position: { x: 340, y: 240 } },
    ],
  };
}

describe("station canvas placement and connection regression", () => {
  it("opens an empty canvas without automatic fitting", () => {
    const { graph } = canvas();
    expect(graph.fitView).toBe(false);
    expect(graph.zoomOnDoubleClick).toBe(false);
  });

  it("fits an existing saved graph on entry", () => {
    expect(canvas({ flow: flowWithNodes() }).graph.fitView).toBe(true);
  });

  it("places the first station at the converted drop point and creates its instance", () => {
    const { surface, update, screenToFlowPosition, fitView } = canvas();
    const event = drop(surface, "new-station", 253.4, 168.6);
    expect(event.getData).toHaveBeenCalledWith("application/x-plc-canvas-entry");
    expect(event.preventDefault).toHaveBeenCalledOnce();
    expect(screenToFlowPosition).toHaveBeenCalledWith({ x: 253.4, y: 168.6 });
    const [flow, additions] = update.mock.calls[0];
    expect(flow.nodes[0].position).toEqual({ x: 133, y: 89 });
    expect(flow.start).toBe(flow.nodes[0].id);
    expect(flow.nodes[0].station_ids).toEqual([additions!.station!.id]);
    expect(fitView).not.toHaveBeenCalled();
  });

  it("keeps existing coordinates and wiring when dropping the next node", () => {
    const flow = flowWithNodes();
    flow.edges = [{ id: "route", from_id: "source", to_id: "target", outcome: "next" }];
    const { surface, update, fitView } = canvas({ flow });
    drop(surface, "new-station", 710, 380);
    const [next] = update.mock.calls[0];
    expect(next.nodes.slice(0, 3)).toEqual(flow.nodes);
    expect(next.nodes[3].position).toEqual({ x: 590, y: 300 });
    expect(next.start).toBe(flow.start);
    expect(next.edges).toEqual(flow.edges);
    expect(fitView).not.toHaveBeenCalled();
  });

  it("connects a source outlet to a target inlet", () => {
    const { graph, update } = canvas({ flow: flowWithNodes() });
    graph.onConnect!({ source: "source", sourceHandle: "next", target: "target", targetHandle: "in" });
    expect(update.mock.calls[0][0].edges).toEqual([
      expect.objectContaining({ from_id: "source", to_id: "target", outcome: "next" }),
    ]);
  });

  it("rejects self connections, unavailable outlets and non-execution inlets", () => {
    const { graph, update } = canvas({ flow: flowWithNodes() });
    graph.onConnect!({ source: "source", sourceHandle: "next", target: "source", targetHandle: "in" });
    graph.onConnect!({ source: "source", sourceHandle: "timeout", target: "target", targetHandle: "in" });
    graph.onConnect!({ source: "source", sourceHandle: "next", target: "target", targetHandle: "permission" });
    expect(update).not.toHaveBeenCalled();
  });

  it("reconnects an occupied outlet while preserving the edge identity", () => {
    const flow = flowWithNodes();
    flow.edges = [{ id: "route", from_id: "source", to_id: "target", outcome: "next" }];
    const { graph, update } = canvas({ flow });
    const connection = { source: "source", sourceHandle: "next", target: "other", targetHandle: "in" };
    graph.onConnect!(connection);
    expect(update).not.toHaveBeenCalled();
    graph.onReconnect!({ id: "route", source: "source", target: "target" }, connection);
    expect(update.mock.calls[0][0].edges).toEqual([
      { id: "route", from_id: "source", to_id: "other", outcome: "next" },
    ]);
  });

  it("allows distinct parallel branches and rejects a duplicate branch", () => {
    const flow = flowWithNodes();
    flow.nodes[0].kind = "fork";
    flow.edges = [{ id: "branchA", from_id: "source", to_id: "target", outcome: "branch" }];
    const { graph, update } = canvas({ flow });
    graph.onConnect!({ source: "source", sourceHandle: "branch", target: "target", targetHandle: "in" });
    expect(update).not.toHaveBeenCalled();
    graph.onConnect!({ source: "source", sourceHandle: "branch", target: "other", targetHandle: "in" });
    expect(update.mock.calls[0][0].edges).toHaveLength(2);
  });

  it("persists a moved node without changing execution order", () => {
    const flow = flowWithNodes();
    flow.edges = [{ id: "route", from_id: "source", to_id: "target", outcome: "next" }];
    const { graph, update } = canvas({ flow });
    const moved = { id: "source", position: { x: 112.4, y: 279.8 }, data: {} };
    graph.onNodeDragStop!({} as Parameters<NonNullable<typeof graph.onNodeDragStop>>[0], moved, [moved]);
    const [next] = update.mock.calls[0];
    expect(next.nodes[0].position).toEqual({ x: 112, y: 280 });
    expect(next.nodes.slice(1)).toEqual(flow.nodes.slice(1));
    expect(next.edges).toEqual(flow.edges);
    expect(next.start).toBe(flow.start);
  });

  it("prevents adding and wiring nodes during proposal preview", () => {
    const { graph, surface, update } = canvas({ flow: flowWithNodes(), preview: flowWithNodes() });
    drop(surface, "new-station", 300, 200);
    graph.onConnect!({ source: "source", sourceHandle: "next", target: "target", targetHandle: "in" });
    expect(graph.nodesDraggable).toBe(false);
    expect(graph.nodesConnectable).toBe(false);
    expect(graph.edgesReconnectable).toBe(false);
    expect(update).not.toHaveBeenCalled();
  });

  it("records typed signal wires separately and blocks incompatible endpoints", () => {
    const flow = flowWithNodes();
    flow.nodes.push(
      { ...newNode("logic"), id: "gate", operator: "and" },
      { ...newNode("decision"), id: "decision" },
      { ...newNode("logic"), id: "number", operator: "eq", ports: [
        { id: "operand", name: "工件号", direction: "input", type: "DINT" },
      ] },
    );
    const { graph, update } = canvas({ flow });
    graph.onConnect!({ source: "gate", sourceHandle: "data-result", target: "number", targetHandle: "data-operand" });
    expect(update).not.toHaveBeenCalled();
    graph.onConnect!({ source: "gate", sourceHandle: "data-result", target: "decision", targetHandle: "data-condition" });
    expect(update.mock.calls[0][0].wires).toEqual([expect.objectContaining({
      from_id: "gate", from_port: "result", to_id: "decision", to_port: "condition",
    })]);
    expect(update.mock.calls[0][0].edges).toEqual(flow.edges);
  });
});
