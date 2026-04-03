import type { AgentCard } from './types';

export const AGENT_CARDS: AgentCard[] = [
  { id: 'user', label: 'Lab User', label_en: 'Researcher', desc: '人工输入 & 审计', desc_en: 'Human Input & Audit', icon: '🧪', color: '#2b90d9' },
  { id: 'assistant', label: 'AI Core', label_en: 'Mission Director', desc: 'LLM 主体对话', desc_en: 'Core LLM Chat', icon: '🤖', color: '#8a63d2' },
  { id: 'data_processing_agent', label: 'Data Agent', label_en: 'Data Agent', desc: '数据压缩与上传', desc_en: 'Data Processing & Upload', icon: '🗂️', color: '#4caf50' },
  { id: 'ratio_generator', label: 'Ratio Agent', label_en: 'Ratio Agent', desc: '配比表生成', desc_en: 'Recipe Ratio Generation', icon: '📊', color: '#d1a73b' },
  { id: 'ml_training_agent', label: 'ML Agent', label_en: 'Performance Predictor', desc: '模型训练/预测', desc_en: 'ML Training/Prediction', icon: '🧠', color: '#2db6a3' },
  { id: 'synthesis_robot', label: 'Robot Exec', label_en: 'Robot Exec', desc: '合成工站流程', desc_en: 'Robot Workstation Orchestration', icon: '🛠️', color: '#7b8b9a' },
  { id: 'synthesis_expert', label: 'Synth Expert', label_en: 'Knowledge Explorer', desc: '合成方案专家', desc_en: 'Synthesis Expert', icon: '👨‍🔬', color: '#673ab7' },
  { id: 'protocol_converter', label: 'Protocol Agent', label_en: 'Auto-Lab Designer', desc: '手册转自动流程', desc_en: 'Manual-to-Protocol Conv.', icon: '📑', color: '#f97316' },
  { id: 'shell_exec_agent', label: 'Shell Agent', label_en: 'Shell Agent', desc: '执行脚本/命令', desc_en: 'Shell Script Execution', icon: '💻', color: '#f472b6' },
  { id: 'file_service_agent', label: 'File Agent', label_en: 'File I/O Channel', desc: '文件服务与存储', desc_en: 'File Service & Storage', icon: '📁', color: '#607d8b' },
  { id: 'merge_csv_agent', label: 'Merge Agent', label_en: 'Merge Agent', desc: '数据合并与清洗', desc_en: 'Data Merging & Cleaning', icon: '🔗', color: '#ff9800' },
  { id: 'protocol_batch_agent', label: 'Batch Agent', label_en: 'Electrodata Processor', desc: '协议批量处理', desc_en: 'Protocol Batch Processing', icon: '📦', color: '#9c27b0' },
  { id: 'audit', label: 'Audit Guard', label_en: 'Audit Guard', desc: '合规审计/风险提示', desc_en: 'Compliance & Risk Guard', icon: '🛡️', color: '#ffd166' },
];

export const ROLE_META: Record<
  string,
  { label: string; label_en: string; icon: string; color: string; hint?: string; hint_en?: string }
> = {
  user_message: { label: 'USER', label_en: 'USER', icon: '🧪', color: '#2b90d9', hint: '实验人员输入', hint_en: 'Human input' },
  assistant_message: { label: 'AI', label_en: 'AI', icon: '🤖', color: '#8a63d2', hint: '模型回复', hint_en: 'AI response' },
  tool_call: { label: 'CALL', label_en: 'CALL', icon: '🛠️', color: '#5a6b7f', hint: '工具调用', hint_en: 'Tool invocation' },
  tool_result: { label: 'RESULT', label_en: 'RESULT', icon: '📦', color: '#5dd39e', hint: '工具返回', hint_en: 'Tool output' },
  audit_request: { label: 'AUDIT', label_en: 'AUDIT', icon: '🛡️', color: '#ffd166', hint: '需要人工确认', hint_en: 'Requires audit' },
  audit_decision: { label: 'AUDIT', label_en: 'AUDIT', icon: '✅', color: '#22c55e', hint: '审计结论', hint_en: 'Audit decision' },
  system: { label: 'SYSTEM', label_en: 'SYSTEM', icon: '🛰️', color: '#ff6b6b', hint: '系统事件', hint_en: 'System event' },
};
