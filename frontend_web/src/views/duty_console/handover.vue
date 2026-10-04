<script setup>
import { onMounted, reactive, ref } from 'vue'
import AppShell from '../../components/AppShell.vue'
import { getSession, jsonApi } from '../../api/request.js'
import { WEEKDAYS, fmtDateTime } from '../../utils.js'

const session = getSession() || {}
const schedule = ref([])
const current = ref(null)
const note = ref('')
const error = ref('')
const success = ref('')
const loading = ref(false)
const forms = reactive({})

function initForms() {
  for (const p of current.value?.patrols || []) {
    if (!forms[p.id]) forms[p.id] = { booking_match_ok: true, hygiene_ok: true, safety_ok: true, order_ok: true, facility_ok: true, issue_note: '' }
  }
}
async function load() {
  error.value = ''
  try {
    const [s, c] = await Promise.all([jsonApi('/duty/schedule'), jsonApi('/duty/current')])
    schedule.value = s; current.value = c; note.value = c.log?.handover_note || ''; initForms()
  } catch (e) { error.value = e.message }
}
async function checkin() {
  loading.value = true; error.value = ''; success.value = ''
  try { current.value = await jsonApi('/duty/checkin', { method: 'POST' }); initForms(); success.value = '值班签到成功。请按计划完成两次社区巡视。' }
  catch (e) { error.value = e.message } finally { loading.value = false }
}
async function submitPatrol(p) {
  error.value = ''; success.value = ''
  try {
    const updated = await jsonApi(`/duty/patrols/${p.id}`, { method: 'POST', body: forms[p.id] })
    current.value.patrols = current.value.patrols.map(x => x.id === updated.id ? updated : x)
    success.value = `第 ${p.sequence} 次巡视已提交`
  } catch (e) { error.value = e.message }
}
async function handover() {
  if (!current.value?.log) return
  error.value = ''; success.value = ''
  try {
    const log = await jsonApi(`/duty/handover/${current.value.log.id}`, { method: 'POST', body: { note: note.value } })
    current.value.log = log; success.value = '交接班完成，本班次值班记录已闭环。'
  } catch (e) { error.value = e.message }
}
function timingText(p) {
  if (p.submitted_at) return p.timing_status === 'late' ? '已完成（迟交）' : '已完成'
  if (p.timing_status === 'not_open') return '未到巡视时间'
  if (p.timing_status === 'late') return '已超计划时间，请尽快补巡'
  return '当前应进行巡视'
}
function completeCount() { return (current.value?.patrols || []).filter(x => x.submitted_at).length }
onMounted(load)
</script>

<template>
  <AppShell title="值班任务与巡视">
    <div class="page-header"><div><h2 class="page-title">两小时值班闭环</h2><p class="page-desc">每班至少完成两次社区巡视：开班后 30 分钟、90 分钟各一次。异常项目必须填写说明，完成两次巡视后才能交接。</p></div><button class="btn btn-secondary" @click="load">刷新</button></div>
    <div v-if="error" class="error">{{ error }}</div><div v-if="success" class="success">{{ success }}</div>

    <div class="grid grid-2">
      <div class="card card-pad">
        <h3 style="margin-top:0">当前班次</h3>
        <template v-if="current">
          <p><strong>{{ String(current.start_hour).padStart(2,'0') }}:00–{{ String(current.end_hour).padStart(2,'0') }}:00</strong> · 应值班班级：{{ current.scheduled_class || '尚未配置' }}</p>
          <p class="muted">值班学生：{{ session.name }}（{{ session.login_id }}）</p>
          <template v-if="session.role==='admin'"><div class="muted">管理员可查看工作台，但不需要执行学生值班签到。</div></template>
          <template v-else-if="!current.log"><button class="btn btn-primary" :disabled="loading" @click="checkin">签到上岗并生成两次巡视任务</button></template>
          <template v-else>
            <div class="success">已签到：{{ fmtDateTime(current.log.checkin_at) }} · 巡视完成 {{ completeCount() }}/2</div>
            <div v-if="current.log.handover_at" class="success">本班次已于 {{ fmtDateTime(current.log.handover_at) }} 完成交接</div>
          </template>
        </template>
      </div>
      <div class="card card-pad"><h3 style="margin-top:0">本周排班</h3><div class="table-wrap"><table><thead><tr><th>星期</th><th>班次</th><th>值班班级</th></tr></thead><tbody><tr v-for="x in schedule" :key="`${x.weekday}-${x.start_hour}`"><td>{{ WEEKDAYS[x.weekday] }}</td><td>{{ String(x.start_hour).padStart(2,'0') }}:00–{{ String(x.start_hour+2).padStart(2,'0') }}:00</td><td>{{ x.class_name }}</td></tr></tbody></table></div></div>
    </div>

    <div v-if="current?.log" class="grid grid-2" style="margin-top:16px">
      <div v-for="p in current.patrols" :key="p.id" class="card card-pad">
        <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start">
          <div><h3 style="margin:0">第 {{ p.sequence }} 次社区巡视</h3><p class="muted">计划时间：{{ fmtDateTime(p.due_at) }}</p></div>
          <span class="badge" :class="p.submitted_at ? (p.timing_status==='late'?'orange':'green') : (p.can_submit?'orange':'gray')">{{ timingText(p) }}</span>
        </div>
        <template v-if="p.submitted_at">
          <p>提交：{{ fmtDateTime(p.submitted_at) }}</p><p class="muted">{{ p.issue_note || '无异常' }}</p>
        </template>
        <template v-else>
          <div class="check-grid">
            <label><input type="checkbox" v-model="forms[p.id].booking_match_ok"> 房间实际使用与预约记录一致</label>
            <label><input type="checkbox" v-model="forms[p.id].hygiene_ok"> 公共区域与房间卫生正常</label>
            <label><input type="checkbox" v-model="forms[p.id].safety_ok"> 消防、门窗等安全状态正常</label>
            <label><input type="checkbox" v-model="forms[p.id].order_ok"> 噪音与社区秩序正常</label>
            <label><input type="checkbox" v-model="forms[p.id].facility_ok"> 公共设施设备正常</label>
          </div>
          <div class="field" style="margin-top:14px"><label class="label">巡视说明 / 异常情况</label><textarea v-model="forms[p.id].issue_note" class="textarea" placeholder="正常可留空；任一项目异常时必须写明房间、人员、问题与处理情况"></textarea></div>
          <button class="btn btn-primary" :disabled="!p.can_submit" @click="submitPatrol(p)">提交本次巡视</button>
        </template>
      </div>
    </div>

    <div v-if="current?.log" class="card card-pad" style="margin-top:16px">
      <h3 style="margin-top:0">交接班反馈</h3>
      <p class="muted">两次巡视都完成后，记录本班次整体情况和需要下一班继续跟进的事项。</p>
      <textarea v-model="note" class="textarea" placeholder="例如：两次巡视均正常；A103 设备异常已报修；下一班继续关注……"></textarea>
      <button class="btn btn-primary" style="margin-top:12px" :disabled="completeCount()<2 || !note.trim() || current.log.handover_at" @click="handover">完成交接</button>
    </div>
  </AppShell>
</template>
