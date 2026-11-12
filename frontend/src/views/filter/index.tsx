import { useCallback, useEffect, useMemo, useState } from 'react'

import { request } from '@/api/client'
import EffectiveFilterBar from '@/components/EffectiveFilterBar'
import { useFilterState, type FilterState } from '@/state/FilterContext'

const ENDPOINT = '/api/filter'
const SEARCH_FIELDS = [
  { value: '', label: '全部入口' },
  { value: '筛选器编号', label: '按筛选器编号' },
  { value: '关联字段', label: '按关联字段' },
  { value: '联动维度', label: '按联动维度' },
]

type ConfigRow = Record<string, string | number | null> & { id: number }

export default function FilterView() {
  const { filters, errorMessage, selectValue, resetValue, changeSource, saveDefault } = useFilterState()
  const [keyword, setKeyword] = useState('')
  const [searchField, setSearchField] = useState('')
  const [configRows, setConfigRows] = useState<ConfigRow[]>([])
  const [total, setTotal] = useState(0)
  const [listError, setListError] = useState('')
  const [feedback, setFeedback] = useState('')
  const [editingId, setEditingId] = useState<number | null>(null)
  const [defaultDraft, setDefaultDraft] = useState('')
  const [sourceDraft, setSourceDraft] = useState('')
  const [optionsDraft, setOptionsDraft] = useState('')

  const loadConfigList = useCallback(async () => {
    const params = new URLSearchParams()
    if (keyword.trim()) params.set('keyword', keyword.trim())
    if (searchField) params.set('field', searchField)
    try {
      const response = await request(`${ENDPOINT}?${params.toString()}`)
      if (!response.ok) throw new Error('筛选器配置列表读取失败')
      const payload = await response.json()
      setConfigRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
      setListError('')
    } catch (error) {
      setListError(error instanceof Error ? error.message : '筛选器配置列表读取失败')
    }
  }, [keyword, searchField])

  useEffect(() => {
    void loadConfigList()
  }, [loadConfigList])

  // 前端本地兜底检索：编号（支持省略补零）、关联字段、联动维度命中同一条
  const runtimeRows = useMemo(() => {
    const key = keyword.trim().toLowerCase()
    if (!key) return filters
    const normalize = (code: string) => {
      const match = code.match(/^([A-Za-z]+)-0*(\d+)$/)
      return match ? `${match[1].toLowerCase()}-${Number(match[2])}` : code.toLowerCase()
    }
    return filters.filter((item) => {
      const matched =
        normalize(item.筛选器编号) === normalize(keyword.trim()) ||
        item.筛选器编号.toLowerCase().includes(key) ||
        item.关联字段.toLowerCase().includes(key) ||
        item.联动维度.toLowerCase().includes(key) ||
        item.筛选器名称.toLowerCase().includes(key)
      if (!searchField) return matched
      if (searchField === '筛选器编号') return normalize(item.筛选器编号) === normalize(keyword.trim()) || item.筛选器编号.toLowerCase().includes(key)
      return String(item[searchField as keyof FilterState] ?? '').toLowerCase().includes(key)
    })
  }, [filters, keyword, searchField])

  async function handleSelect(item: FilterState, value: string) {
    setFeedback('')
    const result = await selectValue(item.id, value)
    if (result?.ok) setFeedback(result.message)
    else if (result) setFeedback(result.message)
  }

  async function handleReset(item: FilterState) {
    setFeedback('')
    await resetValue(item.id)
    setFeedback(`已清空「${item.筛选器编号}」的临时选择，回到系统默认值`)
  }

  function openEditor(item: FilterState) {
    setEditingId(item.id)
    setDefaultDraft(item.系统默认值 ?? '')
    setSourceDraft(item.可选值来源)
    setOptionsDraft(item.可选值.join('、'))
    setFeedback('')
  }

  async function handleSaveDefault(item: FilterState) {
    setFeedback('')
    const result = await saveDefault(item.id, { 系统默认值: defaultDraft || null })
    if (!result) return
    if (result.ok) {
      setFeedback(`「${item.筛选器编号}」默认值已保存：${result.entry?.当前有效值 ?? '（空）'}`)
      setEditingId(null)
    } else {
      const failed = result.entry?.规则校验?.filter((check) => check.passed !== 'true') ?? []
      setFeedback(`${result.message}；依据：${failed.map((check) => check.basis).join(' / ')}`)
    }
  }

  async function handleChangeSource(item: FilterState) {
    setFeedback('')
    const options = optionsDraft.split(/[、,\s]+/).map((text) => text.trim()).filter(Boolean)
    const result = await changeSource(item.id, sourceDraft.trim(), options)
    if (!result) return
    setFeedback(result.message)
    if (result.ok) setEditingId(null)
  }

  return (
    <section className="page" data-module="filter">
      <header className="page-head">
        <div>
          <h2>全局筛选器管理</h2>
          <p className="page-desc">
            按筛选器编号、关联字段或联动维度都能定位到同一筛选器；切换、清空与来源变更后，
            图表配置、数据看板、导出任务始终读取当前有效值。
          </p>
        </div>
        <div className="page-actions">
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出全局筛选器清单
          </button>
        </div>
      </header>

      <EffectiveFilterBar />

      <form
        className="filter-bar"
        onSubmit={(event) => {
          event.preventDefault()
          void loadConfigList()
        }}
      >
        <label className="filter-item">
          <span>检索入口</span>
          <select value={searchField} onChange={(event) => setSearchField(event.target.value)}>
            {SEARCH_FIELDS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
        <label className="filter-item filter-item-grow">
          <span>关键字（如 FILT-002 / region / 地区，可定位同一条筛选器）</span>
          <input
            value={keyword}
            placeholder="输入筛选器编号、关联字段或联动维度"
            onChange={(event) => setKeyword(event.target.value)}
          />
        </label>
        <button className="btn" type="submit">查询</button>
        <button
          className="btn ghost"
          type="button"
          onClick={() => {
            setKeyword('')
            setSearchField('')
          }}
        >
          重置条件
        </button>
      </form>

      {feedback && <div className="notice-banner" role="status">{feedback}</div>}
      {(errorMessage || listError) && <div className="error-text">{errorMessage || listError}</div>}

      <h3 className="section-title">运行态：当前有效值与选择/清空</h3>
      <table className="data-table">
        <thead>
          <tr>
            <th>筛选器编号</th>
            <th>关联字段</th>
            <th>联动维度</th>
            <th>可选值来源</th>
            <th>系统默认值</th>
            <th>当前有效值</th>
            <th>值来源</th>
            <th>选择有效值</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {runtimeRows.map((item) => (
            <tr key={item.id} className={item.notice ? 'row-warning' : ''}>
              <td>{item.筛选器编号}</td>
              <td>{item.关联字段}</td>
              <td>{item.联动维度}</td>
              <td>{item.可选值来源}</td>
              <td>{item.系统默认值 ?? '（已失效）'}</td>
              <td>
                <strong>{item.当前有效值 ?? '（待选择）'}</strong>
                {item.notice && <p className="warning-text">{item.notice}</p>}
              </td>
              <td>
                {item.用户已自定义
                  ? <span className="tag tag-user">用户选择优先</span>
                  : <span className="tag tag-default">系统默认</span>}
              </td>
              <td>
                <select
                  aria-label={`${item.筛选器编号}有效值`}
                  value={item.当前有效值 ?? ''}
                  onChange={(event) => void handleSelect(item, event.target.value)}
                >
                  {item.当前有效值 === null && <option value="">请选择</option>}
                  {item.可选值.map((option) => (
                    <option key={option} value={option}>{option}</option>
                  ))}
                </select>
              </td>
              <td className="row-actions">
                <button className="link" type="button" disabled={!item.用户已自定义} onClick={() => void handleReset(item)}>
                  清空回默认
                </button>
                <button className="link" type="button" onClick={() => openEditor(item)}>
                  配置默认值
                </button>
              </td>
            </tr>
          ))}
          {runtimeRows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={9}>没有匹配的筛选器，换个编号、关联字段或联动维度试试</td>
            </tr>
          )}
        </tbody>
      </table>

      {editingId !== null && (() => {
        const item = filters.find((entry) => entry.id === editingId)
        if (!item) return null
        return (
          <section className="editor-panel" aria-label="默认值配置">
            <h3>配置「{item.筛选器编号}」默认值规则</h3>
            <div className="editor-grid">
              <label className="filter-item">
                <span>默认值（必须在可选值范围内）</span>
                <input value={defaultDraft} onChange={(event) => setDefaultDraft(event.target.value)} />
              </label>
              <label className="filter-item">
                <span>可选值来源</span>
                <input value={sourceDraft} onChange={(event) => setSourceDraft(event.target.value)} />
              </label>
              <label className="filter-item filter-item-grow">
                <span>可选值清单（顿号或逗号分隔）</span>
                <input value={optionsDraft} onChange={(event) => setOptionsDraft(event.target.value)} />
              </label>
            </div>
            <div className="editor-actions">
              <button className="btn primary" type="button" onClick={() => void handleSaveDefault(item)}>保存默认值</button>
              <button className="btn" type="button" onClick={() => void handleChangeSource(item)}>切换来源</button>
              <button className="btn ghost" type="button" onClick={() => setEditingId(null)}>取消</button>
            </div>
            <ul className="rule-list">
              {item.规则校验.map((check) => (
                <li key={check.rule} className={check.passed === 'true' ? 'rule-pass' : 'rule-fail'}>
                  <strong>{check.passed === 'true' ? '✓' : '✕'} {check.rule}</strong>
                  <span>{check.basis}</span>
                </li>
              ))}
            </ul>
          </section>
        )
      })()}

      <h3 className="section-title">筛选器配置清单（共 {total} 条）</h3>
      <table className="data-table">
        <thead>
          <tr>
            <th>筛选器编号</th>
            <th>筛选器名称</th>
            <th>关联字段</th>
            <th>筛选类型</th>
            <th>默认值</th>
            <th>可选值来源</th>
            <th>联动维度</th>
            <th>是否启用</th>
          </tr>
        </thead>
        <tbody>
          {configRows.map((row) => (
            <tr key={row.id}>
              <td>{row.筛选器编号}</td>
              <td>{row.筛选器名称}</td>
              <td>{row.关联字段}</td>
              <td>{row.筛选类型}</td>
              <td>{row.默认值}</td>
              <td>{row.可选值来源}</td>
              <td>{row.联动维度}</td>
              <td>{row.是否启用}</td>
            </tr>
          ))}
          {configRows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={8}>暂无匹配的筛选器配置</td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  )
}
