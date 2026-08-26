<template>
  <div class="business-page" v-loading="loading">
    <section class="page-header">
      <div>
        <div class="eyebrow"><el-icon><Briefcase /></el-icon> BUSINESS HOURS</div>
        <h1>业务与工作时间</h1>
        <p>配置业务资料、营业时段和日期例外，供对话流程判断服务时间。</p>
      </div>
      <div class="header-actions">
        <el-tag :type="dirty ? 'warning' : 'success'" effect="plain">
          {{ dirty ? '有未保存修改' : '配置已同步' }}
        </el-tag>
        <el-button :loading="loading" @click="reloadConfig">
          <el-icon><Refresh /></el-icon>重新读取
        </el-button>
        <el-button type="primary" :loading="saving" :disabled="!dirty" @click="saveConfig">
          <el-icon><FolderChecked /></el-icon>保存配置
        </el-button>
      </div>
    </section>

    <el-alert
      class="status-alert"
      :title="form.enabled ? '业务配置已启用' : '业务配置未启用'"
      :type="form.enabled ? 'success' : 'info'"
      show-icon
      :closable="false"
    >
      <template #default>
        {{ form.enabled ? '系统可以使用下面的资料和时间段进行判断。' : '保存后不会使用业务时间判断，但配置内容仍会保留。' }}
      </template>
    </el-alert>

    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="business-form">
      <div class="top-grid">
        <el-card class="panel" shadow="never">
          <div class="panel-heading">
            <div>
              <div class="panel-title">业务资料</div>
              <div class="panel-description">这些信息用于识别业务场景和对外显示名称。</div>
            </div>
            <el-switch v-model="form.enabled" active-text="启用" inactive-text="停用" />
          </div>

          <div class="form-grid two-columns">
            <el-form-item label="业务类型" prop="category" required>
              <el-select v-model="form.category" filterable allow-create default-first-option placeholder="选择或输入业务类型" class="full-width">
                <el-option v-for="option in categoryOptions" :key="option.value" :label="option.label" :value="option.value" />
              </el-select>
            </el-form-item>
            <el-form-item label="显示名称" prop="display_name" required>
              <el-input v-model="form.display_name" maxlength="80" show-word-limit placeholder="例如：城市生活服务" />
            </el-form-item>
          </div>

          <el-form-item label="时区" prop="timezone" required>
            <el-select v-model="form.timezone" filterable allow-create default-first-option placeholder="选择 IANA 时区" class="full-width">
              <el-option v-for="timezone in timezoneOptions" :key="timezone" :label="timezone" :value="timezone" />
            </el-select>
            <div class="field-help">工作时间按此时区解释，建议使用 IANA 格式。</div>
          </el-form-item>

          <el-form-item label="服务项目">
            <div class="service-list">
              <div v-for="(_service, index) in form.services" :key="`service-${index}`" class="service-row">
                <el-input v-model="form.services[index]" maxlength="80" placeholder="例如：预约咨询" />
                <el-tooltip content="删除服务项目" placement="top">
                  <el-button circle text type="danger" aria-label="删除服务项目" @click="removeService(index)">
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </el-tooltip>
              </div>
              <el-button class="add-button" text type="primary" @click="addService">
                <el-icon><Plus /></el-icon>添加服务项目
              </el-button>
            </div>
          </el-form-item>

          <el-form-item label="补充说明">
            <el-input v-model="form.notes" type="textarea" :rows="5" maxlength="1000" show-word-limit resize="vertical" placeholder="补充业务范围、服务边界或其他需要说明的信息" />
          </el-form-item>
        </el-card>

        <el-card class="panel policy-panel" shadow="never">
          <div class="panel-heading">
            <div>
              <div class="panel-title">非工作时间策略</div>
              <div class="panel-description">控制非营业时段的时间说明范围。</div>
            </div>
            <el-icon class="heading-icon"><Clock /></el-icon>
          </div>
          <el-form-item label="说明范围" prop="off_hours_policy" required>
            <el-radio-group v-model="form.off_hours_policy" class="policy-options">
              <el-radio label="relevant_only">仅相关咨询时说明</el-radio>
              <el-radio label="all">所有咨询均说明</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-alert
            title="默认仅在相关咨询中说明"
            description="这样不会让无关对话被营业时间信息打断。"
            type="info"
            :closable="false"
            show-icon
          />
        </el-card>
      </div>

      <el-card class="panel hours-panel" shadow="never">
        <div class="panel-heading">
          <div>
            <div class="panel-title">每周工作时间</div>
            <div class="panel-description">每天可以配置多个时间段；结束时间早于开始时间时，表示跨午夜营业。</div>
          </div>
          <el-icon class="heading-icon"><Calendar /></el-icon>
        </div>

        <div class="hours-list">
          <div v-for="day in dayOptions" :key="day.key" class="hours-row">
            <div class="day-name">
              <strong>{{ day.label }}</strong>
              <span>{{ form.weekly_hours[day.key].length ? `${form.weekly_hours[day.key].length} 个时段` : '休息' }}</span>
            </div>
            <div class="interval-area">
              <div v-for="(interval, index) in form.weekly_hours[day.key]" :key="`${day.key}-${index}`" class="interval-row">
                <el-time-picker v-model="interval.start" format="HH:mm" value-format="HH:mm" placeholder="开始" :clearable="false" />
                <span class="time-separator">至</span>
                <el-time-picker v-model="interval.end" format="HH:mm" value-format="HH:mm" placeholder="结束" :clearable="false" />
                <el-tooltip content="删除时间段" placement="top">
                  <el-button circle text type="danger" aria-label="删除时间段" @click="removeInterval(day.key, index)">
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </el-tooltip>
              </div>
              <div v-if="!form.weekly_hours[day.key].length" class="closed-label">未设置营业时间</div>
              <el-button size="small" text type="primary" @click="addInterval(day.key)">
                <el-icon><Plus /></el-icon>添加时段
              </el-button>
            </div>
          </div>
        </div>
      </el-card>

      <el-card class="panel exceptions-panel" shadow="never">
        <div class="panel-heading">
          <div>
            <div class="panel-title">日期例外</div>
            <div class="panel-description">为节假日、临时营业或特殊安排覆盖对应日期的周计划。</div>
          </div>
          <el-button size="small" @click="addException"><el-icon><Plus /></el-icon>添加例外</el-button>
        </div>

        <div v-if="form.exceptions.length" class="exception-list">
          <article v-for="(exception, index) in form.exceptions" :key="`exception-${index}`" class="exception-item">
            <div class="exception-grid">
              <el-form-item label="日期" :prop="`exceptions.${index}.date`" required>
                <el-date-picker v-model="exception.date" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" class="full-width" />
              </el-form-item>
              <el-form-item label="安排" required>
                <el-select v-model="exception.type" class="full-width">
                  <el-option label="休息" value="closed" />
                  <el-option label="临时营业" value="open" />
                  <el-option label="特殊时间" value="special" />
                </el-select>
              </el-form-item>
              <el-form-item label="备注">
                <el-input v-model="exception.note" maxlength="160" placeholder="例如：节假日调整" />
              </el-form-item>
            </div>

            <div v-if="exception.type !== 'closed'" class="exception-intervals">
              <div class="subsection-label">特殊时段</div>
              <div v-for="(interval, intervalIndex) in exception.intervals" :key="`exception-${index}-${intervalIndex}`" class="interval-row">
                <el-time-picker v-model="interval.start" format="HH:mm" value-format="HH:mm" placeholder="开始" :clearable="false" />
                <span class="time-separator">至</span>
                <el-time-picker v-model="interval.end" format="HH:mm" value-format="HH:mm" placeholder="结束" :clearable="false" />
                <el-tooltip content="删除特殊时段" placement="top">
                  <el-button circle text type="danger" aria-label="删除特殊时段" @click="removeExceptionInterval(exception, intervalIndex)">
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </el-tooltip>
              </div>
              <el-button size="small" text type="primary" @click="addExceptionInterval(exception)">
                <el-icon><Plus /></el-icon>添加特殊时段
              </el-button>
            </div>
            <div v-else class="closed-label exception-closed">当天休息，不配置时段</div>

            <div class="exception-footer">
              <span class="field-help">结束早于开始表示跨午夜。</span>
              <el-button text type="danger" @click="removeException(index)"><el-icon><Delete /></el-icon>删除例外</el-button>
            </div>
          </article>
        </div>
        <el-empty v-else description="暂未设置日期例外" :image-size="72" />
      </el-card>
    </el-form>

    <div class="bottom-bar">
      <span><el-icon><InfoFilled /></el-icon>保存只更新业务配置，不会修改其他配置。</span>
      <div>
        <el-button :disabled="!dirty" @click="restoreSaved">撤销修改</el-button>
        <el-button type="primary" :loading="saving" :disabled="!dirty" @click="saveConfig">保存配置</el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getBusinessConfig, updateBusinessConfig } from '../api'

