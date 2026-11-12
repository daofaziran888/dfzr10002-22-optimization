/**
 * 有效筛选条：在图表配置、数据看板、导出任务页面统一展示筛选器当前有效值。
 * 切换或清空后这里立即反映新值；来源变更导致默认值失效时展示醒目提示。
 */
import { useState } from 'react'

import { useFilterState, type FilterState } from '@/state/FilterContext'

interface EffectiveFilterBarProps {
  /** 只展示指定编号的筛选器；不传则展示全部 */
  codes?: string[]
}

function FilterCard({ item }: { item: FilterState }) {
  const { selectValue, resetValue } = useFilterState()
  const [busy, setBusy] = useState(false)

  async function handleChange(value: string) {
    setBusy(true)
    await selectValue(item.id, value)
    setBusy(false)
  }

  async function handleReset() {
    setBusy(true)
    await resetValue(item.id)
    setBusy(false)
  }

  return (
    <article className={`filter-card ${item.notice ? 'filter-card-warning' : ''}`}>
      <header className="filter-card-head">
        <span className="filter-card-code">{item.筛选器编号}</span>
        <span className="filter-card-dim">{item.联动维度}（{item.关联字段}）</span>
      </header>
      <div className="filter-card-value">
        <strong title="当前有效值：用户选择优先，清空后回落到系统默认值">
          {item.当前有效值 ?? '（待选择）'}
        </strong>
        {item.用户已自定义 && <span className="tag tag-user">用户选择</span>}
        {!item.用户已自定义 && <span className="tag tag-default">系统默认</span>}
      </div>
      <select
        aria-label={`${item.筛选器编号}选择有效值`}
        value={item.当前有效值 ?? ''}
        disabled={busy}
        onChange={(event) => void handleChange(event.target.value)}
      >
        {item.当前有效值 === null && <option value="">请选择当前有效值</option>}
        {item.可选值.map((option) => (
          <option key={option} value={option}>{option}</option>
        ))}
      </select>
      <div className="filter-card-meta">
        <span>来源：{item.可选值来源}</span>
        <button className="link" type="button" disabled={busy || !item.用户已自定义} onClick={() => void handleReset()}>
          清空回默认值
        </button>
      </div>
      {item.notice && <p className="warning-text">{item.notice}</p>}
    </article>
  )
}

export default function EffectiveFilterBar({ codes }: EffectiveFilterBarProps) {
  const { filters, globalNotice, loading } = useFilterState()
  const visible = codes ? filters.filter((item) => codes.includes(item.筛选器编号)) : filters

  if (loading) return <p className="page-desc">正在读取全局筛选器当前有效值…</p>

  return (
    <section className="effective-filter" data-testid="effective-filter-bar">
      <div className="effective-filter-head">
        <h3>全局筛选器 · 当前有效值</h3>
        <span className="page-desc">图表配置、数据看板与导出任务共用同一份筛选状态</span>
      </div>
      {globalNotice && <div className="notice-banner">⚠️ {globalNotice}</div>}
      <div className="filter-card-row">
        {visible.map((item) => <FilterCard key={item.id} item={item} />)}
      </div>
    </section>
  )
}
