import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, asList, dryRun, postJson, putJson, uploadFiles } from './client'
import type { AddModelPayload, Cell, DiscoverVertexResponse, DocumentItem, DryRun, FieldRow, LeaderboardRow, ModelItem, PackMeta, Prompt, RunDetail, RunItem, RunSpec, SideBySide } from '../types'

export const useDocuments = () => useQuery({ queryKey: ['documents'], queryFn: async () => asList<DocumentItem>(await api('/documents'), 'documents') })
export const usePacks = () => useQuery({ queryKey: ['packs'], queryFn: async () => asList<PackMeta>(await api('/packs'), 'packs') })
export const useCatalog = () => useQuery({ queryKey: ['catalog'], queryFn: async () => {
  const data = await api<ModelItem[] | {models?: ModelItem[]; providers?: Record<string, ModelItem[]>}>('/catalog')
  if (Array.isArray(data)) return data
  return data.models ?? Object.values(data.providers ?? {}).flat()
} })
export const useDiscoverVertexModels = () => useQuery({
  queryKey: ['discover-vertex'],
  queryFn: () => postJson<DiscoverVertexResponse>('/catalog/discover/vertex', {}),
  staleTime: 60 * 1000,
})
export const useOpenRouterSearch = (query: string) => useQuery({
  queryKey: ['openrouter-search', query],
  queryFn: () => api<{ total: number; models: ModelItem[] }>(`/catalog/openrouter/search?q=${encodeURIComponent(query)}&limit=60`),
  enabled: query.trim().length >= 2,
  staleTime: 5 * 60 * 1000,
})
export const usePrompts = (pack: string) => useQuery({ queryKey: ['prompts', pack], queryFn: async () => asList<Prompt>(await api(`/prompts?pack=${pack}`), 'prompts') })
export const useRuns = () => useQuery({ queryKey: ['runs'], queryFn: async () => asList<RunItem>(await api('/runs'), 'runs'), refetchInterval: query => query.state.data?.some(run => run.status === 'running') ? 5000 : false })
export const useRun = (id?: string, polling = false) => useQuery({ queryKey: ['run', id], queryFn: () => api<RunDetail>(`/runs/${id}`), enabled: Boolean(id), refetchInterval: polling ? 3000 : false })
export const useResults = (id?: string) => useQuery({ queryKey: ['results', id], queryFn: () => api<{results: Cell[]}>(`/runs/${id}/results?include_raw=true`), enabled: Boolean(id) })
export const useLeaderboard = (id?: string) => useQuery({ queryKey: ['leaderboard', id], queryFn: async () => asList<LeaderboardRow>(await api(`/runs/${id}/leaderboard`), 'rows'), enabled: Boolean(id) })
export const useFields = (id?: string, task?: string) => useQuery({ queryKey: ['fields', id, task], queryFn: async () => asList<FieldRow>(await api(`/runs/${id}/field-breakdown?task=${encodeURIComponent(task ?? '')}`), 'fields'), enabled: Boolean(id && task) })
export const useSideBySide = (id?: string, documentId?: number, task?: string, polling = false) => useQuery({ queryKey: ['side', id, documentId, task], queryFn: () => api<SideBySide>(`/runs/${id}/side-by-side?document_id=${documentId}&task=${encodeURIComponent(task ?? '')}`), enabled: Boolean(id && documentId && task), refetchInterval: polling ? 3000 : false })
export const useGold = (documentId?: number) => useQuery({ queryKey: ['gold', documentId], queryFn: () => api<{document_id: number; tasks: Record<string, unknown>}>(`/gold/${documentId}`), enabled: Boolean(documentId), retry: false })
export const usePromptVersions = (pack: string, task?: string) => useQuery({ queryKey: ['promptVersions', pack, task], queryFn: async () => asList<Prompt>(await api(`/prompts/${pack}/${task}/versions`), 'versions'), enabled: Boolean(task) })