type Interval = { start: string; end: string }
type DayKey = 'monday' | 'tuesday' | 'wednesday' | 'thursday' | 'friday' | 'saturday' | 'sunday'
type ExceptionType = 'closed' | 'open' | 'special'
type BusinessException = { date: string; type: ExceptionType; intervals: Interval[]; note: string }

type BusinessForm = {
  enabled: boolean
  category: string
  display_name: string
  timezone: string
  services: string[]
  weekly_hours: Record<DayKey, Interval[]>
  exceptions: BusinessException[]
  notes: string
  off_hours_policy: 'relevant_only' | 'all'
}

const dayOptions: Array<{ key: DayKey; label: string }> = [
  { key: 'monday', label: '周一' },
  { key: 'tuesday', label: '周二' },
  { key: 'wednesday', label: '周三' },
  { key: 'thursday', label: '周四' },
  { key: 'friday', label: '周五' },
  { key: 'saturday', label: '周六' },
  { key: 'sunday', label: '周日' },
]

const dayAliases: Record<DayKey, string[]> = {
  monday: ['monday', 'mon'],
  tuesday: ['tuesday', 'tue'],
  wednesday: ['wednesday', 'wed'],
  thursday: ['thursday', 'thu'],
  friday: ['friday', 'fri'],
  saturday: ['saturday', 'sat'],
  sunday: ['sunday', 'sun'],
}

