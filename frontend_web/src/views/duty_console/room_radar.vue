<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import AppShell from '../../components/AppShell.vue'
import { jsonApi } from '../../api/request.js'
import { fmtDateTime } from '../../utils.js'

const rooms = ref([])
const loading = ref(false)
const error = ref('')
let timer = null

async function load() {
  loading.value = true; error.value = ''
  try { rooms.value = await jsonApi('/duty/rooms') }
  catch (e) { error.value = e.message } finally { loading.value = false }
}

async function markViolation(room) {
  const reason = prompt(`请输入 ${room.room_code} 的违规/清退原因`)
  if (!reason) return
  try { await jsonApi(`/duty/rooms/${room.room_code}/violation`, { method: 'POST', body: { reason } }); alert('已标记违规'); await load() }
  catch (e) { error.value = e.message }
}

onMounted(() => { load(); timer = setInterval(load, 15000) })
onBeforeUnmount(() => { if (timer) clearInterval(timer) })
</script>

<template>
  <AppShell title="实时房间雷达">
    <div class="page-header"><div><h2 class="page-title">当前空间应有状态</h2><p class="page-desc">每 15 秒自动刷新。值班巡查发现用途不符时，可对系统中当前在用预约直接标记违规。</p></div><button class="btn btn-secondary" @click="load">立即刷新</button></div>
    <div v-if="error" class="error">{{ error }}</div>
    <div class="room-grid"><div v-for="r in rooms" :key="r.room_code" class="card room" :class="{occupied:r.occupied}">
      <div class="room-code">{{ r.room_code }}</div><div class="room-status"><span class="badge" :class="r.occupied ? 'green' : 'gray'">{{ r.occupied ? '按预约在用' : '应为空闲' }}</span></div>
      <div v-if="r.occupied" class="room-detail"><strong>{{ r.user_name }}</strong> · {{ r.class_name || '未登记班级' }}<br>{{ r.purpose }}<br>{{ fmtDateTime(r.start_time) }} – {{ fmtDateTime(r.end_time) }}</div>
      <div v-else class="room-detail muted">当前无系统有效预约。若现场有人使用，应人工核查。</div>
      <button v-if="r.occupied" class="btn btn-danger" style="margin-top:12px" @click="markViolation(r)">标记违规 / 清退</button>
    </div></div>
    <div v-if="loading" class="loading" style="margin-top:12px">正在同步房间状态…</div>
  </AppShell>
</template>
