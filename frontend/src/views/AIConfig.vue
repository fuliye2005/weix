<template>
  <div class="ai-config-page" v-loading="loading">
    <section class="page-hero">
      <div>
        <div class="eyebrow"><el-icon><Setting /></el-icon> AI CONFIGURATION</div>
        <h1>AI 配置</h1>
        <p>用表单快速配置，也可以直接编辑 JSON。两种方式始终保持同步，最终写入 `config/config.yaml`。</p>
      </div>
      <div class="hero-actions">
        <el-tag :type="dirty ? 'warning' : 'success'" effect="plain">{{ dirty ? '有未保存修改' : '配置已同步' }}</el-tag>
        <el-button :loading="loading" @click="reloadConfig"><el-icon><Refresh /></el-icon>重新读取</el-button>
        <el-button :loading="saving" :disabled="!jsonValid || !dirty" type="primary" @click="saveConfig"><el-icon><FolderChecked /></el-icon>保存配置</el-button>
      </div>
    </section>

    <el-alert
      class="security-alert"
      title="纯自定义模式"
      description="不限制供应商、Base URL、模型名称或额外字段。API Key 可以在表单里输入，也可以直接在右侧 JSON 中修改。"
      type="info"
      show-icon
      :closable="false"
    />

    <div class="config-layout">
      <main class="form-column">
        <el-card class="panel" shadow="never">
          <div class="panel-heading">
            <div>
              <div class="panel-title">连接配置</div>
              <div class="panel-description">填写任意兼容当前运行引擎的模型服务。</div>
            </div>
            <el-tag :type="keyConfigured ? 'success' : 'warning'" effect="light">
              {{ keyConfigured ? 'API Key 已配置' : '需要 API Key' }}
            </el-tag>
          </div>

          <el-form :model="form" label-position="top" class="config-form">
            <div class="form-grid two-columns">
              <el-form-item label="Provider">
                <el-input v-model="form.provider" placeholder="自定义供应商标识，例如 custom" @input="syncJsonFromForm" />
                <div class="field-help">仅作为配置标识，不会限制你使用哪家服务。</div>
              </el-form-item>
              <el-form-item label="Protocol">
                <el-input v-model="form.protocol" placeholder="chat_completions" @input="syncJsonFromForm" />
                <div class="field-help">当前运行适配器默认使用 Chat Completions 兼容协议。</div>
              </el-form-item>
            </div>

            <div class="form-grid two-columns">
              <el-form-item label="Base URL" required>
                <el-input v-model="form.base_url" placeholder="https://your-provider.example/v1" clearable @input="syncJsonFromForm" />
                <div class="field-help">填写 API 根地址，不要重复添加具体请求路径。</div>
              </el-form-item>
              <el-form-item label="Model" required>
                <el-input v-model="form.model" placeholder="your-model-name" clearable @input="syncJsonFromForm" />
                <div class="field-help">模型名称完全由上游服务决定。</div>
              </el-form-item>
            </div>

            <el-form-item label="API Key" required>
              <el-input
                v-model="keyInput"
                type="password"
                show-password
                clearable
                autocomplete="new-password"
                :placeholder="keyConfigured ? apiKeyPreview : '粘贴 API Key，或在右侧 JSON 中填写'"
                @input="syncJsonFromForm"
              >
                <template #prefix><el-icon><Key /></el-icon></template>
              </el-input>
              <div class="field-help">当前 Key 不会自动回显完整内容；输入新值后保存即可替换。</div>
            </el-form-item>

            <div class="form-grid three-columns">
              <el-form-item label="Temperature">
                <el-input-number v-model="form.temperature" :min="0" :max="2" :step="0.1" controls-position="right" style="width: 100%" @change="syncJsonFromForm" />
              </el-form-item>
              <el-form-item label="Max Tokens">
                <el-input-number v-model="form.max_tokens" :min="100" :max="32000" :step="100" controls-position="right" style="width: 100%" @change="syncJsonFromForm" />
              </el-form-item>
              <el-form-item label="JSON 状态">
                <div class="json-status" :class="jsonValid ? 'valid' : 'invalid'"><el-icon><CircleCheckFilled v-if="jsonValid" /><CircleCloseFilled v-else /></el-icon>{{ jsonValid ? '格式有效' : '格式错误' }}</div>
              </el-form-item>
            </div>

            <el-form-item label="System Prompt">
              <el-input v-model="form.system_prompt" type="textarea" :rows="5" resize="vertical" placeholder="定义助手的基础行为……" @input="syncJsonFromForm" />
            </el-form-item>

            <el-collapse v-model="expandedSections" class="advanced-collapse">
              <el-collapse-item name="persona">
                <template #title><div class="collapse-title"><el-icon><User /></el-icon><span>Persona 参数</span><small>聊天风格分析使用</small></div></template>
                <div class="form-grid three-columns advanced-grid">
                  <el-form-item label="Persona 模式">
                    <el-input v-model="form.persona_mode" placeholder="contextual" @input="syncJsonFromForm" />
                  </el-form-item>
                  <el-form-item label="回溯天数">
                    <el-input-number v-model="form.persona_since_days" :min="1" :max="3650" :step="30" controls-position="right" style="width: 100%" @change="syncJsonFromForm" />
                  </el-form-item>
                  <el-form-item label="分析消息数">
                    <el-input-number v-model="form.persona_message_limit" :min="100" :max="100000" :step="100" controls-position="right" style="width: 100%" @change="syncJsonFromForm" />
                  </el-form-item>
                </div>
                <div class="form-grid two-columns advanced-grid">
                  <el-form-item label="JSON 单文件上限（MB）">
                    <el-input-number v-model="form.persona_import_max_mb" :min="0" :max="4096" :step="16" controls-position="right" style="width: 100%" @change="syncJsonFromForm" />
                  </el-form-item>
                  <el-form-item label="配置备注">
                    <el-input v-model="form.profile_name" placeholder="可选，仅用于识别" @input="syncJsonFromForm" />
                  </el-form-item>
                </div>
              </el-collapse-item>
            </el-collapse>
          </el-form>
        </el-card>
      </main>

      <aside class="json-column">
        <el-card class="json-card" shadow="never">
          <div class="json-heading">
            <div>
              <div class="panel-title">AI 配置 JSON</div>
              <div class="panel-description">表单输入会自动生成；直接修改后点击“应用 JSON”。</div>
            </div>
            <el-tag :type="jsonValid ? 'success' : 'danger'" effect="light">{{ jsonValid ? 'Valid JSON' : 'Invalid JSON' }}</el-tag>
          </div>

          <div class="json-toolbar">
            <el-button size="small" @click="formatJson"><el-icon><MagicStick /></el-icon>格式化</el-button>
            <el-button size="small" @click="applyJsonToForm"><el-icon><Download /></el-icon>应用 JSON</el-button>
            <el-button size="small" @click="copyJson"><el-icon><CopyDocument /></el-icon>复制</el-button>
          </div>

          <el-input
            v-model="jsonText"
            class="json-editor"
            type="textarea"
            :rows="34"
            resize="none"
            spellcheck="false"
            placeholder="在这里编辑 AI 配置 JSON…"
            @input="handleJsonInput"
            @blur="autoApplyJson"
          />
          <div class="json-error" v-if="jsonError"><el-icon><Warning /></el-icon>{{ jsonError }}</div>
          <div class="json-footer"><span><el-icon><Lock /></el-icon> 当前编辑的是 `ai` 配置段</span><span>{{ jsonText.length.toLocaleString() }} 字符</span></div>
        </el-card>

        <el-card class="summary-card" shadow="never">
          <div class="side-title"><span>当前状态</span><el-icon><Connection /></el-icon></div>
          <div class="summary-grid">
            <div><span>配置文件</span><strong>config.yaml</strong></div>
            <div><span>Key</span><strong :class="keyConfigured ? 'ok' : 'warn'">{{ keyConfigured ? apiKeyPreview : '未配置' }}</strong></div>
            <div><span>保存状态</span><strong>{{ dirty ? '待保存' : '已同步' }}</strong></div>
          </div>
          <el-button class="full-button" :loading="testing" :disabled="dirty" @click="testCurrentConfig"><el-icon><CircleCheck /></el-icon>测试已保存配置</el-button>
          <div v-if="dirty" class="test-hint">请先保存配置，再测试当前连接。</div>
        </el-card>

        <el-card v-if="testResult" class="result-card" shadow="never" :class="testResult.success ? 'success' : 'error'">
          <div class="result-title"><el-icon><CircleCheckFilled v-if="testResult.success" /><CircleCloseFilled v-else /></el-icon>{{ testResult.success ? '连接成功' : '连接失败' }}</div>
          <div class="result-text">{{ testResult.success ? `${testResult.model} · ${testResult.latency_ms}ms · ${testResult.preview || 'OK'}` : testResult.error }}</div>
        </el-card>
      </aside>
    </div>

    <div class="bottom-bar">
      <span><el-icon><InfoFilled /></el-icon> 保存时只更新 `ai` 配置段，其他 YAML 配置保持不变。</span>
      <div><el-button :disabled="!dirty" @click="restoreSaved">撤销修改</el-button><el-button type="primary" :loading="saving" :disabled="!jsonValid || !dirty" @click="saveConfig">保存配置</el-button></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getAIConfig, testCurrentAIConnection, updateAIConfig } from '../api'