const categoryOptions = [
  { label: '通用服务', value: 'general_service' },
  { label: '咨询服务', value: 'consulting' },
  { label: '预约服务', value: 'appointment' },
  { label: '售后支持', value: 'support' },
  { label: '其他', value: 'other' },
]

const timezoneOptions = [
  'Asia/Shanghai',
  'Asia/Tokyo',
  'Asia/Singapore',
  'Asia/Seoul',
  'UTC',
  'Europe/London',
  'Europe/Berlin',
  'America/New_York',
  'America/Los_Angeles',
]

function newInterval(): Interval {
  return { start: '09:00', end: '18:00' }
}

function newWeeklyHours(): Record<DayKey, Interval[]> {
  const result = {} as Record<DayKey, Interval[]>
  for (const { key } of dayOptions) result[key] = []
  return result
}

function newForm(): BusinessForm {
  return {
    enabled: false,
    category: 'general_service',
    display_name: '',
    timezone: 'Asia/Shanghai',
    services: [''],
    weekly_hours: newWeeklyHours(),
    exceptions: [],
    notes: '',
    off_hours_policy: 'relevant_only',
  }
}

const loading = ref(false)
const saving = ref(false)
const formRef = ref<any>()
const savedSnapshot = ref('')
const form = reactive<BusinessForm>(newForm())

