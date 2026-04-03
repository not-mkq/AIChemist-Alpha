import { writable, derived } from 'svelte/store';

export type Language = 'zh' | 'en';

export const language = writable<Language>('zh');

const translations = {
  zh: {
    // TopBar
    'topbar.refresh': '刷新',
    'topbar.files': '文件管理',
    'topbar.history': '历史会话',
    'topbar.logs': '系统日志',
    'topbar.create': '新建会话',
    'topbar.exportPdf': '导出 PDF',
    'topbar.exportHtml': '导出 HTML',
    'topbar.close': '结束会话',
    'topbar.version': '版本',
    'topbar.tag': '标签',
    'topbar.noActiveSession': '未选择会话',

    // SessionSidebar
    'sidebar.sessions': '当前活跃会话',
    'sidebar.agents': '智能体集群',
    'sidebar.noSessions': '暂无会话',

    // ChatPane
    'chat.inputPlaceholder': '输入指令或问题...',
    'chat.thinkMode': '深度思考模式',
    'chat.send': '发送',
    'chat.sending': '发送中...',
    'chat.workspaceFiles': '工作空间文件',
    'chat.noEvents': '暂无事件',
    'chat.thoughtTitle': '思考过程',

    // AuditPane
    'audit.pending': '待审计',
    'audit.history': '审计历史',
    'audit.approve': '通过',
    'audit.reject': '拒绝',
    'audit.notePlaceholder': '添加审计备注...',
    'audit.noPending': '暂无待处理审计',
    'audit.noHistory': '暂无历史记录',

    // Statusbar
    'status.events': '事件',
    'status.pending': '待审计',
    'status.refreshRate': '刷新频率',

    // Modals
    'modal.close': '关闭',
    'modal.confirm': '确认',
    'modal.cancel': '取消',
    'modal.delete': '删除',

    // History Modal
    'history.title': '历史会话管理器',
    'history.sessions': '历史会话列表',
    'history.preview': '事件预览',
    'history.contexts': '上下文快照',
    'history.load': '加载会话',
    'history.clone': '克隆为新会话',
    'history.compress': '压缩上下文',
    'history.noContexts': '暂无快照',
    'history.loadOptions': '加载选项',
    'history.versionLabel': '版本号',
    'history.tagLabel': '用户标签',
    'history.forceRebuild': '强制重建',
    'history.fromEvents': '从事件重建',

    // Agent Info
    'agent.info': '智能体详情',
    'agent.description': '描述',
    'agent.tools': '可用工具',

    // File Manager
    'file.manager': '工作空间文件管理',
    'file.name': '文件名',
    'file.size': '大小',
    'file.mtime': '最后修改',
    'file.preview': '预览',
    'file.refresh': '刷新列表',
  },
  en: {
    // TopBar
    'topbar.refresh': 'Refresh',
    'topbar.files': 'Files',
    'topbar.history': 'History',
    'topbar.logs': 'Logs',
    'topbar.create': 'New Session',
    'topbar.exportPdf': 'Export PDF',
    'topbar.exportHtml': 'Export HTML',
    'topbar.close': 'Close Session',
    'topbar.version': 'Ver',
    'topbar.tag': 'Tag',
    'topbar.noActiveSession': 'No Active Session',

    // SessionSidebar
    'sidebar.sessions': 'Active Sessions',
    'sidebar.agents': 'Agents',
    'sidebar.noSessions': 'No sessions',

    // ChatPane
    'chat.inputPlaceholder': 'Type a message...',
    'chat.thinkMode': 'Deep Think',
    'chat.send': 'Send',
    'chat.sending': 'Sending...',
    'chat.workspaceFiles': 'Workspace Files',
    'chat.noEvents': 'No events',
    'chat.thoughtTitle': 'Thought Process',

    // AuditPane
    'audit.pending': 'Pending Audits',
    'audit.history': 'Audit History',
    'audit.approve': 'Approve',
    'audit.reject': 'Reject',
    'audit.notePlaceholder': 'Add audit notes...',
    'audit.noPending': 'No pending audits',
    'audit.noHistory': 'No audit history',

    // Statusbar
    'status.events': 'Events',
    'status.pending': 'Pending',
    'status.refreshRate': 'Refresh Interval',

    // Modals
    'modal.close': 'Close',
    'modal.confirm': 'Confirm',
    'modal.cancel': 'Cancel',
    'modal.delete': 'Delete',

    // History Modal
    'history.title': 'History Sessions',
    'history.sessions': 'Session List',
    'history.preview': 'Preview',
    'history.contexts': 'Context Snapshots',
    'history.load': 'Load',
    'history.clone': 'Clone as New',
    'history.compress': 'Compress',
    'history.noContexts': 'No snapshots',
    'history.loadOptions': 'Load Options',
    'history.versionLabel': 'Version',
    'history.tagLabel': 'Tag',
    'history.forceRebuild': 'Force Rebuild',
    'history.fromEvents': 'From Events',

    // Agent Info
    'agent.info': 'Agent Info',
    'agent.description': 'Description',
    'agent.tools': 'Tools',

    // File Manager
    'file.manager': 'Workspace Files',
    'file.name': 'Name',
    'file.size': 'Size',
    'file.mtime': 'Modified',
    'file.preview': 'Preview',
    'file.refresh': 'Refresh',
  }
};

export const t = derived(language, ($language) => {
  return (key: keyof typeof translations['zh']) => {
    return translations[$language][key] || key;
  };
});