type AnyRecord = Record<string, any>
type TestResult = { success: boolean; error?: string; model?: string; latency_ms?: number; preview?: string }

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const keyConfigured = ref(false)
const apiKeyPreview = ref('')
const keyInput = ref('')
const jsonText = ref('')
const savedJson = ref('')
const jsonError = ref('')
const jsonObject = ref<AnyRecord>({})
const expandedSections = ref<string[]>([])
const testResult = ref<TestResult | null>(null)

const form = reactive<AnyRecord>({
  provider: '',
  protocol: 'chat_completions',
  api_key: '',
  base_url: '',
  model: '',
  temperature: 0.7,
  max_tokens: 2000,
  persona_mode: 'contextual',
  persona_since_days: 90,
  persona_message_limit: 3000,
  persona_import_max_mb: 256,
  profile_name: '',
  system_prompt: '',
})

const jsonValid = computed(() => {
  if (!jsonText.value.trim()) return false
  try {
    const parsed = JSON.parse(jsonText.value)
    return parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed)
  } catch {
    return false
  }
})
const dirty = computed(() => jsonText.value !== savedJson.value)

function currentJsonObject(): AnyRecord {
  try {
    const parsed = JSON.parse(jsonText.value)
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) return parsed
  } catch {}
  return { ...jsonObject.value }
}

