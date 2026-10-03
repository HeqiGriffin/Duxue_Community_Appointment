<script setup>
import { onMounted, reactive, ref } from 'vue'
import AppShell from '../../components/AppShell.vue'
import { jsonApi } from '../../api/request.js'
import { SHIFTS, WEEKDAYS } from '../../utils.js'

const loading = ref(false)
const error = ref('')
const success = ref('')
const schedule = reactive({})

for (let d = 0; d < 7; d++) for (const h of SHIFTS) schedule[`${d}-${h}`] = ''

async function load() {
  loading.value = true; error.value = ''
  try {
    const rows = await jsonApi('/duty/schedule')
    for (let d = 0; d < 7; d++) for (const h of SHIFTS) schedule[`${d}-${h}`] = ''
    for (const row of rows) schedule[`${row.weekday}-${row.start_hour}`] = row.class_name
  } catch (e) { error.value = e.message } finally { loading.value = false }
}

async function save() {
  const items = []
  for (let d = 0; d < 7; d++) {
    for (const h of SHIFTS) {
      const className = schedule[`${d}-${h}`].trim()
      if (className) items.push({ weekday: d, start_hour: h, class_name: className })
    }
  }
  if (!items.length) { error.value = '排班表不能为空'; return }
  loading.value = true; error.value = ''; success.value = ''
  try { await jsonApi('/duty/admin/schedule', { method: 'PUT', body: items }); success.value = `排班表已下发，共 ${items.length} 个班次` }
  catch (e) { error.value = e.message } finally { loading.value = false }
}

onMounted(load)
</script>

<template>
  <AppShell title="值班排班管理">
    <div class="page-header"><div><h2 class="page-title">每周值班排班表</h2><p class="page-desc">08:00–22:00，每两小时一班。保存时以当前表格完整替换后台周排班。</p></div><div class="actions"><button class="btn btn-ghost" @click="load">恢复服务器数据</button><button class="btn btn-primary" :disabled="loading" @click="save">保存并下发</button></div></div>
    <div v-if="error" class="error">{{ error }}</div><div v-if="success" class="success">{{ success }}</div>
    <div class="card card-pad">
      <div class="table-wrap schedule-table"><table><thead><tr><th>班次</th><th v-for="(d,i) in WEEKDAYS" :key="i">{{ d }}</th></tr></thead><tbody>
        <tr v-for="h in SHIFTS" :key="h"><th>{{ String(h).padStart(2,'0') }}:00–{{ String(h+2).padStart(2,'0') }}:00</th><td v-for="(_,d) in WEEKDAYS" :key="d" class="schedule-cell"><input v-model="schedule[`${d}-${h}`]" class="input" placeholder="值班班级"></td></tr>
      </tbody></table></div>
      <p class="muted" style="margin-bottom:0">留空代表该班次不排班。值班学生登录公用电脑后，系统会核对其班级是否与当前班次一致。</p>
    </div>
  </AppShell>
</template>
