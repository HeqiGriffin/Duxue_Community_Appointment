<script setup>
import { computed, onMounted, ref } from 'vue'
import AppShell from '../../components/AppShell.vue'
import { jsonApi } from '../../api/request.js'
import { WEEKDAYS, fmtDateTime, statusText } from '../../utils.js'

const data = ref(null)
const error = ref('')
const mode = ref('all')
const schedule = computed(() => data.value?.week_schedule || [])
const bookings = computed(() => data.value?.today_bookings || [])
const summary = computed(() => data.value?.weekly_summary || {})
async function load() { try { data.value = await jsonApi('/duty/print-data') } catch (e) { error.value = e.message } }
function printSection(which) { mode.value = which; setTimeout(() => { window.print(); mode.value = 'all' }, 30) }
onMounted(load)
</script>

<template>
  <AppShell title="一键打印中心">
    <div class="page-header no-print"><div><h2 class="page-title">打印调度中心</h2><p class="page-desc">网页已按 A4 打印优化，可直接调起浏览器打印组件。</p></div><button class="btn btn-secondary" @click="load">刷新数据</button></div>
    <div v-if="error" class="error no-print">{{ error }}</div>
    <div class="toolbar no-print"><button class="btn btn-primary" @click="printSection('schedule')">打印本周值班表</button><button class="btn btn-primary" @click="printSection('bookings')">打印今日预约清单</button><button class="btn btn-primary" @click="printSection('summary')">打印社区管理周报</button><button class="btn btn-ghost" @click="printSection('all')">全部打印</button></div>
    <div v-if="data" class="card print-area">
      <div v-show="mode==='all' || mode==='schedule'" class="print-section"><h2>笃学书院本周值班表</h2><div class="print-meta">生成时间：{{ fmtDateTime(data.generated_at) }}</div><div class="table-wrap"><table><thead><tr><th>星期</th><th>时间</th><th>值班班级</th></tr></thead><tbody><tr v-for="x in schedule" :key="`${x.weekday}-${x.start_hour}`"><td>{{ WEEKDAYS[x.weekday] }}</td><td>{{ x.start_hour }}:00–{{ x.end_hour }}:00</td><td>{{ x.class_name }}</td></tr></tbody></table></div></div>
      <div v-show="mode==='all' || mode==='bookings'" class="print-section"><h2>今日社区空间预约清单</h2><div class="print-meta">共 {{ bookings.length }} 条</div><div class="table-wrap"><table><thead><tr><th>房间</th><th>时间</th><th>申请人</th><th>班级</th><th>人数</th><th>用途</th><th>状态</th></tr></thead><tbody><tr v-for="b in bookings" :key="b.booking_id"><td>{{ b.room_code || '—' }}</td><td>{{ fmtDateTime(b.start_time) }} – {{ fmtDateTime(b.end_time) }}</td><td>{{ b.name }}</td><td>{{ b.class_name || '—' }}</td><td>{{ b.people_count }}</td><td>{{ b.purpose }}</td><td>{{ statusText[b.status] || b.status }}</td></tr></tbody></table></div></div>
      <div v-show="mode==='all' || mode==='summary'" class="print-section"><h2>社区管理周报</h2><div class="grid grid-3"><div class="card stat"><div class="stat-label">本周值班签到</div><div class="stat-value">{{ summary.duty_checkins || 0 }}</div></div><div class="card stat"><div class="stat-label">本周预约</div><div class="stat-value">{{ summary.bookings || 0 }}</div></div><div class="card stat"><div class="stat-label">本周违规</div><div class="stat-value">{{ summary.violations || 0 }}</div></div></div></div>
    </div>
  </AppShell>
</template>
