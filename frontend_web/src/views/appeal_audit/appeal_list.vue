<script setup>
import { computed, onMounted, ref } from 'vue'
import AppShell from '../../components/AppShell.vue'
import { jsonApi } from '../../api/request.js'
import { ROOM_CODES, fmtDateTime } from '../../utils.js'

const appeals = ref([])
const users = ref([])
const loading = ref(false)
const error = ref('')
const success = ref('')
const modal = ref(null)
const action = ref('approve')
const comment = ref('')
const roomCode = ref('')
const userMap = computed(() => Object.fromEntries(users.value.map(x => [x.id, x])))

async function load() {
  loading.value = true; error.value = ''
  try {
    const [a, u] = await Promise.all([jsonApi('/appeals/admin/pending?limit=200'), jsonApi('/auth/admin/users?limit=500')])
    appeals.value = a; users.value = u
  } catch (e) { error.value = e.message } finally { loading.value = false }
}
function open(item) {
  modal.value = item
  action.value = 'approve'
  comment.value = ''
  roomCode.value = item.requested_room_code || ''
}
async function submit() {
  try {
    const isBooking = modal.value.appeal_type === 'booking_review'
    await jsonApi(`/appeals/admin/${modal.value.id}/review`, {
      method: 'POST',
      body: {
        action: action.value,
        comment: comment.value || (action.value === 'approve'
          ? (isBooking ? '人工复核通过' : '申诉通过，恢复账号权限')
          : '申诉材料不足'),
        room_code: isBooking && action.value === 'approve' ? (roomCode.value || null) : null,
      }
    })
    success.value = `申诉 #${modal.value.id} 已处理`; modal.value = null; await load()
  } catch (e) { error.value = e.message }
}
onMounted(load)
</script>

<template>
  <AppShell title="申诉处理中心">
    <div class="page-header"><div><h2 class="page-title">待处理申诉</h2><p class="page-desc">统一处理账号解封申诉与 AI 驳回预约的人工复核。</p></div><button class="btn btn-secondary" @click="load">刷新</button></div>
    <div v-if="error" class="error">{{ error }}</div><div v-if="success" class="success">{{ success }}</div>
    <div class="card card-pad"><div class="table-wrap"><table><thead><tr><th>ID</th><th>类型</th><th>学生</th><th>关联预约</th><th>申请时间</th><th>情况说明</th><th>操作</th></tr></thead><tbody>
      <tr v-for="a in appeals" :key="a.id">
        <td>#{{ a.id }}</td>
        <td><span class="badge" :class="a.appeal_type === 'booking_review' ? 'blue' : 'orange'">{{ a.appeal_type === 'booking_review' ? '预约复核' : '账号解封' }}</span></td>
        <td><strong>{{ userMap[a.user_id]?.name || `用户${a.user_id}` }}</strong><br><span class="muted">{{ userMap[a.user_id]?.login_id || '' }} {{ userMap[a.user_id]?.class_name || '' }}</span></td>
        <td><template v-if="a.booking_id">#{{ a.booking_id }}<br><span class="muted">{{ a.booking_purpose || '' }}</span><br><span class="muted">用户选择：{{ a.requested_room_code || '—' }}</span></template><span v-else>—</span></td>
        <td>{{ fmtDateTime(a.created_at) }}</td><td class="purpose">{{ a.statement }}</td><td><button class="btn btn-secondary" @click="open(a)">审核</button></td>
      </tr>
    </tbody></table><div v-if="!appeals.length && !loading" class="empty">目前没有待处理申诉</div></div></div>

    <div v-if="modal" class="modal-backdrop" @click.self="modal=null"><div class="modal"><div class="modal-head"><h3>审核{{ modal.appeal_type === 'booking_review' ? '预约复核' : '解封申诉' }} #{{ modal.id }}</h3><button class="btn btn-ghost" @click="modal=null">关闭</button></div><div class="modal-body">
      <p v-if="modal.booking_purpose"><strong>原预约用途：</strong>{{ modal.booking_purpose }}</p>
      <p><strong>情况说明：</strong>{{ modal.statement }}</p>
      <div class="form-grid">
        <div class="field"><label class="label">处理结果</label><select v-model="action" class="select" style="width:100%"><option value="approve">{{ modal.appeal_type === 'booking_review' ? '通过复核并锁房' : '通过并解冻' }}</option><option value="reject">驳回</option></select></div>
        <div class="field" v-if="modal.appeal_type === 'booking_review' && action === 'approve'"><label class="label">房间</label><select v-model="roomCode" class="select" style="width:100%"><option value="">按用户原选择</option><option v-for="r in ROOM_CODES" :key="r" :value="r">{{ r }}</option></select></div>
        <div class="field wide"><label class="label">管理员处理意见</label><textarea v-model="comment" class="textarea"></textarea></div>
      </div>
      <div class="modal-actions"><button class="btn btn-primary" @click="submit">提交处理结果</button></div>
    </div></div></div>
  </AppShell>
</template>