const rules = {
  category: [{ required: true, message: '请选择或输入业务类型', trigger: 'change' }],
  display_name: [{ required: true, message: '请输入显示名称', trigger: 'blur' }],
  timezone: [{ required: true, message: '请选择时区', trigger: 'change' }],
  off_hours_policy: [{ required: true, message: '请选择非工作时间策略', trigger: 'change' }],
}

const dirty = computed(() => serializeForm() !== savedSnapshot.value)

function cloneInterval(value: any): Interval | null {
  if (!value || typeof value !== 'object') return null
  const start = String(value.start ?? value.open ?? '').trim()
  const end = String(value.end ?? value.close ?? '').trim()
  if (!start && !end) return null
  return { start, end }
}

function normalizeIntervals(value: any): Interval[] {
  const source = Array.isArray(value) ? value : Array.isArray(value?.intervals) ? value.intervals : []
  return source.map(cloneInterval).filter(Boolean) as Interval[]
}

function normalizeWeeklyHours(value: any): Record<DayKey, Interval[]> {
  const source = value && typeof value === 'object' ? value : {}
  const result = newWeeklyHours()
  for (const { key } of dayOptions) {
    const raw = dayAliases[key].map((alias) => source[alias]).find((item) => item !== undefined)
    result[key] = normalizeIntervals(raw)
  }
  return result
}

function normalizeException(value: any): BusinessException {
  const rawType = String(value?.type ?? value?.status ?? 'closed').toLowerCase()
  const type: ExceptionType = ['open', 'temporary_open', 'business'].includes(rawType)
    ? 'open'
    : ['special', 'special_hours'].includes(rawType)
      ? 'special'
      : 'closed'
  return {
    date: String(value?.date ?? '').slice(0, 10),
    type,
    intervals: normalizeIntervals(value?.intervals ?? value?.hours),
    note: String(value?.note ?? value?.notes ?? '').trim(),
  }
}

function applyData(data: any) {
  const next = newForm()
  next.enabled = Boolean(data?.enabled)
  next.category = String(data?.category ?? next.category)
  next.display_name = String(data?.display_name ?? '')
  next.timezone = String(data?.timezone ?? next.timezone)
  next.services = Array.isArray(data?.services)
    ? data.services.map((item: any) => typeof item === 'string' ? item : String(item?.name ?? item?.label ?? '')).filter(Boolean)
    : ['']
  if (!next.services.length) next.services = ['']
  next.weekly_hours = normalizeWeeklyHours(data?.weekly_hours)
  next.exceptions = Array.isArray(data?.exceptions) ? data.exceptions.map(normalizeException) : []
  next.notes = String(data?.notes ?? '').trim()
  next.off_hours_policy = data?.off_hours_policy === 'all' || data?.off_hours_policy === 'all_requests' ? 'all' : 'relevant_only'
  Object.assign(form, next)
}

function serializeForm() {
  return JSON.stringify(buildPayload())
}

function buildPayload() {
  return {
    enabled: Boolean(form.enabled),
    category: form.category.trim(),
    display_name: form.display_name.trim(),
    timezone: form.timezone.trim(),
    services: form.services.map((item) => item.trim()).filter(Boolean),
    weekly_hours: Object.fromEntries(dayOptions.map(({ key }) => [
      key,
      form.weekly_hours[key].map(({ start, end }) => ({ start, end })),
    ])),
    exceptions: form.exceptions.map((item) => ({
      date: item.date,
      type: item.type,
      intervals: item.type === 'closed' ? [] : item.intervals.map(({ start, end }) => ({ start, end })),
      note: item.note.trim(),
    })),
    notes: form.notes.trim(),
    off_hours_policy: form.off_hours_policy,
  }
}

function addService() {
  form.services.push('')
}

function removeService(index: number) {
  form.services.splice(index, 1)
  if (!form.services.length) form.services.push('')
}