export function useActions() {
  const client = useQueryClient()
  return {
    dryRun: useMutation<DryRun, Error, RunSpec>({ mutationFn: dryRun }),
    launch: useMutation<{run_id: number; status: string}, Error, RunSpec>({ mutationFn: spec => postJson('/runs', spec) }),
    cancel: useMutation({ mutationFn: (id: number) => postJson(`/runs/${id}/cancel`), onSuccess: (_, id) => { client.invalidateQueries({queryKey: ['runs']}); client.invalidateQueries({queryKey: ['run', String(id)]}); client.invalidateQueries({queryKey: ['results', String(id)]}) } }),
    renameRun: useMutation({ mutationFn: ({id, name}: {id: number; name: string}) => api(`/runs/${id}`, {method: 'PATCH', body: JSON.stringify({name})}), onSuccess: (_, vars) => { client.invalidateQueries({queryKey: ['runs']}); client.invalidateQueries({queryKey: ['run', String(vars.id)]}) } }),
    deleteRun: useMutation({ mutationFn: (id: number) => api(`/runs/${id}`, {method: 'DELETE'}), onSuccess: () => client.invalidateQueries({queryKey: ['runs']}) }),
    upload: useMutation({ mutationFn: (files: File[]) => uploadFiles('/documents', files), onSuccess: () => client.invalidateQueries({queryKey: ['documents']}) }),
    deleteDocument: useMutation({ mutationFn: (id: number) => api(`/documents/${id}`, {method: 'DELETE'}), onSuccess: () => client.invalidateQueries({queryKey: ['documents']}) }),
    saveGold: useMutation({ mutationFn: ({id, tasks}: {id: number; tasks: Record<string, unknown>}) => putJson(`/gold/${id}`, {tasks}), onSuccess: (_, vars) => { client.invalidateQueries({queryKey: ['gold', vars.id]}); client.invalidateQueries({queryKey: ['documents']}) } }),
    importGold: useMutation({ mutationFn: (files: File[]) => uploadFiles('/gold/import', files, 'file'), onSuccess: () => client.invalidateQueries({queryKey: ['documents']}) }),
    verify: useMutation({ mutationFn: (id: string) => postJson<{ok: boolean; error?: string; latency_ms?: number}>(`/catalog/${encodeURIComponent(id)}/verify`), onSuccess: () => client.invalidateQueries({queryKey: ['catalog']}) }),
    discoverVertex: useMutation({ mutationFn: () => postJson<DiscoverVertexResponse>('/catalog/discover/vertex', {}), onSuccess: () => { client.invalidateQueries({queryKey: ['discover-vertex']}); client.invalidateQueries({queryKey: ['catalog']}) } }),
    addModel: useMutation({
      mutationFn: (payload: AddModelPayload) => postJson<ModelItem>('/catalog/models', payload),
      onSuccess: () => {
        client.invalidateQueries({queryKey: ['catalog']})
        client.invalidateQueries({queryKey: ['discover-vertex']})
      },
    }),
    deleteModel: useMutation({
      mutationFn: (id: string) => api(`/catalog/models/${encodeURIComponent(id)}`, {method: 'DELETE'}),
      onSuccess: () => {
        client.invalidateQueries({queryKey: ['catalog']})
        client.invalidateQueries({queryKey: ['discover-vertex']})
      },
    }),
    judge: useMutation({ mutationFn: ({id, body}: {id: string; body: unknown}) => postJson(`/runs/${id}/judge`, body), onSuccess: (_, vars) => {
      client.invalidateQueries({queryKey: ['run', vars.id]})
      client.invalidateQueries({queryKey: ['side', vars.id]})
      client.invalidateQueries({queryKey: ['leaderboard', vars.id]})
    } }),
    createPrompt: useMutation({
      mutationFn: ({pack, task, body}: {pack: string; task: string; body: unknown}) => postJson(`/prompts/${pack}/${task}/versions`, body),
      onSuccess: () => {
        client.invalidateQueries({queryKey: ['prompts']})
        client.invalidateQueries({queryKey: ['promptVersions']})
      },
    }),
    activatePrompt: useMutation({
      mutationFn: ({pack, task, version}: {pack: string; task: string; version: number}) => postJson(`/prompts/${pack}/${task}/versions/${version}/activate`),
      onSuccess: () => {
        client.invalidateQueries({queryKey: ['prompts']})
        client.invalidateQueries({queryKey: ['promptVersions']})
      },
    }),
  }
}