function formFields() {
  return {
    provider: form.provider,
    protocol: form.protocol,
    api_key: keyInput.value.trim() || form.api_key || '',
    base_url: form.base_url,
    model: form.model,
    temperature: form.temperature,
    max_tokens: form.max_tokens,
    persona_mode: form.persona_mode,
    persona_since_days: form.persona_since_days,
    persona_message_limit: form.persona_message_limit,
    persona_import_max_mb: form.persona_import_max_mb,
    profile_name: form.profile_name,
    system_prompt: form.system_prompt,
  }
}

function syncJsonFromForm() {
  const next = { ...currentJsonObject(), ...formFields() }
  jsonObject.value = next
  jsonText.value = JSON.stringify(next, null, 2)
  jsonError.value = ''
}

function handleJsonInput() {
  try {
    const parsed = JSON.parse(jsonText.value)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('JSON 顶层必须是对象')
    jsonObject.value = parsed
    jsonError.value = ''
  } catch (error: any) {
    jsonError.value = error?.message || 'JSON 格式错误'
  }
}

function applyJsonToForm(showMessage = true) {
  handleJsonInput()
  if (!jsonValid.value) {
    ElMessage.error(jsonError.value || 'JSON 格式错误，无法应用')
    return false
  }
  const data = jsonObject.value
  for (const key of Object.keys(form)) {
    if (Object.prototype.hasOwnProperty.call(data, key)) form[key] = data[key]
  }
  const incomingKey = String(data.api_key ?? '')
  if (incomingKey && !incomingKey.startsWith('***')) {
    keyInput.value = incomingKey
    form.api_key = incomingKey
  } else {
    keyInput.value = ''
    form.api_key = incomingKey
  }
  if (showMessage) ElMessage.success('JSON 已应用到表单')
  return true
}

