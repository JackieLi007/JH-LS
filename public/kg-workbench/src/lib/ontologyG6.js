let graph = null;

const SVG_NS = 'http://www.w3.org/2000/svg';

function createSvgElement(tagName, attributes = {}) {
  const element = document.createElementNS(SVG_NS, tagName);
  for (const [key, value] of Object.entries(attributes)) {
    if (value !== undefined && value !== null) element.setAttribute(key, String(value));
  }
  return element;
}

function nodeSize(label = '') {
  if (label.length <= 2) return 118;
  if (label.length <= 4) return 142;
  if (label.length <= 6) return 172;
  return 212;
}

function wrapNodeLabel(label = '') {
  const text = String(label || '').trim();
  if (!text) return [];
  if (text.length <= 4) return [text];
  const chunkSize = text.length <= 8 ? 4 : 5;
  return text.match(new RegExp(`.{1,${chunkSize}}`, 'g')) || [text];
}

function edgeEndpoint(source, target, sourceRadius, targetRadius) {
  const dx = target.x - source.x;
  const dy = target.y - source.y;
  const length = Math.max(Math.hypot(dx, dy), 1);
  const ux = dx / length;
  const uy = dy / length;
  return {
    x1: source.x + ux * sourceRadius,
    y1: source.y + uy * sourceRadius,
    x2: target.x - ux * targetRadius,
    y2: target.y - uy * targetRadius,
    angle: Math.atan2(dy, dx) * 180 / Math.PI,
  };
}

function textRotation(angle) {
  if (angle > 90 || angle < -90) return angle + 180;
  return angle;
}

function buildViewBox(nodes, container) {
  const fallbackWidth = Math.max(container.clientWidth || 0, 1700);
  const fallbackHeight = Math.max(container.clientHeight || 0, 1200);
  if (!nodes.length) return { x: 0, y: 0, width: fallbackWidth, height: fallbackHeight };

  const bounds = nodes.reduce((acc, node) => {
    const radius = node.radius || 80;
    acc.minX = Math.min(acc.minX, node.x - radius);
    acc.minY = Math.min(acc.minY, node.y - radius);
    acc.maxX = Math.max(acc.maxX, node.x + radius);
    acc.maxY = Math.max(acc.maxY, node.y + radius);
    return acc;
  }, { minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity });

  const paddingX = 180;
  const paddingY = 120;
  return {
    x: bounds.minX - paddingX,
    y: bounds.minY - paddingY,
    width: Math.max(bounds.maxX - bounds.minX + paddingX * 2, fallbackWidth),
    height: Math.max(bounds.maxY - bounds.minY + paddingY * 2, fallbackHeight),
  };
}

function setViewBox(svg, viewBox) {
  svg.setAttribute('viewBox', `${viewBox.x} ${viewBox.y} ${viewBox.width} ${viewBox.height}`);
}

function svgPoint(svg, event, viewBox) {
  const rect = svg.getBoundingClientRect();
  const px = (event.clientX - rect.left) / Math.max(rect.width, 1);
  const py = (event.clientY - rect.top) / Math.max(rect.height, 1);
  return {
    x: viewBox.x + px * viewBox.width,
    y: viewBox.y + py * viewBox.height,
  };
}

function renderGrid(svg, defs, viewBox) {
  const pattern = createSvgElement('pattern', {
    id: 'ontology-local-grid',
    width: 36,
    height: 36,
    patternUnits: 'userSpaceOnUse',
  });
  pattern.appendChild(createSvgElement('path', {
    d: 'M 36 0 L 0 0 0 36',
    fill: 'none',
    stroke: '#edf2fb',
    'stroke-width': 1.4,
  }));
  defs.appendChild(pattern);

  svg.appendChild(createSvgElement('rect', {
    x: viewBox.x - viewBox.width,
    y: viewBox.y - viewBox.height,
    width: viewBox.width * 3,
    height: viewBox.height * 3,
    fill: 'url(#ontology-local-grid)',
    class: 'ontology-local-grid-hit',
  }));
}

function renderMarkers(defs) {
  [
    ['ontology-arrow-normal', '#8da6df'],
    ['ontology-arrow-active', '#2555d9'],
  ].forEach(([id, color]) => {
    const marker = createSvgElement('marker', {
      id,
      markerWidth: 14,
      markerHeight: 14,
      refX: 12,
      refY: 7,
      orient: 'auto',
      markerUnits: 'strokeWidth',
    });
    marker.appendChild(createSvgElement('path', {
      d: 'M 1 1 L 13 7 L 1 13 z',
      fill: color,
    }));
    defs.appendChild(marker);
  });
}

