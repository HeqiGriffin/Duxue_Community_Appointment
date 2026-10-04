<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import AppShell from '../../components/AppShell.vue'
import { jsonApi } from '../../api/request.js'
import { fmtDateTime } from '../../utils.js'

const rooms = ref([])
const loading = ref(false)
const error = ref('')
let timer = null
async function load() { loading.value = true; error.value = ''; try { rooms.value = await jsonApi('/duty/rooms') } catch (e) { error.value = e.message } finally { loading.value = false } }
async function markViolation(booking) {
  const reason = prompt(`请输入预约 #${booking.booking_id}（${booking.user_name}）的违规/清退原因`)
  if (!reason) return
  try { await jsonApi(`/duty/bookings/${booking.booking_id}/violation`, { method: 'POST', body: { reason } }); alert('已标记违规'); await load() }
  catch (e) { error.value = e.message }
}
onMounted(() => { load(); timer = setInterval(load, 15000) })
onBeforeUnmount(() => { if (timer) clearInterval(timer) })
</script>

<template>
  <AppShell title="实时房间雷达">
    <div class="page-header"><div><h2 class="page-title">当前空间应有状态</h2><p class="page-desc">自习共享房会同时列出多名使用者；非自习仍为独占。每 15 秒自动刷新。</p></div><button class="btn btn-secondary" @click="load">立即刷新</button></div>
    <div v-if="error" class="error">{{ error }}</div>
    <div class="room-grid"><div v-for="r in rooms" :key="r.room_code" class="card room" :class="{occupied:r.occupied}">
      <div class="room-code">{{ r.room_code }}</div>
      <div class="room-status"><span class="badge" :class="r.occupied ? 'green' : 'gray'">{{ !r.occupied ? '应为空闲' : (r.occupancy_mode==='study_shared' ? `自习共享 · ${r.people_total} 人` : '非自习占用') }}</span></div>
      <div v-if="!r.occupied" class="room-detail muted">当前无系统有效预约。若现场有人使用，应人工核查。</div>
      <div v-else class="occupant-list">
        <div v-for="o in r.occupants" :key="o.booking_id" class="occupant-item">
          <strong>{{ o.user_name }}</strong> · {{ o.class_name || '未登记班级' }} · {{ o.people_count }} 人<br>
          <span>{{ o.purpose }}</span><br><span class="muted">{{ fmtDateTime(o.start_time) }} – {{ fmtDateTime(o.end_time) }}</span>
          <button class="btn btn-danger" style="margin-top:8px" @click="markViolation(o)">标记该预约违规</button>
        </div>
      </div>
    </div></div>
    <div v-if="loading" class="loading" style="margin-top:12px">正在同步房间状态…</div>
  </AppShell>
</template>
