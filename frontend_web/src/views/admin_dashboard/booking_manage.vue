<script setup>
import { computed, onMounted, ref } from 'vue'
import AppShell from '../../components/AppShell.vue'
import { blobApi, jsonApi, qs } from '../../api/request.js'
import { ROOM_CODES, fmtDateTime, statusText, toApiDateTime } from '../../utils.js'

const tab = ref('bookings')
const loading = ref(false)
const error = ref('')
const success = ref('')
const bookings = ref([])
const total = ref(0)
const statusFilter = ref('')
const users = ref([])
const userKeyword = ref('')
const cleanupItems = ref([])
const modal = ref(null)
const review = ref({ action: 'approve', room_code: '', reason: '' })
const superForm = ref({ user_id: '', room_code: 'A101', start_time: '', end_time: '', people_count: 1, purpose: '' })
const userAction = ref({ action: 'freeze', reason: '' })
const photoUrl = ref('')

const userMap = computed(() => Object.fromEntries(users.value.map(x => [x.id, x])))
const pendingCount = computed(() => bookings.value.filter(x => x.status === 'pending_manual').length)
const violationCount = computed(() => bookings.value.filter(x => x.is_violation).length)

function badgeClass(status) {
  if (['approved', 'active', 'completed', 'admin_pass', 'auto_pass', 'normal'].includes(status)) return 'green'
  if (['rejected', 'invalidated', 'admin_reject', 'frozen'].includes(status)) return 'red'
  if (['pending_manual', 'pending_ai', 'awaiting_cleanup', 'manual_required'].includes(status)) return 'orange'
  return 'gray'
}

async function loadBookings() {
  loading.value = true; error.value = ''
  try {
    const data = await jsonApi(`/bookings/admin/all${qs({ status: statusFilter.value, limit: 200 })}`)
    bookings.value = data.items; total.value = data.total
  } catch (e) { error.value = e.message } finally { loading.value = false }
}

async function loadUsers() {
  try { users.value = await jsonApi(`/auth/admin/users${qs({ q: userKeyword.value, limit: 500 })}`) }
  catch (e) { error.value = e.message }
}

async function loadCleanup() {
  try { cleanupItems.value = await jsonApi('/cleanup/admin/pending') }
  catch (e) { error.value = e.message }
}

async function refreshAll() { await Promise.all([loadBookings(), loadUsers(), loadCleanup()]) }

function openReview(item) {
  review.value = { action: 'approve', room_code: item.candidate_rooms?.[0] || '', reason: '' }
  modal.value = { type: 'review', item }
}

async function submitReview() {
  const item = modal.value.item
  try {
    await jsonApi(`/bookings/admin/${item.id}/review`, { method: 'POST', body: review.value })
    modal.value = null; success.value = `预约 #${item.id} 已处理`; await loadBookings()
  } catch (e) { error.value = e.message }
}

async function createSuperBooking() {
  try {
    await jsonApi('/bookings/admin/super', {
      method: 'POST', body: {
        ...superForm.value,
        user_id: Number(superForm.value.user_id),
        people_count: Number(superForm.value.people_count),
        start_time: toApiDateTime(superForm.value.start_time),
        end_time: toApiDateTime(superForm.value.end_time),
      },
    })
    modal.value = null; success.value = '超级预约创建成功'; await loadBookings()
  } catch (e) { error.value = e.message }
}

function openUserStatus(user) {
  userAction.value = { action: user.account_status === 'frozen' ? 'unfreeze' : 'freeze', reason: '' }
  modal.value = { type: 'user', item: user }
}

async function submitUserStatus() {
  const item = modal.value.item
  try {
    await jsonApi(`/auth/admin/users/${item.id}/status`, { method: 'POST', body: userAction.value })
    modal.value = null; success.value = `${item.name} 的账号状态已更新`; await loadUsers()
  } catch (e) { error.value = e.message }
}

async function openPhoto(item) {
  try {
    if (photoUrl.value) URL.revokeObjectURL(photoUrl.value)
    const { blob } = await blobApi(`/cleanup/admin/${item.booking_id}/photo`)
    photoUrl.value = URL.createObjectURL(blob)
    modal.value = { type: 'cleanup', item }
  } catch (e) { error.value = e.message }
}

async function reviewCleanup(action) {
  const item = modal.value.item
  const comment = prompt(action === 'pass' ? '核验备注（可填写“现场清理符合要求”）' : '请输入违规/不合格原因')
  if (comment === null) return
  try {
    await jsonApi(`/cleanup/admin/${item.booking_id}/review`, { method: 'POST', body: { action, comment: comment || '管理员人工核验' } })
    modal.value = null; success.value = `预约 #${item.booking_id} 清扫核验已处理`; await Promise.all([loadCleanup(), loadUsers(), loadBookings()])
  } catch (e) { error.value = e.message }
}

onMounted(refreshAll)
</script>

