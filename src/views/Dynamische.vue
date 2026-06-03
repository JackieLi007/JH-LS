<script setup lang="ts">
import type { VNodeChild } from 'vue'
import { computed, defineComponent, h, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

type GraphNodeType = 'component' | 'fault' | 'root-cause' | 'condition' | 'impact'

type GraphNode = {
  id: string
  name: string
  shortName: string
  x: number
  y: number
  type: GraphNodeType
  level: string
  status: string
  description: string
  tags: string[]
  hierarchyPath: string[]
  priority: 'P1' | 'P2' | 'P3'
  label: string
  owner: string
  rawText: string
  key: string
}

type GraphEdge = {
  from: string
  to: string
  label: string
  strength: 'normal' | 'critical'
  relationType: string
  rawRelationType?: string
}

type HierarchyNode = {
  id: string
  name: string
  children?: HierarchyNode[]
}

type OntologyNode = {
  id: string
  name: string
  level?: string
  meta?: string
  relation?: string
  children?: OntologyNode[]
}

type GraphPayload = {
  nodes: GraphNode[]
  edges: GraphEdge[]
  hierarchyTree?: HierarchyNode[]
  ontologyTree: OntologyNode[]
  defaultNodeId: string
  stats: { nodeCount: number; edgeCount: number }
  version?: Record<string, unknown> | null
}

type QueryStep = {
  stage: string
  nodeId: string
  nodeName: string
  nodeLevel: string
  summary: string
}

type QueryTopMatch = {
  rank: number
  id: string
  name: string
  level: string
  owner: string
  score: number
  confidence: number
  matchedKeywords: string[]
}

type QueryResult = {
  nodeId: string
  title: string
  summary: string
  pathNodeIds: string[]
  reasoningSteps: QueryStep[]
  topMatches: QueryTopMatch[]
}

type TreeNode = {
  id: string
  label: string
  nodeId?: string
  ontologyNodeId?: string
  meta?: string
  graphNodeIds: string[]
  children?: TreeNode[]
}

type AppView = 'ontology' | 'fault'

const props = withDefaults(defineProps<{
  initialView?: AppView
  embedded?: boolean
}>(), {
  initialView: 'ontology',
  embedded: false,
})

const route = useRoute()

type RenderNode = {
  id: string
  name: string
  shortName: string
  level: string
  x: number
  y: number
  r: number
  fill: string
}

type RenderEdge = GraphEdge & {
  path: string
  labelText: string
  labelX: number
  labelY: number
}

type OntologyMapNode = {
  key: string
  label: string
  lines: string[]
  x: number
  y: number
  r: number
  fill: string
  count: number
}

type OntologyMapEdge = {
  key: string
  from: string
  to: string
  label: string
  startX: number
  startY: number
  endX: number
  endY: number
  labelX: number
  labelY: number
}

type NodePoint = {
  x: number
  y: number
}

type DragState =
  | {
    kind: 'graph'
    target: 'ontologyPage' | 'faultPage' | 'zoom'
    id: string
    startClientX: number
    startClientY: number
    originX: number
    originY: number
    radius: number
    canvasWidth: number
    scaleX: number
    scaleY: number
  }
  | {
    kind: 'ontology'
    key: string
    startClientX: number
    startClientY: number
    originX: number
    originY: number
    radius: number
    scaleX: number
    scaleY: number
  }

const query = ref('')
const currentQuery = ref('')
const isLoading = ref(false)
const isQuerying = ref(false)
const graphError = ref('')
const queryError = ref('')
const graph = ref<GraphPayload | null>(null)
const queryResult = ref<QueryResult | null>(null)
const selectedOntologyNodeId = ref('')
const selectedFaultNodeId = ref('')
const selectedOntologyTreeId = ref('graph-ontology-tree-root')
const selectedFaultTreeId = ref('')
const isInitialOntologySampleMode = ref(false)
const initialOntologySampleIds = ref<Set<string> | null>(null)
const expandedOntologyIds = ref<string[]>([])
const expandedFaultIds = ref<string[]>([])
const activeView = ref<AppView>(props.initialView)
const viewportScale = ref(1)
const viewportRef = ref<HTMLElement | null>(null)
const graphZoomScale = ref(1)
const ontologyMapZoomScale = ref(1)
const isGraphZoomOpen = ref(false)
const graphBoardRef = ref<HTMLElement | null>(null)
const zoomBoardRef = ref<HTMLElement | null>(null)
const ontologyMapBoardRef = ref<HTMLElement | null>(null)
const ontologyGraphPositions = ref<Record<string, NodePoint>>({})
const faultGraphPositions = ref<Record<string, NodePoint>>({})
const zoomGraphPositions = ref<Record<string, NodePoint>>({})
const ontologyMapPositions = ref<Record<string, NodePoint>>({})
const dragState = ref<DragState | null>(null)
const lastAutoQuery = ref('')
const nodeOperationMode = ref<'none' | 'add' | 'edit'>('none')
const nodeFormType = ref<'属性值' | '故障现象'>('属性值')
const nodeFormName = ref('')
const nodeFormParentId = ref('')
const nodeFormRelationType = ref('发生阶段')
const nodeOperationError = ref('')
const isNodeSaving = ref(false)

const STAGE_WIDTH = 1600
const STAGE_HEIGHT = 900
const GRAPH_WIDTH = 1520
const GRAPH_MAX_ZOOM = 2.4
const GRAPH_ZOOM_STEP = 0.1
const ONTOLOGY_MAP_WIDTH = 2400
const ONTOLOGY_MAP_HEIGHT = 1220
const ONTOLOGY_MAP_MAX_ZOOM = 2.2
const ONTOLOGY_MAP_ZOOM_STEP = 0.1
const ONTOLOGY_TEMPLATE_TREE_ROOT_ID = 'graph-ontology-tree-root'
const ONTOLOGY_TEMPLATE_GROUP_PREFIX = 'ontology-template-group::'
const ONTOLOGY_TEMPLATE_LEAF_PREFIX = 'ontology-template-leaf::'
const faultChainRelationTypes = new Set([
  'HAS_FAILURE_MODE',
  'HAS',
  'INCLUDE',
  'LEADS_TO',
  'LEVEL_CLASSIFICATION',
  'OCCURRENCE_STAGE',
  'PROBABILITY',
  'SOLUTION',
  'YES_OR_NO',
])
const faultChainRelationLabels = new Set(['故障模式', '功能', '有', '包含', '导致', '严酷度等级', '发生阶段', '发生概率', '设计措施', '是否单点'])
const attributeLevelLabels = new Set(['属性', '属性值', '发生阶段', '发生概率', '严酷度等级', '是否单点', '设计措施'])
const phenomenonLevelLabels = new Set(['故障现象', '组件级故障现象', '单机级故障现象', '系统级故障现象', '总体级故障现象'])
const attributeRelationOptions = ['发生阶段', '是否单点', '严酷度等级', '发生概率', '设计措施']

function isFaultChainEdge(edge: GraphEdge) {
  return faultChainRelationTypes.has(edge.relationType) || faultChainRelationLabels.has(edge.label)
}

function isSimilarEdge(edge: GraphEdge) {
  return [edge.label, edge.relationType, edge.rawRelationType].some((value) => {
    const text = String(value ?? '').trim()
    return text.includes('相似') || text.toLowerCase().includes('similar')
  })
}

function refreshInitialOntologySample() {
  initialOntologySampleIds.value = null
}

const builderOntologyNodeSpecs = [
  { id: 'fn-left-top', name: '零部组件功能', group: '功能', x: 120, y: 120 },
  { id: 'component-main', name: '零部组件', group: '实体对象', x: 440, y: 108 },
  { id: 'machine-main', name: '单机', group: '实体对象', x: 274, y: 392 },
  { id: 'fn-left-bottom', name: '单机功能', group: '功能', x: 170, y: 878 },
  { id: 'component-fault', name: '组件级故障模式', group: '故障模式', x: 846, y: 120 },
  { id: 'machine-fault', name: '单机级故障模式', group: '故障模式', x: 900, y: 396 },
  { id: 'system-main', name: '系统', group: '实体对象', x: 1426, y: 108 },
  { id: 'global-main', name: '总体', group: '实体对象', x: 1658, y: 96 },
  { id: 'fn-global-top', name: '总体功能', group: '功能', x: 2262, y: 96 },
  { id: 'fn-right-top', name: '系统功能', group: '功能', x: 1878, y: 96 },
  { id: 'system-fault', name: '系统级故障模式', group: '故障模式', x: 1454, y: 394 },
  { id: 'global-fault', name: '总体级故障模式', group: '故障模式', x: 1872, y: 392 },
  { id: 'phen-top', name: '组件级故障现象', group: '故障现象', x: 1188, y: 214 },
  { id: 'phen-mid', name: '单机级故障现象', group: '故障现象', x: 566, y: 666 },
  { id: 'phen-right', name: '系统级故障现象', group: '故障现象', x: 1456, y: 666 },
  { id: 'phen-rightmost', name: '总体级故障现象', group: '故障现象', x: 1894, y: 666 },
  { id: 'attr-stage', name: '发生阶段', group: '属性要素', x: 538, y: 988 },
  { id: 'attr-single', name: '是否单点', group: '属性要素', x: 880, y: 988 },
  { id: 'attr-level', name: '严酷度等级', group: '属性要素', x: 1248, y: 988 },
  { id: 'attr-probability', name: '发生概率', group: '属性要素', x: 1606, y: 988 },
  { id: 'attr-solution', name: '设计措施', group: '属性要素', x: 1942, y: 988 },
] as const

const builderOntologyEdgeSpecs = [
  { from: 'component-main', to: 'fn-left-top', label: '具有功能', relationType: 'HAS_FUNCTION' },
  { from: 'machine-main', to: 'component-main', label: '包含', relationType: 'INCLUDE' },
  { from: 'system-main', to: 'machine-main', label: '包含', relationType: 'INCLUDE' },
  { from: 'machine-main', to: 'fn-left-bottom', label: '具有功能', relationType: 'HAS_FUNCTION' },
  { from: 'component-main', to: 'component-fault', label: '存在故障', relationType: 'HAS_FAILURE_MODE' },
  { from: 'machine-main', to: 'machine-fault', label: '存在故障', relationType: 'HAS_FAILURE_MODE' },
  { from: 'component-fault', to: 'machine-fault', label: '导致', relationType: 'LEADS_TO' },
  { from: 'system-main', to: 'fn-right-top', label: '具有功能', relationType: 'HAS_FUNCTION' },
  { from: 'global-main', to: 'fn-global-top', label: '具有功能', relationType: 'HAS_FUNCTION' },
  { from: 'system-main', to: 'system-fault', label: '存在故障', relationType: 'HAS_FAILURE_MODE' },
  { from: 'global-main', to: 'global-fault', label: '存在故障', relationType: 'HAS_FAILURE_MODE' },
  { from: 'global-main', to: 'system-main', label: '包含', relationType: 'INCLUDE' },
  { from: 'machine-fault', to: 'system-fault', label: '导致', relationType: 'LEADS_TO' },
  { from: 'system-fault', to: 'global-fault', label: '导致', relationType: 'LEADS_TO' },
  { from: 'component-fault', to: 'phen-top', label: '有', relationType: 'HAS' },
  { from: 'machine-fault', to: 'phen-mid', label: '有', relationType: 'HAS' },
  { from: 'system-fault', to: 'phen-right', label: '有', relationType: 'HAS' },
  { from: 'global-fault', to: 'phen-rightmost', label: '有', relationType: 'HAS' },
  { from: 'machine-fault', to: 'attr-stage', label: '发生阶段', relationType: 'OCCURRENCE_STAGE' },
  { from: 'machine-fault', to: 'attr-single', label: '是否单点', relationType: 'YES_OR_NO' },
  { from: 'machine-fault', to: 'attr-level', label: '严酷度等级', relationType: 'LEVEL_CLASSIFICATION' },
  { from: 'machine-fault', to: 'attr-probability', label: '发生概率', relationType: 'PROBABILITY' },
  { from: 'machine-fault', to: 'attr-solution', label: '设计措施', relationType: 'SOLUTION' },
] as const

function builderOntologyType(group: string): GraphNodeType {
  if (group === '故障模式') return 'fault'
  if (group === '故障现象') return 'impact'
  if (group === '属性要素') return 'condition'
  if (group === '功能') return 'root-cause'
  return 'component'
}

function ontologyNodeRadius(label: string) {
  if (label.length <= 2) return 59
  if (label.length <= 4) return 71
  if (label.length <= 6) return 86
  return 106
}

const builderOntologyNodes: GraphNode[] = builderOntologyNodeSpecs.map((node) => ({
  id: node.id,
  name: node.name,
  shortName: node.name,
  x: node.x,
  y: node.y,
  type: builderOntologyType(node.group),
  level: node.group,
  status: node.group,
  description: `${node.name}本体节点`,
  tags: [node.group, node.name],
  hierarchyPath: [node.group, node.name],
  priority: 'P2',
  label: node.name,
  owner: '',
  rawText: '',
  key: node.id,
}))

const builderOntologyEdges: GraphEdge[] = builderOntologyEdgeSpecs.map((edge) => ({
  from: edge.from,
  to: edge.to,
  label: edge.label,
  relationType: edge.relationType,
  strength: edge.relationType === 'LEADS_TO' || edge.relationType === 'HAS_FAILURE_MODE' ? 'critical' : 'normal',
}))

const builderOntologyNodeMap = new Map(builderOntologyNodes.map((node) => [node.id, node] as const))
const builderOntologyGroupOrder = ['实体对象', '故障模式', '故障现象']
const ontologyTemplateTreeOrder = new Map([
  ['global-main', 0],
  ['system-main', 1],
  ['machine-main', 2],
  ['component-main', 3],
  ['global-fault', 0],
  ['system-fault', 1],
  ['machine-fault', 2],
  ['component-fault', 3],
])
const attributeRelationTypes = new Set(['OCCURRENCE_STAGE', 'YES_OR_NO', 'LEVEL_CLASSIFICATION', 'PROBABILITY', 'SOLUTION'])
const attributeRelationLabels = new Set(['发生阶段', '是否单点', '严酷度等级', '发生概率', '设计措施'])
const entityTemplateIds = new Set(['component-main', 'machine-main', 'system-main', 'global-main'])
const functionTemplateIds = new Set(['fn-left-top', 'fn-left-bottom', 'fn-right-top', 'fn-global-top'])
const attributeTemplateIds = new Set(['attr-stage', 'attr-single', 'attr-level', 'attr-probability', 'attr-solution'])

function ontologyTemplateIdForGraphNode(node: GraphNode | null | undefined) {
  if (!node) return ''
  const level = node.level || ''
  const label = node.label || ''
  const text = `${node.name || ''} ${node.owner || ''} ${node.rawText || ''} ${node.key || ''} ${level} ${label}`

  if (level.includes('组件级故障现象')) return 'phen-top'
  if (level.includes('单机级故障现象')) return 'phen-mid'
  if (level.includes('系统级故障现象')) return 'phen-right'
  if (level.includes('总体级故障现象')) return 'phen-rightmost'
  if (level.includes('组件级故障模式') || label === 'ComponentFailureMode') return 'component-fault'
  if (level.includes('单机级故障模式') || label === 'UnitFailureMode') return 'machine-fault'
  if (level.includes('系统级故障模式') || label === 'SystemFailureMode') return 'system-fault'
  if (level.includes('总体级故障模式') || label === 'OverallFailureMode') return 'global-fault'
  if (level === '组件' || level === '零部组件' || label === 'Component') return 'component-main'
  if (level === '单机' || label === 'Machine') return 'machine-main'
  if (level === '系统' || label === 'System') return 'system-main'
  if ((level === '总体' || label === 'Overall') && !level.includes('故障')) return 'global-main'
  if (level === '发生阶段' || label === 'OccurrenceStage' || text.includes('发生阶段')) return 'attr-stage'
  if (level === '发生概率' || label === 'ProbabilityLevel' || text.includes('发生概率')) return 'attr-probability'
  if (level === '严酷度等级' || label === 'SeverityLevel' || text.includes('严酷度')) return 'attr-level'
  if (level === '是否单点' || label === 'SinglePoint' || text.includes('单点')) return 'attr-single'
  if (level === '设计措施' || label === 'DesignMeasure' || text.includes('设计措施')) return 'attr-solution'
  if (level === '属性' || label === 'Attribute') return 'attr-stage'
  if (level.includes('功能') || label === 'Function') {
    if (text.includes('总体')) return 'fn-global-top'
    if (text.includes('系统')) return 'fn-right-top'
    if (text.includes('单机') || text.includes('单体')) return 'fn-left-bottom'
    return 'fn-left-top'
  }
  return ''
}

const ontologyMapPreset: Record<string, { x: number; y: number; r: number; fill: string }> = {
  功能: { x: 120, y: 88, r: 48, fill: '#ff2d2d' },
  组件: { x: 120, y: 228, r: 46, fill: '#ff9b24' },
  单机: { x: 120, y: 430, r: 48, fill: '#ff9b24' },
  系统: { x: 700, y: 208, r: 48, fill: '#ff9b24' },
  组件级故障模式: { x: 390, y: 228, r: 74, fill: '#5579d6' },
  单机级故障模式: { x: 430, y: 428, r: 84, fill: '#5579d6' },
  系统级故障模式: { x: 860, y: 428, r: 72, fill: '#5579d6' },
  总体级故障模式: { x: 1110, y: 428, r: 72, fill: '#5579d6' },
  发生阶段: { x: 640, y: 652, r: 52, fill: '#8bd53f' },
  发生概率: { x: 828, y: 652, r: 52, fill: '#8bd53f' },
  严酷度等级: { x: 1002, y: 652, r: 56, fill: '#8bd53f' },
  是否单点: { x: 448, y: 652, r: 52, fill: '#8bd53f' },
  设计措施: { x: 1178, y: 652, r: 56, fill: '#8bd53f' },
}

const nodeMap = computed(() => new Map(graph.value?.nodes.map((node) => [node.id, node] as const) ?? []))

function findSimilarParent(parent: Map<string, string>, nodeId: string) {
  let cursor = parent.get(nodeId) ?? nodeId
  const trail: string[] = []

  while ((parent.get(cursor) ?? cursor) !== cursor) {
    trail.push(cursor)
    cursor = parent.get(cursor) ?? cursor
  }

  for (const item of trail) parent.set(item, cursor)
  return cursor
}

function buildSimilarRepresentativeMap(nodes: GraphNode[], edges: GraphEdge[]) {
  const parent = new Map(nodes.map((node) => [node.id, node.id] as const))

  const union = (left: string, right: string) => {
    if (!parent.has(left) || !parent.has(right)) return
    const leftRoot = findSimilarParent(parent, left)
    const rightRoot = findSimilarParent(parent, right)
    if (leftRoot !== rightRoot) parent.set(rightRoot, leftRoot)
  }

  for (const edge of edges) {
    if (isSimilarEdge(edge)) union(edge.from, edge.to)
  }

  const nodeById = new Map(nodes.map((node) => [node.id, node] as const))
  const groups = new Map<string, string[]>()
  for (const node of nodes) {
    const root = findSimilarParent(parent, node.id)
    const members = groups.get(root) ?? []
    members.push(node.id)
    groups.set(root, members)
  }

  const representativeById = new Map<string, string>()
  for (const members of groups.values()) {
    const representative = members
      .slice()
      .sort((left, right) => {
        const leftNode = nodeById.get(left)
        const rightNode = nodeById.get(right)
        const nameCompare = (leftNode?.name ?? left).localeCompare(rightNode?.name ?? right, 'zh-CN')
        return nameCompare || left.localeCompare(right)
      })[0]!
    for (const member of members) representativeById.set(member, representative)
  }

  return representativeById
}

const similarRepresentativeByNodeId = computed(() => {
  if (!graph.value) return new Map<string, string>()
  return buildSimilarRepresentativeMap(graph.value.nodes, graph.value.edges)
})

const similarMembersByRepresentative = computed(() => {
  const members = new Map<string, string[]>()
  for (const node of graph.value?.nodes ?? []) {
    const representative = similarRepresentativeByNodeId.value.get(node.id) ?? node.id
    const group = members.get(representative) ?? []
    group.push(node.id)
    members.set(representative, group)
  }
  return members
})

function normalizeGraphNodeId(nodeId: string) {
  return similarRepresentativeByNodeId.value.get(nodeId) ?? nodeId
}

function expandGraphIdsWithSimilarGroups(ids: Set<string>) {
  const expanded = new Set(ids)
  for (const id of ids) {
    const representative = normalizeGraphNodeId(id)
    for (const member of similarMembersByRepresentative.value.get(representative) ?? [id]) {
      expanded.add(member)
    }
  }
  return expanded
}

function mergeSimilarGraphNodes(nodes: GraphNode[]) {
  const merged = new Map<string, GraphNode>()
  for (const node of nodes) {
    const representative = normalizeGraphNodeId(node.id)
    if (!merged.has(representative)) merged.set(representative, nodeMap.value.get(representative) ?? node)
  }
  return Array.from(merged.values())
}

function mergeSimilarGraphEdges(edges: GraphEdge[]) {
  const merged: GraphEdge[] = []
  const seen = new Set<string>()

  for (const edge of edges) {
    if (isSimilarEdge(edge)) continue

    const from = normalizeGraphNodeId(edge.from)
    const to = normalizeGraphNodeId(edge.to)
    if (from === to) continue

    const key = `${from}::${to}::${edge.label}::${edge.relationType}`
    if (seen.has(key)) continue
    seen.add(key)
    merged.push({ ...edge, from, to })
  }

  return merged
}

const selectedFaultNode = computed(() => {
  const map = nodeMap.value
  return map.get(selectedFaultNodeId.value) ?? null
})

const selectedOntologyNode = computed(() => nodeMap.value.get(selectedOntologyNodeId.value) ?? null)
const selectedGraphNode = computed(() => (isOntologyView.value ? selectedOntologyNode.value : selectedFaultNode.value))

function isAttributeValueNode(node: GraphNode | null | undefined) {
  return Boolean(node && attributeLevelLabels.has(node.level))
}

function isPhenomenonNode(node: GraphNode | null | undefined) {
  return Boolean(node && phenomenonLevelLabels.has(node.level))
}

function isFailureModeNode(node: GraphNode | null | undefined) {
  return Boolean(node && node.level.includes('故障模式'))
}

const canModifySelectedNode = computed(() => Boolean(selectedGraphNode.value))
const canDeleteSelectedNode = computed(() => isAttributeValueNode(selectedGraphNode.value) || isPhenomenonNode(selectedGraphNode.value))
const addParentOptions = computed(() => {
  const nodes = graph.value?.nodes ?? []
  return nodes
    .filter((node) => nodeFormType.value === '属性值' ? node.level === '单机级故障模式' : isFailureModeNode(node))
    .sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
})

const topMatches = computed(() => queryResult.value?.topMatches ?? [])
const isOntologyView = computed(() => activeView.value === 'ontology')
const activeViewMeta = computed(() => {
  if (activeView.value === 'ontology') {
    return {
      eyebrow: '图谱展示',
      title: '图谱关系总览',
      description: '与图谱构建使用同一套数据库查询逻辑，展示节点、语义关系与图谱树。',
      graphTitle: '图谱总览',
    }
  }

  return {
    eyebrow: '故障链查询',
    title: '故障链路推演',
    description: '输入故障现象后，系统会定位命中节点并展示关联路径与支撑条件。',
    graphTitle: '故障关联图谱',
  }
})

const toneByNode = (node: Pick<GraphNode, 'label' | 'level'>) => {
  const preset = ontologyMapPreset[getOntologyMapKey(node)]
  if (preset) return preset.fill

  if (node.level.includes('故障模式')) return '#5579d6'
  if (node.level.includes('故障现象')) return '#37b8b4'
  if (node.level.includes('属性') || ['发生阶段', '发生概率', '严酷度等级', '是否单点', '设计措施'].some((item) => node.level.includes(item))) return '#8bd53f'
  if (node.level.includes('功能')) return '#ff2d2d'
  if (node.level.includes('系统') || node.level.includes('单机') || node.level.includes('组件')) return '#ff9b24'
  return '#94a3b8'
}

const stageByLevel = (level: string) => {
  if (level.includes('总体')) return 0
  if (level.includes('系统')) return 1
  if (level.includes('单机')) return 2
  if (level.includes('组件')) return 3
  return 4
}

function compareOntologyTemplateTreeNode(left: GraphNode, right: GraphNode) {
  const leftOrder = ontologyTemplateTreeOrder.get(left.id)
  const rightOrder = ontologyTemplateTreeOrder.get(right.id)
  if (leftOrder !== undefined || rightOrder !== undefined) {
    return (leftOrder ?? 999) - (rightOrder ?? 999)
  }
  return 0
}

function isOntologyTemplateGroupTreeNode(treeNode: TreeNode | null | undefined) {
  return Boolean(
    treeNode
      && treeNode.id.startsWith(ONTOLOGY_TEMPLATE_GROUP_PREFIX)
      && builderOntologyGroupOrder.includes(treeNode.label),
  )
}

function isOntologyTemplateTreeNode(treeNode: TreeNode | null | undefined) {
  return Boolean(
    treeNode
      && (
        treeNode.id === ONTOLOGY_TEMPLATE_TREE_ROOT_ID
        || treeNode.id.startsWith(ONTOLOGY_TEMPLATE_LEAF_PREFIX)
        || isOntologyTemplateGroupTreeNode(treeNode)
      ),
  )
}

function isOntologyTemplateRenderModeActive() {
  return isOntologyView.value
    && !isInitialOntologySampleMode.value
    && !selectedOntologyNodeId.value
    && isOntologyTemplateTreeNode(selectedOntologyTree.value)
}

function isFocusedOntologyGraphRenderMode(activeNodeId: string) {
  return isOntologyView.value
    && !isOntologyTemplateRenderModeActive()
    && Boolean(activeNodeId)
    && Boolean(selectedOntologyNodeId.value)
}

function relatedFocusSortKey(node: GraphNode, activeNodeId: string) {
  const edge = graphSubsetEdges.value.find((item) => item.from === activeNodeId && item.to === node.id)
    ?? graphSubsetEdges.value.find((item) => item.to === activeNodeId && item.from === node.id)
  const directionOrder = edge?.from === activeNodeId ? 0 : edge?.to === activeNodeId ? 1 : 2
  return [
    directionOrder,
    stageByLevel(node.level),
    edge?.label ?? '',
    node.name,
  ] as const
}

function compareFocusRelatedNodes(left: GraphNode, right: GraphNode, activeNodeId: string) {
  const leftKey = relatedFocusSortKey(left, activeNodeId)
  const rightKey = relatedFocusSortKey(right, activeNodeId)
  for (let index = 0; index < leftKey.length; index += 1) {
    const leftValue = leftKey[index]
    const rightValue = rightKey[index]
    if (typeof leftValue === 'number' && typeof rightValue === 'number') {
      if (leftValue !== rightValue) return leftValue - rightValue
      continue
    }
    const result = String(leftValue).localeCompare(String(rightValue), 'zh-CN')
    if (result) return result
  }
  return left.id.localeCompare(right.id)
}

function buildFocusedGraphRenderNodes(positionOverrides: Record<string, NodePoint>, activeNodeId: string) {
  const nodes = graphSubsetNodes.value
  const focusNode = nodes.find((node) => node.id === activeNodeId) ?? nodes[0]
  if (!focusNode) return []

  const relatedNodes = nodes
    .filter((node) => node.id !== focusNode.id)
    .sort((left, right) => compareFocusRelatedNodes(left, right, focusNode.id))
  const ringCapacity = 10
  const ringCount = Math.max(1, Math.ceil(relatedNodes.length / ringCapacity))
  const centerX = GRAPH_WIDTH / 2
  const centerY = 360 + Math.min(ringCount, 5) * 110
  const focusOverride = positionOverrides[focusNode.id]
  const renderNodes: RenderNode[] = [{
    id: focusNode.id,
    name: focusNode.name,
    shortName: focusNode.shortName || focusNode.name,
    level: focusNode.level,
    x: focusOverride?.x ?? centerX,
    y: focusOverride?.y ?? centerY,
    r: 62,
    fill: toneByNode(focusNode),
  }]

  relatedNodes.forEach((node, index) => {
    const ring = Math.floor(index / ringCapacity)
    const ringStart = ring * ringCapacity
    const itemsInRing = Math.min(ringCapacity, relatedNodes.length - ringStart)
    const ringIndex = index - ringStart
    const angleOffset = ring % 2 ? Math.PI / Math.max(itemsInRing, 1) : 0
    const angle = -Math.PI / 2 + angleOffset + (Math.PI * 2 * ringIndex) / Math.max(itemsInRing, 1)
    const horizontalRadius = 300 + ring * 175
    const verticalRadius = 190 + ring * 130
    const override = positionOverrides[node.id]

    renderNodes.push({
      id: node.id,
      name: node.name,
      shortName: node.shortName || node.name,
      level: node.level,
      x: override?.x ?? centerX + Math.cos(angle) * horizontalRadius,
      y: override?.y ?? centerY + Math.sin(angle) * verticalRadius,
      r: 50,
      fill: toneByNode(node),
    })
  })

  return renderNodes
}

function buildRenderNodes(positionOverrides: Record<string, NodePoint>, activeNodeId: string) {
  if (isOntologyTemplateRenderModeActive()) {
    return graphSubsetNodes.value.map((node) => {
      const override = positionOverrides[node.id]
      return {
        id: node.id,
        name: node.name,
        shortName: node.shortName || node.name,
        level: node.level,
        x: override?.x ?? node.x,
        y: override?.y ?? node.y,
        r: activeNodeId === node.id ? ontologyNodeRadius(node.name) + 8 : ontologyNodeRadius(node.name),
        fill: toneByNode(node),
      }
    })
  }

  if (isFocusedOntologyGraphRenderMode(activeNodeId)) {
    return buildFocusedGraphRenderNodes(positionOverrides, activeNodeId)
  }

  const columns = [160, 470, 800, 1130, 1420]
  const grouped = new Map<number, GraphNode[]>()

  for (const node of graphSubsetNodes.value) {
    const stage = stageByLevel(node.level)
    const bucket = grouped.get(stage) ?? []
    bucket.push(node)
    grouped.set(stage, bucket)
  }

  return Array.from(grouped.entries()).flatMap(([stage, nodes]) => {
    const sorted = nodes.slice().sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
    return sorted.map((node, index) => {
      const defaultX = columns[stage] ?? 1420
      const defaultY = 180 + index * 168
      const override = positionOverrides[node.id]

      return {
        id: node.id,
        name: node.name,
        shortName: node.shortName || node.name,
        level: node.level,
        x: override?.x ?? defaultX,
        y: override?.y ?? defaultY,
        r: activeNodeId === node.id ? 56 : 50,
        fill: toneByNode(node),
      }
    })
  })
}

function buildRenderEdges(edges: GraphEdge[], map: Map<string, RenderNode>) {
  return edges.flatMap((edge) => {
    const source = map.get(edge.from)
    const target = map.get(edge.to)
    if (!source || !target) return []

    const dx = target.x - source.x
    const dy = target.y - source.y
    const length = Math.sqrt(dx * dx + dy * dy) || 1
    const unitX = dx / length
    const unitY = dy / length
    const startX = source.x + unitX * source.r
    const startY = source.y + unitY * source.r
    const endX = target.x - unitX * target.r
    const endY = target.y - unitY * target.r
    const normalX = -unitY
    const normalY = unitX
    const labelOffset = 18

    return [{
      ...edge,
      path: `M ${startX} ${startY} L ${endX} ${endY}`,
      labelText: edge.label || edge.relationType,
      labelX: (startX + endX) / 2 + normalX * labelOffset,
      labelY: (startY + endY) / 2 + normalY * labelOffset,
    }]
  })
}

function measureGraphCanvasHeight(nodes: RenderNode[]) {
  if (!nodes.length) return 960
  const bottom = Math.max(...nodes.map((node) => node.y + node.r + 80))
  return Math.max(960, bottom)
}

function measureGraphCanvasWidth(nodes: RenderNode[]) {
  if (!nodes.length) return GRAPH_WIDTH
  const right = Math.max(...nodes.map((node) => node.x + node.r + 120))
  return Math.max(GRAPH_WIDTH, right)
}

const currentPageGraphPositions = computed(() => (isOntologyView.value ? ontologyGraphPositions.value : faultGraphPositions.value))

const pageRenderNodes = computed<RenderNode[]>(() => buildRenderNodes(currentPageGraphPositions.value, graphActiveNodeId.value))
const pageRenderNodeMap = computed(() => new Map(pageRenderNodes.value.map((node) => [node.id, node] as const)))
const pageRenderEdges = computed<RenderEdge[]>(() => buildRenderEdges(graphSubsetEdges.value, pageRenderNodeMap.value))
const pageGraphCanvasHeight = computed(() => measureGraphCanvasHeight(pageRenderNodes.value))
const pageGraphCanvasWidth = computed(() => measureGraphCanvasWidth(pageRenderNodes.value))

const zoomRenderNodes = computed<RenderNode[]>(() => buildRenderNodes(zoomGraphPositions.value, graphActiveNodeId.value))
const zoomRenderNodeMap = computed(() => new Map(zoomRenderNodes.value.map((node) => [node.id, node] as const)))
const zoomRenderEdges = computed<RenderEdge[]>(() => buildRenderEdges(graphSubsetEdges.value, zoomRenderNodeMap.value))
const zoomGraphCanvasHeight = computed(() => measureGraphCanvasHeight(zoomRenderNodes.value))
const zoomGraphCanvasWidth = computed(() => measureGraphCanvasWidth(zoomRenderNodes.value))

const pageGraphSvgStyle = computed(() => ({
  width: `${pageGraphCanvasWidth.value * graphZoomScale.value}px`,
  minWidth: `${pageGraphCanvasWidth.value * graphZoomScale.value}px`,
  height: `${pageGraphCanvasHeight.value * graphZoomScale.value}px`,
}))

const zoomGraphSvgStyle = computed(() => ({
  width: `${zoomGraphCanvasWidth.value * graphZoomScale.value}px`,
  minWidth: `${zoomGraphCanvasWidth.value * graphZoomScale.value}px`,
  height: `${zoomGraphCanvasHeight.value * graphZoomScale.value}px`,
}))

const graphZoomLabel = computed(() => `${Math.round(graphZoomScale.value * 100)}%`)

const ontologyMapSvgStyle = computed(() => ({
  width: `${ONTOLOGY_MAP_WIDTH * ontologyMapZoomScale.value}px`,
  minWidth: `${ONTOLOGY_MAP_WIDTH * ontologyMapZoomScale.value}px`,
  height: `${ONTOLOGY_MAP_HEIGHT * ontologyMapZoomScale.value}px`,
}))

const ontologyMapZoomLabel = computed(() => `${Math.round(ontologyMapZoomScale.value * 100)}%`)

function getOntologyMapKey(node: Pick<GraphNode, 'label' | 'level'>) {
  const directLabel = node.label?.trim() || ''
  if (directLabel && ontologyMapPreset[directLabel]) return directLabel

  const levelLabel = node.level?.trim() || ''
  if (levelLabel && ontologyMapPreset[levelLabel]) return levelLabel

  return directLabel || levelLabel
}

function wrapOntologyMapLabel(label: string) {
  if (label.endsWith('级故障模式')) {
    const prefix = label.slice(0, label.indexOf('故障模式'))
    return [prefix, '故障模式']
  }

  if (label.length <= 4) return [label]

  const midpoint = Math.ceil(label.length / 2)
  return [label.slice(0, midpoint), label.slice(midpoint)]
}

const ontologyMapNodes = computed<OntologyMapNode[]>(() => {
  return builderOntologyNodes.map((node) => {
    const override = ontologyMapPositions.value[node.id]
    return {
      key: node.id,
      label: node.name,
      lines: wrapOntologyMapLabel(node.name),
      x: override?.x ?? node.x,
      y: override?.y ?? node.y,
      r: ontologyNodeRadius(node.name),
      fill: toneByNode(node),
      count: 0,
    }
  })
})

const ontologyMapNodeMap = computed(() => new Map(ontologyMapNodes.value.map((node) => [node.key, node] as const)))

const ontologyMapEdges = computed<OntologyMapEdge[]>(() => {
  return builderOntologyEdges.flatMap((edge) => {
    const source = ontologyMapNodeMap.value.get(edge.from)
    const target = ontologyMapNodeMap.value.get(edge.to)
    if (!source || !target) return []

    const dx = target.x - source.x
    const dy = target.y - source.y
    const length = Math.hypot(dx, dy) || 1
    const unitX = dx / length
    const unitY = dy / length
    const startX = source.x + unitX * (source.r + 4)
    const startY = source.y + unitY * (source.r + 4)
    const endX = target.x - unitX * (target.r + 4)
    const endY = target.y - unitY * (target.r + 4)
    const normalX = -unitY
    const normalY = unitX
    const labelOffset = Math.abs(dx) > Math.abs(dy) ? -18 : 18

    return [{
      key: `${edge.from}-${edge.to}-${edge.label}`,
      from: edge.from,
      to: edge.to,
      label: edge.label,
      startX,
      startY,
      endX,
      endY,
      labelX: (startX + endX) / 2 + normalX * labelOffset,
      labelY: (startY + endY) / 2 + normalY * labelOffset,
    }]
  })
})

function buildTreeLabel(name: string, level?: string) {
  return level ? `${level}：${name}` : name
}

function findTreePath(root: TreeNode | null, predicate: (node: TreeNode) => boolean): string[] {
  if (!root) return []

  const walk = (node: TreeNode, trail: string[]): string[] | null => {
    const nextTrail = [...trail, node.id]
    if (predicate(node)) return nextTrail

    for (const child of node.children ?? []) {
      const result = walk(child, nextTrail)
      if (result) return result
    }

    return null
  }

  return walk(root, []) ?? []
}

function collectTreeNodeIds(nodes: TreeNode[]) {
  const ids = new Set<string>()

  const visit = (node: TreeNode) => {
    for (const id of node.graphNodeIds) ids.add(id)
    for (const child of node.children ?? []) visit(child)
  }

  for (const node of nodes) visit(node)
  return Array.from(ids)
}

function countGraphRelations(nodeIds: string[]) {
  if (!graph.value || !nodeIds.length) return 0
  const ids = new Set(nodeIds)
  return graph.value.edges.filter((edge) => !isSimilarEdge(edge) && (ids.has(edge.from) || ids.has(edge.to))).length
}

function formatGraphMeta(nodeIds: string[]) {
  return `${nodeIds.length} 个节点 / ${countGraphRelations(nodeIds)} 条关系`
}

function ontologyModuleLabel(node: GraphNode) {
  const ontologyNodeId = ontologyTemplateIdForGraphNode(node)
  return builderOntologyNodeMap.get(ontologyNodeId)?.name ?? node.level
}

function buildFaultTree(): TreeNode | null {
  if (!queryResult.value || !graph.value) return null

  const orderedSteps = queryResult.value.reasoningSteps.slice().reverse()
  if (!orderedSteps.length) return null

  const makeLabel = (step: QueryStep) => `${step.stage}：${step.nodeName}`
  const root: TreeNode = {
    id: `fault-tree::${orderedSteps[0]!.nodeId}`,
    nodeId: orderedSteps[0]!.nodeId,
    label: makeLabel(orderedSteps[0]!),
    meta: orderedSteps[0]!.nodeLevel,
    graphNodeIds: [orderedSteps[0]!.nodeId],
  }
  let cursor = root

  for (const step of orderedSteps.slice(1)) {
    const next: TreeNode = {
      id: `fault-tree::${step.nodeId}`,
      nodeId: step.nodeId,
      label: makeLabel(step),
      meta: step.nodeLevel,
      graphNodeIds: [step.nodeId],
      children: [],
    }
    cursor.children = [next]
    cursor = next
  }

  const focusId = queryResult.value.nodeId
  const supportChildren: TreeNode[] = []

  for (const edge of graph.value.edges) {
    if (!isFaultChainEdge(edge)) continue
    const neighborId = edge.from === focusId ? edge.to : edge.to === focusId ? edge.from : null
    if (!neighborId) continue
    const neighbor = nodeMap.value.get(neighborId)
    if (!neighbor || (!attributeLevelLabels.has(neighbor.level) && !phenomenonLevelLabels.has(neighbor.level))) continue
    if (supportChildren.some((item) => item.nodeId === neighbor.id)) continue
    supportChildren.push({
      id: `fault-support::${neighbor.id}`,
      nodeId: neighbor.id,
      label: buildTreeLabel(neighbor.name, neighbor.level),
      meta: edge.label,
      graphNodeIds: [neighbor.id],
    })
  }

  if (supportChildren.length) {
    cursor.children = supportChildren
  }

  return root
}

function buildGraphOntologyTree(): TreeNode | null {
  const graphNodes = graph.value?.nodes ?? []
  const graphNodeById = new Map(graphNodes.map((node) => [node.id, node] as const))
  const graphIdsByOntologyNode = new Map(builderOntologyNodes.map((node) => [node.id, [] as string[]]))
  const matchedGraphIds = new Set<string>()
  for (const node of graphNodes) {
    const ontologyNodeId = ontologyTemplateIdForGraphNode(node)
    if (!ontologyNodeId) continue
    graphIdsByOntologyNode.get(ontologyNodeId)?.push(node.id)
  }

  const makeGraphDataNode = (node: GraphNode, nestedChildren: TreeNode[] = []): TreeNode => {
    matchedGraphIds.add(node.id)
    return {
      id: `ontology-graph-data::${node.id}`,
      nodeId: node.id,
      label: node.name,
      meta: [ontologyModuleLabel(node), node.owner].filter(Boolean).join(' / ') || node.status,
      graphNodeIds: [node.id],
      children: nestedChildren,
    }
  }

  const isFunctionEdge = (edge: GraphEdge) => edge.relationType === 'HAS_FUNCTION' || edge.relationType === '具有功能' || edge.label === '具有功能'
  const isAttributeEdge = (edge: GraphEdge) => attributeRelationTypes.has(edge.relationType) || attributeRelationLabels.has(edge.relationType) || attributeRelationLabels.has(edge.label)

  const relatedNodes = (nodeId: string, edgeMatcher: (edge: GraphEdge) => boolean, nodeMatcher: (node: GraphNode) => boolean) => {
    const related: GraphNode[] = []
    const seen = new Set<string>()
    for (const edge of graph.value?.edges ?? []) {
      if (!edgeMatcher(edge)) continue
      const relatedId = edge.from === nodeId ? edge.to : edge.to === nodeId ? edge.from : ''
      if (!relatedId || seen.has(relatedId)) continue
      const relatedNode = graphNodeById.get(relatedId)
      if (!relatedNode || !nodeMatcher(relatedNode)) continue
      seen.add(relatedId)
      related.push(relatedNode)
    }
    return related.sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
  }

  const makeTemplateNode = (node: GraphNode, nestedChildren: TreeNode[] = []): TreeNode => {
    const graphNodeIds = graphIdsByOntologyNode.get(node.id) ?? []
    const graphDataChildren = graphNodeIds
      .map((id) => graphNodeById.get(id))
      .filter((item): item is GraphNode => Boolean(item))
      .sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
      .map((graphNode) => {
        const ontologyId = ontologyTemplateIdForGraphNode(graphNode)
        if (entityTemplateIds.has(ontologyId)) {
          const functionNodes = relatedNodes(
            graphNode.id,
            isFunctionEdge,
            (relatedNode) => functionTemplateIds.has(ontologyTemplateIdForGraphNode(relatedNode)),
          )
          return makeGraphDataNode(graphNode, functionNodes.map((item) => makeGraphDataNode(item)))
        }

        if (ontologyId === 'machine-fault') {
          const attributeNodes = relatedNodes(
            graphNode.id,
            isAttributeEdge,
            (relatedNode) => attributeTemplateIds.has(ontologyTemplateIdForGraphNode(relatedNode)),
          )
          return makeGraphDataNode(graphNode, attributeNodes.map((item) => makeGraphDataNode(item)))
        }

        return makeGraphDataNode(graphNode)
      })

    return {
      id: `ontology-template-leaf::${node.id}`,
      ontologyNodeId: node.id,
      label: node.name,
      meta: formatGraphMeta(graphNodeIds),
      graphNodeIds,
      children: [...nestedChildren, ...graphDataChildren],
    }
  }

  const makeGroupNode = (group: string, leafNodes: TreeNode[]): TreeNode => {
    const groupGraphNodeIds = collectTreeNodeIds(leafNodes)
    return {
      id: `ontology-template-group::${group}`,
      label: group,
      meta: formatGraphMeta(groupGraphNodeIds),
      graphNodeIds: groupGraphNodeIds,
      children: leafNodes,
    }
  }

  const children: TreeNode[] = builderOntologyGroupOrder.map((group) => {
    const groupNodes = builderOntologyNodes
      .filter((node) => node.level === group)
      .sort(compareOntologyTemplateTreeNode)
    const leafNodes = groupNodes.map((node) => makeTemplateNode(node))
    return makeGroupNode(group, leafNodes)
  })
  const unmatchedNodes = graphNodes
    .filter((node) => !matchedGraphIds.has(node.id))
    .sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
  if (unmatchedNodes.length) {
    children.push({
      id: 'ontology-template-group::unmatched-graph-data',
      label: '其他图谱数据',
      meta: formatGraphMeta(unmatchedNodes.map((node) => node.id)),
      graphNodeIds: unmatchedNodes.map((node) => node.id),
      children: unmatchedNodes.map((node) => makeGraphDataNode(node)),
    })
  }
  const allGraphNodeIds = graphNodes.map((node) => node.id)

  return {
    id: ONTOLOGY_TEMPLATE_TREE_ROOT_ID,
    label: '图谱树',
    meta: `${graph.value?.stats.nodeCount ?? 0} 个节点 / ${(graph.value?.edges ?? []).filter((edge) => !isSimilarEdge(edge)).length} 条关系`,
    graphNodeIds: allGraphNodeIds.length ? allGraphNodeIds : collectTreeNodeIds(children),
    children,
  }
}

const faultTree = computed(() => buildFaultTree())
const graphOntologyTree = computed(() => buildGraphOntologyTree())

const ontologyTreeNodeMap = computed(() => {
  const map = new Map<string, TreeNode>()

  const visit = (node: TreeNode | null) => {
    if (!node) return
    map.set(node.id, node)
    for (const child of node.children ?? []) visit(child)
  }

  visit(graphOntologyTree.value)
  return map
})

const ontologyTreeIdByNodeId = computed(() => {
  const map = new Map<string, string>()
  for (const [treeId, treeNode] of ontologyTreeNodeMap.value) {
    if (treeNode.nodeId && !map.has(treeNode.nodeId)) map.set(treeNode.nodeId, treeId)
    for (const graphNodeId of treeNode.graphNodeIds) {
      map.set(graphNodeId, treeId)
    }
  }
  return map
})

const ontologyMapTreeIdByLabel = computed(() => {
  const map = new Map<string, string>()

  const visit = (node: TreeNode | null) => {
    if (!node) return
    map.set(node.label, node.id)
    if (node.nodeId) map.set(node.nodeId, node.id)
    if (node.ontologyNodeId) map.set(node.ontologyNodeId, node.id)
    const tailLabel = node.label.split('：').pop()?.trim()
    if (tailLabel) map.set(tailLabel, node.id)
    for (const child of node.children ?? []) visit(child)
  }

  visit(graphOntologyTree.value)
  return map
})

const faultTreeIdByNodeId = computed(() => {
  const map = new Map<string, string>()

  const visit = (node: TreeNode | null) => {
    if (!node) return
    if (node.nodeId && !map.has(node.nodeId)) map.set(node.nodeId, node.id)
    for (const child of node.children ?? []) visit(child)
  }

  visit(faultTree.value)
  return map
})

const selectedOntologyTree = computed(() => ontologyTreeNodeMap.value.get(selectedOntologyTreeId.value) ?? graphOntologyTree.value)

const ontologyTemplateRenderNodeIds = computed(() => {
  if (!isOntologyTemplateRenderModeActive()) return new Set<string>()

  const focusTreeNode = selectedOntologyTree.value
  if (!focusTreeNode || focusTreeNode.id === ONTOLOGY_TEMPLATE_TREE_ROOT_ID) {
    return new Set(builderOntologyNodes.map((node) => node.id))
  }

  const baseIds = new Set<string>()
  if (focusTreeNode.ontologyNodeId) {
    baseIds.add(focusTreeNode.ontologyNodeId)
  } else if (isOntologyTemplateGroupTreeNode(focusTreeNode)) {
    for (const node of builderOntologyNodes) {
      if (node.level === focusTreeNode.label) baseIds.add(node.id)
    }
  }

  if (!baseIds.size) return new Set(builderOntologyNodes.map((node) => node.id))

  const ids = new Set(baseIds)
  for (const edge of builderOntologyEdges) {
    if (baseIds.has(edge.from) || baseIds.has(edge.to)) {
      ids.add(edge.from)
      ids.add(edge.to)
    }
  }
  return ids
})

const selectedOntologyMapKey = computed(() => {
  const focusTreeNode = selectedOntologyTree.value
  if (focusTreeNode?.ontologyNodeId) return focusTreeNode.ontologyNodeId

  if (selectedOntologyNodeId.value) {
    return ontologyTemplateIdForGraphNode(nodeMap.value.get(selectedOntologyNodeId.value))
  }

  if (!focusTreeNode) return ''

  if (focusTreeNode.nodeId) {
    return ontologyTemplateIdForGraphNode(nodeMap.value.get(focusTreeNode.nodeId))
  }

  const tailLabel = focusTreeNode.label.split('：').pop()?.trim() ?? ''
  return ontologyMapTreeIdByLabel.value.has(tailLabel) ? tailLabel : ''
})

const currentFocusLabel = computed(() => {
  if (isOntologyView.value) {
    const focusTreeNode = selectedOntologyTree.value
    if (selectedOntologyNodeId.value) return nodeMap.value.get(selectedOntologyNodeId.value)?.name ?? focusTreeNode?.label ?? '图谱树'
    if (focusTreeNode?.ontologyNodeId) return builderOntologyNodeMap.get(focusTreeNode.ontologyNodeId)?.name ?? focusTreeNode.label
    if (focusTreeNode) return focusTreeNode.label
  }

  return selectedFaultNode.value?.name || '等待选择节点'
})

const graphActiveNodeId = computed(() => {
  if (isOntologyTemplateRenderModeActive()) return selectedOntologyTree.value?.ontologyNodeId ?? ''
  if (isOntologyView.value) return selectedOntologyNodeId.value ? normalizeGraphNodeId(selectedOntologyNodeId.value) : ''
  return selectedFaultNodeId.value ? normalizeGraphNodeId(selectedFaultNodeId.value) : ''
})

const graphSubsetIds = computed(() => {
  if (isOntologyView.value) {
    if (isOntologyTemplateRenderModeActive()) return new Set(ontologyTemplateRenderNodeIds.value)
    if (!graph.value?.nodes.length) return new Set<string>()
    if (isInitialOntologySampleMode.value && initialOntologySampleIds.value?.size) {
      return new Set(initialOntologySampleIds.value)
    }

    const focusTreeNode = selectedOntologyTree.value ?? graphOntologyTree.value
    if (!focusTreeNode) return new Set(graph.value.nodes.map((node) => node.id))

    if (selectedOntologyNodeId.value) {
      const baseIds = expandGraphIdsWithSimilarGroups(new Set<string>([selectedOntologyNodeId.value]))
      const ids = new Set(baseIds)
      for (const edge of graph.value.edges) {
        if (isSimilarEdge(edge)) continue
        if (baseIds.has(edge.from) || baseIds.has(edge.to)) {
          ids.add(edge.from)
          ids.add(edge.to)
        }
      }
      return expandGraphIdsWithSimilarGroups(ids)
    }

    const baseIds = expandGraphIdsWithSimilarGroups(new Set(focusTreeNode.graphNodeIds))
    const ids = new Set(baseIds)
    for (const edge of graph.value.edges) {
      if (isSimilarEdge(edge)) continue
      if (baseIds.has(edge.from) || baseIds.has(edge.to)) {
        ids.add(edge.from)
        ids.add(edge.to)
      }
    }
    return expandGraphIdsWithSimilarGroups(ids)
  }

  if (!graph.value?.nodes.length) return new Set<string>()
  if (!queryResult.value && !selectedFaultNodeId.value) return new Set<string>()

  const ids = new Set<string>()
  if (queryResult.value?.pathNodeIds?.length) {
    for (const id of queryResult.value.pathNodeIds) ids.add(id)
  }
  if (selectedFaultNodeId.value) ids.add(selectedFaultNodeId.value)

  if (selectedFaultNodeId.value && graph.value) {
    const baseIds = expandGraphIdsWithSimilarGroups(new Set([selectedFaultNodeId.value]))
    for (const id of baseIds) ids.add(id)
    for (const edge of graph.value.edges) {
      if (!isFaultChainEdge(edge) || isSimilarEdge(edge)) continue
      if (baseIds.has(edge.from) || baseIds.has(edge.to)) {
        ids.add(edge.from)
        ids.add(edge.to)
      }
    }
  }

  return expandGraphIdsWithSimilarGroups(ids)
})

const graphSubsetNodes = computed(() => {
  if (isOntologyTemplateRenderModeActive()) {
    const ids = ontologyTemplateRenderNodeIds.value
    return builderOntologyNodes.filter((node) => ids.has(node.id))
  }

  if (!graph.value) return []
  const ids = graphSubsetIds.value
  if (isOntologyView.value) return mergeSimilarGraphNodes(graph.value.nodes.filter((node) => ids.has(node.id)))
  if (!queryResult.value && !selectedFaultNodeId.value) return []

  const connectedIds = new Set<string>()
  for (const edge of graph.value.edges) {
    if (!isFaultChainEdge(edge) || isSimilarEdge(edge) || !ids.has(edge.from) || !ids.has(edge.to)) continue
    connectedIds.add(edge.from)
    connectedIds.add(edge.to)
  }
  if (selectedFaultNodeId.value) connectedIds.add(selectedFaultNodeId.value)

  return mergeSimilarGraphNodes(graph.value.nodes.filter((node) => ids.has(node.id) && connectedIds.has(node.id)))
})

const graphSubsetEdges = computed(() => {
  if (isOntologyTemplateRenderModeActive()) {
    const ids = ontologyTemplateRenderNodeIds.value
    return builderOntologyEdges.filter((edge) => ids.has(edge.from) && ids.has(edge.to))
  }

  if (isOntologyView.value) {
    if (!graph.value) return []
    const ids = graphSubsetIds.value
    return mergeSimilarGraphEdges(graph.value.edges.filter((edge) => ids.has(edge.from) && ids.has(edge.to)))
  }

  if (!graph.value) return []
  if (!queryResult.value && !selectedFaultNodeId.value) return []

  const ids = graphSubsetIds.value
  return mergeSimilarGraphEdges(graph.value.edges.filter((edge) => ids.has(edge.from) && ids.has(edge.to) && isFaultChainEdge(edge)))
})

function syncOntologyExpandedState(focusNodeId = selectedOntologyNodeId.value) {
  const nextExpanded = new Set<string>()

  if (graphOntologyTree.value) nextExpanded.add(graphOntologyTree.value.id)

  if (focusNodeId) {
    for (const id of findTreePath(graphOntologyTree.value, (node) => node.nodeId === focusNodeId || node.graphNodeIds.includes(focusNodeId))) nextExpanded.add(id)
  }

  if (selectedOntologyTreeId.value) {
    for (const id of findTreePath(graphOntologyTree.value, (node) => node.id === selectedOntologyTreeId.value)) nextExpanded.add(id)
  }

  expandedOntologyIds.value = Array.from(nextExpanded)
}

function syncFaultExpandedState(focusNodeId = selectedFaultNodeId.value) {
  const nextExpanded = new Set<string>()

  if (faultTree.value) nextExpanded.add(faultTree.value.id)

  if (focusNodeId) {
    for (const id of findTreePath(faultTree.value, (node) => node.nodeId === focusNodeId)) nextExpanded.add(id)
  }

  if (selectedFaultTreeId.value) {
    for (const id of findTreePath(faultTree.value, (node) => node.id === selectedFaultTreeId.value)) nextExpanded.add(id)
  }

  expandedFaultIds.value = Array.from(nextExpanded)
}

function setGraphNodePosition(target: 'ontologyPage' | 'faultPage' | 'zoom', id: string, point: NodePoint) {
  if (target === 'ontologyPage') {
    ontologyGraphPositions.value = {
      ...ontologyGraphPositions.value,
      [id]: point,
    }
    return
  }

  if (target === 'faultPage') {
    faultGraphPositions.value = {
      ...faultGraphPositions.value,
      [id]: point,
    }
    return
  }

  zoomGraphPositions.value = {
    ...zoomGraphPositions.value,
    [id]: point,
  }
}

function applyGraphPayload(nextGraph: GraphPayload, focusNodeId = '') {
  graph.value = nextGraph
  refreshInitialOntologySample()
  if (focusNodeId && nodeMap.value.has(focusNodeId)) {
    isInitialOntologySampleMode.value = false
    if (isOntologyView.value) {
      selectedOntologyNodeId.value = focusNodeId
      selectedOntologyTreeId.value = ontologyTreeIdByNodeId.value.get(focusNodeId) ?? selectedOntologyTreeId.value
    } else {
      selectedFaultNodeId.value = focusNodeId
      selectedFaultTreeId.value = faultTreeIdByNodeId.value.get(focusNodeId) ?? selectedFaultTreeId.value
    }
  }
  syncOntologyExpandedState()
  syncFaultExpandedState()
}

function graphPayloadFromResponse(payload: Record<string, any>): GraphPayload | null {
  return (payload.graph ?? payload.result?.graph ?? null) as GraphPayload | null
}

type LoadGraphOptions = {
  resetViewState?: boolean
}

async function loadGraph(options: LoadGraphOptions = {}) {
  const { resetViewState = true } = options
  if (graph.value) return true
  graphError.value = ''
  isLoading.value = true
  try {
    const response = await fetch('/api/graph', { cache: 'no-store' })
    const payload = await response.json()
    const nextGraph = graphPayloadFromResponse(payload)
    if (!nextGraph) throw new Error('empty graph payload')
    graph.value = nextGraph
    refreshInitialOntologySample()
    ontologyGraphPositions.value = {}
    faultGraphPositions.value = {}
    zoomGraphPositions.value = {}
    ontologyMapPositions.value = {}
    if (resetViewState) {
      selectedOntologyNodeId.value = ''
      selectedOntologyTreeId.value = ONTOLOGY_TEMPLATE_TREE_ROOT_ID
      isInitialOntologySampleMode.value = false
    }
    syncGraphBoardCenter()
    syncOntologyMapBoardCenter()
    syncOntologyExpandedState()
    syncFaultExpandedState()
    return true
  } catch {
    graphError.value = '图谱加载失败，请检查 Flask 服务和 Neo4j 连接'
    return false
  } finally {
    isLoading.value = false
  }
}

function ensureGraphLoadedForOntology() {
  if (activeView.value !== 'ontology' || graph.value || isLoading.value) return
  void nextTick(() => {
    if (activeView.value === 'ontology' && !graph.value) {
      void loadGraph({ resetViewState: false })
    }
  })
}

async function refreshQueryResultAfterGraphChange() {
  const text = currentQuery.value || query.value.trim()
  if (!text || !graph.value) return
  try {
    const response = await fetch('/api/query', {
      method: 'POST',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    })
    const payload = await response.json()
    if (!response.ok) return
    queryResult.value = payload.result as QueryResult
    currentQuery.value = text
    if (selectedFaultNodeId.value && !nodeMap.value.has(selectedFaultNodeId.value)) {
      selectedFaultNodeId.value = queryResult.value.nodeId || ''
    }
    selectedFaultTreeId.value = faultTreeIdByNodeId.value.get(selectedFaultNodeId.value) ?? selectedFaultTreeId.value
    syncFaultExpandedState(selectedFaultNodeId.value)
  } catch {
    // 查询刷新失败时保留图谱更新结果，避免阻断节点操作。
  }
}

function openAddNodeForm() {
  nodeOperationError.value = ''
  nodeOperationMode.value = 'add'
  nodeFormType.value = '属性值'
  nodeFormName.value = ''
  nodeFormRelationType.value = '发生阶段'
  const selected = selectedGraphNode.value
  nodeFormParentId.value = selected?.level === '单机级故障模式'
    ? selected.id
    : addParentOptions.value[0]?.id ?? ''
}

function handleAddClick(event?: Event) {
  event?.preventDefault()
  event?.stopPropagation()
  openAddNodeForm()
}

function openEditNodeForm() {
  const selected = selectedGraphNode.value
  if (!selected) return
  nodeOperationError.value = ''
  nodeOperationMode.value = 'edit'
  nodeFormName.value = selected.name
}

function handleEditClick(event?: Event) {
  event?.preventDefault()
  event?.stopPropagation()
  openEditNodeForm()
}

function cancelNodeOperation() {
  nodeOperationMode.value = 'none'
  nodeOperationError.value = ''
  nodeFormName.value = ''
}

watch(nodeFormType, () => {
  const selected = selectedGraphNode.value
  if (nodeFormType.value === '属性值' && selected?.level === '单机级故障模式') {
    nodeFormParentId.value = selected.id
    return
  }
  if (nodeFormType.value === '故障现象' && isFailureModeNode(selected)) {
    nodeFormParentId.value = selected!.id
    return
  }
  nodeFormParentId.value = addParentOptions.value[0]?.id ?? ''
})

async function submitNodeOperation() {
  nodeOperationError.value = ''
  const name = nodeFormName.value.trim()
  if (!name) {
    nodeOperationError.value = '请输入节点名称。'
    return
  }

  isNodeSaving.value = true
  try {
    const selected = selectedGraphNode.value
    const isEdit = nodeOperationMode.value === 'edit'
    const url = isEdit && selected ? `/api/graph/nodes/${encodeURIComponent(selected.id)}` : '/api/graph/nodes'
    const body = isEdit
      ? { name }
      : {
          type: nodeFormType.value,
          name,
          parentId: nodeFormParentId.value,
          relationType: nodeFormType.value === '属性值' ? nodeFormRelationType.value : '有',
        }
    const response = await fetch(url, {
      method: isEdit ? 'PATCH' : 'POST',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const payload = await response.json()
    if (!response.ok || payload.success === false) {
      nodeOperationError.value = payload.message ?? '节点操作失败。'
      return
    }
    const result = payload.result ?? {}
    const nextGraph = graphPayloadFromResponse(payload)
    if (!nextGraph) {
      nodeOperationError.value = '后端未返回刷新后的图谱数据。'
      return
    }
    applyGraphPayload(nextGraph, result.nodeId || selected?.id || '')
    nodeOperationMode.value = 'none'
    await refreshQueryResultAfterGraphChange()
  } catch {
    nodeOperationError.value = '节点操作失败，请检查后端服务。'
  } finally {
    isNodeSaving.value = false
  }
}

async function deleteSelectedNode() {
  const selected = selectedGraphNode.value
  if (!selected || !canDeleteSelectedNode.value) return
  const confirmed = window.confirm(`确认删除节点“${selected.name}”？`)
  if (!confirmed) return

  nodeOperationError.value = ''
  isNodeSaving.value = true
  try {
    const response = await fetch(`/api/graph/nodes/${encodeURIComponent(selected.id)}`, { method: 'DELETE', cache: 'no-store' })
    const payload = await response.json()
    if (!response.ok || payload.success === false) {
      nodeOperationError.value = payload.message ?? '节点删除失败。'
      return
    }
    const result = payload.result ?? {}
    const nextGraph = graphPayloadFromResponse(payload)
    if (!nextGraph) {
      nodeOperationError.value = '后端未返回刷新后的图谱数据。'
      return
    }
    applyGraphPayload(nextGraph)
    selectedOntologyNodeId.value = ''
    selectedFaultNodeId.value = ''
    await refreshQueryResultAfterGraphChange()
  } catch {
    nodeOperationError.value = '节点删除失败，请检查后端服务。'
  } finally {
    isNodeSaving.value = false
  }
}

function routeQueryText() {
  const keys = ['text', 'query', 'q', 'faultMode', 'name', 'keyword', 'content']
  for (const key of keys) {
    const value = route.query[key]
    const rawText = Array.isArray(value) ? value[0] : value
    const text = String(rawText ?? '').trim()
    if (text) return text
  }
  return ''
}

async function applyRouteQuery() {
  const text = routeQueryText()
  if (!text) return
  if (text === lastAutoQuery.value && queryResult.value) return

  query.value = text
  activeView.value = 'fault'
  await nextTick()
  lastAutoQuery.value = text
  await runQuery()
}

async function runQuery() {
  const text = query.value.trim()
  queryError.value = ''
  if (!text) {
    queryError.value = '请输入故障现象'
    return
  }

  isQuerying.value = true
  try {
    const response = await fetch('/api/query', {
      method: 'POST',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    })
    const payload = await response.json()
    if (!response.ok) {
      queryError.value = payload.message ?? '查询失败，请稍后重试'
      return
    }
    queryResult.value = payload.result as QueryResult
    currentQuery.value = text
    activeView.value = 'fault'
    selectedFaultNodeId.value = queryResult.value.nodeId || selectedFaultNodeId.value
    if (!graph.value) await loadGraph({ resetViewState: false })
    await nextTick()
    selectedFaultTreeId.value = faultTreeIdByNodeId.value.get(selectedFaultNodeId.value) ?? selectedFaultTreeId.value
    syncFaultExpandedState(selectedFaultNodeId.value)
    syncGraphBoardCenter()
  } catch {
    queryError.value = '查询失败，请检查 Flask 服务是否正常'
  } finally {
    isQuerying.value = false
  }
}

function switchView(nextView: AppView) {
  activeView.value = nextView
  if (nextView === 'ontology') {
    syncOntologyExpandedState()
    ensureGraphLoadedForOntology()
  } else {
    syncFaultExpandedState()
  }
  syncGraphBoardCenter()
  if (nextView === 'ontology') syncOntologyMapBoardCenter()
}

function selectNode(nodeId: string) {
  if (isOntologyView.value) {
    if (builderOntologyNodeMap.has(nodeId)) {
      const label = builderOntologyNodeMap.get(nodeId)?.name ?? ''
      const treeId = ontologyMapTreeIdByLabel.value.get(nodeId) ?? ontologyMapTreeIdByLabel.value.get(label)
      const treeNode = treeId ? ontologyTreeNodeMap.value.get(treeId) : null
      if (treeNode) selectOntologyTreeNode(treeNode)
      return
    }

    isInitialOntologySampleMode.value = false
    const normalizedNodeId = normalizeGraphNodeId(nodeId)
    selectedOntologyNodeId.value = normalizedNodeId
    selectedOntologyTreeId.value = ontologyTreeIdByNodeId.value.get(normalizedNodeId) ?? selectedOntologyTreeId.value
    syncOntologyExpandedState(normalizedNodeId)
  } else {
    const normalizedNodeId = normalizeGraphNodeId(nodeId)
    selectedFaultNodeId.value = normalizedNodeId
    selectedFaultTreeId.value = faultTreeIdByNodeId.value.get(normalizedNodeId) ?? selectedFaultTreeId.value
    syncFaultExpandedState(normalizedNodeId)
  }
}

async function selectTopMatch(match: QueryTopMatch) {
  activeView.value = 'fault'
  selectedFaultNodeId.value = match.id
  selectedFaultTreeId.value = faultTreeIdByNodeId.value.get(match.id) ?? selectedFaultTreeId.value
  syncFaultExpandedState(match.id)

  const text = currentQuery.value || query.value.trim()
  const previousTopMatches = queryResult.value?.topMatches ?? []
  if (!text) {
    syncGraphBoardCenter()
    return
  }

  queryError.value = ''
  isQuerying.value = true
  try {
    const response = await fetch('/api/query/node', {
      method: 'POST',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text,
        nodeId: match.id,
        topMatches: previousTopMatches.length ? previousTopMatches : topMatches.value,
      }),
    })
    const payload = await response.json()
    if (!response.ok) {
      queryError.value = payload.message ?? '候选结果切换失败，请重新查询'
      return
    }

    const nextResult = payload.result as QueryResult
    queryResult.value = {
      ...nextResult,
      topMatches: previousTopMatches.length ? previousTopMatches : nextResult.topMatches,
    }
    currentQuery.value = text
    selectedFaultNodeId.value = nextResult.nodeId || match.id
    if (!graph.value) await loadGraph({ resetViewState: false })
    await nextTick()
    selectedFaultTreeId.value = faultTreeIdByNodeId.value.get(selectedFaultNodeId.value) ?? selectedFaultTreeId.value
    syncFaultExpandedState(selectedFaultNodeId.value)
    syncGraphBoardCenter()
  } catch {
    queryError.value = '候选结果切换失败，请检查 Flask 服务是否正常'
  } finally {
    isQuerying.value = false
  }
}

function selectOntologyTreeNode(treeNode: TreeNode) {
  isInitialOntologySampleMode.value = false
  selectedOntologyTreeId.value = treeNode.id

  if (isOntologyTemplateTreeNode(treeNode)) {
    selectedOntologyNodeId.value = ''
    syncOntologyExpandedState('')
    return
  }

  if (treeNode.nodeId) {
    const normalizedNodeId = normalizeGraphNodeId(treeNode.nodeId)
    selectedOntologyNodeId.value = normalizedNodeId
    syncOntologyExpandedState(normalizedNodeId)
    return
  }

  if (treeNode.graphNodeIds.length === 1) {
    selectedOntologyNodeId.value = normalizeGraphNodeId(treeNode.graphNodeIds[0] ?? '')
    syncOntologyExpandedState(selectedOntologyNodeId.value)
    return
  }

  selectedOntologyNodeId.value = ''
  syncOntologyExpandedState('')
}

function selectOntologyMapNode(typeKey: string) {
  const treeId = ontologyMapTreeIdByLabel.value.get(typeKey)
  if (!treeId) return

  const treeNode = ontologyTreeNodeMap.value.get(treeId)
  if (treeNode) selectOntologyTreeNode(treeNode)
}

function selectFaultTreeNode(treeNode: TreeNode) {
  selectedFaultTreeId.value = treeNode.id
  if (!treeNode.nodeId) return

  selectedFaultNodeId.value = treeNode.nodeId
  syncFaultExpandedState(treeNode.nodeId)
}

function topMatchTitle(match: QueryTopMatch) {
  const parts = [
    `节点：${match.name}`,
    `类型：${match.level}`,
    match.owner ? `对象：${match.owner}` : '',
    `匹配度：${match.confidence}%`,
    match.matchedKeywords.length ? `命中词：${match.matchedKeywords.join(' / ')}` : '',
  ]
  return parts.filter(Boolean).join('\n')
}

function toggleExpanded(nodeId: string) {
  if (isOntologyView.value) {
    expandedOntologyIds.value = expandedOntologyIds.value.includes(nodeId)
      ? expandedOntologyIds.value.filter((id) => id !== nodeId)
      : [...expandedOntologyIds.value, nodeId]
    return
  }

  expandedFaultIds.value = expandedFaultIds.value.includes(nodeId)
    ? expandedFaultIds.value.filter((id) => id !== nodeId)
    : [...expandedFaultIds.value, nodeId]
}

function openGraphZoom() {
  zoomGraphPositions.value = { ...currentPageGraphPositions.value }
  isGraphZoomOpen.value = true
  syncGraphBoardCenter()
}

function closeGraphZoom() {
  isGraphZoomOpen.value = false
}

function createZoomScrollSync(
  board: HTMLElement | null,
  previousScale: number,
  nextScale: number,
  anchor?: { x: number; y: number },
) {
  if (!board) return null
  const anchorX = anchor?.x ?? board.clientWidth / 2
  const anchorY = anchor?.y ?? board.clientHeight / 2
  const contentX = (board.scrollLeft + anchorX) / previousScale
  const contentY = (board.scrollTop + anchorY) / previousScale

  return () => {
    board.scrollLeft = Math.max(contentX * nextScale - anchorX, 0)
    board.scrollTop = Math.max(contentY * nextScale - anchorY, 0)
  }
}

function graphZoomBoards(focusBoard?: HTMLElement | null) {
  if (focusBoard) return [focusBoard]
  return [graphBoardRef.value, zoomBoardRef.value].filter((board): board is HTMLElement => Boolean(board))
}

function setGraphZoom(nextScale: number, anchor?: { board?: HTMLElement | null; x: number; y: number }) {
  if (!Number.isFinite(nextScale) || nextScale <= 0) return
  const previousScale = graphZoomScale.value
  const nextZoomScale = Math.min(GRAPH_MAX_ZOOM, Number(nextScale.toFixed(3)))
  if (Math.abs(nextZoomScale - previousScale) < 0.001) return

  const scrollSyncs = graphZoomBoards(anchor?.board).map((board) => createZoomScrollSync(
    board,
    previousScale,
    nextZoomScale,
    anchor?.board === board ? { x: anchor.x, y: anchor.y } : undefined,
  ))

  graphZoomScale.value = nextZoomScale
  void nextTick(() => {
    for (const sync of scrollSyncs) sync?.()
  })
}

function zoomGraph(direction: 1 | -1) {
  const factor = 1 + GRAPH_ZOOM_STEP
  setGraphZoom(direction > 0 ? graphZoomScale.value * factor : graphZoomScale.value / factor)
}

function resetGraphZoom() {
  setGraphZoom(1)
}

function handleGraphWheel(event: WheelEvent) {
  event.preventDefault()
  const board = event.currentTarget instanceof HTMLElement ? event.currentTarget : null
  const rect = board?.getBoundingClientRect()
  const factor = 1 + GRAPH_ZOOM_STEP
  const nextScale = event.deltaY < 0 ? graphZoomScale.value * factor : graphZoomScale.value / factor
  setGraphZoom(nextScale, rect && board
    ? { board, x: event.clientX - rect.left, y: event.clientY - rect.top }
    : undefined)
}

function setOntologyMapZoom(nextScale: number, anchor?: { board?: HTMLElement | null; x: number; y: number }) {
  if (!Number.isFinite(nextScale) || nextScale <= 0) return
  const previousScale = ontologyMapZoomScale.value
  const nextZoomScale = Math.min(ONTOLOGY_MAP_MAX_ZOOM, Number(nextScale.toFixed(3)))
  if (Math.abs(nextZoomScale - previousScale) < 0.001) return

  const board = anchor?.board ?? ontologyMapBoardRef.value
  const anchorPoint = anchor && anchor.board === board ? { x: anchor.x, y: anchor.y } : undefined
  const scrollSync = createZoomScrollSync(board, previousScale, nextZoomScale, anchorPoint)

  ontologyMapZoomScale.value = nextZoomScale
  void nextTick(() => scrollSync?.())
}

function zoomOntologyMap(direction: 1 | -1) {
  const factor = 1 + ONTOLOGY_MAP_ZOOM_STEP
  setOntologyMapZoom(direction > 0 ? ontologyMapZoomScale.value * factor : ontologyMapZoomScale.value / factor)
}

function resetOntologyMapZoom() {
  setOntologyMapZoom(1)
}

function handleOntologyMapWheel(event: WheelEvent) {
  event.preventDefault()
  const board = event.currentTarget instanceof HTMLElement ? event.currentTarget : null
  const rect = board?.getBoundingClientRect()
  const factor = 1 + ONTOLOGY_MAP_ZOOM_STEP
  const nextScale = event.deltaY < 0 ? ontologyMapZoomScale.value * factor : ontologyMapZoomScale.value / factor
  setOntologyMapZoom(nextScale, rect && board
    ? { board, x: event.clientX - rect.left, y: event.clientY - rect.top }
    : undefined)
}

function centerScrollableBoard(board: HTMLElement | null) {
  if (!board) return
  board.scrollLeft = Math.max((board.scrollWidth - board.clientWidth) / 2, 0)
  board.scrollTop = Math.max((board.scrollHeight - board.clientHeight) / 2, 0)
}

function syncGraphBoardCenter() {
  void nextTick(() => {
    centerScrollableBoard(graphBoardRef.value)
    centerScrollableBoard(zoomBoardRef.value)
  })
}

function syncOntologyMapBoardCenter() {
  void nextTick(() => {
    centerScrollableBoard(ontologyMapBoardRef.value)
  })
}

function getSvgScale(target: EventTarget | null, viewWidth: number, viewHeight: number) {
  if (!(target instanceof SVGElement)) return null
  const svg = target.closest('svg')
  if (!(svg instanceof SVGSVGElement)) return null

  const rect = svg.getBoundingClientRect()
  return {
    scaleX: viewWidth / (rect.width || viewWidth),
    scaleY: viewHeight / (rect.height || viewHeight),
  }
}

function clampGraphPoint(point: NodePoint, radius: number, canvasWidth = GRAPH_WIDTH): NodePoint {
  return {
    x: Math.min(Math.max(point.x, radius + 20), canvasWidth - radius - 20),
    y: Math.max(point.y, radius + 20),
  }
}

function clampOntologyMapPoint(point: NodePoint, radius: number): NodePoint {
  return {
    x: Math.min(Math.max(point.x, radius + 16), ONTOLOGY_MAP_WIDTH - radius - 16),
    y: Math.min(Math.max(point.y, radius + 16), ONTOLOGY_MAP_HEIGHT - radius - 16),
  }
}

function startGraphDrag(event: PointerEvent, nodeId: string, target: 'ontologyPage' | 'faultPage' | 'zoom') {
  if (event.button !== 2) return

  const map = target === 'zoom' ? zoomRenderNodeMap.value : pageRenderNodeMap.value
  const canvasHeight = target === 'zoom' ? zoomGraphCanvasHeight.value : pageGraphCanvasHeight.value
  const canvasWidth = target === 'zoom' ? zoomGraphCanvasWidth.value : pageGraphCanvasWidth.value
  const node = map.get(nodeId)
  const scale = getSvgScale(event.currentTarget, canvasWidth, canvasHeight)
  if (!node || !scale) return

  dragState.value = {
    kind: 'graph',
    target,
    id: nodeId,
    startClientX: event.clientX,
    startClientY: event.clientY,
    originX: node.x,
    originY: node.y,
    radius: node.r,
    canvasWidth,
    scaleX: scale.scaleX,
    scaleY: scale.scaleY,
  }
  event.preventDefault()
}

function startOntologyMapDrag(event: PointerEvent, key: string) {
  if (event.button !== 2) return

  const node = ontologyMapNodeMap.value.get(key)
  const scale = getSvgScale(event.currentTarget, ONTOLOGY_MAP_WIDTH, ONTOLOGY_MAP_HEIGHT)
  if (!node || !scale) return

  dragState.value = {
    kind: 'ontology',
    key,
    startClientX: event.clientX,
    startClientY: event.clientY,
    originX: node.x,
    originY: node.y,
    radius: node.r,
    scaleX: scale.scaleX,
    scaleY: scale.scaleY,
  }
  event.preventDefault()
}

function handlePointerMove(event: PointerEvent) {
  const active = dragState.value
  if (!active) return

  const nextPoint = {
    x: active.originX + (event.clientX - active.startClientX) * active.scaleX,
    y: active.originY + (event.clientY - active.startClientY) * active.scaleY,
  }

  if (active.kind === 'graph') {
    setGraphNodePosition(active.target, active.id, clampGraphPoint(nextPoint, active.radius, active.canvasWidth))
    return
  }

  ontologyMapPositions.value = {
    ...ontologyMapPositions.value,
    [active.key]: clampOntologyMapPoint(nextPoint, active.radius),
  }
}

function stopDrag() {
  if (!dragState.value) return
  dragState.value = null
}

function suppressGraphAreaContextMenu(event: MouseEvent) {
  const target = event.target
  if (!(target instanceof Element)) return
  if (target.closest('.graph-board, .zoom-board, .ontology-map-board')) {
    event.preventDefault()
  }
}

function syncViewportScale() {
  const host = props.embedded ? viewportRef.value : null
  const availableWidth = Math.max((host?.clientWidth || window.innerWidth) - 12, 320)
  const availableHeight = Math.max((host?.clientHeight || window.innerHeight) - 12, 320)
  viewportScale.value = props.embedded
    ? availableWidth / STAGE_WIDTH
    : Math.min(availableWidth / STAGE_WIDTH, availableHeight / STAGE_HEIGHT)
}

onMounted(async () => {
  syncViewportScale()
  window.addEventListener('resize', syncViewportScale)
  window.addEventListener('pointermove', handlePointerMove)
  window.addEventListener('pointerup', stopDrag)
  window.addEventListener('pointercancel', stopDrag)
  window.addEventListener('contextmenu', suppressGraphAreaContextMenu)
  syncOntologyExpandedState()
  await applyRouteQuery()
  ensureGraphLoadedForOntology()
})

watch(() => route.fullPath, () => {
  void applyRouteQuery()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', syncViewportScale)
  window.removeEventListener('pointermove', handlePointerMove)
  window.removeEventListener('pointerup', stopDrag)
  window.removeEventListener('pointercancel', stopDrag)
  window.removeEventListener('contextmenu', suppressGraphAreaContextMenu)
})

const TreeBranch: ReturnType<typeof defineComponent> = defineComponent({
  name: 'TreeBranch',
  props: {
    node: {
      type: Object as () => TreeNode,
      required: true,
    },
    activeTreeId: {
      type: String,
      required: true,
    },
    activeNodeId: {
      type: String,
      required: true,
    },
    expandedIds: {
      type: Array as () => string[],
      required: true,
    },
    tone: {
      type: String,
      required: true,
    },
  },
  emits: ['select', 'toggle'],
  setup(props, { emit }): () => VNodeChild {
    const isExpanded = () => props.expandedIds.includes(props.node.id)
    const hasChildren = () => Boolean(props.node.children?.length)
    const isActive = () => props.activeTreeId
      ? props.activeTreeId === props.node.id
      : Boolean(props.node.nodeId && props.activeNodeId === props.node.nodeId)

    return () => h('li', { class: 'tree-item' }, [
      h('div', { class: 'tree-row' }, [
        hasChildren()
          ? h(
            'button',
            {
              class: 'tree-toggle',
              onClick: () => emit('toggle', props.node.id),
              'aria-label': isExpanded() ? '收起' : '展开',
            },
            h('span', { class: ['tree-toggle-icon', { expanded: isExpanded() }] }, '›'),
          )
          : h('span', { class: 'tree-toggle tree-toggle--ghost' }, h('span', { class: 'tree-leaf-dot' })),
        h(
          'button',
          {
            class: ['tree-button', `tree-button--${props.tone}`, { active: isActive() }],
            onClick: () => emit('select', props.node),
          },
          [
            h('span', { class: 'tree-label' }, props.node.label),
            props.node.meta
              ? h('span', { class: 'tree-meta' }, [
                h('span', { class: 'tree-meta-pill' }, props.node.meta),
              ])
              : null,
          ],
        ),
      ]),
      props.node.children?.length && isExpanded()
        ? h(
          'ul',
          { class: 'tree-children' },
          props.node.children.map((child) => h(TreeBranch, {
            node: child,
            activeTreeId: props.activeTreeId,
            activeNodeId: props.activeNodeId,
            expandedIds: props.expandedIds,
            tone: props.tone,
            onSelect: (node: TreeNode) => emit('select', node),
            onToggle: (id: string) => emit('toggle', id),
          })),
        )
        : null,
    ])
  },
})
</script>

<template>
  <div ref="viewportRef" :class="['viewport', { 'viewport--embedded': props.embedded }]">
    <div class="stage-shell" :style="{ height: `${STAGE_HEIGHT * viewportScale}px` }">
      <div class="stage" :style="{ width: `${STAGE_WIDTH}px`, height: `${STAGE_HEIGHT}px`, transform: `scale(${viewportScale})` }">
        <div :class="['page', { 'page--embedded': props.embedded }]">
          <aside v-if="!props.embedded" class="sidebar">
            <div class="brand-block">
              <div class="brand-kicker">Knowledge Graph</div>
              <div class="brand">智能排故知识图谱系统</div>
              <p class="brand-note">通过菜单切换图谱展示与故障链查询，分别查看全量结构与诊断链路。</p>
            </div>

            <section class="side-panel menu-panel">
              <div class="eyebrow dark">功能菜单</div>
              <div class="menu-list">
                <button type="button" :class="['menu-item', { active: activeView === 'ontology' }]" @click="switchView('ontology')">
                  <span class="menu-item-index">01</span>
                  <span class="menu-item-body">
                    <span class="menu-item-title">图谱展示</span>
                    <span class="menu-item-note">浏览图谱树与全量图谱关系</span>
                  </span>
                </button>
                <button type="button" :class="['menu-item', { active: activeView === 'fault' }]" @click="switchView('fault')">
                  <span class="menu-item-index">02</span>
                  <span class="menu-item-body">
                    <span class="menu-item-title">故障链查询</span>
                    <span class="menu-item-note">输入故障现象并查看推演链路</span>
                  </span>
                </button>
              </div>
            </section>

            <section class="side-panel">
              <div class="eyebrow dark">当前焦点</div>
              <p class="query-text">{{ currentFocusLabel }}</p>
            </section>

            <section class="side-panel">
              <div class="eyebrow dark">数据状态</div>
              <ul class="side-list">
                <li>{{ graph ? `图谱节点 ${graph.stats.nodeCount} 个` : '图谱数据加载中' }}</li>
                <li>{{ graph ? `图谱关系 ${graph.stats.edgeCount} 条` : '图谱数据加载中' }}</li>
                <li>{{ queryResult ? '查询结果已联动' : '等待发起查询' }}</li>
              </ul>
            </section>
          </aside>

          <main :class="['main', isOntologyView ? 'main--ontology' : 'main--fault']">
            <template v-if="isOntologyView">
              <section class="view-grid view-grid--ontology">
                <section class="card tree-card">
                  <div class="eyebrow">图谱树</div>
                  <ul v-if="graphOntologyTree" class="tree-root">
                    <TreeBranch :node="graphOntologyTree" :active-tree-id="selectedOntologyTreeId" :active-node-id="selectedOntologyNodeId" :expanded-ids="expandedOntologyIds" tone="system" @select="selectOntologyTreeNode" @toggle="toggleExpanded" />
                  </ul>
                  <div v-else class="tree-empty">暂无图谱数据</div>
                </section>

                <section class="card graph-panel graph-panel--ontology">
                  <div class="panel-head">
                    <div>
                      <div class="eyebrow">{{ activeViewMeta.graphTitle }}</div>
                    </div>
                    <div class="panel-actions">
                      <div class="node-actions">
                        <button type="button" class="node-action" :disabled="isNodeSaving || !graph" @pointerdown.stop @click.prevent.stop="handleAddClick">新增</button>
                        <button type="button" class="node-action" :disabled="isNodeSaving || !canModifySelectedNode" @pointerdown.stop @click.prevent.stop="handleEditClick">修改</button>
                        <button type="button" class="node-action danger" :disabled="isNodeSaving || !canDeleteSelectedNode" @pointerdown.stop @click.stop="deleteSelectedNode">删除</button>
                      </div>
                      <div class="graph-legend">
                        <span class="graph-zoom-tools">
                          <button type="button" class="graph-zoom-btn" @click.stop="zoomGraph(-1)">-</button>
                          <button type="button" class="graph-zoom-value" @click.stop="resetGraphZoom">{{ graphZoomLabel }}</button>
                          <button type="button" class="graph-zoom-btn" @click.stop="zoomGraph(1)">+</button>
                        </span>
                        <span><i class="legend-dot legend-dot--orange"></i>实体对象</span>
                        <span><i class="legend-dot legend-dot--blue"></i>故障模式</span>
                        <span><i class="legend-dot legend-dot--green"></i>属性要素</span>
                        <span><i class="legend-dot legend-dot--bright-red"></i>功能</span>
                        <span><i class="legend-ring"></i>当前焦点</span>
                      </div>
                    </div>
                  </div>

                  <form v-if="nodeOperationMode !== 'none'" class="node-form node-form--floating" @submit.prevent="submitNodeOperation" @pointerdown.stop @click.stop>
                    <template v-if="nodeOperationMode === 'add'">
                      <label>
                        类型
                        <select v-model="nodeFormType">
                          <option value="属性值">属性值</option>
                          <option value="故障现象">故障现象</option>
                        </select>
                      </label>
                      <label>
                        所属节点
                        <select v-model="nodeFormParentId">
                          <option v-for="node in addParentOptions" :key="node.id" :value="node.id">{{ node.name }}（{{ node.level }}）</option>
                        </select>
                      </label>
                      <label v-if="nodeFormType === '属性值'">
                        关系
                        <select v-model="nodeFormRelationType">
                          <option v-for="item in attributeRelationOptions" :key="item" :value="item">{{ item }}</option>
                        </select>
                      </label>
                    </template>
                    <label>
                      名称
                      <input v-model="nodeFormName" type="text" placeholder="请输入节点名称" />
                    </label>
                    <div class="node-form-actions">
                      <button type="submit" class="node-action primary-action" :disabled="isNodeSaving || (nodeOperationMode === 'add' && !nodeFormParentId)">{{ isNodeSaving ? '保存中' : '保存' }}</button>
                      <button type="button" class="node-action" :disabled="isNodeSaving" @click="cancelNodeOperation">取消</button>
                    </div>
                    <p v-if="nodeOperationError" class="node-operation-error">{{ nodeOperationError }}</p>
                  </form>

                  <div ref="graphBoardRef" class="graph-board" role="button" tabindex="0" @click="openGraphZoom" @wheel="handleGraphWheel" @keydown.enter.prevent="openGraphZoom" @keydown.space.prevent="openGraphZoom" @contextmenu.prevent>
                    <div v-if="pageRenderNodes.length" class="canvas-center-wrap">
                      <svg :viewBox="`0 0 ${pageGraphCanvasWidth} ${pageGraphCanvasHeight}`" class="graph-svg" :style="pageGraphSvgStyle" aria-label="图谱视图">
                        <defs>
                          <marker id="graph-arrow" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto" markerUnits="strokeWidth">
                            <path d="M 1 1 L 10 6 L 1 11 z" class="graph-arrow-head" />
                          </marker>
                        </defs>
                        <g v-for="edge in pageRenderEdges" :key="`${edge.from}-${edge.to}-${edge.label}`">
                          <path :d="edge.path" class="graph-edge" marker-end="url(#graph-arrow)" />
                          <text v-if="edge.labelText" :x="edge.labelX" :y="edge.labelY" class="graph-edge-label" text-anchor="middle">
                            {{ edge.labelText }}
                          </text>
                        </g>

                        <g
                          v-for="node in pageRenderNodes"
                          :key="node.id"
                          :class="['graph-node-wrap', { dragging: dragState?.kind === 'graph' && dragState.id === node.id }]"
                          @pointerdown.stop="startGraphDrag($event, node.id, 'ontologyPage')"
                          @contextmenu.prevent
                          @click.stop="selectNode(node.id)"
                        >
                          <title>{{ node.name }}</title>
                          <circle
                            :cx="node.x"
                            :cy="node.y"
                            :r="node.r"
                            :fill="node.fill"
                            :class="['graph-node', { active: graphActiveNodeId === node.id }]"
                          />
                          <text :x="node.x" :y="node.y - 6" class="graph-node-text" text-anchor="middle">
                            <tspan :x="node.x" class="graph-node-name">{{ node.shortName }}</tspan>
                            <tspan :x="node.x" dy="18" class="graph-node-level">{{ node.level }}</tspan>
                          </text>
                        </g>
                      </svg>
                    </div>
                    <div v-else class="empty">{{ isLoading ? '加载图谱中...' : '暂无数据' }}</div>
                  </div>
                </section>
              </section>
            </template>

            <template v-else>
              <section class="card query-panel">
                <div class="query-head">
                  <div>
                    <div class="eyebrow">故障检索</div>
                    <h2>故障链查询</h2>
                  </div>
                </div>

                <div class="query-body">
                  <textarea class="query-input" v-model="query" placeholder="请输入故障现象，例如“液氧阀打不开”" @keydown.enter.prevent="runQuery" />
                  <button class="primary query-action" :disabled="isQuerying || isLoading" @click="runQuery">
                    {{ isQuerying ? '查询中...' : '点击查询' }}
                  </button>
                </div>
                <p v-if="graphError || queryError" class="hint">{{ graphError || queryError }}</p>
                <div v-if="topMatches.length" class="top-matches">
                  <div class="top-matches-head">
                    <span>Top 5 候选结果</span>
                    <span>按匹配度排序</span>
                  </div>
                  <div class="top-match-list">
                    <button
                      v-for="match in topMatches"
                      :key="match.id"
                      type="button"
                      :class="['top-match', { active: selectedFaultNodeId === match.id }]"
                      :title="topMatchTitle(match)"
                      @click="selectTopMatch(match)"
                    >
                      <span class="top-match-rank">{{ match.rank }}</span>
                      <span class="top-match-main">
                        <span class="top-match-name">{{ match.name }}</span>
                        <span class="top-match-meta">
                          <span>{{ match.level }}</span>
                          <span v-if="match.owner">{{ match.owner }}</span>
                          <span v-if="match.matchedKeywords.length">{{ match.matchedKeywords.slice(0, 3).join(' / ') }}</span>
                        </span>
                      </span>
                      <span class="top-match-score">{{ match.confidence }}%</span>
                    </button>
                  </div>
                </div>
              </section>

              <section class="content-grid">
                <section class="card graph-panel">
                  <div class="panel-head">
                    <div>
                      <div class="eyebrow">{{ activeViewMeta.graphTitle }}</div>
                    </div>
                    <div class="graph-legend">
                      <span class="graph-zoom-tools">
                        <button type="button" class="graph-zoom-btn" @click.stop="zoomGraph(-1)">-</button>
                        <button type="button" class="graph-zoom-value" @click.stop="resetGraphZoom">{{ graphZoomLabel }}</button>
                        <button type="button" class="graph-zoom-btn" @click.stop="zoomGraph(1)">+</button>
                      </span>
                      <span><i class="legend-dot legend-dot--orange"></i>实体对象</span>
                      <span><i class="legend-dot legend-dot--blue"></i>故障模式</span>
                      <span><i class="legend-dot legend-dot--green"></i>属性要素</span>
                      <span><i class="legend-dot legend-dot--bright-red"></i>功能</span>
                      <span><i class="legend-ring"></i>当前焦点</span>
                    </div>
                  </div>

                  <div ref="graphBoardRef" class="graph-board" role="button" tabindex="0" @click="openGraphZoom" @wheel="handleGraphWheel" @keydown.enter.prevent="openGraphZoom" @keydown.space.prevent="openGraphZoom" @contextmenu.prevent>
                    <div v-if="pageRenderNodes.length" class="canvas-center-wrap">
                      <svg :viewBox="`0 0 ${pageGraphCanvasWidth} ${pageGraphCanvasHeight}`" class="graph-svg" :style="pageGraphSvgStyle" aria-label="图谱视图">
                        <defs>
                          <marker id="graph-arrow" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto" markerUnits="strokeWidth">
                            <path d="M 1 1 L 10 6 L 1 11 z" class="graph-arrow-head" />
                          </marker>
                        </defs>
                        <g v-for="edge in pageRenderEdges" :key="`${edge.from}-${edge.to}-${edge.label}`">
                          <path :d="edge.path" class="graph-edge" marker-end="url(#graph-arrow)" />
                          <text v-if="edge.labelText" :x="edge.labelX" :y="edge.labelY" class="graph-edge-label" text-anchor="middle">
                            {{ edge.labelText }}
                          </text>
                        </g>

                        <g
                          v-for="node in pageRenderNodes"
                          :key="node.id"
                          :class="['graph-node-wrap', { dragging: dragState?.kind === 'graph' && dragState.id === node.id }]"
                          @pointerdown.stop="startGraphDrag($event, node.id, 'faultPage')"
                          @contextmenu.prevent
                          @click.stop="selectNode(node.id)"
                        >
                          <title>{{ node.name }}</title>
                          <circle
                            :cx="node.x"
                            :cy="node.y"
                            :r="node.r"
                            :fill="node.fill"
                            :class="['graph-node', { active: graphActiveNodeId === node.id }]"
                          />
                          <text :x="node.x" :y="node.y - 6" class="graph-node-text" text-anchor="middle">
                            <tspan :x="node.x" class="graph-node-name">{{ node.shortName }}</tspan>
                            <tspan :x="node.x" dy="18" class="graph-node-level">{{ node.level }}</tspan>
                          </text>
                        </g>
                      </svg>
                    </div>
                    <div v-else class="empty">{{ isLoading ? '加载图谱中...' : '暂无数据' }}</div>
                  </div>
                </section>

                <section class="side-column">
                  <section class="card tree-card">
                    <div class="eyebrow">故障推演链</div>
                    <ul v-if="faultTree" class="tree-root">
                      <TreeBranch :node="faultTree" :active-tree-id="selectedFaultTreeId" :active-node-id="selectedFaultNodeId" :expanded-ids="expandedFaultIds" tone="fault" @select="selectFaultTreeNode" @toggle="toggleExpanded" />
                    </ul>
                    <div v-else class="tree-empty">暂无推演结果</div>
                  </section>
                </section>
              </section>
            </template>
          </main>
        </div>
      </div>
    </div>
  </div>
  <div v-if="isGraphZoomOpen" class="zoom-overlay" @click.self="closeGraphZoom">
    <div class="zoom-dialog">
      <div class="zoom-head">
        <div>
          <div class="eyebrow">知识图谱放大查看</div>
          <h2>统一视图</h2>
        </div>
        <div class="zoom-actions">
          <button type="button" class="graph-zoom-btn" @click="zoomGraph(-1)">-</button>
          <button type="button" class="graph-zoom-value" @click="resetGraphZoom">{{ graphZoomLabel }}</button>
          <button type="button" class="graph-zoom-btn" @click="zoomGraph(1)">+</button>
          <button class="zoom-close" type="button" @click="closeGraphZoom">关闭</button>
        </div>
      </div>
      <div ref="zoomBoardRef" class="zoom-board" @wheel="handleGraphWheel" @contextmenu.prevent>
        <div v-if="zoomRenderNodes.length" class="canvas-center-wrap">
          <svg :viewBox="`0 0 ${zoomGraphCanvasWidth} ${zoomGraphCanvasHeight}`" class="zoom-svg" :style="zoomGraphSvgStyle" aria-label="图谱放大视图">
            <defs>
              <marker id="zoom-graph-arrow" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto" markerUnits="strokeWidth">
                <path d="M 1 1 L 10 6 L 1 11 z" class="graph-arrow-head" />
              </marker>
            </defs>
            <g v-for="edge in zoomRenderEdges" :key="`zoom-${edge.from}-${edge.to}-${edge.label}`">
              <path :d="edge.path" class="graph-edge" marker-end="url(#zoom-graph-arrow)" />
              <text v-if="edge.labelText" :x="edge.labelX" :y="edge.labelY" class="graph-edge-label" text-anchor="middle">
                {{ edge.labelText }}
              </text>
            </g>
            <g
              v-for="node in zoomRenderNodes"
              :key="`zoom-${node.id}`"
              :class="['graph-node-wrap', { dragging: dragState?.kind === 'graph' && dragState.id === node.id }]"
              @pointerdown.stop="startGraphDrag($event, node.id, 'zoom')"
              @contextmenu.prevent
              @click="selectNode(node.id)"
            >
              <title>{{ node.name }}</title>
              <circle
                :cx="node.x"
                :cy="node.y"
                :r="node.r"
                :fill="node.fill"
                :class="['graph-node', { active: graphActiveNodeId === node.id }]"
              />
              <text :x="node.x" :y="node.y - 6" class="graph-node-text" text-anchor="middle">
                <tspan :x="node.x" class="graph-node-name">{{ node.shortName }}</tspan>
                <tspan :x="node.x" dy="18" class="graph-node-level">{{ node.level }}</tspan>
              </text>
            </g>
          </svg>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
:global(body){margin:0;font-family:"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:linear-gradient(180deg,#eef4fb,#f8fbff);color:#13253f}
:global(*){box-sizing:border-box}
.viewport{min-height:100vh;padding:6px;overflow:hidden}
.viewport--embedded{height:100%;min-height:0;padding:0;overflow:auto}
.stage-shell{position:relative;width:100%;display:flex;justify-content:center;align-items:flex-start}
.stage{transform-origin:top center}
.page{width:1600px;height:900px;display:grid;grid-template-columns:276px minmax(0,1fr);overflow:hidden;border-radius:28px;box-shadow:0 18px 44px rgba(22,47,89,.12)}
.page--embedded{grid-template-columns:minmax(0,1fr);border-radius:8px}
.sidebar{padding:20px 16px;background:linear-gradient(180deg,#0b1a31,#0f2b4d 58%,#133a69);color:#edf5ff;overflow:auto}
.brand-block{padding:6px 4px 12px}
.brand-kicker{font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:#95baff}
.brand{margin-top:10px;font-size:30px;font-weight:900;line-height:1.04}
.brand-note{margin:12px 0 0;color:#c0d3ee;line-height:1.5;font-size:13px}
.side-panel{margin-top:16px;padding:16px;border-radius:22px;background:rgba(146,181,242,.11);border:1px solid rgba(198,216,245,.14)}
.eyebrow{display:inline-flex;align-items:center;min-height:28px;padding:0 10px;border-radius:999px;background:#ebf2ff;color:#4c6998;font-size:12px;font-weight:800}
.eyebrow.dark{background:rgba(239,246,255,.12);color:#d8e7ff}
.query-text{margin:10px 0 0;font-size:26px;font-weight:900;color:#fff;line-height:1.15}
.side-list{margin:10px 0 0;padding-left:18px;display:grid;gap:8px;color:#c0d3ee}
.menu-panel{padding:12px}
.menu-list{display:grid;gap:10px;margin-top:12px}
.menu-item{width:100%;border:1px solid rgba(198,216,245,.18);border-radius:18px;background:rgba(255,255,255,.04);padding:12px;display:grid;grid-template-columns:34px minmax(0,1fr);gap:10px;align-items:start;color:#eaf3ff;text-align:left;cursor:pointer;transition:transform .18s ease,border-color .18s ease,background .18s ease;box-shadow:none}
.menu-item:hover{transform:translateY(-1px);border-color:rgba(147,189,255,.42);background:rgba(255,255,255,.07)}
.menu-item.active{border-color:#8ab2ff;background:linear-gradient(180deg,rgba(92,141,232,.22),rgba(49,87,163,.18));box-shadow:inset 0 0 0 1px rgba(157,193,255,.22)}
.menu-item-index{width:34px;height:34px;border-radius:12px;display:grid;place-items:center;background:rgba(255,255,255,.12);color:#9fc0ff;font-size:12px;font-weight:900}
.menu-item-body{min-width:0;display:grid;gap:4px}
.menu-item-title{font-size:14px;font-weight:900;color:#fff}
.menu-item-note{font-size:11px;line-height:1.4;color:#bdd1ef}
.main{padding:18px;display:grid;gap:14px;overflow:hidden;min-height:0;min-width:0}
.main--ontology{grid-template-rows:minmax(0,1fr)}
.main--fault{grid-template-rows:auto minmax(0,1fr)}
.view-header{display:flex;align-items:center;min-height:118px}
.view-header-copy{display:grid;gap:6px}
.view-header h2{margin:0;font-size:28px;line-height:1.05;color:#17355e}
.view-header-note{margin:0;color:#617694;font-size:14px;line-height:1.5}
.view-grid{display:grid;gap:14px;min-height:0;overflow:hidden;align-items:stretch}
.view-grid--ontology{grid-template-columns:340px minmax(0,1fr)}
.card{background:rgba(255,255,255,.94);border:1px solid #dbe6f3;border-radius:22px;padding:14px;box-shadow:0 18px 44px rgba(22,47,89,.08)}
.query-panel{display:grid;gap:6px}
.query-head{display:flex;justify-content:flex-start;align-items:flex-start;gap:16px}
.query-head h2{margin:4px 0 0;font-size:24px}
.primary{border:0;border-radius:999px;background:linear-gradient(135deg,#2d82ff,#134db7);color:#fff;font-weight:900;padding:0 14px;min-height:34px;cursor:pointer;box-shadow:0 12px 24px rgba(29,89,193,.22)}
.primary:disabled{opacity:.72;cursor:wait}
.query-body{display:grid;grid-template-columns:minmax(0,1fr) 104px;gap:12px;align-items:stretch}
textarea,.query-input{width:100%;min-height:64px;height:64px;border:1px solid #d7e2ef;border-radius:18px;padding:16px 16px 0;font:inherit;font-size:18px;line-height:1.35;resize:none;background:linear-gradient(180deg,#fbfdff,#f4f8ff)}
.query-input{overflow:hidden}
.query-action{width:100%;min-height:52px;height:52px;align-self:center;font-size:14px}
.hint{color:#b3354b;margin:0 2px}
.top-matches{display:grid;gap:8px}
.top-matches-head{display:flex;justify-content:space-between;align-items:center;gap:12px;color:#5f7391;font-size:12px;font-weight:800}
.top-match-list{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px}
.top-match{width:100%;min-width:0;border:1px solid #d9e5f2;border-radius:8px;background:linear-gradient(180deg,#fff,#f6f9ff);padding:8px;display:grid;grid-template-columns:24px minmax(0,1fr) auto;gap:7px;align-items:center;text-align:left;color:#17355e;cursor:pointer;box-shadow:0 8px 18px rgba(29,65,118,.07)}
.top-match:hover,.top-match.active{border-color:#7ba8f4;background:#eef5ff}
.top-match.active{box-shadow:inset 0 0 0 1px #2d82ff,0 10px 20px rgba(45,130,255,.12)}
.top-match-rank{width:24px;height:24px;border-radius:999px;display:grid;place-items:center;background:#dfeaff;color:#2359b0;font-size:12px;font-weight:900}
.top-match-main{min-width:0;display:grid;gap:3px}
.top-match-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px;font-weight:900}
.top-match-meta{display:flex;gap:6px;min-width:0;color:#6b7f9d;font-size:10px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.top-match-score{font-size:12px;font-weight:900;color:#0f766e}
.content-grid{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:14px;min-height:0;overflow:hidden;align-items:stretch}
.canvas-center-wrap{min-width:100%;width:max-content;min-height:100%;display:flex;justify-content:center;align-items:center}
.graph-panel{position:relative;display:grid;grid-template-rows:auto minmax(0,1fr);min-height:0;height:100%}
.graph-panel--ontology .graph-board{min-height:0}
.panel-head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px}
.panel-hint{max-width:460px}
.panel-actions{display:grid;gap:8px;justify-items:end;min-width:0}
.node-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:flex-end}
.node-action{border:1px solid #cbd8ea;border-radius:8px;background:#fff;color:#17355e;font:inherit;font-size:12px;font-weight:900;min-height:30px;padding:0 12px;cursor:pointer;box-shadow:0 6px 14px rgba(33,83,174,.08)}
.node-action:hover:not(:disabled){background:#eef5ff;border-color:#9ab7e8}
.node-action:disabled{opacity:.48;cursor:not-allowed;box-shadow:none}
.node-action.danger{color:#b4233a;border-color:#efc6cf}
.node-action.primary-action{background:#226ee6;border-color:#226ee6;color:#fff}
.node-form{margin-top:10px;padding:10px;border:1px solid #d8e3f1;border-radius:8px;background:#f8fbff;display:flex;align-items:end;gap:10px;flex-wrap:wrap}
.node-form--floating{position:absolute;top:60px;right:14px;left:auto;z-index:8;width:min(780px,calc(100% - 28px));box-shadow:0 18px 36px rgba(21,49,91,.18)}
.node-form label{display:grid;gap:4px;color:#5d718f;font-size:11px;font-weight:900}
.node-form input,.node-form select{height:32px;min-width:154px;border:1px solid #cddbed;border-radius:8px;background:#fff;color:#17355e;font:inherit;font-size:12px;padding:0 9px}
.node-form-actions{display:flex;gap:8px;align-items:center}
.node-operation-error{width:100%;margin:0;color:#b4233a;font-size:12px;font-weight:800}
.graph-legend{display:flex;gap:14px;flex-wrap:wrap;justify-content:flex-end;color:#627594;font-size:13px;font-weight:700}
.graph-legend span{display:inline-flex;align-items:center;gap:8px}
.graph-zoom-tools{padding:2px 6px;border-radius:999px;background:#eef5ff;border:1px solid #d7e3f2}
.graph-zoom-btn,.graph-zoom-value{border:0;border-radius:999px;background:#fff;color:#275aaf;font:inherit;font-weight:900;min-width:28px;height:26px;padding:0 9px;cursor:pointer;box-shadow:0 4px 12px rgba(33,83,174,.12)}
.graph-zoom-value{min-width:58px;color:#17355e}
.graph-zoom-btn:hover,.graph-zoom-value:hover{background:#dfeaff}
.legend-dot{width:12px;height:12px;border-radius:999px;display:inline-block}
.legend-dot--orange{background:#ff9b24}
.legend-dot--blue{background:#4f79d4}
.legend-dot--green{background:#8bd53f}
.legend-dot--red{background:#d71920}
.legend-dot--bright-red{background:#ff2d2d}
.legend-ring{width:12px;height:12px;border-radius:999px;display:inline-block;background:#fff;border:3px solid #ef1d2f;box-shadow:0 0 0 2px rgba(239,29,47,.18)}
.graph-board{position:relative;margin-top:12px;height:100%;min-height:420px;overflow:auto;scrollbar-gutter:stable both-edges;border-radius:20px;border:1px solid #d8e3f1;background:
radial-gradient(circle at 24px 24px,rgba(120,152,208,.14) 1.2px,transparent 1.2px),
linear-gradient(180deg,#ffffff,#eef5ff);
background-size:28px 28px,100% 100%;
box-shadow:inset 0 1px 0 rgba(255,255,255,.9);cursor:zoom-in}
.graph-svg{width:100%;min-width:1520px;display:block}
.graph-edge{fill:none;stroke:#5a86df;stroke-width:3;stroke-linecap:round;filter:drop-shadow(0 3px 6px rgba(90,134,223,.18))}
.graph-arrow-head{fill:#5a86df}
.graph-edge-label{font-size:12px;font-weight:900;fill:#275aaf;paint-order:stroke;stroke:rgba(255,255,255,.96);stroke-width:7px;stroke-linejoin:round;pointer-events:none}
.graph-node-wrap{cursor:grab;touch-action:none}
.graph-node-wrap.dragging{cursor:grabbing}
.graph-node{stroke:#3768c5;stroke-width:2;transition:all .2s ease;filter:drop-shadow(0 10px 20px rgba(28,55,102,.16))}
.graph-node.active{stroke:#ef1d2f;stroke-width:5;filter:drop-shadow(0 0 22px rgba(239,29,47,.34))}
.graph-node-text{pointer-events:none;paint-order:stroke;stroke:rgba(0,0,0,.08);stroke-width:2px;stroke-linejoin:round}
.graph-node-name{font-size:11px;font-weight:900;fill:#fff}
.graph-node-level{font-size:13px;font-weight:900;fill:#f3f8ff}
.empty{display:grid;place-items:center;min-height:100%;color:#6b81a4;font-weight:800}
.side-column{display:grid;grid-template-rows:minmax(0,1fr);gap:12px;min-height:0;height:100%}
.card-hint{margin:6px 0 0;color:#667a98;line-height:1.45;font-size:12px}
.tree-card{background:linear-gradient(180deg,rgba(255,255,255,.96),rgba(244,249,255,.92));display:flex;flex-direction:column;min-height:0;overflow:hidden;padding:14px 14px 14px 8px}
:deep(.tree-root),:deep(.tree-children){list-style:none;margin:12px 0 0;padding:0;overflow-y:auto;overflow-x:hidden;scrollbar-gutter:stable both-edges;flex:1;min-height:0}
:deep(.tree-root){padding-right:4px;padding-left:0;margin-left:-2px}
:deep(.tree-children){position:relative;margin:5px 0 0 6px;padding:2px 0 0 7px;overflow:visible}
:deep(.tree-children::before){content:"";position:absolute;left:2px;top:2px;bottom:12px;width:1px;background:linear-gradient(180deg,#dbe5f3,#eef4fb)}
:deep(.tree-item){position:relative;margin:8px 0}
:deep(.tree-item::before){content:"";position:absolute;left:2px;top:18px;width:6px;height:1px;background:#dfe8f4}
:deep(.tree-root > .tree-item::before){display:none}
:deep(.tree-row){display:grid;grid-template-columns:20px minmax(0,1fr);align-items:start;gap:5px}
:deep(.tree-toggle){width:20px;height:20px;border:0;background:transparent;color:#6d82a3;font:inherit;line-height:1;cursor:pointer;display:grid;place-items:center;box-shadow:none;padding:0;appearance:none;-webkit-appearance:none}
:deep(.tree-toggle:hover){color:#3e68c9}
:deep(.tree-toggle--ghost){cursor:default}
:deep(.tree-toggle-icon){display:block;font-size:18px;font-weight:900;transform:rotate(0deg);transition:transform .18s ease}
:deep(.tree-toggle-icon.expanded){transform:rotate(90deg)}
:deep(.tree-leaf-dot){width:6px;height:6px;border-radius:999px;background:#b8c8df;display:block;margin:auto}
:deep(.tree-button){position:relative;width:100%;text-align:left;border:0 !important;background:transparent !important;padding:3px 2px 3px 7px;color:#17355e;font:inherit;cursor:pointer;transition:transform .18s ease,color .18s ease;display:grid;gap:3px;box-shadow:none !important;outline:none !important;appearance:none;-webkit-appearance:none;border-radius:0}
:deep(.tree-button:hover){transform:translateX(1px);color:#0f4fa8}
:deep(.tree-button:focus),:deep(.tree-button:focus-visible){outline:none !important;box-shadow:none !important}
:deep(.tree-button.active){font-weight:700}
:deep(.tree-button--fault.active){color:#9f1239}
:deep(.tree-button--system.active){color:#0f766e}
:deep(.tree-button--fault::before),:deep(.tree-button--system::before){content:"";position:absolute;left:0;top:5px;bottom:5px;width:3px;border-radius:999px}
:deep(.tree-button--fault::before){background:linear-gradient(180deg,#ef4444,#b91c1c)}
:deep(.tree-button--system::before){background:linear-gradient(180deg,#2a9d8f,#167c6f)}
:deep(.tree-label){font-weight:700;font-size:13px;line-height:1.35;color:inherit}
:deep(.tree-meta){display:flex;flex-wrap:wrap;gap:6px}
:deep(.tree-meta-pill){display:inline-flex;align-items:center;min-height:16px;padding:0;color:#7b8da8;font-size:10px;font-weight:700;line-height:1.2;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;background:transparent}
.tree-empty{padding:12px;border-radius:14px;background:#fff;color:#6b7f9d;font-size:13px}
@media (max-width: 1200px){
  .query-body{grid-template-columns:minmax(0,1fr)}
  .primary{min-height:40px}
}
.zoom-overlay{position:fixed;inset:0;background:rgba(10,23,43,.42);display:grid;place-items:center;padding:24px;z-index:50}
.zoom-dialog{width:min(96vw,1480px);height:min(92vh,980px);background:rgba(255,255,255,.98);border:1px solid #dbe6f3;border-radius:28px;box-shadow:0 24px 60px rgba(15,36,71,.24);display:grid;grid-template-rows:auto minmax(0,1fr);overflow:hidden}
.zoom-head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;padding:18px 20px 10px}
.zoom-head h2{margin:8px 0 0;font-size:30px;line-height:1.05;color:#17355e}
.zoom-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:flex-end}
.zoom-close{border:0;border-radius:999px;background:linear-gradient(135deg,#2d82ff,#134db7);color:#fff;font-weight:900;padding:0 16px;min-height:38px;cursor:pointer;box-shadow:0 12px 24px rgba(29,89,193,.22)}
.zoom-board{margin:0 20px 20px;overflow:auto;border-radius:22px;border:1px solid #d8e3f1;background:radial-gradient(circle at 24px 24px,rgba(120,152,208,.14) 1.2px,transparent 1.2px),linear-gradient(180deg,#ffffff,#eef5ff);background-size:28px 28px,100% 100%;scrollbar-gutter:stable both-edges}
.zoom-svg{width:100%;min-width:1520px;display:block}
</style>
