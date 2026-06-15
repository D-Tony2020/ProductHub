// 采购件状态 → 标签映射（共享常量，消除 PartsTable / PartDetailDrawer 重复定义）。
export interface StatusMeta {
  label: string
  type: 'primary' | 'success' | 'warning' | 'info' | 'danger'
}

export const PART_STATUS: Record<string, StatusMeta> = {
  draft: { label: '草稿', type: 'warning' },
  active: { label: '正式', type: 'success' },
  merged: { label: '已合并', type: 'info' },
  retired: { label: '已停用', type: 'info' },
}
