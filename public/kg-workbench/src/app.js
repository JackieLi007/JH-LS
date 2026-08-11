import { requestJson } from './api/client.js';
import { sourceMeta } from './config/sourceMeta.js';
import { destroyOntologyGraph, renderOntologyGraph } from './lib/ontologyG6.js';
import { state } from './state/store.js';

const SCHEMA_STORAGE_KEY = 'fmeafront-schema';
const ONTOLOGY_STORAGE_KEY = 'fmeafront-ontology';
const ONTOLOGY_TEMPLATE_VERSION = '20260421-template-12';
const ONTOLOGY_HISTORY_LIMIT = 24;
const ONTOLOGY_HISTORY_SCHEMA_VERSION = '20260421-versioning-v2';
const ONTOLOGY_VERSION_INITIAL_LABEL = 'V1初始版';

const T = {
  pageOntology: '\u672c\u4f53\u6784\u5efa',
  pageExtract: '\u77e5\u8bc6\u62bd\u53d6',
  pageVersion: '\u7248\u672c\u7ba1\u7406',
  system: '\u667a\u80fd\u6392\u6545\u77e5\u8bc6\u56fe\u8c31\u7cfb\u7edf',
  frontDesk: '\u524d\u7aef\u5de5\u4f5c\u53f0',
  apiConnected: 'API \u5df2\u8fde\u63a5',
  operator: '\u5de5\u7a0b\u7ba1\u7406\u5458',
  ontologyTitle: '\u53ef\u89c6\u5316\u672c\u4f53\u8bbe\u8ba1\u5668',
  ontologyDesc: '\u81ea\u52a8\u751f\u6210\u5206\u5c42\u672c\u4f53\uff0c\u652f\u6301\u53f3\u4fa7\u6dfb\u52a0\u5b9e\u4f53\u8282\u70b9\u548c\u5173\u7cfb\uff0c\u5e76\u6309\u5173\u7cfb\u7b5b\u9009\u5173\u8054\u8282\u70b9\u3002',
  ontologyAutoBuild: '\u81ea\u52a8\u6784\u5efa\u672c\u4f53',
  ontologySaveVersion: '\u4fdd\u5b58\u7248\u672c',
  ontologyUnsavedChanges: '\u6709\u672a\u4fdd\u5b58\u53d8\u66f4',
  ontologyLayeredView: '\u5206\u5c42\u5c55\u793a',
  ontologyRelationFilter: '\u5173\u7cfb\u7b5b\u9009',
  ontologyAllRelations: '\u5168\u90e8\u5173\u7cfb',
  ontologySelectedNode: '\u5f53\u524d\u9009\u4e2d\u8282\u70b9',
  ontologyNodeEmpty: '\u70b9\u51fb\u5de6\u4fa7\u8282\u70b9\u540e\uff0c\u53ef\u5728\u8fd9\u91cc\u67e5\u770b\u4fe1\u606f\u5e76\u7ee7\u7eed\u8865\u5145\u5173\u7cfb\u3002',
  ontologyConnected: '\u76f4\u63a5\u5173\u8054\u5173\u7cfb',
  ontologyEntityEditor: '\u5b9e\u4f53\u8282\u70b9',
  ontologyRelationEditor: '\u5173\u7cfb\u7f16\u8f91',
  ontologyEntityName: '\u8282\u70b9\u540d\u79f0',
  ontologyEntityType: '\u5b9e\u4f53\u7c7b\u578b',
  ontologyEntityTypePlaceholder: '\u8bf7\u9009\u62e9\u5b9e\u4f53\u7c7b\u578b',
  ontologyAddEntity: '\u6dfb\u52a0\u5b9e\u4f53\u8282\u70b9',
  ontologyDeleteEntity: '\u5220\u9664\u5f53\u524d\u5b9e\u4f53\u8282\u70b9',
  ontologyDeleteEntityEmpty: '\u5148\u70b9\u9009\u4e00\u4e2a\u5b9e\u4f53\u8282\u70b9\uff0c\u518d\u8fdb\u884c\u5220\u9664',
  ontologyRelationName: '\u5173\u7cfb\u540d\u79f0',
  ontologyRelationSource: '\u8d77\u70b9\u8282\u70b9',
  ontologyRelationTarget: '\u7ec8\u70b9\u8282\u70b9',
  ontologyAddRelation: '\u6dfb\u52a0\u5173\u7cfb',
  ontologyDeleteRelation: '\u5220\u9664\u5f53\u524d\u5173\u7cfb',
  ontologyDeleteRelationEmpty: '\u5148\u70b9\u9009\u4e00\u6761\u5173\u7cfb\uff0c\u518d\u8fdb\u884c\u5220\u9664',
  ontologyNoConnected: '\u5f53\u524d\u8282\u70b9\u6682\u65e0\u76f4\u63a5\u5173\u8054\u5173\u7cfb',
  ontologyVersionTitle: '\u7248\u672c\u8bb0\u5f55',
  ontologyVersionCurrent: '\u5f53\u524d\u7248',
  ontologyVersionRestore: '\u6062\u590d\u5230\u8fd9\u4e00\u7248',
  ontologyVersionEmpty: '\u6682\u65e0\u7248\u672c\u8bb0\u5f55',
  ontologyVersionInit: '\u521d\u59cb\u672c\u4f53',
  ontologyVersionAddNode: '\u65b0\u589e\u8282\u70b9',
  ontologyVersionDeleteNode: '\u5220\u9664\u8282\u70b9',
  ontologyVersionAddRelation: '\u65b0\u589e\u5173\u7cfb',
  ontologyVersionDeleteRelation: '\u5220\u9664\u5173\u7cfb',
  ontologyVersionRebuild: '\u91cd\u5efa\u672c\u4f53',
  relationSummaryTitle: '\u76f8\u5173\u5173\u7cfb\u6982\u89c8',
  relationSummaryOpen: '\u5c55\u5f00\u67e5\u770b',
  relationSummaryClose: '\u6536\u8d77',
  extractTitle: '\u591a\u6e90\u77e5\u8bc6\u62bd\u53d6\u5de5\u4f5c\u53f0',
  extractCompactTitle: '',
  extractDesc: '\u652f\u6301\u6587\u6863\u3001\u8868\u683c\u548c\u56fe\u50cf\u89e3\u6790\uff0c\u5148\u751f\u6210\u89e3\u6790\u9884\u89c8\u4e0e\u5b57\u6bb5\u6620\u5c04\uff0c\u518d\u8fdb\u884c\u77e5\u8bc6\u62bd\u53d6\u3002',
  extractSourceType: '\u89e3\u6790\u6e90',
  extractPrimaryFile: '\u4e3b\u6587\u4ef6',
  extractExtraFile: '\u9644\u52a0\u8868\u683c',
  extractChooseFile: '\u9009\u62e9\u6587\u4ef6',
  extractChooseExtra: '\u9009\u62e9\u9644\u52a0\u8868\u683c',
  extractNoFile: '\u672a\u9009\u62e9\u6587\u4ef6',
  extractRun: '\u6267\u884c\u77e5\u8bc6\u62bd\u53d6',
  extractReset: '\u91cd\u7f6e\u5f53\u524d\u8868\u5355',
  extractMappingTitle: '\u5b57\u6bb5\u6620\u5c04',
  extractSummaryTitle: '\u62bd\u53d6\u6982\u89c8',
  extractStatsTitle: '\u7edf\u8ba1\u6982\u89c8',
  extractCountsTriples: '\u4e09\u5143\u7ec4',
  extractCountsEntities: '\u5b9e\u4f53',
  extractCountsRelations: '\u5173\u7cfb',
  extractCountsNodes: '\u8282\u70b9\u6570',
  extractCountsEdges: '\u5173\u7cfb\u6570',
  extractResultsTitle: '\u62bd\u53d6\u7ed3\u679c',
  extractEntityResults: '\u5b9e\u4f53\u5217\u8868',
  extractRelationResults: '\u5173\u7cfb\u7edf\u8ba1',
  extractTripleResults: '\u4e09\u5143\u7ec4\u5217\u8868',
  extractSampleEntities: '\u5b9e\u4f53\u793a\u4f8b',
  extractSampleTriples: '\u4e09\u5143\u7ec4\u793a\u4f8b',
  extractNeedPrimary: '\u8bf7\u5148\u9009\u62e9\u4e3b\u6587\u4ef6',
  extracting: '\u6b63\u5728\u62bd\u53d6...',
  extractNoPreview: '\u5c1a\u672a\u751f\u6210\u89e3\u6790\u9884\u89c8',
  extractNoResult: '\u5c1a\u672a\u6267\u884c\u77e5\u8bc6\u62bd\u53d6',
  extractFileLabel: '\u5f53\u524d\u6587\u4ef6',
  extractRowCount: '\u89e3\u6790\u884c\u6570',
  extractMainTitle: '\u4e0a\u4f20\u6e90\u6587\u4ef6',
  extractReadyHint: '\u4e3b\u8868\u5df2\u4e0a\u4f20\uff0c\u53ef\u76f4\u63a5\u5f00\u59cb\u89e3\u6790\uff0c\u6216\u7ee7\u7eed\u4e0a\u4f20\u65b0\u8868\u683c\u3002',
  extractWaitingHint: '\u8bf7\u5148\u9009\u62e9\u9700\u8981\u89e3\u6790\u7684\u6587\u4ef6\u3002',
  extractPrimaryRole: '\u4f5c\u4e3a\u4e3b\u8868\u53c2\u4e0e\u89e3\u6790',
  extractContinueUpload: '\u6279\u91cf\u9009\u62e9\u8868\u683c',
  extractGeneratedOnly: '\u751f\u6210\u9884\u89c8\u6216\u62bd\u53d6\u540e\uff0c\u4e0b\u65b9\u624d\u4f1a\u663e\u793a\u6620\u5c04\u548c\u7ed3\u679c\u3002',
  extractActionText: '\u63d0\u53d6\u6587\u5b57',
  extractMoreActions: '\u66f4\u591a\u529f\u80fd',
  extractBatchHint: '\u6279\u91cf\u4e0a\u4f20\u548c\u89e3\u6790Excel\u8868\u683c',
  extractBatchFiles: '\u6279\u91cf\u8868\u683c',
  extractBatchCount: '\u5df2\u9009\u8868\u683c',
  extractPrimaryBatchRole: '\u7b2c\u4e00\u4e2a\u6587\u4ef6\u4f5c\u4e3a\u4e3b\u8868\uff0c\u5176\u4f59\u6587\u4ef6\u4f5c\u4e3a\u6279\u91cf\u8865\u5145\u8868\u683c',
  initFailed: '\u521d\u59cb\u5316\u5931\u8d25\uff1a',
};

const LABELS = {
  componentFunction: '\u96f6\u90e8\u7ec4\u4ef6\u529f\u80fd',
  machineFunction: '\u5355\u673a\u529f\u80fd',
  systemFunction: '\u7cfb\u7edf\u529f\u80fd',
  globalFunction: '\u603b\u4f53\u529f\u80fd',
  component: '\u96f6\u90e8\u7ec4\u4ef6',
  machine: '\u5355\u673a',
  system: '\u7cfb\u7edf',
  global: '\u603b\u4f53',
  componentFault: '\u7ec4\u4ef6\u7ea7\u6545\u969c\u6a21\u5f0f',
  machineFault: '\u5355\u673a\u7ea7\u6545\u969c\u6a21\u5f0f',
  systemFault: '\u7cfb\u7edf\u7ea7\u6545\u969c\u6a21\u5f0f',
  globalFault: '\u603b\u4f53\u7ea7\u6545\u969c\u6a21\u5f0f',
  componentPhenomenon: '\u7ec4\u4ef6\u7ea7\u6545\u969c\u73b0\u8c61',
  machinePhenomenon: '\u5355\u673a\u7ea7\u6545\u969c\u73b0\u8c61',
  systemPhenomenon: '\u7cfb\u7edf\u7ea7\u6545\u969c\u73b0\u8c61',
  globalPhenomenon: '\u603b\u4f53\u7ea7\u6545\u969c\u73b0\u8c61',
  attrStage: '\u53d1\u751f\u9636\u6bb5',
  attrSingle: '\u662f\u5426\u5355\u70b9',
  attrLevel: '\u4e25\u9177\u5ea6\u7b49\u7ea7',
  attrProbability: '\u53d1\u751f\u6982\u7387',
  attrSolution: '\u8bbe\u8ba1\u63aa\u65bd',
  attribute: '\u5c5e\u6027\u503c',
};

const RELATION_LABELS = {
  'has function': '\u5177\u6709\u529f\u80fd',
  Include: '\u5305\u542b',
  'has failure mode': '\u5b58\u5728\u6545\u969c',
  'lead to': '\u5bfc\u81f4',
  has: '\u6709',
  'Occurrence stage': '\u53d1\u751f\u9636\u6bb5',
  'yes/no': '\u662f\u5426\u5355\u70b9',
  'Level Classification': '\u4e25\u9177\u5ea6\u7b49\u7ea7',
  Probability: '\u53d1\u751f\u6982\u7387',
  Solution: '\u8bbe\u8ba1\u63aa\u65bd',
};

