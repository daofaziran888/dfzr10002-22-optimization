/**
 * 全局筛选器共享状态：图表配置、数据看板、导出任务都读取这一份当前有效值。
 *
 * 竞态保护：每次选择都携带后端返回的 version 作为基准版本，并在本地维护
 * 单调递增的请求序号。连续切换两次时，先发的旧响应即使晚到，也会因为
 * 序号过期而被丢弃，只有最后一次选择能更新界面 —— 旧响应不能覆盖新选择。
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'

import { request } from '@/api/client'

export interface RuleCheck {
  rule: string
  passed: 'true' | 'false'
  basis: string
}

export interface FilterState {
  id: number
  筛选器编号: string
  筛选器名称: string
  关联字段: string
  筛选类型: string
  联动维度: string
  是否启用: string
  可选值来源: string
  可选值: string[]
  系统默认值: string | null
  用户选择: string | null
  用户已自定义: boolean
  当前有效值: string | null
  version: number
  notice: string | null
  规则校验: RuleCheck[]
}

interface Snapshot {
  items: FilterState[]
  version: number
  notice: string | null
}

interface ActionResponse {
  ok: boolean
  message: string
  entry: FilterState
}

interface FilterContextValue {
  filters: FilterState[]
  loading: boolean
  errorMessage: string
  globalNotice: string | null
  refresh: () => Promise<void>
  selectValue: (id: number, value: string | null) => Promise<ActionResponse | null>
  resetValue: (id: number) => Promise<void>
  changeSource: (id: number, source: string, options: string[]) => Promise<ActionResponse | null>
  saveDefault: (id: number, values: Record<string, unknown>) => Promise<ActionResponse | null>
  /** 按编号/关联字段/联动维度定位同一条筛选器，供下游页面快速取用 */
  locate: (keyword: string) => FilterState | undefined
}

const FilterContext = createContext<FilterContextValue | null>(null)