function addInterval(day: DayKey) {
  form.weekly_hours[day].push(newInterval())
}

function removeInterval(day: DayKey, index: number) {
  form.weekly_hours[day].splice(index, 1)
}

function addException() {
  form.exceptions.push({ date: '', type: 'closed', intervals: [], note: '' })
}

function removeException(index: number) {
  form.exceptions.splice(index, 1)
}

function addExceptionInterval(exception: BusinessException) {
  exception.intervals.push(newInterval())
}

function removeExceptionInterval(exception: BusinessException, index: number) {
  exception.intervals.splice(index, 1)
}

function isValidTime(value: string) {
  return /^([01]\d|2[0-3]):[0-5]\d$/.test(value)
}

function validateIntervals(intervals: Interval[], label: string) {
  if (!intervals.length) return true
  for (const interval of intervals) {
    if (!isValidTime(interval.start) || !isValidTime(interval.end)) {
      ElMessage.error(`${label}的时间格式无效`)
      return false
    }
    if (interval.start === interval.end) {
      ElMessage.error(`${label}的开始和结束时间不能相同`)
      return false
    }
  }
  return true
}

async function validateBeforeSave() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return false
  const services = form.services.map((item) => item.trim()).filter(Boolean)
  if (new Set(services).size !== services.length) {
    ElMessage.error('服务项目不能重复')
    return false
  }
  for (const day of dayOptions) {
    if (!validateIntervals(form.weekly_hours[day.key], day.label)) return false
  }
  const dates = new Set<string>()
  for (const exception of form.exceptions) {
    if (!exception.date) {
      ElMessage.error('请为每条日期例外选择日期')
      return false
    }
    if (dates.has(exception.date)) {
      ElMessage.error(`日期例外不能重复：${exception.date}`)
      return false
    }
    dates.add(exception.date)
    if (exception.type !== 'closed' && !exception.intervals.length) {
      ElMessage.error(`${exception.date}至少需要一个特殊时段`)
      return false
    }
    if (!validateIntervals(exception.intervals, exception.date)) return false
  }
  return true
}

async function loadConfig() {
  const response = await getBusinessConfig()
  applyData(response.data || {})
  savedSnapshot.value = serializeForm()
}

async function reloadConfig() {
  loading.value = true
  try {
    await loadConfig()
    ElMessage.success('业务配置已重新读取')
  } catch {
    ElMessage.error('业务配置读取失败')
  } finally {
    loading.value = false
  }
}

async function saveConfig() {
  if (!(await validateBeforeSave())) return
  saving.value = true
  try {
    await updateBusinessConfig(buildPayload())
    await loadConfig()
    ElMessage.success('业务与工作时间配置已保存')
  } catch {
    // axios interceptor displays the request error.
  } finally {
    saving.value = false
  }
}

function restoreSaved() {
  try {
    applyData(JSON.parse(savedSnapshot.value))
    ElMessage.info('已撤销未保存修改')
  } catch {
    ElMessage.error('撤销失败，请重新读取配置')
  }
}