const COLORS = {
  [LABELS.componentFunction]: '#ff1d1d',
  [LABELS.machineFunction]: '#ff1d1d',
  [LABELS.systemFunction]: '#ff1d1d',
  [LABELS.globalFunction]: '#ff1d1d',
  [LABELS.component]: '#ff8a1f',
  [LABELS.machine]: '#ff8a1f',
  [LABELS.system]: '#ff8a1f',
  [LABELS.global]: '#ff8a1f',
  [LABELS.componentFault]: '#4f79cc',
  [LABELS.machineFault]: '#4f79cc',
  [LABELS.systemFault]: '#4f79cc',
  [LABELS.globalFault]: '#4f79cc',
  [LABELS.componentPhenomenon]: '#37b8b4',
  [LABELS.machinePhenomenon]: '#37b8b4',
  [LABELS.systemPhenomenon]: '#37b8b4',
  [LABELS.globalPhenomenon]: '#37b8b4',
  [LABELS.attribute]: '#8dd447',
  default: '#2c67d6',
};

const ATTRIBUTE_LABELS = [
  LABELS.attrStage,
  LABELS.attrSingle,
  LABELS.attrLevel,
  LABELS.attrProbability,
  LABELS.attrSolution,
];

const ENTITY_TYPE_OPTIONS = [
  LABELS.componentFunction,
  LABELS.machineFunction,
  LABELS.systemFunction,
  LABELS.globalFunction,
  LABELS.component,
  LABELS.machine,
  LABELS.system,
  LABELS.global,
  LABELS.componentFault,
  LABELS.machineFault,
  LABELS.systemFault,
  LABELS.globalFault,
  LABELS.componentPhenomenon,
  LABELS.machinePhenomenon,
  LABELS.systemPhenomenon,
  LABELS.globalPhenomenon,
  LABELS.attribute,
];

const ONTOLOGY_TEMPLATE_NODES = [
  { id: 'fn-left-top', label: LABELS.componentFunction, type: LABELS.componentFunction, level: 2, x: 120, y: 120 },
  { id: 'component-main', label: LABELS.component, type: LABELS.component, level: 2, x: 440, y: 108 },
  { id: 'machine-main', label: LABELS.machine, type: LABELS.machine, level: 2, x: 274, y: 392 },
  { id: 'fn-left-bottom', label: LABELS.machineFunction, type: LABELS.machineFunction, level: 3, x: 170, y: 878 },
  { id: 'component-fault', label: LABELS.componentFault, type: LABELS.componentFault, level: 2, x: 846, y: 120 },
  { id: 'machine-fault', label: LABELS.machineFault, type: LABELS.machineFault, level: 2, x: 900, y: 396 },
  { id: 'system-main', label: LABELS.system, type: LABELS.system, level: 2, x: 1426, y: 108 },
  { id: 'global-main', label: LABELS.global, type: LABELS.global, level: 1, x: 1658, y: 96 },
  { id: 'fn-global-top', label: LABELS.globalFunction, type: LABELS.globalFunction, level: 1, x: 2262, y: 96 },
  { id: 'fn-right-top', label: LABELS.systemFunction, type: LABELS.systemFunction, level: 2, x: 1878, y: 96 },
  { id: 'system-fault', label: LABELS.systemFault, type: LABELS.systemFault, level: 2, x: 1454, y: 394 },
  { id: 'global-fault', label: LABELS.globalFault, type: LABELS.globalFault, level: 2, x: 1872, y: 392 },
  { id: 'phen-top', label: LABELS.componentPhenomenon, type: LABELS.componentPhenomenon, level: 2, x: 1188, y: 214 },
  { id: 'phen-mid', label: LABELS.machinePhenomenon, type: LABELS.machinePhenomenon, level: 3, x: 566, y: 666 },
  { id: 'phen-right', label: LABELS.systemPhenomenon, type: LABELS.systemPhenomenon, level: 3, x: 1456, y: 666 },
  { id: 'phen-rightmost', label: LABELS.globalPhenomenon, type: LABELS.globalPhenomenon, level: 3, x: 1894, y: 666 },
  { id: 'attr-stage', label: LABELS.attrStage, type: LABELS.attribute, level: 4, x: 538, y: 988 },
  { id: 'attr-single', label: LABELS.attrSingle, type: LABELS.attribute, level: 4, x: 880, y: 988 },
  { id: 'attr-level', label: LABELS.attrLevel, type: LABELS.attribute, level: 4, x: 1248, y: 988 },
  { id: 'attr-probability', label: LABELS.attrProbability, type: LABELS.attribute, level: 4, x: 1606, y: 988 },
  { id: 'attr-solution', label: LABELS.attrSolution, type: LABELS.attribute, level: 4, x: 1942, y: 988 },
];

const ONTOLOGY_TEMPLATE_EDGES = [
  { source: 'component-main', target: 'fn-left-top', label: 'has function' },
  { source: 'machine-main', target: 'component-main', label: 'Include' },
  { source: 'system-main', target: 'machine-main', label: 'Include' },
  { source: 'machine-main', target: 'fn-left-bottom', label: 'has function' },
  { source: 'component-main', target: 'component-fault', label: 'has failure mode' },
  { source: 'machine-main', target: 'machine-fault', label: 'has failure mode' },
  { source: 'component-fault', target: 'machine-fault', label: 'lead to' },
  { source: 'system-main', target: 'fn-right-top', label: 'has function' },
  { source: 'global-main', target: 'fn-global-top', label: 'has function' },
  { source: 'system-main', target: 'system-fault', label: 'has failure mode' },
  { source: 'global-main', target: 'global-fault', label: 'has failure mode' },
  { source: 'global-main', target: 'system-main', label: 'Include' },
  { source: 'machine-fault', target: 'system-fault', label: 'lead to' },
  { source: 'system-fault', target: 'global-fault', label: 'lead to' },
  { source: 'component-fault', target: 'phen-top', label: 'has' },
  { source: 'machine-fault', target: 'phen-mid', label: 'has' },
  { source: 'system-fault', target: 'phen-right', label: 'has' },
  { source: 'global-fault', target: 'phen-rightmost', label: 'has' },
  { source: 'machine-fault', target: 'attr-stage', label: 'Occurrence stage' },
  { source: 'machine-fault', target: 'attr-single', label: 'yes/no' },
  { source: 'machine-fault', target: 'attr-level', label: 'Level Classification' },
  { source: 'machine-fault', target: 'attr-probability', label: 'Probability' },
  { source: 'machine-fault', target: 'attr-solution', label: 'Solution' },
];

const baseState = {
  currentPage: 'ontology',
  sourceType: 'table',
  schema: { entityTypes: [], relationTypes: [] },
  ontology: {
    nodes: [],
    edges: [],
    selectedNodeId: null,
    activeEdgeId: null,
    relationFilter: 'all',
    relationPanelOpen: false,
    zoom: 1,
    entityDraft: '',
    entityTypeDraft: '',
    relationDraft: '',
    relationSourceDraft: '',
    relationTargetDraft: '',
    layout: {},
    history: [],
    currentVersionId: '',
    pendingChanges: false,
  },
  parseConfig: null,
  extractionResult: null,
  kgBuildProgress: null,
  selectedFileName: '',
  selectedFile: null,
  selectedFiles: [],
  imagePreviewUrl: '',
  extraTableFiles: [],
  extraTableFileName: '',
  extraTableFile: null,
  versioning: {
    versions: [],
    loaded: false,
    loading: false,
    rollbacking: false,
    error: '',
    lastRollback: null,
  },
  loading: false,
};

function unique(items = []) {
  return [...new Set(items.map((item) => String(item || '').trim()).filter(Boolean))];
}

