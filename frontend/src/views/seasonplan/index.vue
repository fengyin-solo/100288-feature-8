<template>
  <section class="page" data-module="seasonplan">
    <header class="page-head">
      <div>
        <h2>季度养护方案管理</h2>
        <p class="page-desc">
          养护内容逐条填，同一季度的方案多选后一次送审；审批只审已编完的，退回的留在原处等重提。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="showCreate = !showCreate">登记养护方案</button>
        <button class="btn" type="button" :disabled="!selectedIds.length" @click="submitBatch">
          批量送审<template v-if="selectedIds.length">（{{ selectedIds.length }} 片 · {{ selectedQuarter }}）</template>
        </button>
        <button class="btn" type="button" @click="exportRows">导出季度养护方案清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form v-if="showCreate" class="panel" @submit.prevent="createPlan">
      <h3>登记养护方案</h3>
      <div class="form-grid">
        <label>方案编号<input v-model="createForm.方案编号" required placeholder="如 SEAS-0006" /></label>
        <label>方案季度<input v-model="createForm.方案季度" required placeholder="如 2026-Q4" /></label>
        <label>覆盖绿地<input v-model="createForm.覆盖绿地" required placeholder="绿地名称" /></label>
        <label>预算金额（万元）<input v-model="createForm.预算金额" type="number" step="0.01" min="0" /></label>
        <label>编制人<input v-model="createForm.编制人" placeholder="选填" /></label>
      </div>
      <label class="content-input">
        养护内容（逐条填，每行一条；没填内容不能标已编制）
        <textarea v-model="createForm.方案内容" rows="4" placeholder="乔木冬季修剪 120 株&#10;草坪追肥 800㎡"></textarea>
      </label>
      <div class="panel-actions">
        <button class="btn primary" type="submit">保存方案</button>
        <button class="btn ghost" type="button" @click="showCreate = false">收起</button>
      </div>
    </form>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th title="同一批只能选同一季度的方案">送审</th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td>
            <input
              type="checkbox"
              :checked="selectedIds.includes(Number(row.id))"
              :disabled="!canSelect(row)"
              :title="canSelect(row) ? '选中后一起送审' : '同一批只能选同一季度的方案'"
              @change="toggleSelect(row)"
            />
          </td>
          <td v-for="column in columns" :key="column">{{ displayCell(row, column) }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <button class="link" type="button" @click="appendContent(row)">补录内容</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无季度养护方案数据，可先登记养护方案</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条季度养护方案记录</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <section class="panel">
      <h3>送审批次</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>批次号</th>
            <th>方案季度</th>
            <th>方案数</th>
            <th>状态</th>
            <th>预算合计（万元）</th>
            <th>审批人</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="batch in batches" :key="String(batch.批次号)">
            <td>{{ batch.批次号 }}</td>
            <td>{{ batch.方案季度 }}</td>
            <td>{{ batch.方案数 }}</td>
            <td>{{ batch.状态 }}</td>
            <td>{{ batch.预算合计 }}</td>
            <td>{{ batch.审批人 || '—' }}</td>
            <td><button class="link" type="button" @click="openApprove(batch)">审批</button></td>
          </tr>
          <tr v-if="!batches.length">
            <td colspan="7" class="empty-state">还没有送审批次，勾选同季度方案后点「批量送审」</td>
          </tr>
        </tbody>
      </table>

      <div v-if="approving" class="approve-panel">
        <h4>审批批次 {{ approving.批次号 }}（{{ approving.方案季度 }}）</h4>
        <p v-if="approving.审批结果" class="page-desc">
          该批次已审批过，按第一次审批结果为准：通过 {{ approving.审批结果.已审.length }} 条、
          退回 {{ approving.审批结果.退回.length }} 条、未编完挑出 {{ approving.审批结果.未编完挑出.length }} 条。
        </p>
        <p v-else class="page-desc">未编完（待编制）的会自动挑出，不参与本次审批；勾选「退回」的留在原处等重提。</p>
        <table class="data-table">
          <thead>
            <tr>
              <th>方案编号</th>
              <th>覆盖绿地</th>
              <th>当前状态</th>
              <th>预算金额（万元）</th>
              <th>退回</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="plan in approvingPlans" :key="String(plan.id)">
              <td>{{ plan.方案编号 }}</td>
              <td>{{ plan.覆盖绿地 }}</td>
              <td>{{ plan.status }}</td>
              <td>{{ plan.预算金额 }}</td>
              <td>
                <input
                  type="checkbox"
                  :checked="rejectIds.includes(Number(plan.id))"
                  :disabled="plan.status !== '已编制' || !!approving.审批结果"
                  @change="toggleReject(Number(plan.id))"
                />
              </td>
            </tr>
          </tbody>
        </table>
        <div class="form-grid">
          <label>审批人<input v-model="approveForm.审批人" placeholder="必填" /></label>
          <label>退回原因<input v-model="approveForm.退回原因" placeholder="有退回时填写" /></label>
        </div>
        <div class="panel-actions">
          <button class="btn primary" type="button" :disabled="!!approving.审批结果" @click="approveBatch">
            提交审批
          </button>
          <button class="btn ghost" type="button" @click="approving = null">关闭</button>
        </div>
        <p v-if="approveResult" class="notice-text">{{ approveResult }}</p>
      </div>
    </section>

    <section class="panel">
      <h3>审批汇总</h3>
      <div class="filter-bar">
        <label class="filter-item">
          <span>方案季度</span>
          <input v-model="summaryForm.方案季度" placeholder="如 2026-Q4" />
        </label>
        <label class="filter-item">
          <span>预算下限（万元）</span>
          <input v-model="summaryForm.预算下限" type="number" step="0.01" />
        </label>
        <label class="filter-item">
          <span>预算上限（万元）</span>
          <input v-model="summaryForm.预算上限" type="number" step="0.01" />
        </label>
        <button class="btn" type="button" @click="loadSummary">查询汇总</button>
      </div>
      <p class="page-desc">方案季度与预算条件同时给时，以方案季度为准；汇总预算与方案台账、批次留痕三方对账。</p>
      <div v-if="summary">
        <div class="stat-row">
          <article class="stat-card">
            <span class="stat-label">已审批条数</span>
            <strong class="stat-value">{{ summary.审批汇总.条数 }}</strong>
          </article>
          <article class="stat-card">
            <span class="stat-label">预算合计（万元）</span>
            <strong class="stat-value">{{ summary.审批汇总.预算合计 }}</strong>
          </article>
          <article class="stat-card">
            <span class="stat-label">台账核对</span>
            <strong class="stat-value" :class="summary.台账核对.是否对上 ? 'ok-text' : 'error-text'">
              {{ summary.台账核对.是否对上 ? '已对上' : '对不上' }}
            </strong>
          </article>
        </div>
        <p class="page-desc">
          {{ summary.口径说明 }}；台账 {{ summary.台账核对.台账预算合计 }} 万元 /
          批次留痕 {{ summary.台账核对.批次留痕预算合计 }} 万元
        </p>
        <table class="data-table">
          <thead>
            <tr>
              <th>方案编号</th>
              <th>方案季度</th>
              <th>覆盖绿地</th>
              <th>预算金额（万元）</th>
              <th>审批人</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in summary.明细" :key="String(item.id)">
              <td>{{ item.方案编号 }}</td>
              <td>{{ item.方案季度 }}</td>
              <td>{{ item.覆盖绿地 }}</td>
              <td>{{ item.预算金额 }}</td>
              <td>{{ item.审批人 || '—' }}</td>
            </tr>
            <tr v-if="!summary.明细.length">
              <td colspan="5" class="empty-state">该条件下没有审批通过的方案</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, any>

const ENDPOINT = '/api/seasonplan'
const columns = ["方案编号", "方案季度", "覆盖绿地", "方案内容", "预算金额", "编制人", "审批人", "方案状态"]
const actions = ["编制方案", "审批方案", "启动执行"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const stats = computed(() => [
  { label: '待编制方案', value: rows.value.filter((row) => row.status === '待编制').length },
  { label: '已审批方案', value: rows.value.filter((row) => row.status === '已审批').length },
  { label: '执行中方案', value: rows.value.filter((row) => row.status === '执行中').length },
])

// ---------- 登记：养护内容逐条填 ----------
const showCreate = ref(false)
const emptyCreate = () => ({ 方案编号: '', 方案季度: '', 覆盖绿地: '', 预算金额: '', 编制人: '', 方案内容: '' })
const createForm = ref(emptyCreate())

async function createPlan() {
  errorMessage.value = ''
  noticeMessage.value = ''
  const contents = createForm.value.方案内容.split('\n').map((line) => line.trim()).filter(Boolean)
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { ...createForm.value, 方案内容: contents } }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      throw new Error(payload.message || '养护方案登记未生效')
    }
    noticeMessage.value = payload.message
    showCreate.value = false
    createForm.value = emptyCreate()
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '养护方案登记失败'
  }
}