function autoApplyJson() {
  if (jsonValid.value) applyJsonToForm(false)
}

function formatJson() {
  if (!applyJsonToForm(false)) return
  syncJsonFromForm()
  ElMessage.success('JSON 已格式化')
}

async function copyJson() {
  try {
    await navigator.clipboard.writeText(jsonText.value)
    ElMessage.success('JSON 已复制')
  } catch {
    ElMessage.warning('浏览器不允许访问剪贴板，请手动复制')
  }
}

async function loadConfig() {
  const response = await getAIConfig()
  const data = response.data || {}
  keyConfigured.value = Boolean(data.api_key_configured)
  apiKeyPreview.value = data.api_key_preview || data.api_key || ''
  keyInput.value = ''
  Object.assign(form, data)
  form.api_key = data.api_key || ''
  const { api_key_configured: _configured, api_key_preview: _preview, models: _models, ...initial } = data
  jsonObject.value = initial
  jsonText.value = JSON.stringify(initial, null, 2)
  savedJson.value = jsonText.value
  jsonError.value = ''
  testResult.value = null
}

async function reloadConfig() {
  loading.value = true
  try {
    await loadConfig()
    ElMessage.success('配置已重新读取')
  } catch {
    ElMessage.error('AI 配置读取失败')
  } finally {
    loading.value = false
  }
}

async function saveConfig() {
  if (!applyJsonToForm(false)) return
  const payload = currentJsonObject()
  saving.value = true
  try {
    await updateAIConfig(payload)
    await loadConfig()
    ElMessage.success('AI 配置已保存到 config.yaml')
  } catch {
    // axios interceptor 已显示错误。
  } finally {
    saving.value = false
  }
}

function restoreSaved() {
  jsonText.value = savedJson.value
  applyJsonToForm(false)
  testResult.value = null
  ElMessage.info('已撤销未保存修改')
}

async function testCurrentConfig() {
  testing.value = true
  testResult.value = null
  try {
    const response = await testCurrentAIConnection()
    testResult.value = response.data
    if (response.data?.success) ElMessage.success('连接测试成功')
  } catch {
    testResult.value = { success: false, error: '连接测试请求失败，请确认后端服务正常运行' }
  } finally {
    testing.value = false
  }
}

onMounted(async () => {
  loading.value = true
  try { await loadConfig() } catch { ElMessage.error('AI 配置读取失败') } finally { loading.value = false }
})
</script>

