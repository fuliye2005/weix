<template>
  <div>
    <h2>消息日志</h2>
    <el-card style="margin-bottom: 16px">
      <el-form :inline="true" :model="filter" label-width="80px">
        <el-form-item label="群聊">
          <el-input v-model="filter.room_id" placeholder="群聊ID" clearable />
        </el-form-item>
        <el-form-item label="用户">
          <el-input v-model="filter.user_id" placeholder="wxid" clearable />
        </el-form-item>
        <el-form-item label="方向">
          <el-select v-model="filter.direction" placeholder="全部" clearable style="width: 120px">
            <el-option label="收到" value="inbound" />
            <el-option label="发出" value="outbound" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="filter.status" placeholder="全部" clearable style="width: 150px">
            <el-option label="已收到" value="received" />
            <el-option label="已生成" value="generated" />
            <el-option label="发送中" value="sending" />
            <el-option label="已发送" value="sent" />
            <el-option label="待验证" value="pending_verify" />
            <el-option label="失败" value="failed" />
            <el-option label="跳过" value="skipped" />
          </el-select>
        </el-form-item>
        <el-form-item label="时间范围">
          <el-date-picker
            v-model="filter.dateRange"
            type="daterange"
            range-separator="至"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            value-format="YYYY-MM-DD"
            style="width: 300px"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="loadMessages">查询</el-button>
          <el-button @click="resetFilter">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-table :data="messages" stripe v-loading="loading" border style="width: 100%">
      <el-table-column prop="msg_id" label="消息ID" width="180" show-overflow-tooltip />
      <el-table-column label="方向" width="80">
        <template #default="{ row }">
          <el-tag size="small" :type="row.direction === 'outbound' ? 'warning' : 'info'">
            {{ directionLabel(row.direction) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="105">
        <template #default="{ row }">
          <el-tag size="small" :type="statusType(row.status)">
            {{ statusLabel(row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="发送者/对象" width="150" show-overflow-tooltip>
        <template #default="{ row }">
          {{ senderLabel(row) }}
        </template>
      </el-table-column>
      <el-table-column label="会话" width="150" show-overflow-tooltip>
        <template #default="{ row }">
          {{ conversationLabel(row) }}
        </template>
      </el-table-column>
      <el-table-column prop="send_method" label="发送方式" width="125" show-overflow-tooltip />
      <el-table-column prop="reply_source" label="回复来源" width="95" />
      <el-table-column prop="error_code" label="错误码" width="150" show-overflow-tooltip />
      <el-table-column label="类型" width="80">
        <template #default="{ row }">
          <el-tag size="small">{{ typeLabel(row.msg_type) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="content" label="内容" show-overflow-tooltip min-width="300" />
      <el-table-column prop="create_time" label="时间" width="170" />
      <el-table-column label="操作" width="100">
        <template #default="{ row }">
          <el-button size="small" @click="viewDetail(row)">详情</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-model:current-page="pagination.page"
      :page-size="pagination.size"
      :total="pagination.total"
      layout="total, prev, pager, next"
      style="margin-top: 16px; justify-content: flex-end"
      @current-change="loadMessages"
    />

    <el-dialog title="消息详情" v-model="detailVisible" width="500px">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="消息ID">{{ detail.msg_id }}</el-descriptions-item>
        <el-descriptions-item label="发送者/对象">
          {{ senderLabel(detail) }}
          <span v-if="inboundSenderId(detail)"> ({{ inboundSenderId(detail) }})</span>
        </el-descriptions-item>
        <el-descriptions-item label="会话">{{ conversationLabel(detail) }}</el-descriptions-item>
        <el-descriptions-item label="群名">{{ detail.is_group ? (detail.room_name || detail.room_id || '-') : '-' }}</el-descriptions-item>
        <el-descriptions-item label="目标会话 ID">{{ detail.target_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="类型">{{ typeLabel(detail.msg_type) }}</el-descriptions-item>
        <el-descriptions-item label="方向">{{ directionLabel(detail.direction) }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ statusLabel(detail.status) }}</el-descriptions-item>
        <el-descriptions-item label="发送方式">{{ detail.send_method || '-' }}</el-descriptions-item>
        <el-descriptions-item label="回复来源">{{ detail.reply_source || '-' }}</el-descriptions-item>
        <el-descriptions-item label="尝试ID">{{ detail.attempt_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="关联消息">{{ detail.reply_to_msg_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="内容哈希">
          <span class="hash-value">{{ detail.content_hash || '-' }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="错误阶段">{{ detail.error_stage || '-' }}</el-descriptions-item>
        <el-descriptions-item label="错误码">{{ detail.error_code || '-' }}</el-descriptions-item>
        <el-descriptions-item label="错误原因">
          <div style="white-space: pre-wrap; max-height: 120px; overflow: auto">{{ detail.error_message || '-' }}</div>
        </el-descriptions-item>
        <el-descriptions-item label="时间">{{ detail.create_time }}</el-descriptions-item>
        <el-descriptions-item label="发送完成">{{ detail.sent_at || '-' }}</el-descriptions-item>
        <el-descriptions-item label="内容">
          <div style="white-space: pre-wrap; max-height: 200px; overflow: auto">{{ detail.content }}</div>
        </el-descriptions-item>
      </el-descriptions>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { getMessages } from '../api'

const messages = ref<any[]>([])
const loading = ref(false)
const detailVisible = ref(false)
const detail = ref<any>({})

const filter = reactive<any>({
  room_id: '',
  user_id: '',
  direction: '',
  status: '',
  dateRange: null,
})

const pagination = reactive({ page: 1, size: 20, total: 0 })

function typeLabel(type: number) {
  const map: Record<number, string> = { 1: '文本', 3: '图片', 34: '语音', 43: '视频', 49: '卡片', 10000: '系统' }
  return map[type] || '其他'
}

function directionLabel(direction: string) {
  return direction === 'outbound' ? '发出' : '收到'
}

function inboundSenderId(row: any) {
  if (!row || row.direction === 'outbound') return ''
  if (row.is_group && row.sender_wxid && row.sender_wxid === row.room_id) return ''
  return row.sender_wxid || ''
}

function senderLabel(row: any) {
  if (!row) return '-'
  if (row.direction === 'outbound') return row.target_name || row.target_id || '-'
  if (row.is_group && row.sender_wxid === row.room_id) return row.sender_name || '未知成员'
  return row.sender_name || inboundSenderId(row) || (row.is_group ? '未知成员' : '未知用户')
}

function conversationLabel(row: any) {
  if (!row) return '-'
  if (row.is_group) return row.room_name || row.target_name || row.room_id || row.target_id || '-'
  return row.target_name || row.room_name || row.target_id || row.room_id || '私聊'
}

function statusLabel(status: string) {
  const map: Record<string, string> = {
    received: '已收到',
    generated: '已生成',
    sending: '发送中',
    sent: '已发送',
    pending_verify: '待验证',
    failed: '失败',
    skipped: '跳过',
  }
  return map[status] || status || '未知'
}

function statusType(status: string) {
  if (status === 'sent' || status === 'received') return 'success'
  if (status === 'pending_verify' || status === 'sending') return 'warning'
  if (status === 'failed') return 'danger'
  if (status === 'skipped') return 'info'
  return ''
}

async function loadMessages() {
  loading.value = true
  try {
    const params: any = { page: pagination.page, size: pagination.size }
    if (filter.room_id) params.room_id = filter.room_id
    if (filter.user_id) params.user_id = filter.user_id
    if (filter.direction) params.direction = filter.direction
    if (filter.status) params.status = filter.status
    if (filter.dateRange) {
      params.start_date = filter.dateRange[0]
      params.end_date = filter.dateRange[1]
    }
    const res = await getMessages(params)
    messages.value = res.data.items || res.data
    pagination.total = res.data.total || 0
  } finally {
    loading.value = false
  }
}

function resetFilter() {
  filter.room_id = ''
  filter.user_id = ''
  filter.direction = ''
  filter.status = ''
  filter.dateRange = null
  pagination.page = 1
  loadMessages()
}

function viewDetail(row: any) {
  detail.value = row
  detailVisible.value = true
}

onMounted(loadMessages)
</script>

<style scoped>
.hash-value {
  word-break: break-all;
  font-family: monospace;
  font-size: 12px;
}
</style>
