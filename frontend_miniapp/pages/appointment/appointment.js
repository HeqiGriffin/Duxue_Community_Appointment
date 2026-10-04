const { request, getSession } = require('../../utils/request')

function pad(n) { return String(n).padStart(2, '0') }
function campusNowParts() {
  const d = new Date(Date.now() + 8 * 3600000)
  return { y: d.getUTCFullYear(), m: d.getUTCMonth() + 1, day: d.getUTCDate(), h: d.getUTCHours(), min: d.getUTCMinutes() }
}
function ymdFromOffset(days) {
  const now = new Date(Date.now() + 8 * 3600000)
  const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + days))
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`
}
function addDay(dateText, days) {
  const [y, m, d] = dateText.split('-').map(Number)
  const x = new Date(Date.UTC(y, m - 1, d + days))
  return `${x.getUTCFullYear()}-${pad(x.getUTCMonth() + 1)}-${pad(x.getUTCDate())}`
}
function timeText(minutes) {
  if (minutes === 24 * 60) return '24:00'
  return `${pad(Math.floor(minutes / 60))}:${pad(minutes % 60)}`
}
function apiDateTime(dateText, minutes) {
  if (minutes === 24 * 60) return `${addDay(dateText, 1)}T00:00:00+08:00`
  return `${dateText}T${timeText(minutes)}:00+08:00`
}
function buildSlots(dateText, selected = []) {
  const today = ymdFromOffset(0)
  const now = campusNowParts()
  const nowMinutes = now.h * 60 + now.min
  const selectedSet = new Set(selected)
  const rows = []
  for (let index = 0; index < 48; index += 1) {
    const start = index * 30
    const end = start + 30
    rows.push({
      index,
      start,
      end,
      label: `${timeText(start)}–${timeText(end)}`,
      selected: selectedSet.has(index),
      disabled: dateText === today && start <= nowMinutes
    })
  }
  return rows
}

Page({
  data: {
    date: '', minDate: '', maxDate: '',
    usageMode: 'study',
    slotItems: [], selectedSlots: [],
    durationText: '',
    rooms: [], selectedRoom: '', availabilityLoading: false, freeRoomCount: 0,
    allocationNote: '', recommendedRoom: '',
    peopleCount: 1, purpose: '', purposeLength: 0,
    submitting: false,
    examples: ['期末考试周复习数学分析，需要安静学习', '班级例会，预计 8 人讨论本周工作安排', '心理剧排练，需要完整活动空间进行走位练习']
  },

  onLoad() {
    const session = getSession()
    if (!session || !session.canBook) {
      wx.showModal({ title: '当前不可预约', content: '账号状态或密码状态不允许发起预约。', showCancel: false, success: () => wx.navigateBack() })
      return
    }
    const date = ymdFromOffset(1)
    this.setData({
      date,
      minDate: ymdFromOffset(0),
      maxDate: ymdFromOffset(60),
      slotItems: buildSlots(date)
    })
  },

  onDateChange(e) {
    const date = e.detail.value
    this.setData({
      date,
      selectedSlots: [],
      slotItems: buildSlots(date),
      durationText: '',
      rooms: [],
      selectedRoom: '',
      freeRoomCount: 0,
      allocationNote: '',
      recommendedRoom: ''
    })
  },

  chooseUsageMode(e) {
    const usageMode = e.currentTarget.dataset.mode
    if (!['study', 'exclusive'].includes(usageMode) || usageMode === this.data.usageMode) return
    this.setData({ usageMode, rooms: [], selectedRoom: '', allocationNote: '', recommendedRoom: '' })
    if (this.data.selectedSlots.length) this.loadAvailability()
  },

  onPeopleInput(e) {
    const value = String(e.detail.value || '').replace(/\D/g, '')
    this.setData({ peopleCount: value ? Math.min(500, Number(value)) : '' })
    if (this.data.selectedSlots.length) {
      clearTimeout(this._peopleTimer)
      this._peopleTimer = setTimeout(() => this.loadAvailability(), 250)
    }
  },

  onPurposeInput(e) {
    const purpose = e.detail.value
    this.setData({ purpose, purposeLength: purpose.length })
  },

  useExample(e) {
    const purpose = e.currentTarget.dataset.text
    this.setData({ purpose, purposeLength: purpose.length })
  },

  tapSlot(e) {
    const index = Number(e.currentTarget.dataset.index)
    const item = this.data.slotItems[index]
    if (!item || item.disabled) {
      wx.showToast({ title: '该时段已过', icon: 'none' })
      return
    }

    let selected = [...this.data.selectedSlots].sort((a, b) => a - b)
    if (!selected.length) {
      selected = [index]
    } else {
      const first = selected[0]
      const last = selected[selected.length - 1]
      if (selected.includes(index)) {
        if (selected.length === 1) selected = []
        else if (index === first) selected.shift()
        else if (index === last) selected.pop()
        else selected = [index]
      } else if (index === last + 1) {
        selected.push(index)
      } else if (index === first - 1) {
        selected.unshift(index)
      } else {
        selected = [index]
      }
    }

    const minutes = selected.length * 30
    const h = Math.floor(minutes / 60)
    const m = minutes % 60
    const durationText = selected.length
      ? (h ? `${h} 小时${m ? ` ${m} 分钟` : ''}` : `${m} 分钟`)
      : ''

    this.setData({
      selectedSlots: selected,
      slotItems: buildSlots(this.data.date, selected),
      durationText,
      rooms: [],
      selectedRoom: '',
      freeRoomCount: 0,
      allocationNote: '',
      recommendedRoom: ''
    })

    if (selected.length) this.loadAvailability()
  },

  selectedRange() {
    const selected = [...this.data.selectedSlots].sort((a, b) => a - b)
    if (!selected.length) return null
    const first = selected[0]
    const last = selected[selected.length - 1]
    return {
      startTime: apiDateTime(this.data.date, first * 30),
      endTime: apiDateTime(this.data.date, (last + 1) * 30)
    }
  },

  async loadAvailability() {
    const range = this.selectedRange()
    if (!range || this.data.availabilityLoading) return
    const peopleCount = Number(this.data.peopleCount || 1)
    this.setData({ availabilityLoading: true })
    try {
      const result = await request({
        url: '/bookings/availability',
        query: {
          start_time: range.startTime,
          end_time: range.endTime,
          usage_mode: this.data.usageMode,
          people_count: peopleCount
        }
      })
      const rooms = (result.rooms || []).map(x => ({
        ...x,
        suitableText: (x.suitable || []).join('、'),
        stateClass: x.available ? (x.occupancy_mode === 'study_shared' ? 'shared' : 'free') : 'busy'
      }))
      let selectedRoom = this.data.selectedRoom
      if (!rooms.some(x => x.room_code === selectedRoom && x.available)) selectedRoom = ''
      if (this.data.usageMode === 'study' && result.recommended_room_code) selectedRoom = result.recommended_room_code
      this.setData({
        rooms,
        selectedRoom,
        freeRoomCount: rooms.filter(x => x.available).length,
        allocationNote: result.allocation_note || '',
        recommendedRoom: result.recommended_room_code || ''
      })
    } catch (err) {
      this.setData({ rooms: [], freeRoomCount: 0, allocationNote: '', recommendedRoom: '' })
      wx.showToast({ title: err.message || '读取房间状态失败', icon: 'none', duration: 3000 })
    } finally {
      this.setData({ availabilityLoading: false })
    }
  },

  chooseRoom(e) {
    const roomCode = e.currentTarget.dataset.room
    const room = this.data.rooms.find(x => x.room_code === roomCode)
    if (!room || !room.available) return
    this.setData({ selectedRoom: roomCode })
  },

  async submit() {
    const { selectedSlots, selectedRoom, peopleCount, purpose, submitting, usageMode } = this.data
    if (submitting) return
    if (!selectedSlots.length) { wx.showToast({ title: '请先选择预约时段', icon: 'none' }); return }
    if (!selectedRoom) { wx.showToast({ title: '请选择一个当前可预约的房间', icon: 'none' }); return }
    if (!peopleCount || peopleCount < 1) { wx.showToast({ title: '请输入预约人数', icon: 'none' }); return }
    if (!purpose.trim() || purpose.trim().length < 2) { wx.showToast({ title: '请说明具体用途', icon: 'none' }); return }

    const range = this.selectedRange()
    if (!range) return
    this.setData({ submitting: true })
    try {
      const result = await request({
        url: '/bookings', method: 'POST', loading: true, loadingText: '正在提交',
        data: {
          start_time: range.startTime,
          end_time: range.endTime,
          room_code: selectedRoom,
          usage_mode: usageMode,
          people_count: Number(peopleCount),
          purpose: purpose.trim()
        }
      })
      const studyTip = usageMode === 'study' ? '\n自习最终房间会在审核通过时按实时座位集中调剂。' : ''
      wx.showModal({
        title: '预约已提交',
        content: result.status === 'pending_ai'
          ? `已选择 ${selectedRoom}，AI 正在后台审核，可在首页查看结果。${studyTip}`
          : (result.rejection_reason || result.ai_reason || '可在首页查看最新状态'),
        showCancel: false,
        success: () => wx.navigateBack()
      })
    } catch (err) {
      wx.showToast({ title: err.message || '提交失败', icon: 'none', duration: 3500 })
      if (err.statusCode === 409) this.loadAvailability()
    } finally {
      this.setData({ submitting: false })
    }
  }
})