function escapeHtml(value = '') {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function clearImagePreview() {
  if (state.imagePreviewUrl) URL.revokeObjectURL(state.imagePreviewUrl);
  state.imagePreviewUrl = '';
}

function setImagePreview(file) {
  clearImagePreview();
  state.imagePreviewUrl = file ? URL.createObjectURL(file) : '';
}

function cloneGraph(nodes = [], edges = []) {
  return {
    nodes: nodes.map((node) => ({ ...node })),
    edges: edges.map((edge) => ({ ...edge })),
  };
}

function formatVersionTime(timestamp) {
  try {
    return new Date(timestamp).toLocaleString('zh-CN', {
      hour12: false,
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return '';
  }
}

function colorOf(type = '') {
  return COLORS[type] || COLORS.default;
}

function relationTextZh(label = '') {
  return RELATION_LABELS[label] || label;
}

function canonicalRelationLabel(label = '') {
  const text = String(label || '').trim();
  if (!text) return '';
  const matched = Object.entries(RELATION_LABELS).find(([, zh]) => zh === text);
  return matched?.[0] || text;
}

function sanitizeOntologyEdges(edges = []) {
  const normalized = edges.map((edge) => ({ ...edge, label: canonicalRelationLabel(edge.label) }));
  const leadToPairs = new Set(
    normalized
      .filter((edge) => edge.label === 'lead to')
      .map((edge) => `${edge.source}__${edge.target}`),
  );
  const withoutIncludeDup = normalized.filter((edge) => !(edge.label === 'Include' && leadToPairs.has(`${edge.source}__${edge.target}`)));
  const faultPhenScope = new Set([
    'system-fault__phen-right',
    'system-fault__phen-rightmost',
    'global-fault__phen-right',
    'global-fault__phen-rightmost',
  ]);
  const reuseIds = {
    'system-fault': withoutIncludeDup.find((edge) => edge.label === 'has' && edge.source === 'system-fault' && (edge.target === 'phen-right' || edge.target === 'phen-rightmost'))?.id || '',
    'global-fault': withoutIncludeDup.find((edge) => edge.label === 'has' && edge.source === 'global-fault' && (edge.target === 'phen-right' || edge.target === 'phen-rightmost'))?.id || '',
  };
  const cleaned = withoutIncludeDup.filter((edge) => !(edge.label === 'has' && faultPhenScope.has(`${edge.source}__${edge.target}`)));
  if (!cleaned.some((edge) => edge.label === 'has' && edge.source === 'system-fault' && edge.target === 'phen-right')) {
    cleaned.push({ id: reuseIds['system-fault'] || `ontology-edge-fix-system-fault-phen-right`, source: 'system-fault', target: 'phen-right', label: 'has' });
  }
  if (!cleaned.some((edge) => edge.label === 'has' && edge.source === 'global-fault' && edge.target === 'phen-rightmost')) {
    cleaned.push({ id: reuseIds['global-fault'] || `ontology-edge-fix-global-fault-phen-rightmost`, source: 'global-fault', target: 'phen-rightmost', label: 'has' });
  }
  const required = [
    { source: 'global-main', target: 'global-fault', label: 'has failure mode' },
    { source: 'global-main', target: 'fn-global-top', label: 'has function' },
    { source: 'global-main', target: 'system-main', label: 'Include' },
  ];
  required.forEach((item) => {
    if (!cleaned.some((edge) => edge.source === item.source && edge.target === item.target && edge.label === item.label)) {
      cleaned.push({ id: `ontology-edge-required-${item.source}-${item.target}-${item.label}`.replace(/\s+/g, '-'), ...item });
    }
  });
  return cleaned;
}

function nextOntologyVersionLabel(history = []) {
  const maxMinor = history.reduce((max, item) => {
    const label = String(item?.label || '').trim();
    const matched = /^V1\.(\d+)$/.exec(label);
    if (!matched) return max;
    return Math.max(max, Number(matched[1]));
  }, 0);
  return `V1.${maxMinor + 1}`;
}

function inferLevel(label = '') {
  const text = String(label || '');
  if (text === LABELS.attribute) return 5;
  if (text.includes(LABELS.global) || text.includes(LABELS.globalFault)) return 1;
  if (text.includes(LABELS.system) || text.includes(LABELS.systemFault)) return 2;
  if (text.includes(LABELS.machine) || text.includes(LABELS.machineFault)) return 3;
  if (text.includes(LABELS.component) || text.includes(LABELS.componentFault)) return 4;
  if (text.includes('\u529f\u80fd') || text.includes('\u6545\u969c\u73b0\u8c61')) return 4;
  if (text.includes('\u9636\u6bb5') || text.includes('\u6982\u7387') || text.includes('\u7b49\u7ea7') || text.includes('\u63aa\u65bd') || text.includes('\u5355\u70b9')) return 5;
  return 3;
}

function normalizeOntologyNode(node) {
  const overrides = {
    'fn-left-top': { label: LABELS.componentFunction, type: LABELS.componentFunction },
    'component-main': { label: LABELS.component, type: LABELS.component },
    'fn-left-bottom': { label: LABELS.machineFunction, type: LABELS.machineFunction },
    'fn-right-top': { label: LABELS.systemFunction, type: LABELS.systemFunction },
    'fn-global-top': { label: LABELS.globalFunction, type: LABELS.globalFunction },
    'global-main': { label: LABELS.global, type: LABELS.global },
    'phen-top': { label: LABELS.componentPhenomenon, type: LABELS.componentPhenomenon },
    'phen-mid': { label: LABELS.machinePhenomenon, type: LABELS.machinePhenomenon },
    'phen-right': { label: LABELS.systemPhenomenon, type: LABELS.systemPhenomenon },
    'phen-rightmost': { label: LABELS.globalPhenomenon, type: LABELS.globalPhenomenon },
    'attr-stage': { label: LABELS.attrStage, type: LABELS.attribute },
    'attr-single': { label: LABELS.attrSingle, type: LABELS.attribute },
    'attr-level': { label: LABELS.attrLevel, type: LABELS.attribute },
    'attr-probability': { label: LABELS.attrProbability, type: LABELS.attribute },
    'attr-solution': { label: LABELS.attrSolution, type: LABELS.attribute },
  };
  const next = { ...node, ...(overrides[node.id] || {}) };
  if (ATTRIBUTE_LABELS.includes(next.label)) next.type = LABELS.attribute;
  next.level = inferLevel(next.type || next.label);
  return next;
}

function buildOntology(schema) {
  const nodes = ONTOLOGY_TEMPLATE_NODES.map((node, index) => {
    const normalized = normalizeOntologyNode(node);
    return {
      ...normalized,
      description: `${normalized.label}\u672c\u4f53\u8282\u70b9`,
      tags: unique([normalized.type, normalized.label]),
      order: index,
    };
  });
  const edges = sanitizeOntologyEdges(ONTOLOGY_TEMPLATE_EDGES.map((edge, index) => ({
    id: `ontology-edge-${index + 1}`,
    ...edge,
  })));
  schema.entityTypes = unique([...(schema.entityTypes || []), ...nodes.map((node) => node.type)]);
  schema.relationTypes = unique([...(schema.relationTypes || []), ...edges.map((edge) => edge.label)]);
  return { nodes, edges };
}

function sourceHint(type) {
  return sourceMeta[type]?.hint || '';
}

function mergeExtractionResults(results = [], sourceType = 'table') {
  if (results.length === 1) return results[0] || null;
  const entityMap = new Map();
  const relationCount = new Map();
  const tripleRows = [];
  const kgBuildItems = [];

  results.forEach((result) => {
    (result?.entities || []).forEach((item) => {
      const key = `${item.name}__${item.type}`;
      if (!entityMap.has(key)) entityMap.set(key, item);
    });
    (result?.relations || []).forEach((item) => {
      relationCount.set(item.name, (relationCount.get(item.name) || 0) + Number(item.count || 0));
    });
    for (const item of (result?.tripleRows || [])) {
      tripleRows.push(item);
    }
    if (result?.kgBuild) {
      kgBuildItems.push({
        fileName: result.fileName || '',
        ...result.kgBuild,
        payloadCounts: result.kgBuild.payloadCounts || result.counts || { entities: 0, relations: 0, triples: 0 },
      });
    }
  });
  const firstFailedKgBuild = kgBuildItems.find((item) => item.status === 'failed' && item.error);
  const firstSkippedPostprocess = kgBuildItems.find((item) => item.summary?.postprocess?.status === 'skipped');

  return {
    fileName: sourceType === 'table' ? `批量表格（${results.length}）` : (results[0]?.fileName || ''),
    sourceType,
    entities: [...entityMap.values()],
    relations: [...relationCount.entries()].map(([name, count]) => ({ name, count })),
    tripleRows,
    appliedMappings: [],
    counts: {
      triples: tripleRows.length,
      entities: entityMap.size,
      relations: relationCount.size,
    },
    kgBuild: kgBuildItems.length ? {
      status: kgBuildItems.some((item) => item.status === 'failed') ? 'failed' : 'ok',
      error: firstFailedKgBuild?.error || '',
      postprocessError: firstSkippedPostprocess?.summary?.postprocess?.error || '',
      items: kgBuildItems,
      payloadCounts: kgBuildItems.reduce((acc, item) => {
        acc.entities += Number(item.payloadCounts?.entities || 0);
        acc.relations += Number(item.payloadCounts?.relations || 0);
        acc.triples += Number(item.payloadCounts?.triples || 0);
        return acc;
      }, { entities: 0, relations: 0, triples: 0 }),
    } : undefined,
  };
}

function kgBuildItems(kgBuild = null) {
  if (!kgBuild) return [];
  return Array.isArray(kgBuild.items) && kgBuild.items.length ? kgBuild.items : [kgBuild];
}

function kgPayloadDetail(payloadCounts = {}) {
  if (!payloadCounts) return '';
  return `节点 ${payloadCounts.entities || 0} / 关系类型 ${payloadCounts.relations || 0} / 三元组 ${payloadCounts.triples || 0}`;
}

function kgExtractionCounts(result = {}) {
  const counts = result?.counts || {};
  return {
    entities: Number(counts.entities || (Array.isArray(result?.entities) ? result.entities.length : 0)),
    relations: Number(counts.relations || (Array.isArray(result?.relations) ? result.relations.length : 0)),
    triples: Number(counts.triples || (Array.isArray(result?.triples) ? result.triples.length : (Array.isArray(result?.tripleRows) ? result.tripleRows.length : 0))),
  };
}

function kgBuildPostprocessError(kgBuild = null) {
  const errors = kgBuildItems(kgBuild)
    .map((item) => String(
      item?.postprocessError
        || (item?.summary?.postprocess?.status === 'skipped' ? item.summary.postprocess.error : '')
        || '',
    ).trim())
    .filter(Boolean);
  return unique(errors).join('；');
}

function kgBuildTotals(kgBuild = null) {
  return kgBuildItems(kgBuild).reduce((acc, item) => {
    const write = item?.summary?.write || {};
    const linking = item?.summary?.linking || {};
    const writeback = linking.writeback || {};
    const index = item?.summary?.index || {};
    acc.createdNodes += Number(write.created_nodes || 0);
    acc.matchedNodes += Number(write.matched_nodes || 0);
    acc.createdRelationships += Number(write.created_relationships || 0);
    acc.matchedRelationships += Number(write.matched_relationships || 0);
    acc.addedEdges += Number(linking.added_edge_count || 0);
    acc.writtenSimilarities += Number(writeback.added_relationships || 0);
    acc.indexNodes += Number(index.node_count || 0);
    return acc;
  }, {
    createdNodes: 0,
    matchedNodes: 0,
    createdRelationships: 0,
    matchedRelationships: 0,
    addedEdges: 0,
    writtenSimilarities: 0,
    indexNodes: 0,
  });
}

function kgProgressFromBuild(kgBuild = null) {
  if (!kgBuild) return null;
  const status = kgBuild.status || 'ok';
  const totals = kgBuildTotals(kgBuild);
  const postprocessError = kgBuildPostprocessError(kgBuild);
  const payloadText = kgPayloadDetail(kgBuild.payloadCounts || {});
  const failed = status === 'failed';
  const skipped = status === 'skipped';
  const linkSkipped = Boolean(postprocessError);
  const message = failed
    ? `图谱构建失败：${kgBuild.error || '请检查 Neo4j 连接与模型依赖'}`
    : (skipped
      ? (kgBuild.reason || '无可写入图谱的数据')
      : (linkSkipped ? `已完成落库，知识连接/索引已跳过：${postprocessError}` : '已完成落库、知识连接与索引'));
  const rows = [
    { label: '知识抽取', status: 'ok', detail: '已生成抽取结果' },
    {
      label: '三元组落库',
      status: failed ? 'failed' : (skipped ? 'skipped' : 'ok'),
      detail: skipped
        ? '没有可写入的数据'
        : `新增节点 ${totals.createdNodes}，更新节点 ${totals.matchedNodes}，新增关系 ${totals.createdRelationships}，更新关系 ${totals.matchedRelationships}`,
    },
    {
      label: '知识连接',
      status: failed ? 'failed' : (skipped || linkSkipped ? 'skipped' : 'ok'),
      detail: linkSkipped
        ? postprocessError
        : `新增相似候选 ${totals.addedEdges}，写回相似关系 ${totals.writtenSimilarities}`,
    },
    {
      label: '语义索引',
      status: failed ? 'failed' : (skipped || linkSkipped ? 'skipped' : 'ok'),
      detail: linkSkipped ? postprocessError : `索引节点 ${totals.indexNodes}`,
    },
  ];
  const batchDetail = kgBuildItems(kgBuild).length > 1
    ? kgBuildItems(kgBuild).map((item) => {
      const itemError = item.error || kgBuildPostprocessError(item);
      if (item.status === 'failed') return `${item.fileName || '文件'}：失败${itemError ? `（${itemError}）` : ''}`;
      return `${item.fileName || '文件'}：完成${itemError ? `（后处理跳过：${itemError}）` : ''}`;
    }).join('；')
    : '';
  return {
    status: failed ? 'failed' : (skipped ? 'skipped' : (linkSkipped ? 'skipped' : 'ok')),
    message,
    detail: payloadText,
    rows,
    reportPath: kgBuild.reportPath || '',
    batchDetail,
    result: kgBuild,
  };
}

function kgProgressBuilding(extractionResult = {}) {
  return {
    status: 'building',
    message: '正在写入 Neo4j，并执行知识连接与索引',
    detail: kgPayloadDetail(kgExtractionCounts(extractionResult)),
    rows: [
      { label: '知识抽取', status: 'ok', detail: '已生成抽取结果' },
      { label: '图谱落库与知识连接', status: 'running', detail: '服务端正在依次执行三元组落库、相似关系写回和语义索引构建' },
    ],
  };
}

function kgProgressFailed(error, extractionResult = {}) {
  return {
    status: 'failed',
    message: `图谱构建失败：${error?.message || error || '请检查 Neo4j 连接与模型依赖'}`,
    detail: kgPayloadDetail(kgExtractionCounts(extractionResult)),
    rows: [
      { label: '知识抽取', status: 'ok', detail: '已生成抽取结果' },
      { label: '图谱落库与知识连接', status: 'failed', detail: error?.message || String(error || '') },
    ],
  };
}

function renderKgBuildProgress(progress = null) {
  if (!progress) return '';
  const stateText = {
    ok: '完成',
    failed: '失败',
    skipped: '跳过',
    building: '进行中',
    running: '进行中',
    pending: '等待中',
  };
  const rows = Array.isArray(progress.rows) ? progress.rows : [];
  return `<div class="kg-progress">
    <div class="kg-progress__header">
      <div>
        <strong class="kg-progress__title">知识连接与落库</strong>
        <p class="kg-progress__message">${escapeHtml(progress.message || '')}</p>
      </div>
      <span class="kg-progress__state kg-progress__state--${escapeHtml(progress.status || 'pending')}">${escapeHtml(stateText[progress.status] || progress.status || '等待中')}</span>
    </div>
    ${progress.detail ? `<p class="kg-progress__detail">${escapeHtml(progress.detail)}</p>` : ''}
    ${rows.length ? `<div class="kg-progress__steps">${rows.map((row) => `<div class="kg-progress__step">
      <span class="kg-progress__step-name">${escapeHtml(row.label)}</span>
      <span class="kg-progress__state kg-progress__state--${escapeHtml(row.status || 'pending')}">${escapeHtml(stateText[row.status] || row.status || '等待中')}</span>
      <span class="kg-progress__step-detail">${escapeHtml(row.detail || '')}</span>
    </div>`).join('')}</div>` : ''}
    ${progress.reportPath ? `<p class="kg-progress__detail">报告：${escapeHtml(progress.reportPath)}</p>` : ''}
    ${progress.batchDetail ? `<p class="kg-progress__detail">${escapeHtml(progress.batchDetail)}</p>` : ''}
  </div>`;
}

function shouldBuildKgFromExtraction(result = null) {
  if (!result || result.error || result.kgBuild) return false;
  const counts = kgExtractionCounts(result);
  return Number(counts.triples || 0) > 0
    || Number(counts.entities || 0) > 0
    || (Array.isArray(result.tripleRows) && result.tripleRows.length > 0)
    || (Array.isArray(result.triples) && result.triples.length > 0)
    || (Array.isArray(result.entities) && result.entities.length > 0);
}

export function createApp(root, options = {}) {
  Object.assign(state, { ...baseState, ...state, ontology: { ...baseState.ontology, ...(state.ontology || {}) } });
  if (['ontology', 'extract', 'versions'].includes(options.currentPage)) {
    state.currentPage = options.currentPage;
  }
  const embedded = Boolean(options.embedded);

  const persistSchema = () => localStorage.setItem(SCHEMA_STORAGE_KEY, JSON.stringify(state.schema));
  const persistOntology = () => localStorage.setItem(
    ONTOLOGY_STORAGE_KEY,
    JSON.stringify({
      version: ONTOLOGY_TEMPLATE_VERSION,
      historySchemaVersion: ONTOLOGY_HISTORY_SCHEMA_VERSION,
      nodes: state.ontology.nodes,
      edges: state.ontology.edges,
      history: state.ontology.history,
      currentVersionId: state.ontology.currentVersionId,
      pendingChanges: false,
    }),
  );

  const markOntologyDirty = () => {
    state.ontology.pendingChanges = true;
  };

  const pageTitle = () => ({
    ontology: T.pageOntology,
    extract: T.pageExtract,
    versions: T.pageVersion,
  }[state.currentPage] || T.pageOntology);

  const selectedGraph = () => state.graphs.find((item) => item.database === state.selectedGraphDatabase) || null;
  const graphRequestOptions = (options = {}) => {
    const database = String(state.selectedGraphDatabase || '').trim();
    if (!database) return options;
    return {
      ...options,
      headers: {
        ...(options.headers || {}),
        'X-KG-Database': database,
      },
    };
  };
  const requestGraphJson = (path, options = {}) => requestJson(path, graphRequestOptions(options));
  const graphOptionMarkup = () => state.graphs.map((item) => `<option value="${escapeHtml(item.database)}" ${item.database === state.selectedGraphDatabase ? 'selected' : ''}>${escapeHtml(item.name)}${item.available === false ? '（不可用）' : ''}</option>`).join('');
  const graphPickerMarkup = ({ allowCreate = false, compact = false } = {}) => {
    const current = selectedGraph();
    return `<div class="graph-picker ${compact ? 'graph-picker--compact' : ''}">
      <div class="graph-picker__heading"><div><p class="panel__eyebrow">当前图谱</p><strong>${escapeHtml(current?.name || '加载图谱列表中')}</strong></div>${current ? `<span class="graph-picker__meta">${current.nodeCount || 0} 节点 / ${current.edgeCount || 0} 关系</span>` : ''}</div>
      <label class="graph-picker__field"><span class="field-label">存入/查看图谱</span><select id="graph-select" ${state.graphsLoading ? 'disabled' : ''}>${state.graphs.length ? graphOptionMarkup() : '<option>暂无可用图谱</option>'}</select></label>
      ${allowCreate ? `<div class="graph-picker__create"><label><span class="field-label">新图谱名称</span><input id="graph-create-name" value="${escapeHtml(state.graphCreateName || '')}" maxlength="80" placeholder="例如：CZ-8A"></label><button class="secondary-btn" id="graph-create-btn" ${state.graphCreating ? 'disabled' : ''}>${state.graphCreating ? '正在创建...' : '创建并选中'}</button></div>` : ''}
      ${state.graphError ? `<p class="graph-picker__error">${escapeHtml(state.graphError)}</p>` : ''}
    </div>`;
  };

  const fetchGraphs = async ({ renderAfter = true } = {}) => {
    state.graphsLoading = true;
    state.graphError = '';
    try {
      const result = await requestJson('/api/graphs');
      state.graphs = Array.isArray(result?.graphs) ? result.graphs : [];
      const availableDatabases = new Set(state.graphs.map((item) => item.database));
      if (!availableDatabases.has(state.selectedGraphDatabase)) {
        state.selectedGraphDatabase = String(result?.defaultDatabase || state.graphs[0]?.database || '');
      }
      if (state.selectedGraphDatabase) localStorage.setItem('fmeafront-selected-graph', state.selectedGraphDatabase);
    } catch (error) {
      state.graphs = [];
      state.graphError = error.message || '图谱列表读取失败';
    } finally {
      state.graphsLoading = false;
      if (renderAfter) render();
    }
  };

  const selectGraph = async (database) => {
    const nextDatabase = String(database || '').trim();
    if (!nextDatabase || nextDatabase === state.selectedGraphDatabase) return;
    state.selectedGraphDatabase = nextDatabase;
    localStorage.setItem('fmeafront-selected-graph', nextDatabase);
    state.versioning = { ...state.versioning, versions: [], loaded: false, error: '', lastRollback: null };
    state.kgBuildProgress = null;
    render();
    if (state.currentPage === 'versions') await fetchKgVersions();
  };

  const createGraph = async () => {
    const name = String(state.graphCreateName || '').trim();
    if (!name || state.graphCreating) return;
    state.graphCreating = true;
    state.graphError = '';
    render();
    try {
      const result = await requestJson('/api/graphs', {
        method: 'POST',
        body: JSON.stringify({ name }),
      });
      const database = String(result?.graph?.database || '').trim();
      state.graphCreateName = '';
      await fetchGraphs({ renderAfter: false });
      if (database) await selectGraph(database);
    } catch (error) {
      state.graphError = error.message || '图谱创建失败';
    } finally {
      state.graphCreating = false;
      render();
    }
  };

  const deleteGraph = async (database) => {
    const target = state.graphs.find((item) => item.database === database);
    if (!target || target.isDefault) return;
    if (!window.confirm(`确定删除图谱“${target.name}”吗？该操作会删除图谱数据库及其版本记录，无法恢复。`)) return;
    state.graphError = '';
    try {
      const result = await requestJson(`/api/graphs/${encodeURIComponent(database)}`, { method: 'DELETE' });
      await fetchGraphs({ renderAfter: false });
      if (state.selectedGraphDatabase === database) {
        state.selectedGraphDatabase = String(result?.defaultDatabase || state.graphs[0]?.database || '');
        if (state.selectedGraphDatabase) localStorage.setItem('fmeafront-selected-graph', state.selectedGraphDatabase);
      }
      state.versioning = { ...state.versioning, versions: [], loaded: false, error: '', lastRollback: null };
      if (state.currentPage === 'versions') await fetchKgVersions();
    } catch (error) {
      state.graphError = error.message || '图谱删除失败';
    } finally {
      render();
    }
  };

  const ontologyNode = () => state.ontology.nodes.find((node) => node.id === state.ontology.selectedNodeId) || state.ontology.nodes[0] || null;
  const activeOntologyEdge = () => state.ontology.edges.find((edge) => edge.id === state.ontology.activeEdgeId) || null;
  const extractCounts = () => state.extractionResult?.counts || { triples: 0, entities: 0, relations: 0 };

  const kgSourceText = (type = '') => ({
    table: '表格抽取',
    document: '文档抽取',
    image: '图片抽取',
  }[type] || type || '知识导入');

  const versionWriteText = (item = {}) => {
    const write = item.write || {};
    return `新增节点 ${write.createdNodes || 0}，新增关系 ${write.createdRelationships || 0}，更新节点 ${write.matchedNodes || 0}，更新关系 ${write.matchedRelationships || 0}`;
  };

  const ontologyRelations = () => {
    const rawLabels = unique(state.ontology.edges.map((edge) => edge.label));
    return unique(rawLabels.map((label) => relationTextZh(label))).map((text) => ({ value: text, text }));
  };

  const visibleOntology = () => {
    const filter = String(state.ontology.relationFilter || '').trim();
    if (!filter || filter === 'all') return { nodes: state.ontology.nodes, edges: state.ontology.edges };
    const edges = state.ontology.edges.filter((edge) => relationTextZh(edge.label) === filter);
    const ids = new Set();
    edges.forEach((edge) => {
      ids.add(edge.source);
      ids.add(edge.target);
    });
    return { nodes: state.ontology.nodes.filter((node) => ids.has(node.id)), edges };
  };

  const updateOntologyLayout = () => {
    const layout = {};
    visibleOntology().nodes.forEach((node, index) => {
      if (typeof node.x === 'number' && typeof node.y === 'number') {
        layout[node.id] = { x: node.x, y: node.y };
      } else {
        layout[node.id] = { x: 180 + (index % 5) * 220, y: 140 + Math.floor(index / 5) * 160 };
      }
    });
    state.ontology.layout = layout;
  };

  const ontologyNodeLinks = () => {
    const current = ontologyNode();
    if (!current) return [];
    return state.ontology.edges
      .filter((edge) => edge.source === current.id || edge.target === current.id)
      .map((edge) => {
        const otherId = edge.source === current.id ? edge.target : edge.source;
        const other = state.ontology.nodes.find((node) => node.id === otherId);
        return { id: edge.id, label: edge.label, target: other?.label || otherId, active: edge.id === state.ontology.activeEdgeId };
      });
  };

  const commitOntologyVersion = () => {
    const snapshot = cloneGraph(state.ontology.nodes, state.ontology.edges);
    const withoutDuplicateTail = [...(state.ontology.history || [])];
    const last = withoutDuplicateTail[0];
    if (last && JSON.stringify({ nodes: last.nodes, edges: last.edges }) === JSON.stringify(snapshot)) {
      state.ontology.currentVersionId = last.id;
      persistOntology();
      return;
    }
    const entry = {
      id: `ontology-version-${Date.now()}`,
      label: nextOntologyVersionLabel(withoutDuplicateTail),
      timestamp: new Date().toISOString(),
      nodes: snapshot.nodes,
      edges: snapshot.edges,
    };
    state.ontology.history = [entry, ...withoutDuplicateTail].slice(0, ONTOLOGY_HISTORY_LIMIT);
    state.ontology.currentVersionId = entry.id;
    persistOntology();
  };

  const initializeOntologyHistory = () => {
    const snapshot = cloneGraph(state.ontology.nodes, state.ontology.edges);
    const entry = {
      id: `ontology-version-${Date.now()}`,
      label: ONTOLOGY_VERSION_INITIAL_LABEL,
      timestamp: new Date().toISOString(),
      nodes: snapshot.nodes,
      edges: snapshot.edges,
    };
    state.ontology.history = [entry];
    state.ontology.currentVersionId = entry.id;
    persistOntology();
  };

  const restoreOntologyVersion = (versionId) => {
    const target = (state.ontology.history || []).find((item) => item.id === versionId);
    if (!target) return;
    const graph = cloneGraph(target.nodes, target.edges);
    state.ontology.nodes = graph.nodes;
    state.ontology.edges = graph.edges;
    state.ontology.currentVersionId = target.id;
    state.ontology.selectedNodeId = graph.nodes[0]?.id || null;
    state.ontology.activeEdgeId = null;
    state.ontology.relationFilter = 'all';
    state.ontology.relationPanelOpen = false;
    state.ontology.pendingChanges = false;
    updateOntologyLayout();
    persistOntology();
    render();
  };

  const handleOntologyNodeClick = (nodeId) => {
    state.ontology.selectedNodeId = nodeId;
    state.ontology.relationPanelOpen = false;
    const current = state.ontology.nodes.find((node) => node.id === nodeId);
    if (current) state.ontology.relationSourceDraft = current.id;
    render();
  };

  const syncOntologyGraph = async () => {
    if (state.currentPage !== 'ontology') {
      await destroyOntologyGraph();
      return;
    }
    const container = root.querySelector('#ontology-g6-container');
    if (!container) return;
    const visible = visibleOntology();
    const rawNodes = visible.nodes.map((node) => {
      const point = state.ontology.layout[node.id] || { x: 180, y: 180 };
      return { ...node, x: point.x, y: point.y };
    });
    if (!rawNodes.length) {
      container.innerHTML = '';
      return;
    }
    const minY = Math.min(...rawNodes.map((node) => Number(node.y) || 0));
    const maxY = Math.max(...rawNodes.map((node) => Number(node.y) || 0));
    const topInset = 210;
    const bottomInset = 12;
    const availableHeight = 1220 - topInset - bottomInset;
    const scaleY = maxY > minY ? availableHeight / (maxY - minY) : 1;
    const nodes = rawNodes.map((node) => ({
      id: node.id,
      label: node.label,
      type: node.type,
      x: Number(node.x) || 0,
      y: topInset + ((Number(node.y) || 0) - minY) * scaleY,
      color: colorOf(node.type),
    }));
    const edges = visible.edges.map((edge) => ({ ...edge, label: relationTextZh(edge.label) }));
    try {
      await renderOntologyGraph({
        container,
        nodes,
        edges,
        selectedNodeId: state.ontology.selectedNodeId,
        activeEdgeId: state.ontology.activeEdgeId,
        onNodeClick: handleOntologyNodeClick,
        onEdgeClick: setActiveOntologyEdge,
        onCanvasClick: () => {
          state.ontology.activeEdgeId = null;
          state.ontology.relationPanelOpen = false;
          render();
        },
        onNodeDragEnd: (nodeId, point) => {
          const rawY = minY + ((Number(point.y) || 0) - topInset) / (scaleY || 1);
          const nextPoint = { x: Number(point.x) || 0, y: rawY };
          state.ontology.layout = { ...state.ontology.layout, [nodeId]: nextPoint };
          state.ontology.nodes = state.ontology.nodes.map((node) => (
            node.id === nodeId ? { ...node, ...nextPoint } : node
          ));
          markOntologyDirty();
        },
      });
    } catch (error) {
      container.innerHTML = `<div class="ontology-g6-error">\u672c\u5730\u56fe\u8c31\u6e32\u67d3\u5931\u8d25\uff1a${escapeHtml(error.message || 'unknown error')}</div>`;
    }
  };

  const renderOntology = () => {
    if (state.currentPage !== 'ontology') return '';
    const relationOptions = ontologyRelations();
    const selected = ontologyNode();
    const activeEdge = activeOntologyEdge();
    const links = ontologyNodeLinks();
    const linkNodeCount = new Set(links.map((item) => item.target)).size;
    const history = state.ontology.history || [];
    return `<section class="ontology-page-stack">
      <section class="hero hero--graph">
        <div><p class="panel__eyebrow">${T.pageOntology}</p><h2>${T.ontologyTitle}</h2><p class="panel__desc">${T.ontologyDesc}</p></div>
        <div class="hero__status"><button class="primary-btn" id="rebuild-ontology-btn">${T.ontologyAutoBuild}</button></div>
      </section>
      <section class="ontology-toolbar panel">
        <div class="ontology-toolbar-layout">
          <div class="ontology-toolbar-pane">
            <div class="panel__header panel__header--compact"><div><p class="panel__eyebrow">${T.pageOntology}</p><h3>${T.ontologyLayeredView}</h3></div></div>
            <div class="ontology-toolbar__filters">
              <label class="ontology-filter"><span>${T.ontologyRelationFilter}</span><select id="ontology-relation-filter"><option value="all">${T.ontologyAllRelations}</option>${relationOptions.map((item) => `<option value="${escapeHtml(item.value)}" ${state.ontology.relationFilter === item.value ? 'selected' : ''}>${escapeHtml(item.text)}</option>`).join('')}</select></label>
            </div>
          </div>
          <div class="ontology-toolbar-pane ontology-toolbar-pane--history">
            <div class="panel__header panel__header--compact panel__header--history"><div><p class="panel__eyebrow">${T.pageOntology}</p><h3>${T.ontologyVersionTitle}</h3></div><button class="secondary-btn ontology-save-btn" id="save-ontology-btn" ${state.ontology.pendingChanges ? '' : 'disabled'}>${T.ontologySaveVersion}</button></div>
            ${state.ontology.pendingChanges ? `<div class="ontology-history-status"><span class="status-chip">${T.ontologyUnsavedChanges}</span></div>` : ''}
            ${history.length ? `<div class="version-list">${history.map((item) => `<article class="version-card ${state.ontology.currentVersionId === item.id ? 'version-card--active' : ''}"><div><strong>${escapeHtml(item.label)}</strong><p>${escapeHtml(formatVersionTime(item.timestamp))}</p></div><button class="secondary-btn" data-ontology-version-id="${item.id}" ${state.ontology.currentVersionId === item.id ? 'disabled' : ''}>${state.ontology.currentVersionId === item.id ? T.ontologyVersionCurrent : T.ontologyVersionRestore}</button></article>`).join('')}</div>` : `<div class="empty-state empty-state--compact">${T.ontologyVersionEmpty}</div>`}
          </div>
        </div>
      </section>
      <section class="ontology-grid">
        <section class="panel panel--graph">
          <div class="graph-board ontology-board ontology-board--g6">
            <div id="ontology-g6-container" class="ontology-g6-container" aria-label="${T.ontologyTitle}"></div>
          </div>
        </section>
        <aside class="side-column ontology-side-column">
          <section class="panel panel--side">
            <div class="panel__header panel__header--compact"><div><p class="panel__eyebrow">${T.ontologySelectedNode}</p><h3>${selected ? escapeHtml(selected.label) : '--'}</h3></div></div>
            ${selected ? `<div class="detail-card"><p class="detail-card__description">${escapeHtml(selected.description || '')}</p><div class="tag-list">${(selected.tags || []).map((tag) => `<span class="tag-list__item">${escapeHtml(tag)}</span>`).join('')}</div></div>` : `<div class="empty-state">${T.ontologyNodeEmpty}</div>`}
            <div class="relation-section relation-section--summary">
              <p class="relation-section__title">${T.ontologyConnected}</p>
              ${links.length ? `<button class="relation-summary-card ${state.ontology.relationPanelOpen ? 'relation-summary-card--open' : ''}" id="toggle-ontology-relations-btn" type="button"><span class="relation-summary-card__title">${T.relationSummaryTitle}</span><span class="relation-summary-card__stats">${links.length} \u6761\u5173\u7cfb\uff0c${linkNodeCount} \u4e2a\u76f8\u5173\u8282\u70b9</span><span class="relation-summary-card__action">${state.ontology.relationPanelOpen ? T.relationSummaryClose : T.relationSummaryOpen}</span></button>${state.ontology.relationPanelOpen ? `<div class="relation-section__list">${links.map((item) => `<article class="relation-item ${item.active ? 'relation-item--active' : ''}" data-ontology-edge-id="${item.id}"><div><strong>${escapeHtml(item.target)}</strong></div><div class="relation-item__meta"><span>${escapeHtml(relationTextZh(item.label))}</span></div></article>`).join('')}</div>` : ''}` : `<div class="empty-state empty-state--compact">${T.ontologyNoConnected}</div>`}
            </div>
          </section>
          <section class="panel panel--side">
            <div class="panel__header panel__header--compact"><div><p class="panel__eyebrow">${T.pageOntology}</p><h3>${T.ontologyEntityEditor}</h3></div></div>
            <div class="ontology-form-grid">
              <label><span class="field-label">${T.ontologyEntityName}</span><input id="ontology-entity-name" type="text" value="${escapeHtml(state.ontology.entityDraft)}"></label>
              <label><span class="field-label">${T.ontologyEntityType}</span><select id="ontology-entity-type"><option value="">${T.ontologyEntityTypePlaceholder}</option>${ENTITY_TYPE_OPTIONS.map((type) => `<option value="${escapeHtml(type)}" ${state.ontology.entityTypeDraft === type ? 'selected' : ''}>${escapeHtml(type)}</option>`).join('')}</select></label>
              <button class="primary-btn" id="add-ontology-entity-btn">${T.ontologyAddEntity}</button>
              <button class="secondary-btn secondary-btn--danger" id="delete-ontology-entity-btn" ${selected ? '' : 'disabled'}>${T.ontologyDeleteEntity}</button>
            </div>
            <div class="empty-state empty-state--compact">${selected ? `${escapeHtml(selected.label)} / ${escapeHtml(selected.type || '--')}` : T.ontologyDeleteEntityEmpty}</div>
            <div class="ontology-divider"></div>
            <div class="panel__header panel__header--compact"><div><p class="panel__eyebrow">${T.pageOntology}</p><h3>${T.ontologyRelationEditor}</h3></div></div>
            <div class="ontology-form-grid">
              <label><span class="field-label">${T.ontologyRelationName}</span><input id="ontology-relation-name" type="text" value="${escapeHtml(state.ontology.relationDraft)}"></label>
              <label><span class="field-label">${T.ontologyRelationSource}</span><select id="ontology-relation-source"><option value=""></option>${state.ontology.nodes.map((node) => `<option value="${node.id}" ${state.ontology.relationSourceDraft === node.id ? 'selected' : ''}>${escapeHtml(node.label)}</option>`).join('')}</select></label>
              <label><span class="field-label">${T.ontologyRelationTarget}</span><select id="ontology-relation-target"><option value=""></option>${state.ontology.nodes.map((node) => `<option value="${node.id}" ${state.ontology.relationTargetDraft === node.id ? 'selected' : ''}>${escapeHtml(node.label)}</option>`).join('')}</select></label>
              <button class="primary-btn" id="add-ontology-relation-btn">${T.ontologyAddRelation}</button>
              <button class="secondary-btn secondary-btn--danger" id="delete-ontology-relation-btn" ${activeEdge ? '' : 'disabled'}>${T.ontologyDeleteRelation}</button>
            </div>
            <div class="empty-state empty-state--compact">${activeEdge ? `${escapeHtml((state.ontology.nodes.find((node) => node.id === activeEdge.source)?.label) || activeEdge.source)} -> ${escapeHtml((state.ontology.nodes.find((node) => node.id === activeEdge.target)?.label) || activeEdge.target)} / ${escapeHtml(relationTextZh(activeEdge.label))}` : T.ontologyDeleteRelationEmpty}</div>
          </section>
        </aside>
      </section>
    </section>`;
  };

  const renderExtractClean = () => {
    if (state.currentPage !== 'extract') return '';
    const EXTRACT_SAMPLE_LIMIT = 20;
    if (!['table', 'document', 'image'].includes(state.sourceType)) state.sourceType = 'table';
    const isDocument = state.sourceType === 'document';
    const isImage = state.sourceType === 'image';
    const result = state.extractionResult;
    const counts = extractCounts();
    const kgBuild = result?.kgBuild;
    const kgProgress = state.kgBuildProgress || kgProgressFromBuild(kgBuild);
    const relationRows = isImage ? [] : (result?.tripleRows || []);
    const relationSamples = [];
    const relationSampleKeys = new Set();
    for (const item of relationRows) {
      const key = `${item.subjectType}__${item.predicate}__${item.objectType}`;
      if (relationSampleKeys.has(key)) continue;
      relationSampleKeys.add(key);
      relationSamples.push({
        subject: item.subjectType || item.subject,
        predicate: item.predicate,
        object: item.objectType || item.object,
      });
      if (relationSamples.length >= EXTRACT_SAMPLE_LIMIT) break;
    }
    const relationSampleRows = relationSamples;
    const tripleRows = relationRows.slice(0, EXTRACT_SAMPLE_LIMIT);
    const selectedFiles = [state.selectedFile, ...(state.extraTableFiles || [])].filter(Boolean);
    const hasGeneratedContent = Boolean(result);
    const extractError = String(result?.error || '').trim();
    const sourceLabels = { table: '表格抽取', document: '文档抽取', image: '图片抽取' };
    const loadingText = state.kgBuildProgress?.status === 'building' ? '正在构建图谱...' : T.extracting;
    const sourceTabs = ['table', 'document', 'image'].map((type) => `<button class="tab-group__button ${state.sourceType === type ? 'tab-group__button--active' : ''}" data-source-type="${type}">${sourceLabels[type]}</button>`).join('');
    const docSummary = result?.documentSummary || {};
    const imageSummary = result?.imageSummary || {};
    const imageRows = Array.isArray(result?.imageTableRows) ? result.imageTableRows : [];
    const imageName = imageSummary.imageName || imageSummary.drawingName || state.selectedFileName || '';
    const imageDisplayName = imageSummary.partName || imageName || '图片信息抽取结果';
    const imageSizeText = result?.width && result?.height
      ? `${result.width} x ${result.height}`
      : (result?.fileSize ? `${Math.ceil(result.fileSize / 1024)} KB` : '--');
    const resultScaleText = isDocument
      ? `${result?.charCount || 0} 字${result?.pageCount ? ` / ${result.pageCount} 页` : ''}`
      : (isImage ? imageSizeText : selectedFiles.length);
    const resultJsonPath = result?.documentJsonPath || result?.imageJsonPath || '';
    const resultExcelPath = result?.imageExcelPath || '';
    const docItemText = (item, keys) => {
      if (typeof item === 'string') return item;
      if (!item || typeof item !== 'object') return '';
      const texts = keys.map((key) => item[key]).filter((value) => String(value || '').trim()).map((value) => String(value).trim());
      return texts.length ? texts.join(' / ') : JSON.stringify(item);
    };
    const renderDocSummaryList = (title, items, keys) => {
      const rows = Array.isArray(items) ? items.slice(0, 5) : [];
      return `<article class="document-insight-card"><h4>${escapeHtml(title)}</h4>${rows.length ? `<ul>${rows.map((item) => `<li>${escapeHtml(docItemText(item, keys))}</li>`).join('')}</ul>` : `<p>暂无提取结果</p>`}</article>`;
    };
    const documentSummaryPanel = isDocument && result ? `<section class="panel">
      <div class="panel__header panel__header--compact"><div><p class="panel__eyebrow">文档知识</p><h3>${escapeHtml(docSummary.equipment || '说明书知识概括')}</h3></div></div>
      ${result.llmMessage ? `<div class="empty-state empty-state--compact">${escapeHtml(result.llmMessage)}</div>` : ''}
      <div class="document-insight-grid">
        ${renderDocSummaryList('功能', docSummary.functions, ['name', 'description'])}
        ${renderDocSummaryList('特点', docSummary.features, ['name', 'description'])}
        ${renderDocSummaryList('维修维护', docSummary.maintenance, ['task', 'method', 'cycle', 'warning'])}
        ${renderDocSummaryList('故障类型', docSummary.faultTypes, ['fault', 'phenomenon', 'cause', 'handling'])}
        ${renderDocSummaryList('安全注意事项', docSummary.safetyNotes, ['note', 'context'])}
        ${renderDocSummaryList('技术参数', docSummary.specifications, ['name', 'value', 'unit'])}
      </div>
    </section>` : '';
    const imageResultPanel = extractError ? `
      <div class="empty-state" style="border-color: rgba(210,52,70,0.45); color:#9f1f2d;">解析失败：${escapeHtml(extractError)}</div>
    ` : result ? `
      ${result.llmMessage ? `<div class="empty-state empty-state--compact">${escapeHtml(result.llmMessage)}</div>` : ''}
      <div class="image-result-title">
        <span>图片名称：${escapeHtml(imageName || '--')}</span>
        <strong>零件名称：${escapeHtml(imageSummary.partName || '--')}</strong>
      </div>
      <div class="table-block image-result-table">
        <table>
          <thead>
            <tr><th>序号</th><th>零件名称</th><th>技术要求</th></tr>
          </thead>
          <tbody>
            ${imageRows.length ? imageRows.map((item, index) => `<tr><td>${escapeHtml(item.index || String(index + 1))}</td><td>${escapeHtml(item.partName || imageSummary.partName || imageName || '--')}</td><td>${escapeHtml(item.technicalRequirement || item.requirement || item.imageText || item.text || '--')}</td></tr>`).join('') : '<tr><td colspan="3">暂无技术要求抽取结果</td></tr>'}
          </tbody>
        </table>
      </div>
      ${resultExcelPath ? `<div class="empty-state empty-state--compact">Excel结果：${escapeHtml(resultExcelPath)}</div>` : ''}
      ${renderKgBuildProgress(kgProgress)}
    ` : `<div class="image-result-empty"><div></div><p>${state.selectedFile ? '已选择图片，请点击开始处理' : '暂无处理结果，请上传图片后开始处理'}</p></div>`;
    const uploadPanel = isDocument ? `
            <div class="upload-box upload-box--stage">
              <div class="upload-visual"><div class="upload-icon upload-icon--stage">+</div><div><strong>上传使用说明书文档</strong><p class="upload-helper">支持 .pdf / .docx / .txt / .md，用大模型辅助提取功能、特点、维修维护、故障类型和关键参数。</p></div></div>
              <div class="upload-extra">
                <div class="toolbar-actions extract-stage__actions">
                  <button class="secondary-btn" id="extract-trigger-document-btn">选择文档</button>
                  <button class="tab-group__button tab-group__button--active" id="extract-run-btn" ${state.loading || !state.selectedFile ? 'disabled' : ''}>${state.loading ? loadingText : '执行文档抽取'}</button>
                </div>
                <label><span class="field-label">说明书文档</span><input id="extract-document-file" type="file" accept=".pdf,.docx,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown"></label>
                <div class="summary-bar summary-bar--file"><div><strong>当前文档</strong><span>${state.selectedFile ? escapeHtml(state.selectedFile.name) : '未选择文件'}</span></div><em>${state.selectedFile ? sourceHint('document') : '请先上传一份使用说明书文档'}</em></div>
                ${extractError ? `<div class="empty-state" style="border-color: rgba(210,52,70,0.45); color:#9f1f2d;">解析失败：${escapeHtml(extractError)}</div>` : ''}
              </div>
            </div>` : isImage ? `
            <div class="image-workflow-grid">
              <section class="image-workflow-panel">
                <h4>工作流图片处理</h4>
                <div class="image-form-row">
                  <span class="field-label field-label--required">上传图片</span>
                  <button class="image-upload-preview" id="extract-trigger-image-btn" type="button" aria-label="选择图片">
                    ${state.imagePreviewUrl ? `<img src="${escapeHtml(state.imagePreviewUrl)}" alt="上传图片预览">` : '<span class="image-upload-plus">+</span>'}
                  </button>
                  <p class="upload-helper">支持 jpg、png、jpeg、webp、bmp、tif 格式。</p>
                  <input id="extract-image-file" type="file" accept=".png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff,image/*">
                </div>
                <label><span class="field-label field-label--required">图片名称</span><input class="image-name-input" value="${escapeHtml(imageName || state.selectedFileName || '')}" placeholder="上传图片后自动填充" readonly></label>
                <div class="toolbar-actions extract-stage__actions">
                  <button class="tab-group__button tab-group__button--active" id="extract-run-btn" ${state.loading || !state.selectedFile ? 'disabled' : ''}>${state.loading ? loadingText : '开始处理'}</button>
                  <button class="secondary-btn" id="extract-reset-btn" type="button">重置</button>
                </div>
                ${extractError ? `<div class="empty-state" style="border-color: rgba(210,52,70,0.45); color:#9f1f2d;">解析失败：${escapeHtml(extractError)}</div>` : ''}
              </section>
              <section class="image-workflow-panel image-workflow-panel--result">
                <h4>处理结果</h4>
                ${imageResultPanel}
              </section>
            </div>` : `
            <div class="upload-box upload-box--stage upload-box--table">
              <div class="upload-visual"><div class="upload-icon upload-icon--stage">+</div><div><strong>批量上传 Excel 表格</strong><p class="upload-helper">支持 .xlsx / .xls / .csv，多个文件分别抽取，最后自动合并结果。</p></div></div>
              <div class="upload-extra">
                <div class="toolbar-actions extract-stage__actions">
                  <button class="secondary-btn" id="extract-trigger-batch-btn">批量上传表格</button>
                  <button class="tab-group__button tab-group__button--active" id="extract-run-btn" ${state.loading || !state.selectedFile ? 'disabled' : ''}>${state.loading ? loadingText : '执行表格解析'}</button>
                </div>
                <label><span class="field-label">批量文件</span><input id="extract-batch-files" type="file" multiple accept=".xlsx,.xls,.csv"></label>
                <div class="summary-bar summary-bar--file"><div><strong>当前文件</strong><span>${selectedFiles.length ? escapeHtml(selectedFiles.map((file) => file.name).join('、')) : '未选择文件'}</span></div><em>${selectedFiles.length ? `共 ${selectedFiles.length} 份文件，将分别抽取后自动合并` : '请先批量上传需要解析的表格'}</em></div>
                ${extractError ? `<div class="empty-state" style="border-color: rgba(210,52,70,0.45); color:#9f1f2d;">解析失败：${escapeHtml(extractError)}</div>` : ''}
              </div>
            </div>`;

    return `<section class="extract-page-stack extract-page-shell">
      <section class="extract-stage">
        <h3 class="extract-stage__title">${T.pageExtract}</h3>
        <div class="extract-stage__card">
          <section class="extract-stage__inner">
            <div class="extract-stage__header">
              <div>
                <p class="panel__eyebrow">数据导入</p>
                <h3>${isDocument ? '上传并执行文档知识抽取' : (isImage ? '上传并执行图片信息抽取' : '批量上传并执行表格解析')}</h3>
              </div>
              <div class="tab-group extract-stage__tabs">${sourceTabs}</div>
            </div>
            ${graphPickerMarkup({ allowCreate: true })}
            ${uploadPanel}
          </section>
        </div>
      </section>
      ${!isImage && hasGeneratedContent ? `<section class="extract-grid extract-grid--separated">
        <section class="panel">
          <div class="panel__header panel__header--compact"><div><p class="panel__eyebrow">${T.pageExtract}</p><h3>抽取统计</h3></div></div>
          <div class="table-block">
            <table>
              <thead>
                <tr><th>文件</th><th>抽取类型</th><th>${isDocument ? '文本规模' : (isImage ? '图片信息' : '文件数')}</th><th>节点数</th><th>关系数</th><th>三元组数</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>${escapeHtml(result?.fileName || state.selectedFileName || '--')}</td>
                  <td>${sourceLabels[state.sourceType] || '知识抽取'}</td>
                  <td>${escapeHtml(resultScaleText)}</td>
                  <td>${counts.entities || 0}</td>
                  <td>${counts.relations || 0}</td>
                  <td>${counts.triples || 0}</td>
                </tr>
              </tbody>
            </table>
          </div>
          ${resultJsonPath ? `<div class="empty-state empty-state--compact">结果文件：${escapeHtml(resultJsonPath)}</div>` : ''}
          ${renderKgBuildProgress(kgProgress)}
        </section>
        <section class="panel config-panel">
          <div class="panel__header panel__header--compact"><div><p class="panel__eyebrow">${T.pageExtract}</p><h3>节点关系展示（前 ${EXTRACT_SAMPLE_LIMIT} 条样例）</h3></div></div>
          ${relationSampleRows.length ? `<div class="results-list">${relationSampleRows.map((item) => `<article class="results-item"><strong>${escapeHtml(item.subject)}</strong><p>${escapeHtml(item.predicate)} -> ${escapeHtml(item.object)}</p></article>`).join('')}</div>` : `<div class="empty-state">暂无关系概括</div>`}
        </section>
        <section class="result-stack">
          ${documentSummaryPanel}
          <section class="panel">
            <div class="panel__header panel__header--compact"><div><p class="panel__eyebrow">${T.pageExtract}</p><h3>三元组展示（前 ${EXTRACT_SAMPLE_LIMIT} 条样例）</h3></div></div>
            ${tripleRows.length ? `<div class="triple-list">${tripleRows.map((item) => `<article class="triple-item"><div class="triple-line"><span class="triple-node">${escapeHtml(item.subject)}</span><span class="triple-rel">${escapeHtml(item.predicate)}</span><span class="triple-node">${escapeHtml(item.object)}</span></div></article>`).join('')}</div>` : `<div class="empty-state">${T.extractNoResult}</div>`}
          </section>
        </section>
      </section>` : ``}
    </section>`;
  };

  const renderVersionManagement = () => {
    if (state.currentPage !== 'versions') return '';
    const versionState = state.versioning || {};
    const versions = Array.isArray(versionState.versions) ? versionState.versions : [];
    const latest = versions[0] || null;
    const currentGraph = selectedGraph();
    const graphRows = state.graphs || [];
    const rollbackSummary = versionState.lastRollback?.summary?.rollback || null;
    return `<section class="version-page-stack extract-page-shell">
      <section class="panel">
        <div class="panel__header panel__header--compact">
          <div><p class="panel__eyebrow">${T.pageVersion}</p><h3>全部图谱</h3></div>
          <button class="secondary-btn" id="refresh-graphs-btn" ${state.graphsLoading ? 'disabled' : ''}>${state.graphsLoading ? '正在刷新...' : '刷新图谱列表'}</button>
        </div>
        ${graphPickerMarkup({ compact: true })}
        <div class="table-block graph-catalog-table">
          <table>
            <thead><tr><th>图谱名称</th><th>数据库</th><th>版本数</th><th>节点</th><th>关系</th><th>最新变更</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>${graphRows.length ? graphRows.map((item) => `<tr class="${item.database === state.selectedGraphDatabase ? 'graph-catalog-table__selected' : ''}"><td><strong>${escapeHtml(item.name || item.database)}</strong></td><td>${escapeHtml(item.database)}</td><td>${Number(item.versionCount || 0)}</td><td>${Number(item.nodeCount || 0)}</td><td>${Number(item.edgeCount || 0)}</td><td>${escapeHtml(item.latestVersionAt ? formatVersionTime(item.latestVersionAt) : '--')}</td><td>${item.available === false ? `<span class="status-chip graph-status--error">不可用</span>` : '<span class="status-chip status-chip--online">可用</span>'}</td><td class="graph-catalog-actions"><button class="secondary-btn" data-graph-select="${escapeHtml(item.database)}" ${item.database === state.selectedGraphDatabase ? 'disabled' : ''}>${item.database === state.selectedGraphDatabase ? '当前图谱' : '选择'}</button>${item.isDefault ? '' : `<button class="secondary-btn secondary-btn--danger" data-graph-delete="${escapeHtml(item.database)}">删除</button>`}</td></tr>`).join('') : '<tr><td colspan="8">暂无已登记图谱</td></tr>'}</tbody>
          </table>
        </div>
      </section>
      <section class="panel">
        <div class="panel__header panel__header--compact">
          <div><p class="panel__eyebrow">${T.pageVersion}</p><h3>${escapeHtml(currentGraph?.name || '当前图谱')}的修改记录</h3></div>
          <div class="toolbar-actions">
            <button class="secondary-btn" id="refresh-kg-versions-btn" ${versionState.loading || versionState.rollbacking || !currentGraph ? 'disabled' : ''}>刷新</button>
            <button class="secondary-btn secondary-btn--danger" id="rollback-kg-version-btn" ${latest && !versionState.loading && !versionState.rollbacking && currentGraph ? '' : 'disabled'}>${versionState.rollbacking ? '正在回退...' : '回退上一版'}</button>
          </div>
        </div>
        ${versionState.error ? `<div class="empty-state" style="border-color: rgba(210,52,70,0.45); color:#9f1f2d;">${escapeHtml(versionState.error)}</div>` : ''}
        ${rollbackSummary ? `<div class="empty-state empty-state--compact">最近回退：删除关系 ${rollbackSummary.deleted_relationships || 0}，恢复关系 ${rollbackSummary.restored_relationships || 0}，删除节点 ${rollbackSummary.deleted_nodes || 0}，恢复节点 ${rollbackSummary.restored_nodes || 0}</div>` : ''}
        <div class="table-block">
          <table>
            <thead>
              <tr><th>修改次数</th><th>最新版本时间</th><th>当前节点</th><th>当前关系类型</th><th>当前三元组</th></tr>
            </thead>
            <tbody>
              <tr>
                <td>${currentGraph?.versionCount ?? versions.length}</td>
                <td>${latest ? escapeHtml(formatVersionTime(latest.createdAt)) : escapeHtml(currentGraph?.latestVersionAt ? formatVersionTime(currentGraph.latestVersionAt) : '--')}</td>
                <td>${currentGraph?.nodeCount ?? 0}</td>
                <td>${currentGraph?.relationTypeCount ?? 0}</td>
                <td>${currentGraph?.edgeCount ?? 0}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
      <section class="panel">
        <div class="panel__header panel__header--compact"><div><p class="panel__eyebrow">${T.pageVersion}</p><h3>近 10 次变更</h3></div></div>
        ${versionState.loading ? `<div class="empty-state">正在读取版本记录...</div>` : (versions.length ? `<div class="version-list kg-version-list">${versions.map((item, index) => `
          <article class="version-card ${index === 0 ? 'version-card--active' : ''}">
            <div>
              <strong>${escapeHtml(item.fileName || '未命名数据')}</strong>
              <p>${escapeHtml(formatVersionTime(item.createdAt))} / ${escapeHtml(kgSourceText(item.sourceType))}</p>
              <p>节点 ${item.counts?.entities || 0} / 关系类型 ${item.counts?.relations || 0} / 三元组 ${item.counts?.triples || 0}</p>
              <p>${escapeHtml(versionWriteText(item))}</p>
            </div>
            <button class="secondary-btn ${index === 0 ? 'secondary-btn--danger' : ''}" data-kg-rollback-version="${escapeHtml(item.versionId || '')}" ${index === 0 && !versionState.rollbacking ? '' : 'disabled'}>${index === 0 ? '回退此版本' : '需先回退较新版本'}</button>
          </article>`).join('')}</div>` : `<div class="empty-state">暂无图谱版本记录</div>`)}
      </section>
    </section>`;
  };

  const render = () => {
    if (!['ontology', 'extract', 'versions'].includes(state.currentPage)) state.currentPage = 'ontology';
    const sidebar = embedded ? '' : `<aside class="sidebar"><div class="brand"><div class="brand-logo">KG</div><div><p class="brand-subtitle">Knowledge Graph Platform</p><h1>${T.system}</h1></div></div><nav class="menu"><button class="menu-item ${state.currentPage === 'ontology' ? 'active' : ''}" data-page="ontology">${T.pageOntology}</button><button class="menu-item ${state.currentPage === 'extract' ? 'active' : ''}" data-page="extract">${T.pageExtract}</button><button class="menu-item ${state.currentPage === 'versions' ? 'active' : ''}" data-page="versions">${T.pageVersion}</button></nav></aside>`;
    const topbar = embedded ? '' : `<header class="topbar"><div><p class="topbar-label">${T.frontDesk}</p><h2>${pageTitle()}</h2></div><div class="topbar-actions"><span class="status-chip status-chip--online">${T.apiConnected}</span><span class="status-chip">${T.operator}</span></div></header>`;
    root.innerHTML = `<div class="shell ${embedded ? 'shell--embedded' : ''}">${sidebar}<main class="content ${embedded ? 'content--embedded' : ''}">${topbar}${renderOntology()}${renderExtractClean()}${renderVersionManagement()}</main></div>`;
    bindEvents();
    syncOntologyGraph().catch(() => {});
  };

  const addOntologyEntity = () => {
    const label = String(state.ontology.entityDraft || '').trim();
    const selectedType = String(state.ontology.entityTypeDraft || '').trim();
    const type = ATTRIBUTE_LABELS.includes(label) ? LABELS.attribute : selectedType;
    if (!label) return;
    if (!type) return;
    const existing = state.ontology.nodes.find((node) => node.label === label);
    if (existing) {
      state.ontology.selectedNodeId = existing.id;
      state.ontology.relationSourceDraft = existing.id;
      render();
      return;
    }
    const node = {
      id: `ontology-node-${Date.now()}`,
      label,
      type,
      level: inferLevel(type),
      description: `${label}\u672c\u4f53\u8282\u70b9`,
      tags: unique([type, label]),
    };
    state.ontology.nodes = [...state.ontology.nodes, node].sort((a, b) => (a.level - b.level) || a.label.localeCompare(b.label, 'zh-CN'));
    state.ontology.selectedNodeId = node.id;
    state.ontology.relationSourceDraft = node.id;
    state.ontology.relationTargetDraft = '';
    state.ontology.relationFilter = 'all';
    state.ontology.activeEdgeId = null;
    state.ontology.relationPanelOpen = false;
    state.ontology.entityDraft = '';
    state.ontology.entityTypeDraft = '';
    state.schema.entityTypes = unique([...(state.schema.entityTypes || []), type]);
    persistSchema();
    updateOntologyLayout();
    markOntologyDirty();
    render();
  };

  const deleteSelectedOntologyEntity = () => {
    const selected = ontologyNode();
    if (!selected) return;
    state.ontology.nodes = state.ontology.nodes.filter((node) => node.id !== selected.id);
    state.ontology.edges = state.ontology.edges.filter((edge) => edge.source !== selected.id && edge.target !== selected.id);
    state.ontology.selectedNodeId = state.ontology.nodes[0]?.id || null;
    state.ontology.relationSourceDraft = state.ontology.selectedNodeId || '';
    state.ontology.relationTargetDraft = '';
    state.ontology.activeEdgeId = null;
    state.ontology.relationPanelOpen = false;
    state.ontology.relationFilter = 'all';
    updateOntologyLayout();
    markOntologyDirty();
    render();
  };

  const addOntologyRelation = () => {
    const source = state.ontology.relationSourceDraft;
    const target = state.ontology.relationTargetDraft;
    const labelText = String(state.ontology.relationDraft || '').trim();
    if (!source || !target || !labelText || source === target) return;
    const normalizedLabel = canonicalRelationLabel(labelText);
    if (state.ontology.edges.some((edge) => edge.source === source && edge.target === target && canonicalRelationLabel(edge.label) === normalizedLabel)) return;
    const newEdge = { id: `ontology-edge-${Date.now()}`, source, target, label: normalizedLabel };
    state.ontology.edges = sanitizeOntologyEdges([...state.ontology.edges, newEdge]);
    state.schema.relationTypes = unique([...(state.schema.relationTypes || []), normalizedLabel]);
    state.ontology.relationFilter = relationTextZh(normalizedLabel);
    state.ontology.activeEdgeId = newEdge.id;
    state.ontology.relationDraft = '';
    persistSchema();
    updateOntologyLayout();
    markOntologyDirty();
    render();
  };

  const deleteActiveOntologyRelation = () => {
    const edgeId = state.ontology.activeEdgeId;
    if (!edgeId) return;
    state.ontology.edges = state.ontology.edges.filter((edge) => edge.id !== edgeId);
    state.ontology.activeEdgeId = null;
    state.ontology.relationPanelOpen = false;
    state.ontology.relationFilter = 'all';
    updateOntologyLayout();
    markOntologyDirty();
    render();
  };

  const setActiveOntologyEdge = (edgeId) => {
    state.ontology.activeEdgeId = state.ontology.activeEdgeId === edgeId ? null : edgeId;
    render();
  };

  const resetOntologyRelationView = () => {
    state.ontology.relationFilter = 'all';
    state.ontology.activeEdgeId = null;
    state.ontology.relationPanelOpen = false;
    state.ontology.selectedNodeId = state.ontology.nodes[0]?.id || null;
    updateOntologyLayout();
    render();
  };

  const rebuildOntology = () => {
    const graph = buildOntology(state.schema);
    state.ontology.nodes = graph.nodes;
    state.ontology.edges = graph.edges;
    state.ontology.selectedNodeId = graph.nodes[0]?.id || null;
    state.ontology.activeEdgeId = null;
    state.ontology.relationFilter = 'all';
    updateOntologyLayout();
    markOntologyDirty();
    render();
  };

  const saveOntologyVersion = () => {
    if (!state.ontology.pendingChanges) return;
    commitOntologyVersion();
    state.ontology.pendingChanges = false;
    render();
  };

  const resetExtractWorkspace = () => {
    clearImagePreview();
    state.parseConfig = null;
    state.extractionResult = null;
    state.kgBuildProgress = null;
    state.selectedFileName = '';
    state.selectedFile = null;
    state.selectedFiles = [];
    state.extraTableFiles = [];
    state.extraTableFileName = '';
    state.extraTableFile = null;
    state.loading = false;
    render();
  };

  const changeExtractSourceType = (type) => {
    clearImagePreview();
    state.sourceType = type;
    state.parseConfig = null;
    state.extractionResult = null;
    state.kgBuildProgress = null;
    state.selectedFileName = '';
    state.selectedFile = null;
    state.selectedFiles = [];
    state.extraTableFiles = [];
    state.extraTableFileName = '';
    state.extraTableFile = null;
    render();
  };

  const updateExtractMappingType = (index, entityType) => {
    if (!state.parseConfig?.headers?.[index]) return;
    state.parseConfig.headers[index].entityType = entityType;
    render();
  };

  const buildExtractMappings = () => (state.parseConfig?.headers || []).map((item) => ({
    header: item.header,
    entityType: item.entityType || item.defaultType || LABELS.attribute,
    source: item.source || 'primary',
  }));

  const requestParsePreview = async () => {
    if (!state.selectedFileName && !state.selectedFile) return;
    state.loading = true;
    render();
    try {
      let result;
      if (state.sourceType === 'table' && state.selectedFile) {
        const form = new FormData();
        form.append('sourceType', state.sourceType);
        form.append('file', state.selectedFile);
        if (state.extraTableFile) form.append('extraFile', state.extraTableFile);
        result = await requestGraphJson('/api/parse-preview', { method: 'POST', body: form });
      } else if ((state.sourceType === 'document' || state.sourceType === 'image') && state.selectedFile) {
        const form = new FormData();
        form.append('sourceType', state.sourceType);
        form.append('file', state.selectedFile);
        result = await requestGraphJson('/api/parse-preview', { method: 'POST', body: form });
      } else {
        result = await requestGraphJson('/api/parse-preview', {
          method: 'POST',
          body: JSON.stringify({ sourceType: state.sourceType, fileName: state.selectedFileName }),
        });
      }
      if (Array.isArray(result?.headers)) {
        result.headers = result.headers.map((item) => ({ ...item, entityType: item.entityType || item.defaultType || LABELS.attribute }));
      }
      state.parseConfig = result;
    } catch (error) {
      state.parseConfig = { headers: [], entityTypes: [], fileName: error.message };
    } finally {
      state.loading = false;
      render();
    }
  };

  const runExtraction = async () => {
    if (state.sourceType === 'table' && !state.selectedFile) return;
    if (state.sourceType !== 'table' && !state.selectedFileName && !state.selectedFile) return;
    state.loading = true;
    state.kgBuildProgress = null;
    render();
    try {
      const mappings = buildExtractMappings();
      let result;
      if (state.sourceType === 'table') {
        const batchResults = [];
        const batchFiles = [state.selectedFile, ...(state.extraTableFiles || [])].filter(Boolean);
        for (const file of batchFiles) {
          const form = new FormData();
          form.append('sourceType', state.sourceType);
          form.append('file', file);
          form.append('mappings', JSON.stringify(mappings));
          batchResults.push(await requestGraphJson('/api/extract', { method: 'POST', body: form }));
        }
        result = mergeExtractionResults(batchResults, state.sourceType);
      } else if (state.sourceType === 'document' || state.sourceType === 'image') {
        const form = new FormData();
        form.append('sourceType', state.sourceType);
        form.append('file', state.selectedFile);
        result = await requestGraphJson('/api/extract', { method: 'POST', body: form });
      } else {
        result = await requestGraphJson('/api/extract', {
          method: 'POST',
          body: JSON.stringify({ sourceType: state.sourceType, fileName: state.selectedFileName, mappings }),
        });
      }
      state.extractionResult = result;
      state.kgBuildProgress = result?.kgBuild ? kgProgressFromBuild(result.kgBuild) : null;
      render();
      if (shouldBuildKgFromExtraction(result)) {
        const requestId = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
        state.kgBuildProgress = { ...kgProgressBuilding(result), requestId };
        render();
        try {
          const kgBuild = await requestGraphJson('/api/kg/build', {
            method: 'POST',
            body: JSON.stringify({ extractionResult: result, recordVersion: true }),
          });
          if (state.kgBuildProgress?.requestId === requestId) {
            state.extractionResult = { ...(state.extractionResult || result), kgBuild };
            state.kgBuildProgress = kgProgressFromBuild(kgBuild);
          }
        } catch (buildError) {
          if (state.kgBuildProgress?.requestId === requestId) {
            const kgBuild = {
              status: 'failed',
              error: buildError.message,
              payloadCounts: kgExtractionCounts(result),
            };
            state.extractionResult = { ...(state.extractionResult || result), kgBuild };
            state.kgBuildProgress = kgProgressFailed(buildError, result);
          }
        }
      }
    } catch (error) {
      state.extractionResult = {
        fileName: state.selectedFileName,
        counts: { triples: 0, entities: 0, relations: 0 },
        entities: [],
        relations: [],
        tripleRows: [],
        appliedMappings: [],
        error: error.message,
      };
      state.kgBuildProgress = null;
    } finally {
      state.loading = false;
      render();
    }
  };

  const fetchKgVersions = async () => {
    const requestedDatabase = state.selectedGraphDatabase;
    const requestId = `${Date.now()}-${Math.random()}`;
    state.versioning = { ...(state.versioning || {}), loading: true, error: '', requestId };
    render();
    try {
      const result = await requestGraphJson('/api/kg/versions?limit=10');
      if (state.versioning?.requestId !== requestId) return;
      const returnedDatabase = String(result?.graphDatabase || '').trim();
      if (returnedDatabase && returnedDatabase !== requestedDatabase) {
        throw new Error('版本记录与当前选中图谱不一致，请刷新后重试。');
      }
      state.versioning = {
        ...(state.versioning || {}),
        versions: Array.isArray(result?.versions) ? result.versions : [],
        loaded: true,
        error: '',
      };
    } catch (error) {
      if (state.versioning?.requestId !== requestId) return;
      state.versioning = {
        ...(state.versioning || {}),
        loaded: true,
        error: error.message || '版本记录读取失败',
      };
    } finally {
      if (state.versioning?.requestId === requestId) {
        state.versioning.loading = false;
        render();
      }
    }
  };

  const rollbackKgVersion = async () => {
    const versions = Array.isArray(state.versioning?.versions) ? state.versioning.versions : [];
    if (!versions.length || state.versioning?.rollbacking) return;
    if (!window.confirm('确定回退最近一次图谱修改吗？')) return;
    state.versioning = { ...(state.versioning || {}), rollbacking: true, error: '' };
    render();
    try {
      const result = await requestGraphJson('/api/kg/rollback', { method: 'POST', body: JSON.stringify({}) });
      state.versioning = {
        ...(state.versioning || {}),
        versions: Array.isArray(result?.history?.versions) ? result.history.versions : [],
        loaded: true,
        lastRollback: result,
        error: '',
      };
      if (!Array.isArray(result?.history?.versions)) {
        await fetchKgVersions();
        return;
      }
    } catch (error) {
      state.versioning = {
        ...(state.versioning || {}),
        error: error.message || '版本回退失败',
      };
    } finally {
      state.versioning.rollbacking = false;
      render();
    }
  };

  const bindEvents = () => {
    root.querySelectorAll('[data-page]').forEach((button) => button.addEventListener('click', () => {
      state.currentPage = button.dataset.page;
      render();
      if (state.currentPage === 'versions' && !state.versioning?.loaded) fetchKgVersions();
    }));
    root.querySelectorAll('[data-source-type]').forEach((button) => button.addEventListener('click', () => changeExtractSourceType(button.dataset.sourceType)));
    root.querySelectorAll('#graph-select').forEach((select) => select.addEventListener('change', (event) => {
      void selectGraph(event.target.value);
    }));
    root.querySelectorAll('[data-graph-select]').forEach((button) => button.addEventListener('click', () => {
      void selectGraph(button.dataset.graphSelect);
    }));
    root.querySelectorAll('[data-graph-delete]').forEach((button) => button.addEventListener('click', () => {
      void deleteGraph(button.dataset.graphDelete);
    }));
    const refreshGraphsBtn = root.querySelector('#refresh-graphs-btn');
    if (refreshGraphsBtn) refreshGraphsBtn.addEventListener('click', () => { void fetchGraphs(); });
    const graphCreateName = root.querySelector('#graph-create-name');
    if (graphCreateName) graphCreateName.addEventListener('input', (event) => { state.graphCreateName = event.target.value; });
    const graphCreateBtn = root.querySelector('#graph-create-btn');
    if (graphCreateBtn) graphCreateBtn.addEventListener('click', () => { void createGraph(); });
    root.querySelectorAll('[data-ontology-edge-id]').forEach((item) => item.addEventListener('click', () => setActiveOntologyEdge(item.dataset.ontologyEdgeId)));
    root.querySelectorAll('[data-ontology-version-id]').forEach((button) => button.addEventListener('click', () => restoreOntologyVersion(button.dataset.ontologyVersionId)));
    root.querySelectorAll('[data-mapping-index]').forEach((select) => select.addEventListener('change', (event) => updateExtractMappingType(Number(event.target.dataset.mappingIndex), event.target.value)));
    const relationFilter = root.querySelector('#ontology-relation-filter');
    if (relationFilter) relationFilter.addEventListener('change', (event) => {
      const value = String(event.target.value || '').trim();
      if (value === 'all') {
        resetOntologyRelationView();
        return;
      }
      state.ontology.relationFilter = value;
      state.ontology.activeEdgeId = null;
      state.ontology.relationPanelOpen = false;
      updateOntologyLayout();
      render();
    });
    const toggleRelationsBtn = root.querySelector('#toggle-ontology-relations-btn');
    if (toggleRelationsBtn) toggleRelationsBtn.addEventListener('click', () => {
      state.ontology.relationPanelOpen = !state.ontology.relationPanelOpen;
      render();
    });
    const rebuildBtn = root.querySelector('#rebuild-ontology-btn');
    if (rebuildBtn) rebuildBtn.addEventListener('click', rebuildOntology);
    const saveOntologyBtn = root.querySelector('#save-ontology-btn');
    if (saveOntologyBtn) saveOntologyBtn.addEventListener('click', saveOntologyVersion);
    const entityName = root.querySelector('#ontology-entity-name');
    if (entityName) entityName.addEventListener('input', (event) => { state.ontology.entityDraft = event.target.value; });
    const entityType = root.querySelector('#ontology-entity-type');
    if (entityType) entityType.addEventListener('change', (event) => { state.ontology.entityTypeDraft = event.target.value; });
    const addEntityBtn = root.querySelector('#add-ontology-entity-btn');
    if (addEntityBtn) addEntityBtn.addEventListener('click', addOntologyEntity);
    const deleteEntityBtn = root.querySelector('#delete-ontology-entity-btn');
    if (deleteEntityBtn) deleteEntityBtn.addEventListener('click', deleteSelectedOntologyEntity);
    const relationName = root.querySelector('#ontology-relation-name');
    if (relationName) relationName.addEventListener('input', (event) => { state.ontology.relationDraft = event.target.value; });
    const relationSource = root.querySelector('#ontology-relation-source');
    if (relationSource) relationSource.addEventListener('change', (event) => { state.ontology.relationSourceDraft = event.target.value; });
    const relationTarget = root.querySelector('#ontology-relation-target');
    if (relationTarget) relationTarget.addEventListener('change', (event) => { state.ontology.relationTargetDraft = event.target.value; });
    const addRelationBtn = root.querySelector('#add-ontology-relation-btn');
    if (addRelationBtn) addRelationBtn.addEventListener('click', addOntologyRelation);
    const deleteRelationBtn = root.querySelector('#delete-ontology-relation-btn');
    if (deleteRelationBtn) deleteRelationBtn.addEventListener('click', deleteActiveOntologyRelation);
    const extractBatchFiles = root.querySelector('#extract-batch-files');
    if (extractBatchFiles) extractBatchFiles.addEventListener('change', (event) => {
      const files = [...(event.target.files || [])].filter((file) => !String(file.name || '').startsWith('~$'));
      const primary = files[0] || null;
      clearImagePreview();
      state.sourceType = 'table';
      state.selectedFile = primary;
      state.selectedFileName = primary?.name || '';
      state.selectedFiles = files;
      state.extraTableFiles = files.slice(1);
      state.extraTableFileName = state.extraTableFiles.map((file) => file.name).join('、');
      state.parseConfig = null;
      state.extractionResult = null;
      state.kgBuildProgress = null;
      render();
    });
    const extractTriggerBatchBtn = root.querySelector('#extract-trigger-batch-btn');
    if (extractTriggerBatchBtn && extractBatchFiles) extractTriggerBatchBtn.addEventListener('click', () => extractBatchFiles.click());
    const extractDocumentFile = root.querySelector('#extract-document-file');
    if (extractDocumentFile) extractDocumentFile.addEventListener('change', (event) => {
      const file = [...(event.target.files || [])].find((item) => !String(item.name || '').startsWith('~$')) || null;
      clearImagePreview();
      state.sourceType = 'document';
      state.selectedFile = file;
      state.selectedFileName = file?.name || '';
      state.selectedFiles = file ? [file] : [];
      state.extraTableFiles = [];
      state.extraTableFileName = '';
      state.extraTableFile = null;
      state.parseConfig = null;
      state.extractionResult = null;
      state.kgBuildProgress = null;
      render();
    });
    const extractTriggerDocumentBtn = root.querySelector('#extract-trigger-document-btn');
    if (extractTriggerDocumentBtn && extractDocumentFile) extractTriggerDocumentBtn.addEventListener('click', () => extractDocumentFile.click());
    const extractImageFile = root.querySelector('#extract-image-file');
    if (extractImageFile) extractImageFile.addEventListener('change', (event) => {
      const file = [...(event.target.files || [])].find((item) => !String(item.name || '').startsWith('~$')) || null;
      setImagePreview(file);
      state.sourceType = 'image';
      state.selectedFile = file;
      state.selectedFileName = file?.name || '';
      state.selectedFiles = file ? [file] : [];
      state.extraTableFiles = [];
      state.extraTableFileName = '';
      state.extraTableFile = null;
      state.parseConfig = null;
      state.extractionResult = null;
      state.kgBuildProgress = null;
      render();
    });
    const extractTriggerImageBtn = root.querySelector('#extract-trigger-image-btn');
    if (extractTriggerImageBtn && extractImageFile) extractTriggerImageBtn.addEventListener('click', () => extractImageFile.click());
    const extractRunBtn = root.querySelector('#extract-run-btn');
    if (extractRunBtn) extractRunBtn.addEventListener('click', runExtraction);
    const extractResetBtn = root.querySelector('#extract-reset-btn');
    if (extractResetBtn) extractResetBtn.addEventListener('click', resetExtractWorkspace);
    const refreshKgVersionsBtn = root.querySelector('#refresh-kg-versions-btn');
    if (refreshKgVersionsBtn) refreshKgVersionsBtn.addEventListener('click', fetchKgVersions);
    const rollbackKgVersionBtn = root.querySelector('#rollback-kg-version-btn');
    if (rollbackKgVersionBtn) rollbackKgVersionBtn.addEventListener('click', rollbackKgVersion);
    root.querySelectorAll('[data-kg-rollback-version]').forEach((button) => button.addEventListener('click', rollbackKgVersion));
  };

  const bootstrap = async () => {
    let serverSchema = { entityTypes: [], relationTypes: [] };
    let localSchema = {};
    let localOntology = {};
    await fetchGraphs({ renderAfter: false });
    try { serverSchema = await requestGraphJson('/api/schema'); } catch {}
    try { localSchema = JSON.parse(localStorage.getItem(SCHEMA_STORAGE_KEY) || '{}'); } catch {}
    try { localOntology = JSON.parse(localStorage.getItem(ONTOLOGY_STORAGE_KEY) || '{}'); } catch {}
    state.schema = {
      entityTypes: unique([...(serverSchema.entityTypes || []), ...(localSchema.entityTypes || [])]),
      relationTypes: unique([...(serverSchema.relationTypes || []), ...(localSchema.relationTypes || [])]),
    };
    const hasTemplateLocal = localOntology.version === ONTOLOGY_TEMPLATE_VERSION
      && Array.isArray(localOntology.nodes)
      && localOntology.nodes.some((node) => node.id === 'component-main');
    const graph = hasTemplateLocal ? { nodes: localOntology.nodes, edges: localOntology.edges || [] } : buildOntology(state.schema);
    state.ontology.nodes = graph.nodes.map(normalizeOntologyNode);
    state.ontology.edges = sanitizeOntologyEdges(graph.edges);
    const shouldResetVersionHistory = localOntology.historySchemaVersion !== ONTOLOGY_HISTORY_SCHEMA_VERSION;
    state.ontology.history = shouldResetVersionHistory
      ? []
      : (Array.isArray(localOntology.history)
        ? localOntology.history.map((item) => ({ ...item, edges: sanitizeOntologyEdges(item.edges || []) }))
        : []);
    state.ontology.currentVersionId = shouldResetVersionHistory ? '' : (localOntology.currentVersionId || '');
    state.ontology.pendingChanges = false;
    state.ontology.selectedNodeId = state.ontology.nodes[0]?.id || null;
    state.ontology.relationFilter = 'all';
    updateOntologyLayout();
    persistSchema();
    if (!state.ontology.history.length) {
      initializeOntologyHistory();
    } else {
      persistOntology();
    }
    render();
    if (state.currentPage === 'versions' && !state.versioning?.loaded) {
      fetchKgVersions();
    }
  };

  bootstrap().catch((error) => {
    root.innerHTML = `<div style="padding:32px;font-family:Segoe UI, sans-serif;">${T.initFailed}${escapeHtml(error.message || '')}</div>`;
  });
}