// ---------- 批量送审：同一季度多选 ----------
const selectedIds = ref<number[]>([])
const selectedQuarter = computed(() => {
  const first = rows.value.find((row) => selectedIds.value.includes(Number(row.id)))
  return first ? String(first.方案季度 ?? '') : ''
})

function canSelect(row: Row) {
  if (selectedIds.value.includes(Number(row.id))) return true
  return !selectedIds.value.length || String(row.方案季度) === selectedQuarter.value
}

function toggleSelect(row: Row) {
  const id = Number(row.id)
  if (selectedIds.value.includes(id)) {
    selectedIds.value = selectedIds.value.filter((item) => item !== id)
  } else {
    selectedIds.value = [...selectedIds.value, id]
  }
}

async function submitBatch() {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/batches`, {
      method: 'POST',
      body: JSON.stringify({ values: { 方案季度: selectedQuarter.value, 方案ids: selectedIds.value } }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      throw new Error(payload.message || '批量送审未生效')
    }
    noticeMessage.value = payload.message
    selectedIds.value = []
    await Promise.all([reload(), loadBatches()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量送审失败'
  }
}

// ---------- 送审批次与批量审批 ----------
const batches = ref<Row[]>([])
const approving = ref<Row | null>(null)
const approvingPlans = ref<Row[]>([])
const rejectIds = ref<number[]>([])
const approveForm = ref({ 审批人: '', 退回原因: '' })
const approveResult = ref('')

async function loadBatches() {
  try {
    const response = await request(`${ENDPOINT}/batches?size=100`)
    if (!response.ok) {
      throw new Error('送审批次读取失败')
    }
    const payload = await response.json()
    batches.value = payload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '送审批次读取失败'
  }
}

async function openApprove(batch: Row) {
  errorMessage.value = ''
  approveResult.value = ''
  try {
    const response = await request(`${ENDPOINT}/batches/${encodeURIComponent(String(batch.批次号))}`)
    if (!response.ok) {
      throw new Error('批次详情读取失败')
    }
    const payload = await response.json()
    approving.value = payload
    approvingPlans.value = payload.方案明细 ?? []
    rejectIds.value = []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批次详情读取失败'
  }
}

function toggleReject(id: number) {
  if (rejectIds.value.includes(id)) {
    rejectIds.value = rejectIds.value.filter((item) => item !== id)
  } else {
    rejectIds.value = [...rejectIds.value, id]
  }
}

async function approveBatch() {
  if (!approving.value) return
  errorMessage.value = ''
  approveResult.value = ''
  try {
    const response = await request(
      `${ENDPOINT}/batches/${encodeURIComponent(String(approving.value.批次号))}/approve`,
      {
        method: 'POST',
        body: JSON.stringify({
          values: {
            审批人: approveForm.value.审批人,
            退回原因: approveForm.value.退回原因,
            退回ids: rejectIds.value,
          },
        }),
      },
    )
    const payload = await response.json()
    if (!payload.ok) {
      throw new Error(payload.message || '批量审批未生效')
    }
    await Promise.all([reload(), loadBatches()])
    await openApprove(payload.entry.批次号)
    approveResult.value = payload.message
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量审批失败'
  }
}

// ---------- 审批汇总 ----------
const summaryForm = ref({ 方案季度: '', 预算下限: '', 预算上限: '' })
const summary = ref<Row | null>(null)

async function loadSummary() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (summaryForm.value.方案季度) params.set('方案季度', summaryForm.value.方案季度)
  if (summaryForm.value.预算下限 !== '') params.set('预算下限', summaryForm.value.预算下限)
  if (summaryForm.value.预算上限 !== '') params.set('预算上限', summaryForm.value.预算上限)
  try {
    const response = await request(`${ENDPOINT}/summary?${params.toString()}`)
    if (!response.ok) {
      throw new Error('审批汇总读取失败')
    }
    summary.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '审批汇总读取失败'
  }
}

// ---------- 列表与单条动作 ----------
function displayCell(row: Row, column: string) {
  const value = row[column]
  if (Array.isArray(value)) return value.length ? value.join('；') : '—'
  return value ?? '—'
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      throw new Error(payload.message || '季度养护方案动作未生效')
    }
    noticeMessage.value = payload.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '季度养护方案操作失败'
  }
}

async function appendContent(row: Row) {
  const line = window.prompt(`给 ${row.方案编号} 补录一条养护内容`)
  if (!line || !line.trim()) return
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/contents`, {
      method: 'POST',
      body: JSON.stringify({ values: { 方案内容: [line.trim()] } }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      throw new Error(payload.message || '养护内容补录未生效')
    }
    noticeMessage.value = payload.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '养护内容补录失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(
    Object.entries(filters.value).filter(([, value]) => value),
  ).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('养护方案列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '季度养护方案列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadBatches()
})
</script>

<style scoped>
.panel {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 12px;
}
.panel h3 {
  margin: 0 0 10px;
  font-size: 14px;
}
.panel h4 {
  margin: 0 0 8px;
  font-size: 13px;
}
.form-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 10px;
}
.form-grid label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--muted);
}
.form-grid input {
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  min-width: 180px;
}
.content-input {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 10px;
}
.content-input textarea {
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-family: inherit;
}
.panel-actions {
  display: flex;
  gap: 8px;
  margin-top: 4px;
}
.approve-panel {
  margin-top: 12px;
  border-top: 1px dashed var(--border);
  padding-top: 12px;
}
.approve-panel .data-table {
  margin-bottom: 10px;
}
.notice-text {
  color: #067647;
}
.ok-text {
  color: #067647;
}
</style>