<style scoped>
.ai-config-page { max-width: 1480px; margin: 0 auto; color: #182230; }
.page-hero { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin-bottom: 22px; }.eyebrow { display: flex; align-items: center; gap: 7px; color: #667085; font-size: 12px; font-weight: 700; letter-spacing: .12em; }h1 { margin: 8px 0 6px; color: #101828; font-size: 28px; letter-spacing: -.02em; }.page-hero p { margin: 0; color: #667085; font-size: 13px; }.hero-actions, .bottom-bar, .json-toolbar, .json-footer, .side-title { display: flex; align-items: center; gap: 10px; }.security-alert { margin-bottom: 18px; }
.config-layout { display: grid; grid-template-columns: minmax(0, 1fr) minmax(390px, .78fr); gap: 18px; align-items: start; }.form-column, .json-column { display: flex; flex-direction: column; gap: 18px; min-width: 0; }.panel, .json-card, .summary-card, .result-card { border: 1px solid #e4e7ec; border-radius: 12px; }.panel :deep(.el-card__body), .summary-card :deep(.el-card__body), .result-card :deep(.el-card__body) { padding: 22px; }.json-card :deep(.el-card__body) { padding: 20px; }.panel-heading, .json-heading { display: flex; justify-content: space-between; gap: 18px; margin-bottom: 20px; }.panel-title { color: #101828; font-size: 17px; font-weight: 700; }.panel-description { margin-top: 5px; color: #667085; font-size: 13px; line-height: 1.5; }.config-form :deep(.el-form-item) { margin-bottom: 18px; }.config-form :deep(.el-form-item__label) { padding-bottom: 7px; color: #344054; font-size: 13px; font-weight: 600; }.form-grid { display: grid; gap: 16px; }.two-columns { grid-template-columns: repeat(2, minmax(0, 1fr)); }.three-columns { grid-template-columns: repeat(3, minmax(0, 1fr)); }.field-help { margin-top: 6px; color: #667085; font-size: 12px; line-height: 1.45; }.json-status { display: flex; align-items: center; justify-content: center; gap: 7px; height: 32px; border-radius: 6px; font-size: 13px; }.json-status.valid { background: #ecfdf3; color: #067647; }.json-status.invalid { background: #fef3f2; color: #b42318; }.advanced-collapse { border: 1px solid #e4e7ec; border-radius: 9px; overflow: hidden; }.advanced-collapse :deep(.el-collapse-item__header) { height: 52px; padding: 0 14px; }.collapse-title { display: flex; align-items: center; gap: 8px; font-weight: 700; }.collapse-title small { margin-left: 4px; color: #98a2b3; font-size: 12px; font-weight: 400; }.advanced-grid { padding: 18px 14px 0; }.advanced-grid :deep(.el-form-item) { margin-bottom: 18px; }
.json-toolbar { justify-content: flex-end; margin: -6px 0 12px; }.json-editor :deep(.el-textarea__inner) { min-height: 650px !important; padding: 17px 18px; border: 1px solid #1d2939; border-radius: 9px; background: #101828; box-shadow: none; color: #d1e9ff; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 12px; line-height: 1.7; resize: none; tab-size: 2; }.json-editor :deep(.el-textarea__inner::placeholder) { color: #667085; }.json-error { display: flex; align-items: flex-start; gap: 6px; margin-top: 9px; color: #b42318; font-size: 12px; line-height: 1.45; }.json-footer { justify-content: space-between; margin-top: 10px; color: #98a2b3; font-size: 11px; }.json-footer span { display: flex; align-items: center; gap: 5px; }
.side-title { justify-content: space-between; color: #344054; font-size: 14px; font-weight: 700; }.summary-grid { display: flex; flex-direction: column; gap: 13px; margin-top: 20px; }.summary-grid div { display: flex; justify-content: space-between; gap: 12px; font-size: 12px; }.summary-grid span { color: #667085; }.summary-grid strong { max-width: 230px; overflow: hidden; color: #344054; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }.summary-grid strong.ok { color: #067647; }.summary-grid strong.warn { color: #b54708; }.full-button { width: 100%; margin-top: 20px; }.test-hint { margin-top: 8px; color: #98a2b3; font-size: 11px; text-align: center; }.result-card.success { border-color: #abefc6; background: #f6fef9; }.result-card.error { border-color: #fecdca; background: #fff8f7; }.result-title { display: flex; align-items: center; gap: 7px; font-size: 14px; font-weight: 700; }.result-card.success .result-title { color: #067647; }.result-card.error .result-title { color: #b42318; }.result-text { margin-top: 8px; color: #667085; font-size: 12px; line-height: 1.5; word-break: break-word; }.bottom-bar { justify-content: space-between; margin-top: 18px; padding: 14px 2px 2px; color: #667085; font-size: 12px; }.bottom-bar > span { display: flex; align-items: center; gap: 6px; }
@media (max-width: 1120px) { .config-layout { grid-template-columns: 1fr; }.json-column { display: grid; grid-template-columns: minmax(0, 1fr) minmax(260px, .7fr); }.json-card { grid-row: span 2; } }
@media (max-width: 760px) { .page-hero { align-items: flex-start; flex-direction: column; }.hero-actions { width: 100%; flex-wrap: wrap; }.hero-actions .el-button { flex: 1; }.two-columns, .three-columns, .json-column { grid-template-columns: 1fr; }.json-card { grid-row: auto; }.json-heading { align-items: flex-start; flex-direction: column; }.json-toolbar { justify-content: flex-start; flex-wrap: wrap; }.bottom-bar { align-items: flex-start; flex-direction: column; }.bottom-bar > div { width: 100%; display: flex; }.bottom-bar .el-button { flex: 1; }.collapse-title small { display: none; } }
</style>