function renderEdge(layer, edge, nodeById, activeEdgeId, onEdgeClick) {
  const source = nodeById.get(edge.source);
  const target = nodeById.get(edge.target);
  if (!source || !target) return;

  const isActive = edge.id === activeEdgeId;
  const endpoint = edgeEndpoint(source, target, source.radius, target.radius);
  const group = createSvgElement('g', {
    class: `ontology-local-edge${isActive ? ' ontology-local-edge--active' : ''}`,
    'data-edge-id': edge.id,
  });

  const hitLine = createSvgElement('line', {
    x1: endpoint.x1,
    y1: endpoint.y1,
    x2: endpoint.x2,
    y2: endpoint.y2,
    class: 'ontology-local-edge-hit',
  });
  const line = createSvgElement('line', {
    x1: endpoint.x1,
    y1: endpoint.y1,
    x2: endpoint.x2,
    y2: endpoint.y2,
    stroke: isActive ? '#2555d9' : '#8da6df',
    'stroke-width': isActive ? 4.2 : 3.2,
    'marker-end': `url(#${isActive ? 'ontology-arrow-active' : 'ontology-arrow-normal'})`,
  });

  const label = String(edge.label || '');
  const midpointX = (endpoint.x1 + endpoint.x2) / 2;
  const midpointY = (endpoint.y1 + endpoint.y2) / 2;
  const labelText = createSvgElement('text', {
    x: midpointX,
    y: midpointY - 8,
    class: 'ontology-local-edge-label',
    transform: `rotate(${textRotation(endpoint.angle)} ${midpointX} ${midpointY - 8})`,
  });
  labelText.textContent = label;

  group.appendChild(hitLine);
  group.appendChild(line);
  if (label) group.appendChild(labelText);
  group.addEventListener('click', (event) => {
    event.stopPropagation();
    onEdgeClick?.(edge.id);
  });
  layer.appendChild(group);
}

function renderNode(layer, node, selectedNodeId, dragContext) {
  const {
    svg,
    viewBoxState,
    rerenderEdges,
    onNodeClick,
    onNodeDragEnd,
  } = dragContext;
  const isSelected = node.id === selectedNodeId;
  const group = createSvgElement('g', {
    class: `ontology-local-node${isSelected ? ' ontology-local-node--selected' : ''}`,
    transform: `translate(${node.x} ${node.y})`,
    'data-node-id': node.id,
  });

  group.appendChild(createSvgElement('circle', {
    r: node.radius,
    fill: node.color,
    stroke: isSelected ? '#193d96' : '#ffffff',
    'stroke-width': isSelected ? 4 : 2,
    class: 'ontology-local-node-circle',
  }));

  const lines = wrapNodeLabel(node.label);
  const text = createSvgElement('text', {
    class: 'ontology-local-node-label',
    'text-anchor': 'middle',
    'dominant-baseline': 'middle',
  });
  const startY = -((lines.length - 1) * 22) / 2;
  lines.slice(0, 3).forEach((line, index) => {
    const tspan = createSvgElement('tspan', { x: 0, y: startY + index * 22 });
    tspan.textContent = line;
    text.appendChild(tspan);
  });
  group.appendChild(text);

  let isDragging = false;
  let wasDragged = false;
  let startPoint = null;
  let originPoint = null;

  group.addEventListener('pointerdown', (event) => {
    if (![0, 2].includes(event.button)) return;
    event.preventDefault();
    event.stopPropagation();
    isDragging = true;
    wasDragged = false;
    startPoint = svgPoint(svg, event, viewBoxState.current);
    originPoint = { x: node.x, y: node.y };
    group.setPointerCapture?.(event.pointerId);
  });

  group.addEventListener('pointermove', (event) => {
    if (!isDragging || !startPoint || !originPoint) return;
    event.preventDefault();
    event.stopPropagation();
    const point = svgPoint(svg, event, viewBoxState.current);
    const dx = point.x - startPoint.x;
    const dy = point.y - startPoint.y;
    if (Math.abs(dx) > 2 || Math.abs(dy) > 2) wasDragged = true;
    node.x = originPoint.x + dx;
    node.y = originPoint.y + dy;
    group.setAttribute('transform', `translate(${node.x} ${node.y})`);
    rerenderEdges?.();
  });

  group.addEventListener('pointerup', (event) => {
    if (!isDragging) return;
    event.preventDefault();
    event.stopPropagation();
    group.releasePointerCapture?.(event.pointerId);
    isDragging = false;
    startPoint = null;
    originPoint = null;
    if (wasDragged) onNodeDragEnd?.(node.id, { x: node.x, y: node.y });
    onNodeClick?.(node.id);
  });

  group.addEventListener('click', (event) => {
    event.stopPropagation();
  });
  group.addEventListener('contextmenu', (event) => {
    event.preventDefault();
    event.stopPropagation();
  });
  layer.appendChild(group);
}