<template>
  <AppShell title="预约 / 违规管理">
    <div class="page-header">
      <div><h2 class="page-title">预约审批中心</h2><p class="page-desc">AI 存疑订单人工判定、超级预约、清扫核验与用户冻结管理。</p></div>
      <button class="btn btn-primary" @click="modal = { type: 'super' }">＋ 超级预约</button>
    </div>

    <div class="grid grid-4" style="margin-bottom:16px">
      <div class="card stat"><div class="stat-label">预约记录</div><div class="stat-value">{{ total }}</div></div>
      <div class="card stat"><div class="stat-label">当前页待人工审核</div><div class="stat-value">{{ pendingCount }}</div></div>
      <div class="card stat"><div class="stat-label">待人工清扫核验</div><div class="stat-value">{{ cleanupItems.length }}</div></div>
      <div class="card stat"><div class="stat-label">当前页违规记录</div><div class="stat-value">{{ violationCount }}</div></div>
    </div>

    <div v-if="error" class="error">{{ error }}</div>
    <div v-if="success" class="success">{{ success }}</div>
    <div class="toolbar">
      <button class="btn" :class="tab === 'bookings' ? 'btn-primary' : 'btn-ghost'" @click="tab='bookings'">预约订单</button>
      <button class="btn" :class="tab === 'cleanup' ? 'btn-primary' : 'btn-ghost'" @click="tab='cleanup'">清扫核验</button>
      <button class="btn" :class="tab === 'users' ? 'btn-primary' : 'btn-ghost'" @click="tab='users'">用户权限</button>
    </div>

    <div v-if="tab === 'bookings'" class="card card-pad">
      <div class="toolbar">
        <select v-model="statusFilter" class="select" @change="loadBookings">
          <option value="">全部状态</option><option value="pending_manual">待人工审核</option><option value="approved">已通过</option><option value="active">使用中</option><option value="awaiting_cleanup">待清扫</option><option value="completed">已完结</option><option value="rejected">已驳回</option><option value="invalidated">资源冲突失效</option><option value="cancelled">已取消</option>
        </select>
        <button class="btn btn-secondary" @click="loadBookings">刷新</button>
        <span v-if="loading" class="loading">加载中…</span>
      </div>
      <div class="table-wrap">
        <table><thead><tr><th>ID</th><th>申请人</th><th>时间 / 房间</th><th>人数</th><th>自然语言用途</th><th>AI判断</th><th>状态</th><th>操作</th></tr></thead>
        <tbody><tr v-for="b in bookings" :key="b.id">
          <td>#{{ b.id }}</td>
          <td><strong>{{ userMap[b.user_id]?.name || `用户${b.user_id}` }}</strong><br><span class="muted">{{ userMap[b.user_id]?.login_id || '' }} {{ userMap[b.user_id]?.class_name || '' }}</span></td>
          <td>{{ fmtDateTime(b.start_time) }}<br>至 {{ fmtDateTime(b.end_time) }}<br><span class="badge blue">{{ b.room_code || '待分配' }}</span></td>
          <td>{{ b.people_count }}</td>
          <td class="purpose">{{ b.purpose }}</td>
          <td><span>{{ b.intent_type || '—' }}</span><br><span class="muted">{{ b.ai_reason || b.ai_guidance || '—' }}</span></td>
          <td><span class="badge" :class="badgeClass(b.status)">{{ statusText[b.status] || b.status }}</span><br><span v-if="b.is_violation" class="badge red" style="margin-top:6px">违规：{{ b.violation_reason || '已标记' }}</span><br><span v-if="b.cleanup_review_status" class="badge gray" style="margin-top:6px">{{ statusText[b.cleanup_review_status] || b.cleanup_review_status }}</span></td>
          <td><div class="actions"><button v-if="b.status==='pending_manual'" class="btn btn-secondary" @click="openReview(b)">审核</button></div></td>
        </tr></tbody></table>
        <div v-if="!bookings.length && !loading" class="empty">暂无预约记录</div>
      </div>
    </div>

    <div v-if="tab === 'cleanup'" class="card card-pad">
      <div class="toolbar"><button class="btn btn-secondary" @click="loadCleanup">刷新待核验</button></div>
      <div class="table-wrap"><table><thead><tr><th>预约</th><th>用户</th><th>房间</th><th>OCR结果</th><th>状态</th><th>操作</th></tr></thead>
        <tbody><tr v-for="x in cleanupItems" :key="x.booking_id"><td>#{{ x.booking_id }}</td><td>{{ x.name }}<br><span class="muted">{{ x.login_id }}</span></td><td>{{ x.room_code || '—' }}</td><td class="purpose">{{ x.ocr_result || '—' }}</td><td><span class="badge orange">{{ statusText[x.review_status] || x.review_status }}</span></td><td><button class="btn btn-secondary" @click="openPhoto(x)">查看照片</button></td></tr></tbody>
      </table><div v-if="!cleanupItems.length" class="empty">没有待人工核验的离场照片</div></div>
    </div>

    <div v-if="tab === 'users'" class="card card-pad">
      <div class="toolbar"><input v-model="userKeyword" class="input" placeholder="姓名 / 学号 / 班级" @keyup.enter="loadUsers"><button class="btn btn-secondary" @click="loadUsers">搜索</button></div>
      <div class="table-wrap"><table><thead><tr><th>用户</th><th>班级</th><th>角色</th><th>状态</th><th>冻结原因</th><th>操作</th></tr></thead><tbody>
        <tr v-for="u in users" :key="u.id"><td><strong>{{ u.name }}</strong><br><span class="muted">{{ u.login_id }}</span></td><td>{{ u.class_name || '—' }}</td><td>{{ u.role === 'admin' ? '管理员' : '学生' }}</td><td><span class="badge" :class="badgeClass(u.account_status)">{{ statusText[u.account_status] }}</span></td><td class="purpose">{{ u.frozen_reason || '—' }}</td><td><button v-if="u.role==='student'" class="btn" :class="u.account_status==='frozen' ? 'btn-secondary' : 'btn-danger'" @click="openUserStatus(u)">{{ u.account_status==='frozen' ? '解除冻结' : '冻结账号' }}</button><span v-else class="muted">管理员账号</span></td></tr>
      </tbody></table></div>
    </div>

    <div v-if="modal" class="modal-backdrop" @click.self="modal=null">
      <div class="modal">
        <div class="modal-head"><h3>{{ modal.type==='review' ? `审核预约 #${modal.item.id}` : modal.type==='super' ? '创建超级预约' : modal.type==='cleanup' ? `清扫核验 #${modal.item.booking_id}` : '修改用户状态' }}</h3><button class="btn btn-ghost" @click="modal=null">关闭</button></div>
        <div class="modal-body">
          <template v-if="modal.type==='review'">
            <div class="form-grid"><div class="field"><label class="label">处理动作</label><select v-model="review.action" class="select" style="width:100%"><option value="approve">通过并锁房</option><option value="reject">驳回</option></select></div><div class="field" v-if="review.action==='approve'"><label class="label">指定房间（可留空按 AI 顺序）</label><select v-model="review.room_code" class="select" style="width:100%"><option value="">自动选择</option><option v-for="r in ROOM_CODES" :key="r">{{ r }}</option></select></div><div class="field wide"><label class="label">处理说明</label><textarea v-model="review.reason" class="textarea" placeholder="说明审批依据或驳回原因"></textarea></div></div>
            <div class="modal-actions"><button class="btn btn-primary" @click="submitReview">确认处理</button></div>
          </template>
          <template v-else-if="modal.type==='super'">
            <div class="form-grid">
              <div class="field"><label class="label">预约用户</label><select v-model="superForm.user_id" class="select" style="width:100%"><option value="">请选择</option><option v-for="u in users.filter(x=>x.role==='student')" :key="u.id" :value="u.id">{{ u.name }}（{{ u.login_id }} / {{ u.class_name || '无班级' }}）</option></select></div>
              <div class="field"><label class="label">房间</label><select v-model="superForm.room_code" class="select" style="width:100%"><option v-for="r in ROOM_CODES" :key="r">{{ r }}</option></select></div>
              <div class="field"><label class="label">开始时间</label><input v-model="superForm.start_time" type="datetime-local" step="1800" class="input" style="width:100%"></div>
              <div class="field"><label class="label">结束时间</label><input v-model="superForm.end_time" type="datetime-local" step="1800" class="input" style="width:100%"></div>
              <div class="field"><label class="label">人数</label><input v-model.number="superForm.people_count" type="number" min="1" max="500" class="input" style="width:100%"></div>
              <div class="field wide"><label class="label">用途</label><textarea v-model="superForm.purpose" class="textarea" placeholder="管理员超级预约用途"></textarea></div>
            </div><div class="modal-actions"><button class="btn btn-primary" :disabled="!superForm.user_id || !superForm.start_time || !superForm.end_time || !superForm.purpose" @click="createSuperBooking">创建并直接锁定</button></div>
          </template>
          <template v-else-if="modal.type==='cleanup'">
            <img v-if="photoUrl" :src="photoUrl" alt="离场清扫照片" style="max-width:100%;max-height:55vh;display:block;margin:auto;border-radius:12px">
            <p class="muted">OCR：{{ modal.item.ocr_result || '无结果' }}</p><div class="modal-actions"><button class="btn btn-danger" @click="reviewCleanup('reject')">判定不合格并冻结</button><button class="btn btn-primary" @click="reviewCleanup('pass')">通过核验</button></div>
          </template>
          <template v-else>
            <p>用户：<strong>{{ modal.item.name }}</strong>（{{ modal.item.login_id }}）</p>
            <div class="field"><label class="label">动作</label><select v-model="userAction.action" class="select"><option value="freeze">冻结</option><option value="unfreeze">解除冻结</option></select></div>
            <div class="field" style="margin-top:14px" v-if="userAction.action==='freeze'"><label class="label">原因</label><textarea v-model="userAction.reason" class="textarea"></textarea></div>
            <div class="modal-actions"><button class="btn btn-primary" @click="submitUserStatus">确认</button></div>
          </template>
        </div>
      </div>
    </div>
  </AppShell>
</template>