export function FilterProvider({ children }: { children: React.ReactNode }) {
  const [filters, setFilters] = useState<FilterState[]>([])
  const [loading, setLoading] = useState(true)
  const [errorMessage, setErrorMessage] = useState('')
  const [globalNotice, setGlobalNotice] = useState<string | null>(null)
  // 本地请求序号：只允许最后一次选择的响应落库
  const requestSeq = useRef(0)
  // 记录每个筛选器最新一次成功写入的版本，防止过期响应回退版本号
  const latestVersion = useRef<Record<number, number>>({})

  const refresh = useCallback(async () => {
    const seq = ++requestSeq.current
    try {
      const response = await request('/api/filter/state')
      if (!response.ok) throw new Error('全局筛选状态读取失败')
      const snapshot = (await response.json()) as Snapshot
      if (seq !== requestSeq.current) return // 已有更新的请求，丢弃旧快照
      setFilters(snapshot.items)
      setGlobalNotice(snapshot.notice)
      snapshot.items.forEach((item) => {
        latestVersion.current[item.id] = Math.max(latestVersion.current[item.id] ?? 0, item.version)
      })
      setErrorMessage('')
    } catch (error) {
      if (seq !== requestSeq.current) return
      setErrorMessage(error instanceof Error ? error.message : '全局筛选状态读取失败')
    } finally {
      if (seq === requestSeq.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const mergeEntry = useCallback((entry: FilterState) => {
    // 版本号回退保护：旧响应携带的版本落后于本地已知版本时，拒绝合并
    const known = latestVersion.current[entry.id] ?? 0
    if (entry.version < known) return false
    latestVersion.current[entry.id] = entry.version
    setFilters((prev) => prev.map((item) => (item.id === entry.id ? entry : item)))
    return true
  }, [])

  const selectValue = useCallback(async (id: number, value: string | null) => {
    const seq = ++requestSeq.current
    const base = latestVersion.current[id] ?? 0
    try {
      const response = await request(`/api/filter/state/${id}/select`, {
        method: 'POST',
        body: JSON.stringify({ values: { value, version: base } }),
      })
      const payload = (await response.json()) as ActionResponse
      if (seq !== requestSeq.current) return null // 连续切换时丢弃非最后一次响应
      mergeEntry(payload.entry)
      if (payload.entry.notice) setGlobalNotice(payload.entry.notice)
      else setGlobalNotice(null)
      return payload
    } catch (error) {
      if (seq === requestSeq.current) {
        setErrorMessage(error instanceof Error ? error.message : '筛选值提交失败')
      }
      return null
    }
  }, [mergeEntry])

  const resetValue = useCallback(async (id: number) => {
    const seq = ++requestSeq.current
    try {
      const response = await request(`/api/filter/state/${id}/reset`, { method: 'POST' })
      const payload = (await response.json()) as ActionResponse
      if (seq !== requestSeq.current) return
      mergeEntry(payload.entry)
      if (payload.entry.notice) setGlobalNotice(payload.entry.notice)
    } catch (error) {
      if (seq === requestSeq.current) {
        setErrorMessage(error instanceof Error ? error.message : '清空筛选失败')
      }
    }
  }, [mergeEntry])

  const changeSource = useCallback(async (id: number, source: string, options: string[]) => {
    const seq = ++requestSeq.current
    try {
      const response = await request(`/api/filter/state/${id}/source`, {
        method: 'POST',
        body: JSON.stringify({ values: { source, options } }),
      })
      const payload = (await response.json()) as ActionResponse
      if (seq !== requestSeq.current) return null
      mergeEntry(payload.entry)
      if (payload.entry.notice) setGlobalNotice(payload.entry.notice)
      return payload
    } catch (error) {
      if (seq === requestSeq.current) {
        setErrorMessage(error instanceof Error ? error.message : '来源切换失败')
      }
      return null
    }
  }, [mergeEntry])

  const saveDefault = useCallback(async (id: number, values: Record<string, unknown>) => {
    const seq = ++requestSeq.current
    try {
      const response = await request(`/api/filter/${id}/default`, {
        method: 'POST',
        body: JSON.stringify({ values }),
      })
      const payload = (await response.json()) as ActionResponse
      if (seq !== requestSeq.current) return null
      if (payload.ok && payload.entry?.id) mergeEntry(payload.entry)
      return payload
    } catch (error) {
      if (seq === requestSeq.current) {
        setErrorMessage(error instanceof Error ? error.message : '默认值保存失败')
      }
      return null
    }
  }, [mergeEntry])

  const locate = useCallback((keyword: string) => {
    const key = keyword.trim().toLowerCase()
    const normalize = (code: string) => {
      const match = code.match(/^([A-Za-z]+)-0*(\d+)$/)
      return match ? `${match[1].toLowerCase()}-${Number(match[2])}` : code.toLowerCase()
    }
    return filters.find((item) => {
      return (
        normalize(item.筛选器编号) === normalize(keyword) ||
        item.筛选器编号.toLowerCase().includes(key) ||
        item.关联字段.toLowerCase().includes(key) ||
        item.联动维度.toLowerCase().includes(key) ||
        item.筛选器名称.toLowerCase().includes(key)
      )
    })
  }, [filters])

  const value = useMemo<FilterContextValue>(() => ({
    filters,
    loading,
    errorMessage,
    globalNotice,
    refresh,
    selectValue,
    resetValue,
    changeSource,
    saveDefault,
    locate,
  }), [filters, loading, errorMessage, globalNotice, refresh, selectValue, resetValue, changeSource, saveDefault, locate])

  return <FilterContext.Provider value={value}>{children}</FilterContext.Provider>
}

export function useFilterState(): FilterContextValue {
  const context = useContext(FilterContext)
  if (!context) throw new Error('useFilterState 必须在 FilterProvider 内使用')
  return context
}
