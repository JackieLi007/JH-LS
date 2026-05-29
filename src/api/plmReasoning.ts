export type ApiEnvelope<T> = {
  success: boolean
  code: number
  message: string
  result: T
  token: string | null
  notifyIcon: string | null
}

export type PlmFaultMode = {
  id: string
  containerPath: string | null
  createBy: string | null
  createFullName: string | null
  createName: string | null
  createOrgId: string | null
  createTime: string | null
  createDeptId: string | null
  deleteFlag: string | null
  updateBy: string | null
  updateName: string | null
  updateFullName: string | null
  updateTime: string | null
  updateOrgId: string | null
  updateDeptId: string | null
  partOid: string | null
  productName: string | null
  productCode: string | null
  function: string | null
  faultMode: string | null
  faultReason: string | null
  countermeasures: string | null
  taskPhase: string | null
  singlePoint: 'A' | 'B' | string | null
  severityCategory: string | null
  occurrenceRating: string | null
  projectId: string | null
}

export type FmeaInferenceResult = Pick<
  PlmFaultMode,
  | 'id'
  | 'productName'
  | 'function'
  | 'faultMode'
  | 'faultReason'
  | 'countermeasures'
  | 'taskPhase'
  | 'singlePoint'
  | 'severityCategory'
  | 'occurrenceRating'
>

export type FtaGateType = 'And' | 'Or' | string

export type FtaInferenceNode = {
  Rect: Record<string, unknown>
  Results: Record<string, unknown>
  children: FtaInferenceNode[] | null
  count: number | string | null
  faultMode: string | null
  fmeaId: string | null
  fmeaParentId: string | null
  id: string
  lamda: number | string | null
  name: string
  parentId: string | number
  rmaSTSLibraryVos: unknown[] | null
  selected: boolean | string
  type: FtaGateType
}

type RequestOptions = {
  method?: 'GET' | 'POST'
  params?: Record<string, string | number | boolean | null | undefined>
  body?: unknown
  signal?: AbortSignal
}

export function getFmeaCurrentFaultModes(options?: RequestOptions) {
  return requestApi<PlmFaultMode[]>('/api/fmea/current-fault-modes', options)
}

export function getFmeaInferenceResults(options?: RequestOptions) {
  return requestApi<FmeaInferenceResult[]>('/api/fmea/inference-results', { ...options, method: 'GET' })
}

export function getFtaCurrentFaultModes(options?: RequestOptions) {
  return requestApi<PlmFaultMode[]>('/api/fta/current-fault-modes', options)
}

export function getFtaInferenceResults(options?: RequestOptions) {
  return requestApi<FtaInferenceNode[]>('/api/fta/inference-results', { ...options, method: 'GET' })
}

async function requestApi<T>(path: string, options: RequestOptions = {}): Promise<ApiEnvelope<T>> {
  const method = options.method ?? (options.body === undefined ? 'GET' : 'POST')
  const response = await fetch(buildUrl(path, options.params), {
    method,
    headers: method === 'POST' ? { 'Content-Type': 'application/json' } : undefined,
    body: method === 'POST' ? JSON.stringify(options.body ?? {}) : undefined,
    signal: options.signal,
  })
  const data = await response.json() as ApiEnvelope<T>

  if (!response.ok || !data.success) {
    throw new Error(data.message || `Request failed: ${response.status}`)
  }

  return data
}

function buildUrl(path: string, params?: RequestOptions['params']) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== null && value !== undefined) search.set(key, String(value))
  }

  const queryString = search.toString()
  return queryString ? `${path}?${queryString}` : path
}