onMounted(async () => {
  loading.value = true
  try {
    await loadConfig()
  } catch {
    ElMessage.error('业务配置读取失败')
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.business-page { max-width: 1280px; margin: 0 auto; color: #182230; }
.page-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin-bottom: 22px; }
.eyebrow { display: flex; align-items: center; gap: 7px; color: #667085; font-size: 12px; font-weight: 700; letter-spacing: .12em; }
h1 { margin: 8px 0 6px; color: #101828; font-size: 28px; letter-spacing: 0; }
.page-header p { margin: 0; color: #667085; font-size: 13px; }
.header-actions, .bottom-bar { display: flex; align-items: center; gap: 10px; }
.status-alert { margin-bottom: 18px; }
.business-form { display: flex; flex-direction: column; gap: 18px; }
.top-grid { display: grid; grid-template-columns: minmax(0, 1.45fr) minmax(280px, .75fr); gap: 18px; align-items: start; }
.panel { border: 1px solid #e4e7ec; border-radius: 12px; }
.panel :deep(.el-card__body) { padding: 22px; }
.panel-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; margin-bottom: 20px; }
.panel-title { color: #101828; font-size: 17px; font-weight: 700; }
.panel-description { margin-top: 5px; color: #667085; font-size: 13px; line-height: 1.5; }
.heading-icon { color: #667085; font-size: 20px; }
.form-grid { display: grid; gap: 16px; }
.two-columns { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.full-width { width: 100%; }
.business-form :deep(.el-form-item) { margin-bottom: 18px; }
.business-form :deep(.el-form-item__label) { padding-bottom: 7px; color: #344054; font-size: 13px; font-weight: 600; }
.field-help { color: #667085; font-size: 12px; line-height: 1.45; }
.service-list { display: flex; flex-direction: column; gap: 8px; width: 100%; }
.service-row { display: flex; align-items: center; gap: 8px; }
.service-row .el-input { min-width: 0; }
.add-button { align-self: flex-start; }
.policy-panel { min-height: 260px; }
.policy-options { display: flex; flex-direction: column; align-items: flex-start; gap: 16px; }
.policy-panel .el-alert { margin-top: 12px; }
.hours-list { border-top: 1px solid #eef0f3; }
.hours-row { display: grid; grid-template-columns: 130px minmax(0, 1fr); gap: 18px; padding: 16px 0; border-bottom: 1px solid #eef0f3; }
.day-name { display: flex; flex-direction: column; gap: 4px; padding-top: 5px; }
.day-name strong { color: #344054; font-size: 14px; }
.day-name span, .closed-label { color: #98a2b3; font-size: 12px; }
.interval-area { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; min-width: 0; }
.interval-row { display: flex; align-items: center; gap: 8px; width: 100%; }
.interval-row .el-time-editor { width: 150px; max-width: 100%; }
.time-separator { color: #667085; font-size: 13px; }
.exception-list { display: flex; flex-direction: column; gap: 12px; }
.exception-item { padding: 16px; border: 1px solid #e4e7ec; border-radius: 9px; background: #fcfcfd; }
.exception-grid { display: grid; grid-template-columns: minmax(150px, .8fr) minmax(150px, .8fr) minmax(220px, 1.4fr); gap: 16px; }
.exception-grid :deep(.el-form-item) { margin-bottom: 12px; }
.exception-intervals { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; padding-top: 4px; }
.subsection-label { color: #344054; font-size: 13px; font-weight: 600; }
.exception-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 10px; }
.exception-closed { padding: 8px 0 2px; }
.bottom-bar { justify-content: space-between; margin-top: 18px; padding: 2px 2px 18px; color: #667085; font-size: 12px; }
.bottom-bar > span { display: flex; align-items: center; gap: 6px; }
.bottom-bar > div { display: flex; gap: 10px; }
@media (max-width: 900px) {
  .top-grid { grid-template-columns: 1fr; }
  .exception-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .exception-grid :deep(.el-form-item:last-child) { grid-column: 1 / -1; }
}
@media (max-width: 680px) {
  .page-header { align-items: flex-start; flex-direction: column; }
  .header-actions { width: 100%; flex-wrap: wrap; }
  .header-actions .el-button { flex: 1; }
  .two-columns, .exception-grid { grid-template-columns: 1fr; }
  .exception-grid :deep(.el-form-item:last-child) { grid-column: auto; }
  .hours-row { grid-template-columns: 1fr; gap: 10px; }
  .interval-row { flex-wrap: wrap; }
  .interval-row .el-time-editor { flex: 1 1 125px; width: auto; }
  .exception-footer, .bottom-bar { align-items: flex-start; flex-direction: column; }
  .bottom-bar > div { width: 100%; }
  .bottom-bar > div .el-button { flex: 1; }
}
</style>
