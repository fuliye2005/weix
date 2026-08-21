<template>
  <el-card>
    <template #header>
      <div class="persona-header">
        <span>本人 Skill</span>
        <div>
          <el-button :loading="loading" @click="loadPersona">刷新</el-button>
          <el-button v-if="persona.ready && !editing" :loading="loading" @click="startEdit">
            编辑
          </el-button>
          <el-button v-if="editing" type="primary" :loading="loading" @click="savePersonaEdit">
            保存
          </el-button>
          <el-button v-if="editing" :disabled="loading" @click="cancelEdit">
            取消
          </el-button>
          <el-button type="primary" :loading="loading" @click="runPersonaAnalyze">
            从微信数据库生成
          </el-button>
          <el-button type="danger" :loading="loading" @click="clearPersonaCache">
            清除
          </el-button>
        </div>
      </div>
    </template>

    <el-descriptions :column="3" border>
      <el-descriptions-item label="状态">
        <el-tag :type="persona.ready ? 'success' : 'info'">
          {{ persona.ready ? '已生成' : '未生成' }}
        </el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="模式">
        {{ persona.mode || 'contextual' }}
      </el-descriptions-item>
      <el-descriptions-item label="名称">
        {{ persona.meta?.name || '-' }}
      </el-descriptions-item>
    </el-descriptions>

    <el-divider content-position="left">从聊天 JSON 模仿指定人物</el-divider>
    <el-alert
      title="聊天内容只作为待分析数据，不会被当作指令执行。可同时选择多个聊天记录，系统会按 senderUsername 合并同一个人。"
      type="info"
      :closable="false"
      show-icon
    />
    <div class="import-toolbar">
      <input
        ref="fileInput"
        type="file"
        accept=".json,application/json"
        multiple
        hidden
        @change="handleFileChange"
      />
      <el-button :disabled="loading" @click="openFilePicker">选择多个 JSON</el-button>
      <span v-if="selectedFiles.length" class="file-summary">
        已选择 {{ selectedFiles.length }} 个文件：{{ selectedFiles.map((file) => file.name).join('、') }}
      </span>
      <span v-else class="file-summary">尚未选择文件</span>
      <el-button
        type="primary"
        :loading="loading"
        :disabled="selectedFiles.length === 0"
        @click="uploadChatFiles"
      >
        上传并读取人物
      </el-button>
    </div>

    <div v-if="importData.import_id" class="import-result">
      <el-descriptions :column="3" border>
        <el-descriptions-item label="导入文件">
          {{ importData.file_count }} 个
        </el-descriptions-item>
        <el-descriptions-item label="文本消息">
          {{ importData.total_messages }} 条
        </el-descriptions-item>
        <el-descriptions-item label="人物数量">
          {{ importData.participants.length }} 人
        </el-descriptions-item>
      </el-descriptions>
      <div class="speaker-toolbar">
        <el-select
          v-model="selectedSpeakerId"
          filterable
          placeholder="选择要模仿的人"
          class="speaker-select"
        >
          <el-option
            v-for="participant in importData.participants"
            :key="participant.id"
            :label="`${participant.name}（${participant.message_count} 条，${participant.source_files} 个文件）`"
            :value="participant.id"
          />
        </el-select>
        <el-button
          type="primary"
          :loading="loading"
          :disabled="!selectedSpeakerId"
          @click="analyzeSelectedPersona"
        >
          分析并模仿此人
        </el-button>
        <el-button :loading="loading" @click="removeImportedChat">删除导入数据</el-button>
      </div>
    </div>

    <el-tabs v-if="persona.ready" style="margin-top: 16px">
      <el-tab-pane label="Self Memory">
        <el-input v-model="form.self_memory" type="textarea" :rows="8" :readonly="!editing" />
      </el-tab-pane>
      <el-tab-pane label="Persona">
        <el-input v-model="form.persona" type="textarea" :rows="8" :readonly="!editing" />
      </el-tab-pane>
      <el-tab-pane label="私聊 Prompt">
        <el-input v-model="form.private_prompt" type="textarea" :rows="8" :readonly="!editing" />
      </el-tab-pane>
      <el-tab-pane label="群聊 Prompt">
        <el-input v-model="form.group_prompt" type="textarea" :rows="8" :readonly="!editing" />
      </el-tab-pane>
    </el-tabs>
  </el-card>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  analyzeImportedPersona,
  analyzePersona,
  clearPersona,
  deletePersonaImport,
  getPersona,
  importPersonaChatFiles,
  updatePersona,
} from '../api'

type Participant = {
  id: string
  name: string
  message_count: number
  source_files: number
}

const loading = ref(false)
const editing = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const selectedFiles = ref<File[]>([])
const selectedSpeakerId = ref('')
const importData = reactive<{
  import_id: string
  file_count: number
  total_messages: number
  participants: Participant[]
}>({
  import_id: '',
  file_count: 0,
  total_messages: 0,
  participants: [],
})
const persona = reactive<any>({
  ready: false,
  mode: 'contextual',
  meta: {},
  self_memory: '',
  persona: '',
  private_prompt: '',
  group_prompt: '',
})
const form = reactive<any>({
  self_memory: '',
  persona: '',
  private_prompt: '',
  group_prompt: '',
})

