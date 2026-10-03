<script setup>
import { onMounted, ref } from 'vue'
import AppShell from '../../components/AppShell.vue'
import { getSession, jsonApi } from '../../api/request.js'
import { SHIFTS, WEEKDAYS, fmtDateTime } from '../../utils.js'

const session = getSession() || {}
const schedule = ref([])
const log = ref(null)
const note = ref('')
const error = ref('')
const success = ref('')
const loading = ref(false)

async function load() {
  try { schedule.value = await jsonApi('/duty/schedule') } catch (e) { error.value = e.message }
}
async function checkin() {
  loading.value = true; error.value = ''; success.value = ''
  try { log.value = await jsonApi('/duty/checkin', { method: 'POST' }); success.value = '值班签到成功，系统已记录实名上岗时间' }
  catch (e) { error.value = e.message } finally { loading.value = false }
}
async function handover() {
  if (!log.value) return
  try { log.value = await jsonApi(`/duty/handover/${log.value.id}`, { method: 'POST', body: { note: note.value } }); success.value = '交接班日志已保存' }
  catch (e) { error.value = e.message }
}
onMounted(load)
</script>

<template>
  <AppShell title="交接班与日志">
    <div class="page-header"><div><h2 class="page-title">实名值班签到</h2><p class="page-desc">学生必须从已绑定的值班电脑进入；后台按当前班次核对学生班级与排班表。</p></div></div>
    <div v-if="error" class="error">{{ error }}</div><div v-if="success" class="success">{{ success }}</div>
    <div class="grid grid-2">
      <div class="card card-pad">
        <h3 style="margin-top:0">当前值班员</h3><p><strong>{{ session.name }}</strong>（{{ session.login_id }}）</p>
        <template v-if="session.role==='admin'"><div class="muted">管理员可查看值班工作台，但无需执行学生值班签到。</div></template>
        <template v-else-if="!log"><button class="btn btn-primary" :disabled="loading" @click="checkin">签到上岗</button></template>
        <template v-else><div class="success">已签到：{{ fmtDateTime(log.checkin_at) }} · {{ String(log.start_hour).padStart(2,'0') }}:00–{{ String(log.start_hour+2).padStart(2,'0') }}:00</div><div class="field"><label class="label">交接班日志</label><textarea v-model="note" class="textarea" placeholder="记录巡查情况、异常房间、待后续处理事项"></textarea></div><button class="btn btn-primary" :disabled="!note.trim()" @click="handover">保存交接日志</button></template>
      </div>
      <div class="card card-pad"><h3 style="margin-top:0">本周排班</h3><div class="table-wrap"><table><thead><tr><th>星期</th><th>班次</th><th>值班班级</th></tr></thead><tbody><tr v-for="x in schedule" :key="`${x.weekday}-${x.start_hour}`"><td>{{ WEEKDAYS[x.weekday] }}</td><td>{{ String(x.start_hour).padStart(2,'0') }}:00–{{ String(x.start_hour+2).padStart(2,'0') }}:00</td><td>{{ x.class_name }}</td></tr></tbody></table></div></div>
    </div>
  </AppShell>
</template>
