export const ROOM_CODES = ['A101', 'A102', 'A103', 'A105', 'B102']
export const SHIFTS = [8, 10, 12, 14, 16, 18, 20]
export const WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

export const statusText = {
  pending_ai: 'AI审核中', pending_manual: '待人工审核', approved: '已通过', rejected: '已驳回',
  invalidated: '资源冲突失效', active: '已签到', awaiting_cleanup: '待清扫上传', completed: '已完结',
  expired: '未签到已过期', cancelled: '已取消', pending: '待处理', normal: '正常', frozen: '冻结',
  admin_pass: '人工核验通过', admin_reject: '人工核验不通过', auto_pass: 'OCR自动通过', manual_required: '待人工核验',
}

export function fmtDateTime(value) {
  if (!value) return '—'
  const d = new Date(value)
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(d).replaceAll('/', '-')
}

export function toApiDateTime(localValue) {
  if (!localValue) return ''
  return `${localValue}:00+08:00`
}

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