function syncForm() {
  Object.assign(form, {
    self_memory: persona.self_memory || '',
    persona: persona.persona || '',
    private_prompt: persona.private_prompt || '',
    group_prompt: persona.group_prompt || '',
  })
}

function applyPersonaResult(data: any) {
  Object.assign(persona, {
    ready: true,
    mode: data.mode,
    meta: data.meta,
    self_memory: data.self_memory,
    persona: data.persona,
    private_prompt: data.private_prompt,
    group_prompt: data.group_prompt,
  })
  syncForm()
  editing.value = false
}

async function loadPersona() {
  loading.value = true
  try {
    const res = await getPersona()
    Object.assign(persona, res.data)
    syncForm()
    editing.value = false
  } catch {
    editing.value = false
  } finally {
    loading.value = false
  }
}

function openFilePicker() {
  fileInput.value?.click()
}

function handleFileChange(event: Event) {
  const target = event.target as HTMLInputElement
  selectedFiles.value = Array.from(target.files || []).filter((file) => file.name.toLowerCase().endsWith('.json'))
}

async function uploadChatFiles() {
  loading.value = true
  try {
    const res = await importPersonaChatFiles(selectedFiles.value)
    if (res.data?.success) {
      Object.assign(importData, {
        import_id: res.data.import_id,
        file_count: res.data.file_count,
        total_messages: res.data.total_messages,
        participants: res.data.participants || [],
      })
      selectedSpeakerId.value = importData.participants[0]?.id || ''
      ElMessage.success(`已读取 ${res.data.total_messages} 条文本消息，请选择人物`)
    } else {
      ElMessage.error(res.data?.error || '聊天记录读取失败')
    }
  } catch {
    // 全局 axios interceptor 已提示错误。
  } finally {
    loading.value = false
  }
}

async function analyzeSelectedPersona() {
  if (!importData.import_id || !selectedSpeakerId.value) return
  loading.value = true
  try {
    const res = await analyzeImportedPersona({
      import_id: importData.import_id,
      speaker_id: selectedSpeakerId.value,
      force: true,
    })
    if (res.data?.success) {
      applyPersonaResult(res.data)
      ElMessage.success(`已生成 ${res.data.meta?.name || '所选人物'} 的说话风格，样本 ${res.data.sample_size} 条`)
    } else {
      ElMessage.error(res.data?.error || '人物风格分析失败')
    }
  } catch {
    // 全局 axios interceptor 已提示错误。
  } finally {
    loading.value = false
  }
}

async function removeImportedChat() {
  if (!importData.import_id) return
  loading.value = true
  try {
    const res = await deletePersonaImport(importData.import_id)
    if (res.data?.success) {
      Object.assign(importData, { import_id: '', file_count: 0, total_messages: 0, participants: [] })
      selectedFiles.value = []
      selectedSpeakerId.value = ''
      ElMessage.success('聊天记录导入已删除')
    } else {
      ElMessage.error(res.data?.error || '删除导入数据失败')
    }
  } catch {
    // 全局 axios interceptor 已提示错误。
  } finally {
    loading.value = false
  }
}

async function runPersonaAnalyze() {
  loading.value = true
  try {
    const res = await analyzePersona(true)
    if (res.data?.success) {
      applyPersonaResult(res.data)
      ElMessage.success(`本人 Skill 已生成，样本 ${res.data.sample_size} 条`)
    } else {
      ElMessage.error(res.data?.error || '生成失败')
    }
  } catch {
    // 全局 axios interceptor 已提示错误。
  } finally {
    loading.value = false
  }
}

function startEdit() {
  syncForm()
  editing.value = true
}

function cancelEdit() {
  syncForm()
  editing.value = false
}

async function savePersonaEdit() {
  loading.value = true
  try {
    const res = await updatePersona({
      meta: persona.meta || {},
      mode: persona.mode || 'contextual',
      self_memory: form.self_memory,
      persona: form.persona,
      private_prompt: form.private_prompt,
      group_prompt: form.group_prompt,
    })
    if (res.data?.success) {
      applyPersonaResult(res.data)
      ElMessage.success('本人 Skill 已保存')
    } else {
      ElMessage.error(res.data?.error || '保存失败')
    }
  } catch {
    // 全局 axios interceptor 已提示错误。
  } finally {
    loading.value = false
  }
}

async function clearPersonaCache() {
  loading.value = true
  try {
    await clearPersona()
    Object.assign(persona, {
      ready: false,
      mode: 'contextual',
      meta: {},
      self_memory: '',
      persona: '',
      private_prompt: '',
      group_prompt: '',
    })
    syncForm()
    editing.value = false
    ElMessage.success('本人 Skill 已清除')
  } catch {
    // 全局 axios interceptor 已提示错误。
  } finally {
    loading.value = false
  }
}

onMounted(loadPersona)
</script>

<style scoped>
.persona-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.import-toolbar,
.speaker-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 14px;
}

.file-summary {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  flex: 1;
  min-width: 180px;
}

.import-result {
  margin-top: 14px;
}

.speaker-select {
  min-width: 320px;
}
</style>
