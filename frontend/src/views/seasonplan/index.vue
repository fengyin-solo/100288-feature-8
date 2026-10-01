<template>
  <section class="page" data-module="seasonplan">
    <header class="page-head">
      <div>
        <h2>季度养护方案管理</h2>
        <p class="page-desc">
          同一季度勾选多片绿地一次性送审，养护内容逐条填、方案季度统一带出；
          审批只审已编完的条，退回条留在原批件等重提，预算汇总与方案台账逐项对账。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="exportRows">导出方案台账</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <!-- 第一步：按季度勾选绿地，一次送审 -->
    <section class="panel">
      <div class="panel-head">
        <h3>① 整季选绿地 · 一次性送审</h3>
        <div class="panel-tools">
          <label class="inline">
            方案季度
            <select v-model="submitQuarter" @change="loadPlots">
              <option v-for="q in quarters" :key="q" :value="q">{{ q }}</option>
            </select>
          </label>
          <button class="btn primary" type="button" :disabled="!selectedPlotIds.size" @click="submitPlots">
            一次性送审 {{ selectedPlotIds.size || '' }} 片绿地
          </button>
        </div>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th class="check-col">选择</th>
            <th>绿地编号</th>
            <th>绿地名称</th>
            <th>所属区域</th>
            <th>本季方案</th>
            <th>编制状态</th>
            <th>所在批件</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="plot in plots" :key="String(plot.id)">
            <td>
              <input v-model="plotSelection" type="checkbox" :value="plot.id" />
            </td>
            <td>{{ plot['绿地编号'] }}</td>
            <td>{{ plot['绿地名称'] }}</td>
            <td>{{ plot['所属区域'] }}</td>
            <td>{{ plot['方案编号'] || '尚未编制' }}</td>
            <td>
              <span class="tag" :class="statusClass(plot['编制状态'])">{{ plot['编制状态'] }}</span>
              <em v-if="plot['编制状态'] === '待编制'" class="hint">（未编完）</em>
            </td>
            <td>{{ plot['批次编号'] || '—' }}</td>
          </tr>
          <tr v-if="!plots.length">
            <td colspan="7" class="empty-state">该季度暂无可选绿地</td>
          </tr>
        </tbody>
      </table>
      <p class="tip">同一批方案重复提交只认第一次：季度相同、绿地集合相同会沿用首张批件，不覆盖已填内容。</p>
    </section>

    <!-- 第二步：批件内逐条编制 + 审批/退回 -->
    <section class="panel">
      <div class="panel-head">
        <h3>② 批件流转 · 逐条编制、批量审批</h3>
        <button class="btn ghost" type="button" @click="loadBatches">刷新批件</button>
      </div>

      <article v-for="batch in batches" :key="batch.id" class="batch-card">
        <header class="batch-head">
          <div>
            <strong>{{ batch['批次编号'] }}</strong>
            <span class="tag" :class="batchClass(batch.status)">{{ batch.status }}</span>
            <span class="muted">季度 {{ batch['方案季度'] }} · 送审人 {{ batch['送审人'] || '—' }}</span>
          </div>
          <div class="batch-actions">
            <button class="btn primary" type="button" @click="approveBatch(batch)">
              审批（只审已编完）
            </button>
            <button class="btn danger" type="button" @click="openReturn(batch)">退回勾选项</button>
          </div>
        </header>
        <p v-if="batch['退回说明']" class="return-note">退回说明：{{ batch['退回说明'] }}</p>
        <table class="data-table inner">
          <thead>
            <tr>
              <th class="check-col">退回选择</th>
              <th>方案编号</th>
              <th>覆盖绿地</th>
              <th>养护内容（逐条填，一行一条）</th>
              <th class="num-col">预算金额</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="line in batch.items" :key="String(line.id)">
              <td>
                <input
                  :checked="returnSelection[batch.id]?.includes(line.id)"
                  :disabled="line.status !== '已编制'"
                  type="checkbox"
                  @change="toggleReturn(batch.id, line.id)"
                />
              </td>
              <td>{{ line['方案编号'] }}</td>
              <td>{{ line['覆盖绿地'] }}</td>
              <td>
                <textarea
                  :value="line['方案内容']"
                  :disabled="isLocked(line.status)"
                  rows="2"
                  @change="onEditLine(line, '方案内容', ($event.target as HTMLTextAreaElement).value)"
                ></textarea>
              </td>
              <td>
                <input
                  :value="line['预算金额'] ?? ''"
                  :disabled="isLocked(line.status)"
                  class="budget-input"
                  type="number"
                  @change="onEditLine(line, '预算金额', ($event.target as HTMLInputElement).value)"
                />
              </td>
              <td><span class="tag" :class="statusClass(line.status)">{{ line.status }}</span></td>
              <td>
                <button
                  class="link"
                  type="button"
                  :disabled="isLocked(line.status)"
                  @click="fillEntry(line)"
                >
                  保存并校验
                </button>
              </td>
            </tr>
          </tbody>
        </table>
        <footer class="batch-foot">
          <span>本批已审批预算合计（按整体结果落）：<strong>¥{{ batch['预算合计'] ?? 0 }}</strong></span>
          <span v-if="batch.status === '部分审批'" class="warn">部分条未审或被退回，已审条不动，其余留在本批等重提</span>
        </footer>
      </article>
      <p v-if="!batches.length" class="empty-state">暂无批件，先在上方勾选绿地送审</p>
    </section>

    <!-- 第三步：方案台账 + 审批汇总对账 -->
    <section class="panel">
      <div class="panel-head">
        <h3>③ 方案台账 · 审批汇总对账</h3>
      </div>
      <form class="filter-bar" @submit.prevent="loadLedgerAndSummary">
        <label class="inline">
          方案季度
          <select v-model="ledgerQuarter">
            <option value="">全部季度</option>
            <option v-for="q in quarters" :key="q" :value="q">{{ q }}</option>
          </select>
        </label>
        <label class="inline">
          状态
          <select v-model="ledgerStatus">
            <option value="">全部</option>
            <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
          </select>
        </label>
        <label class="inline">
          预算下限
          <input v-model="budgetMin" type="number" />
        </label>
        <label class="inline">
          预算上限
          <input v-model="budgetMax" type="number" />
        </label>
        <button class="btn" type="submit">查询</button>
        <span v-if="summary?.['季度优先']" class="warn">方案季度与预算牵连，已按方案季度收口</span>
      </form>

      <table class="data-table">
        <thead>
          <tr>
            <th>方案编号</th>
            <th>方案季度</th>
            <th>覆盖绿地</th>
            <th>养护内容</th>
            <th class="num-col">预算金额</th>
            <th>编制人</th>
            <th>审批人</th>
            <th>状态</th>
            <th>批件</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in ledger" :key="String(row.id)">
            <td>{{ row['方案编号'] }}</td>
            <td>{{ row['方案季度'] }}</td>
            <td>{{ row['覆盖绿地'] }}</td>
            <td class="content-cell">{{ row['方案内容'] || '—' }}</td>
            <td class="num-col">{{ row['预算金额'] ?? '—' }}</td>
            <td>{{ row['编制人'] || '—' }}</td>
            <td>{{ row['审批人'] || '—' }}</td>
            <td><span class="tag" :class="statusClass(row.status)">{{ row.status }}</span></td>
            <td>{{ row['批次编号'] || '—' }}</td>
          </tr>
          <tr v-if="!ledger.length">
            <td colspan="9" class="empty-state">当前条件下没有方案记录</td>
          </tr>
        </tbody>
      </table>

      <div v-if="summary" class="reconcile">
        <h4>审批汇总（{{ summary['方案季度'] }}）</h4>
        <div class="reconcile-grid">
          <div>
            <span class="stat-label">台账已审批条数</span>
            <strong>{{ summary['台账已审批条数'] }}</strong>
          </div>
          <div>
            <span class="stat-label">台账审批预算合计</span>
            <strong>¥{{ summary['台账审批预算合计'] }}</strong>
          </div>
          <div>
            <span class="stat-label">批件审批汇总预算</span>
            <strong>¥{{ summary['批件审批汇总预算'] }}</strong>
          </div>
          <div>
            <span class="stat-label">对账结果</span>
            <strong :class="summary['汇总对得上'] ? 'ok' : 'warn'">
              {{ summary['汇总对得上'] ? '对得上' : '对不上' }}
            </strong>
          </div>
        </div>
        <table class="data-table inner">
          <thead>
            <tr>
              <th>批次编号</th>
              <th>方案季度</th>
              <th>批件状态</th>
              <th class="num-col">审批汇总预算</th>
              <th class="num-col">台账核对预算</th>
              <th class="num-col">已审批条数</th>
              <th>核对</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in summary['批件核对']" :key="item['批次编号']">
              <td>{{ item['批次编号'] }}</td>
              <td>{{ item['方案季度'] }}</td>
              <td>{{ item['批件状态'] }}</td>
              <td class="num-col">¥{{ item['审批汇总预算'] }}</td>
              <td class="num-col">¥{{ item['台账核对预算'] }}</td>
              <td class="num-col">{{ item['已审批条数'] }}</td>
              <td>
                <span :class="item['对得上'] ? 'ok' : 'warn'">
                  {{ item['对得上'] ? '一致' : '不一致' }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <footer class="page-foot">
      <span v-if="message" :class="messageOk ? 'ok-text' : 'error-text'">{{ message }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

const ENDPOINT = '/api/seasonplan'
const statuses = ['待编制', '已编制', '已审批', '执行中']

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Row = Record<string, any>
type PlotRow = Row
type Batch = Row
type Summary = Row

const quarters = ref<string[]>([])
const submitQuarter = ref('2026-Q3')
const plots = ref<PlotRow[]>([])
const plotSelection = ref<number[]>([])
const batches = ref<Batch[]>([])
const ledger = ref<Row[]>([])
const summary = ref<Summary | null>(null)
const message = ref('')
const messageOk = ref(true)
const returnSelection = ref<Record<number, number[]>>({})

const ledgerQuarter = ref('')
const ledgerStatus = ref('')
const budgetMin = ref<number | ''>('')
const budgetMax = ref<number | ''>('')

const selectedPlotIds = computed(() => new Set(plotSelection.value))

const stats = computed(() => {
  const all = batches.value.flatMap((batch) => batch.items)
  return [
    { label: '待编制方案', value: all.filter((row) => row.status === '待编制').length },
    { label: '待审批（已编制）', value: all.filter((row) => row.status === '已编制').length },
    { label: '已审批方案', value: all.filter((row) => row.status === '已审批').length },
    { label: '批件预算合计', value: `¥${batches.value.reduce((sum, b) => sum + (Number(b['预算合计']) || 0), 0)}` },
  ]
})

function flash(text: string, ok = true) {
  message.value = text
  messageOk.value = ok
}

function statusClass(status: unknown) {
  return {
    待编制: 'st-draft',
    已编制: 'st-done',
    已审批: 'st-approved',
    执行中: 'st-running',
    未编制: 'st-none',
  }[String(status)] ?? 'st-none'
}

function batchClass(status: string) {
  return { 待审批: 'st-done', 已审批: 'st-approved', 部分审批: 'st-partial' }[status] ?? 'st-none'
}

function isLocked(status: string) {
  return status === '已审批' || status === '执行中'
}

async function getJson(path: string) {
  const response = await request(path)
  if (!response.ok) throw new Error(`接口返回 ${response.status}`)
  return response.json()
}

async function postJson(path: string, body: Record<string, unknown>) {
  const response = await request(path, { method: 'POST', body: JSON.stringify(body) })
  const payload = await response.json()
  return { ok: response.ok && payload.ok !== false, payload }
}

async function loadQuarters() {
  const data = await getJson(`${ENDPOINT}/quarters`)
  quarters.value = data.items ?? []
  if (!submitQuarter.value && quarters.value.length) submitQuarter.value = quarters.value[0]
}

async function loadPlots() {
  plotSelection.value = []
  const data = await getJson(`${ENDPOINT}/plots?quarter=${encodeURIComponent(submitQuarter.value)}`)
  plots.value = data.items ?? []
}

async function submitPlots() {
  const { ok, payload } = await postJson(`${ENDPOINT}/batches/submit`, {
    values: { quarter: submitQuarter.value, plot_ids: [...selectedPlotIds.value], operator: '当前编制人' },
  })
  flash(payload.message ?? '送审结果未知', ok)
  await Promise.all([loadPlots(), loadBatches()])
}

async function loadBatches() {
  const data = await getJson(`${ENDPOINT}/batches`)
  const detail = await Promise.all(
    (data.items as Batch[]).map((batch) => getJson(`${ENDPOINT}/batches/${batch.id}`)),
  )
  batches.value = detail
}

async function onEditLine(line: Row, field: string, value: string) {
  const values: Record<string, string> = { [field]: value }
  const { ok, payload } = await postJson(`${ENDPOINT}/${line.id}/fill`, { values })
  flash(payload.message ?? '已保存', ok)
}

async function fillEntry(line: Row) {
  const { ok, payload } = await postJson(`${ENDPOINT}/${line.id}/fill`, {
    values: { 方案内容: line['方案内容'] ?? '', 预算金额: line['预算金额'] ?? '' },
  })
  flash(payload.message ?? '已校验', ok)
  await loadBatches()
}

async function approveBatch(batch: Batch) {
  const { ok, payload } = await postJson(`${ENDPOINT}/batches/${batch.id}/approve`, {
    values: { reviewer: '当前审批人' },
  })
  flash(payload.message ?? '审批完成', ok)
  await Promise.all([loadBatches(), loadLedgerAndSummary()])
}

function toggleReturn(batchId: number, entryId: number) {
  const current = returnSelection.value[batchId] ?? []
  returnSelection.value[batchId] = current.includes(entryId)
    ? current.filter((id) => id !== entryId)
    : [...current, entryId]
}

async function openReturn(batch: Batch) {
  const ids = returnSelection.value[batch.id] ?? []
  if (!ids.length) {
    flash('请先在左侧勾选要退回的「已编制」条目', false)
    return
  }
  const reason = window.prompt('退回原因（退回条留在原批件，完善后重提）', '养护内容需调整')
  if (reason === null) return
  const { ok, payload } = await postJson(`${ENDPOINT}/batches/${batch.id}/return`, {
    values: { entry_ids: ids, reason },
  })
  flash(payload.message ?? '退回完成', ok)
  returnSelection.value[batch.id] = []
  await Promise.all([loadBatches(), loadLedgerAndSummary()])
}

async function loadLedgerAndSummary() {
  const query = new URLSearchParams()
  if (ledgerQuarter.value) query.set('quarter', ledgerQuarter.value)
  if (ledgerStatus.value) query.set('status', ledgerStatus.value)
  if (budgetMin.value !== '') query.set('budget_min', String(budgetMin.value))
  if (budgetMax.value !== '') query.set('budget_max', String(budgetMax.value))

  const [listData, summaryData] = await Promise.all([
    getJson(`${ENDPOINT}?${query.toString()}`),
    getJson(`${ENDPOINT}/summary?${query.toString()}`),
  ])
  ledger.value = listData.items ?? []
  summary.value = summaryData
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

onMounted(async () => {
  try {
    await loadQuarters()
    await Promise.all([loadPlots(), loadBatches(), loadLedgerAndSummary()])
  } catch (error) {
    flash(error instanceof Error ? error.message : '季度养护方案页面加载失败', false)
  }
})
</script>

<style scoped>
.panel {
  background: var(--surface, #f7f8fa);
  border: 1px solid var(--border, #e2e5ea);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 18px;
}
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.panel-head h3 {
  margin: 0;
  font-size: 15px;
}
.panel-tools {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}
.inline {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}
.inline select,
.inline input {
  padding: 5px 8px;
  border: 1px solid var(--border, #d5d9e0);
  border-radius: 6px;
}
.check-col {
  width: 56px;
  text-align: center;
}
.num-col {
  text-align: right;
  width: 110px;
}
.tag {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
  font-style: normal;
  border: 1px solid transparent;
}
.st-draft { background: #f2f3f5; color: #7a828f; border-color: #dcdfe5; }
.st-done { background: #eaf3ff; color: #1d62c4; border-color: #b9d6fb; }
.st-approved { background: #e9f8ef; color: #157f43; border-color: #b6e3c7; }
.st-running { background: #fff4e0; color: #b26a00; border-color: #f6d59a; }
.st-partial { background: #fdecec; color: #c0392b; border-color: #f5b9b9; }
.st-none { background: #fafafa; color: #9aa0a8; border-color: #e5e5e5; }
.hint {
  color: #c0392b;
  font-style: normal;
  font-size: 12px;
}
.tip {
  margin: 8px 0 0;
  color: #7a828f;
  font-size: 12px;
}
.batch-card {
  background: #fff;
  border: 1px solid var(--border, #e2e5ea);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 14px;
}
.batch-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.batch-head .muted {
  margin-left: 8px;
  color: #7a828f;
  font-size: 12px;
}
.batch-actions {
  display: flex;
  gap: 8px;
}
.btn.danger {
  border-color: #e2a3a3;
  color: #c0392b;
}
.btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.data-table.inner {
  margin-top: 6px;
}
.data-table textarea,
.budget-input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #d5d9e0;
  border-radius: 4px;
  padding: 4px 6px;
  font-size: 12px;
  resize: vertical;
}
.content-cell {
  white-space: pre-line;
  max-width: 260px;
}
.batch-foot {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 13px;
  padding-top: 8px;
}
.return-note {
  margin: 0 0 8px;
  padding: 6px 10px;
  background: #fdecec;
  border-left: 3px solid #c0392b;
  font-size: 12px;
  color: #8a2b21;
}
.warn {
  color: #c0392b;
  font-size: 12px;
}
.ok {
  color: #157f43;
}
.ok-text {
  color: #157f43;
}
.reconcile {
  margin-top: 14px;
  border-top: 1px dashed #d5d9e0;
  padding-top: 12px;
}
.reconcile h4 {
  margin: 0 0 10px;
}
.reconcile-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
  margin-bottom: 12px;
}
.reconcile-grid > div {
  background: #fff;
  border: 1px solid var(--border, #e2e5ea);
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
</style>