function attachCanvasInteractions(svg, viewBoxState, onCanvasClick) {
  const initialViewBox = { ...viewBoxState.current };
  let isDragging = false;
  let dragStart = null;
  let pointerStart = null;

  svg.addEventListener('click', () => {
    onCanvasClick?.();
  });

  svg.addEventListener('wheel', (event) => {
    event.preventDefault();
    const point = svgPoint(svg, event, viewBoxState.current);
    const scale = event.deltaY > 0 ? 1.12 : 0.88;
    const nextWidth = Math.min(Math.max(viewBoxState.current.width * scale, 420), initialViewBox.width * 2.4);
    const nextHeight = Math.min(Math.max(viewBoxState.current.height * scale, 300), initialViewBox.height * 2.4);
    const ratioX = (point.x - viewBoxState.current.x) / viewBoxState.current.width;
    const ratioY = (point.y - viewBoxState.current.y) / viewBoxState.current.height;
    viewBoxState.current = {
      x: point.x - ratioX * nextWidth,
      y: point.y - ratioY * nextHeight,
      width: nextWidth,
      height: nextHeight,
    };
    setViewBox(svg, viewBoxState.current);
  }, { passive: false });

  svg.addEventListener('pointerdown', (event) => {
    if (event.target.closest?.('.ontology-local-node, .ontology-local-edge')) return;
    isDragging = true;
    pointerStart = { x: event.clientX, y: event.clientY };
    dragStart = { ...viewBoxState.current };
    svg.setPointerCapture?.(event.pointerId);
  });

  svg.addEventListener('pointermove', (event) => {
    if (!isDragging || !pointerStart || !dragStart) return;
    const rect = svg.getBoundingClientRect();
    const dx = (event.clientX - pointerStart.x) / Math.max(rect.width, 1) * dragStart.width;
    const dy = (event.clientY - pointerStart.y) / Math.max(rect.height, 1) * dragStart.height;
    viewBoxState.current = { ...dragStart, x: dragStart.x - dx, y: dragStart.y - dy };
    setViewBox(svg, viewBoxState.current);
  });

  svg.addEventListener('pointerup', (event) => {
    isDragging = false;
    pointerStart = null;
    dragStart = null;
    svg.releasePointerCapture?.(event.pointerId);
  });
}

export async function destroyOntologyGraph() {
  if (graph?.container) graph.container.innerHTML = '';
  graph = null;
}

export async function renderOntologyGraph({
  container,
  nodes,
  edges,
  selectedNodeId,
  activeEdgeId,
  onNodeClick,
  onEdgeClick,
  onCanvasClick,
  onNodeDragEnd,
}) {
  if (!container) return;
  await destroyOntologyGraph();

  const normalizedNodes = nodes.map((node) => {
    const size = nodeSize(node.label);
    return {
      ...node,
      radius: size / 2,
      label: String(node.label || ''),
      x: Number(node.x) || 0,
      y: Number(node.y) || 0,
    };
  });
  const nodeById = new Map(normalizedNodes.map((node) => [node.id, node]));
  const viewBox = buildViewBox(normalizedNodes, container);
  const viewBoxState = { current: viewBox };

  const svg = createSvgElement('svg', {
    class: 'ontology-local-svg',
    role: 'img',
    'aria-label': '本体构建图谱',
    preserveAspectRatio: 'xMidYMid meet',
  });
  setViewBox(svg, viewBox);

  const defs = createSvgElement('defs');
  svg.appendChild(defs);
  renderMarkers(defs);
  renderGrid(svg, defs, viewBox);

  const edgeLayer = createSvgElement('g', { class: 'ontology-local-edge-layer' });
  const nodeLayer = createSvgElement('g', { class: 'ontology-local-node-layer' });
  svg.appendChild(edgeLayer);
  svg.appendChild(nodeLayer);

  const rerenderEdges = () => {
    edgeLayer.innerHTML = '';
    edges.forEach((edge) => renderEdge(edgeLayer, edge, nodeById, activeEdgeId, onEdgeClick));
  };

  rerenderEdges();
  normalizedNodes.forEach((node) => renderNode(nodeLayer, node, selectedNodeId, {
    svg,
    viewBoxState,
    rerenderEdges,
    onNodeClick,
    onNodeDragEnd,
  }));

  container.innerHTML = '';
  container.appendChild(svg);
  attachCanvasInteractions(svg, viewBoxState, onCanvasClick);

  graph = { container, svg };
}
