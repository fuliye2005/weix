<template>
  <div>
    <h2>聊天配置</h2>
    <el-card>
      <el-form :model="form" label-width="140px">
        <el-form-item label="启用机器人">
          <el-switch v-model="form.enabled" />
        </el-form-item>
        <el-form-item label="工作微信账号">
          <el-select
            v-model="selectedAccount"
            placeholder="自动选择"
            clearable
            style="width: 100%"
            :loading="accountLoading"
            @change="changeAccount"
          >
            <el-option
              v-for="account in accounts"
              :key="account.wxid"
              :label="accountLabel(account)"
              :value="account.wxid"
            >
              <div class="account-option">
                <div class="account-option-title">
                  {{ account.nickname || account.alias || account.base_wxid || account.wxid }}
                  <el-tag v-if="account.active" size="small" type="success">当前运行</el-tag>
                  <el-tag v-else-if="account.selected" size="small" type="warning">配置中</el-tag>
                </div>
                <div class="account-option-detail">
                  微信号：{{ account.alias || '未读取' }} · wxid：{{ account.base_wxid || account.wxid }}
                </div>
              </div>
            </el-option>
          </el-select>
          <div v-if="activeAccount" style="color: #67c23a; margin-top: 6px">
            当前运行账号：{{ activeAccountLabel }}；其他选项是本机发现的历史数据目录。
          </div>
          <div v-if="accountHint" style="color: #909399; margin-top: 6px">
            {{ accountHint }}
          </div>
          <div class="restart-row">
            <el-button type="warning" :loading="restarting" @click="restartBackendNow">
              <el-icon><RefreshRight /></el-icon>
              {{ restartRequired ? '重启后端使账号生效' : '重启后端' }}
            </el-button>
            <el-button type="info" plain :loading="uiaDiagnosing" @click="diagnoseUiaNow">
              <el-icon><Monitor /></el-icon>
              UIA 检测
            </el-button>
            <span v-if="restartRequired">切换工作账号后，重启后端才会重新绑定数据库和微信窗口。</span>
            <span v-else>重启后端会重新加载配置、数据库和自动回复流水线。</span>
          </div>
        </el-form-item>
        <el-form-item label="群聊权限">
          <el-radio-group v-model="form.group_chat_mode">
            <el-radio label="all">所有人</el-radio>
            <el-radio label="whitelist">仅白名单</el-radio>
            <el-radio label="none">禁用</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="群聊白名单">
          <div style="margin-bottom: 8px">
            <el-tag v-for="room in form.group_whitelist" :key="room" closable @close="removeRoom(room)" style="margin-right: 8px; margin-bottom: 4px">
              {{ roomName(room) }}
            </el-tag>
          </div>
          <el-select
            v-model="selectedRoom"
            filterable
            remote
            :remote-method="filterRooms"
            placeholder="输入关键词搜索群聊"
            style="width: 100%"
            @change="addRoom"
          >
            <el-option
              v-for="room in filteredRooms"
              :key="room.room_id"
              :label="room.name && room.name !== room.room_id ? room.name : room.room_id"
              :value="room.room_id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="私聊权限">
          <el-radio-group v-model="form.private_chat_mode">
            <el-radio label="all">所有人</el-radio>
            <el-radio label="whitelist">仅白名单</el-radio>
            <el-radio label="none">禁用</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="私聊白名单">
          <div style="margin-bottom: 8px">
            <el-tag v-for="user in form.private_whitelist" :key="user" closable @close="removeUser(user)" style="margin-right: 8px; margin-bottom: 4px">
              {{ userName(user) }}
            </el-tag>
          </div>
          <el-select
            v-model="selectedUser"
            filterable
            remote
            :remote-method="filterContacts"
            placeholder="输入关键词搜索用户"
            style="width: 100%"
            @change="addUser"
          >
            <el-option
              v-for="c in filteredContacts"
              :key="c.wxid"
              :label="c.nickname || c.remark || c.alias || c.wxid"
              :value="c.wxid"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="回复模式">
          <el-radio-group v-model="form.reply_mode">
            <el-radio label="keyword">仅关键词</el-radio>
            <el-radio label="ai">AI 自动回复</el-radio>
            <el-radio label="all">全部回复</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="saveConfig" :loading="saving">保存配置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-dialog v-model="uiaDialogVisible" title="UIA 诊断结果" width="720px">
      <template v-if="uiaDiagnosis">
        <el-alert
          :title="uiaDiagnosis.uia_available ? 'UIA 控件树可访问' : 'UIA 控件树不可用'"
          :type="uiaDiagnosis.uia_available ? 'success' : 'error'"
          show-icon
          :closable="false"
        />
        <el-descriptions class="uia-descriptions" :column="2" border>
          <el-descriptions-item label="发送模式">
            {{ uiaDiagnosis.method || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="当前会话">
            {{ uiaDiagnosis.current_chat || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="选中账号">
            {{ uiaDiagnosis.selected_account || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="绑定 PID">
            {{ uiaDiagnosis.bound_pid || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="驱动 PID">
            {{ uiaDiagnosis.driver_pid || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="会话列表">
            {{ uiaDiagnosis.session_list ? '已发现' : '未发现' }}
          </el-descriptions-item>
          <el-descriptions-item label="微信窗口" :span="2">
            <template v-if="uiaDiagnosis.window">
              {{ uiaDiagnosis.window.name || '-' }} · {{ uiaDiagnosis.window.class_name || '-' }}
              · HWND {{ uiaDiagnosis.window.hwnd || '-' }} · PID {{ uiaDiagnosis.window.pid || '-' }}
            </template>
            <span v-else>-</span>
          </el-descriptions-item>
          <el-descriptions-item label="搜索框" :span="2">
            {{ controlSummary(uiaDiagnosis.search_box) }}
          </el-descriptions-item>
          <el-descriptions-item label="聊天输入框" :span="2">
            {{ controlSummary(uiaDiagnosis.chat_input) }}
          </el-descriptions-item>
          <el-descriptions-item label="发送按钮" :span="2">
            {{ controlSummary(uiaDiagnosis.send_button) }}
          </el-descriptions-item>
          <el-descriptions-item v-if="uiaDiagnosis.error" label="错误" :span="2">
            <span class="uia-error">{{ uiaDiagnosis.error }}</span>
          </el-descriptions-item>
        </el-descriptions>
      </template>
      <template #footer>
        <el-button @click="uiaDialogVisible = false">关闭</el-button>
        <el-button type="primary" :loading="uiaDiagnosing" @click="diagnoseUiaNow">
          <el-icon><RefreshRight /></el-icon>
          重新检测
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, onMounted } from 'vue'
import { getChatConfig, updateChatConfig, getContacts, searchChatrooms, searchContactsApi, getWechatAccounts, selectWechatAccount, restartBackend as restartBackendApi, getHealth, diagnoseUia } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Monitor, RefreshRight } from '@element-plus/icons-vue'

const form = reactive<any>({
  enabled: true,
  group_chat_mode: 'whitelist',
  group_whitelist: [],
  private_chat_mode: 'all',
  private_whitelist: [],
  reply_mode: 'all',
})

// 全量数据：用于已选标签的名称展示
const allChatrooms = ref<any[]>([])
const allContacts = ref<any[]>([])

// 下拉选项：仅展示搜索结果（默认空，避免渲染数千 DOM）
const filteredRooms = ref<any[]>([])
const filteredContacts = ref<any[]>([])

const selectedRoom = ref('')
const selectedUser = ref('')
const saving = ref(false)
const accounts = ref<any[]>([])
const selectedAccount = ref('')
const activeAccount = ref('')
const activeAccountLabel = ref('')
const accountLoading = ref(false)
const accountHint = ref('')
const restartRequired = ref(false)
const restarting = ref(false)
const uiaDiagnosing = ref(false)
const uiaDialogVisible = ref(false)
const uiaDiagnosis = ref<any>(null)

function roomName(id: string) {
  const found = allChatrooms.value.find((r: any) => r.room_id === id)
  if (!found) return id
  return found.name && found.name !== found.room_id ? found.name : found.room_id
}

function userName(id: string) {
  const found = allContacts.value.find((c: any) => c.wxid === id)
  if (!found) return id
  return found.nickname || found.remark || found.alias || id
}

function matchRoom(keyword: string, room: any) {
  const kw = keyword.toLowerCase()
  return (room.name || '').toLowerCase().includes(kw) ||
    (room.room_id || '').toLowerCase().includes(kw)
}

function matchContact(keyword: string, c: any) {
  const kw = keyword.toLowerCase()
  return (c.nickname || '').toLowerCase().includes(kw) ||
    (c.remark || '').toLowerCase().includes(kw) ||
    (c.alias || '').toLowerCase().includes(kw) ||
    (c.wxid || '').toLowerCase().includes(kw)
}

let searchTimer: ReturnType<typeof setTimeout> | null = null

function filterRooms(keyword: string) {
  if (!keyword) { filteredRooms.value = []; return }
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(async () => {
    try {
      const res = await searchChatrooms(keyword)
      filteredRooms.value = (res.data?.chatrooms || []).slice(0, 50)
    } catch {
      filteredRooms.value = allChatrooms.value
        .filter((r: any) => matchRoom(keyword, r))
        .slice(0, 50)
    }
  }, 300)
}

function filterContacts(keyword: string) {
  if (!keyword) { filteredContacts.value = []; return }
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(async () => {
    try {
      const res = await searchContactsApi(keyword)
      filteredContacts.value = (res.data?.contacts || []).slice(0, 50)
    } catch {
      filteredContacts.value = allContacts.value
        .filter((c: any) => matchContact(keyword, c))
        .slice(0, 50)
    }
  }, 300)
}

function addRoom(roomId: string) {
  if (roomId && !form.group_whitelist.includes(roomId)) {
    form.group_whitelist.push(roomId)
  }
  selectedRoom.value = ''
  filteredRooms.value = []
}

function removeRoom(room: string) {
  form.group_whitelist = form.group_whitelist.filter((r: string) => r !== room)
}

function addUser(wxid: string) {
  if (wxid && !form.private_whitelist.includes(wxid)) {
    form.private_whitelist.push(wxid)
  }
  selectedUser.value = ''
  filteredContacts.value = []
}

function removeUser(user: string) {
  form.private_whitelist = form.private_whitelist.filter((u: string) => u !== user)
}

async function changeAccount(wxid: string) {
  accountLoading.value = true
  accountHint.value = ''
  try {
    const res = await selectWechatAccount(wxid || '')
    if (res.data?.success) {
      accountHint.value = '账号已保存，请重启后端后切换数据库和微信窗口。'
      restartRequired.value = true
      ElMessage.success('工作账号已保存')
    } else {
      ElMessage.error(res.data?.error || '账号切换失败')
    }
  } catch {
    accountHint.value = ''
  } finally {
    accountLoading.value = false
  }
}

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

async function restartBackendNow() {
  try {
    await ElMessageBox.confirm(
      '后端会短暂断开并重新加载账号、数据库和自动回复流水线，确定继续吗？',
      '确认重启后端',
      { type: 'warning', confirmButtonText: '立即重启', cancelButtonText: '取消' },
    )
  } catch {
    return
  }

  restarting.value = true
  try {
    await restartBackendApi()
    ElMessage.info('后端正在重启，正在等待服务恢复…')

    const deadline = Date.now() + 60000
    let ready = false
    while (Date.now() < deadline) {
      await sleep(1000)
      try {
        const health = await getHealth()
        if (health.data?.status === 'ok') {
          ready = true
          break
        }
      } catch {
        // 服务重启期间请求失败是预期状态，继续轮询。
      }
    }

    if (!ready) {
      throw new Error('后端超过 60 秒仍未恢复，请检查启动窗口或日志')
    }

    ElMessage.success('后端已重启，正在刷新账号状态')
    window.location.reload()
  } catch (error: any) {
    ElMessage.error(error?.message || '后端重启失败')
  } finally {
    restarting.value = false
  }
}

function controlSummary(control: any) {
  if (!control) return '未发现'
  const patterns = Object.entries(control.patterns || {})
    .filter(([, available]) => Boolean(available))
    .map(([name]) => name)
  const name = control.name || '无名称'
  return patterns.length ? `${name} · ${patterns.join('、')}` : `${name} · 未发现可用模式`
}

async function diagnoseUiaNow() {
  uiaDiagnosing.value = true
  uiaDialogVisible.value = true
  try {
    const res = await diagnoseUia()
    uiaDiagnosis.value = res.data || {}
    if (uiaDiagnosis.value.uia_available) {
      ElMessage.success('UIA 检测完成')
    } else {
      ElMessage.warning(uiaDiagnosis.value.error || '未找到可用的 UIA 控件树')
    }
  } catch (error: any) {
    uiaDiagnosis.value = { uia_available: false, error: error?.message || 'UIA 检测失败' }
    ElMessage.error(uiaDiagnosis.value.error)
  } finally {
    uiaDiagnosing.value = false
  }
}

function accountLabel(account: any) {
  const flags: string[] = []
  if (account.active) flags.push('当前运行')
  if (account.selected) flags.push('配置中')
  const name = account.nickname || account.alias || account.base_wxid || account.wxid
  const identity = account.alias ? `微信号：${account.alias}` : `wxid：${account.base_wxid || account.wxid}`
  const suffix = flags.length ? `，${flags.join('、')}` : ''
  return `${name}（${identity}${suffix}）`
}

onMounted(async () => {
  try {
    const res = await getChatConfig()
    if (res.data) Object.assign(form, res.data)
  } catch {
    ElMessage.error('加载配置失败')
  }

  try {
    const res = await getWechatAccounts()
    accounts.value = res.data?.accounts || []
    const active = res.data?.active || ''
    activeAccount.value = active
    selectedAccount.value = res.data?.selected || active || ''
    restartRequired.value = Boolean(selectedAccount.value && selectedAccount.value !== active)
    const activeInfo = accounts.value.find((account: any) => account.active)
    if (activeInfo) {
      activeAccountLabel.value = accountLabel(activeInfo)
      accountHint.value = `当前运行账号：${accountLabel(activeInfo)}`
    } else if (active) {
      activeAccountLabel.value = active
      accountHint.value = `当前运行账号：${active}`
    }
  } catch {}

  try {
    const res = await getContacts('all')
    if (res.data.error) {
      ElMessage.warning(res.data.error)
    }
    allChatrooms.value = res.data.chatrooms || []
    allContacts.value = res.data.contacts || []
  } catch {
    ElMessage.error('加载联系人列表失败，请确认后端服务已启动')
  }
})

async function saveConfig() {
  saving.value = true
  try {
    await updateChatConfig(form)
    ElMessage.success('配置已保存')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.restart-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
  color: #909399;
  font-size: 12px;
  line-height: 1.5;
}

.uia-descriptions {
  margin-top: 16px;
}

.uia-error {
  color: #f56c6c;
  word-break: break-word;
}

@media (max-width: 640px) {
  .restart-row {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
