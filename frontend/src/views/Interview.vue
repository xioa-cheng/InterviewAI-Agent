<template>
  <div class="page">
    <div class="container">
      <!-- 品牌条 -->
      <div class="brandbar">
        <span class="brand-dot" />
        <span class="brand-name">InterviewAI</span>
        <span class="brand-sub">AI 面试模拟</span>
      </div>

      <!-- 续考提示：检测到本地有未完成的面试 -->
      <transition name="fade">
        <a-card v-if="ongoing && phase === 'setup'" class="card resume-card">
          <div class="resume-row">
            <div class="resume-info">
              <div class="resume-title">检测到未完成的面试</div>
              <div class="resume-sub">
                {{ ongoing.position_name }} · 第 {{ ongoing.current_round }} / {{ ongoing.total_rounds }} 轮
              </div>
            </div>
            <div class="resume-actions">
              <a-button type="primary" @click="resume">继续上次</a-button>
              <a-button status="danger" @click="discardOngoing">放弃</a-button>
            </div>
          </div>
        </a-card>
      </transition>

      <!-- 配置阶段 -->
      <a-card v-if="phase === 'setup'" class="card setup-card">
        <div class="setup-head">
          <div class="setup-title">开始一场模拟面试</div>
          <div class="setup-desc">
            AI 面试官将根据你的岗位与难度，分轮出题、实时评估并给出改进建议，帮助你提前演练。
          </div>
        </div>

        <a-form :model="config" layout="vertical" @submit="start">
          <a-form-item label="应聘岗位">
            <a-input v-model="config.position_name" placeholder="例如：后端开发工程师" allow-clear />
            <div class="chips">
              <button
                v-for="p in popularPositions"
                :key="p"
                type="button"
                class="chip"
                :class="{ on: config.position_name === p }"
                @click="config.position_name = p"
              >
                {{ p }}
              </button>
            </div>
          </a-form-item>

          <a-form-item label="简历（可选，用于定制出题）">
            <a-select v-model="config.resume_id" placeholder="选择简历，不选则用最新简历" allow-clear>
              <a-option v-for="r in resumes" :key="r.id" :value="r.id">{{ r.title }}</a-option>
            </a-select>
          </a-form-item>

          <a-row :gutter="16">
            <a-col :span="8">
              <a-form-item label="面试类型">
                <a-select v-model="config.interview_type">
                  <a-option value="mixed">综合</a-option>
                  <a-option value="technical">技术</a-option>
                  <a-option value="behavioral">行为</a-option>
                  <a-option value="project">项目</a-option>
                  <a-option value="stress">压力</a-option>
                </a-select>
              </a-form-item>
            </a-col>
            <a-col :span="8">
              <a-form-item label="难度">
                <a-select v-model="config.difficulty_level">
                  <a-option value="easy">简单</a-option>
                  <a-option value="medium">中等</a-option>
                  <a-option value="hard">困难</a-option>
                </a-select>
              </a-form-item>
            </a-col>
            <a-col :span="8">
              <a-form-item label="轮数">
                <a-input-number v-model="config.total_rounds" :min="1" :max="10" />
              </a-form-item>
            </a-col>
          </a-row>

          <a-button type="primary" html-type="submit" :loading="loading" long size="large">
            开始面试
          </a-button>
        </a-form>
      </a-card>

      <!-- 面试进行阶段 -->
      <a-card v-else-if="phase === 'session'" class="card session-card">
        <!-- 顶部：岗位信息 + 进度 -->
        <div class="session-top">
          <div class="session-info">
            <div class="session-position">{{ config.position_name || 'AI 面试' }}</div>
            <div class="session-tags">
              <a-tag class="type-tag">{{ typeLabel(config.interview_type) }}</a-tag>
              <a-tag class="type-tag">{{ diffLabel(config.difficulty_level) }}</a-tag>
              <span class="round-label">第 {{ currentRound }} / {{ totalRounds }} 轮</span>
            </div>
          </div>
          <a-button class="restart-btn" size="mini" :disabled="loading" @click="confirmReset">重新开始</a-button>
        </div>

        <!-- 带数字的 stepper -->
        <div class="stepper">
          <template v-for="n in totalRounds" :key="n">
            <div class="step" :class="{ done: n < currentRound, active: n === currentRound }">
              <span class="step-num">{{ n < currentRound ? '✓' : n }}</span>
            </div>
            <div v-if="n < totalRounds" class="step-line" :class="{ done: n < currentRound }" />
          </template>
        </div>
        <div class="progress">
          <div class="progress-bar" :style="{ width: progressPercent + '%' }" />
        </div>

        <a-divider class="hd" />

        <!-- 对话区：面试官左 / 候选人右 -->
        <div ref="chatRef" class="chat">
          <transition-group name="rise">
            <template v-for="m in chatLog" :key="m.uid">
              <!-- 面试官问题气泡 -->
              <div v-if="m.kind === 'question'" class="msg-row ai">
                <div class="avatar ai-avatar">AI</div>
                <div class="bubble ai">
                  <div class="bubble-head">
                    <span class="bubble-type" v-if="m.type">{{ typeLabel(m.type) }}</span>
                    <span class="q-num" v-if="m.num">Q{{ m.num }}</span>
                  </div>
                  <div class="bubble-text">{{ m.text }}</div>
                </div>
              </div>

              <!-- 候选人回答气泡 -->
              <div v-else-if="m.kind === 'answer'" class="msg-row me">
                <div class="bubble me">{{ m.text }}</div>
                <div class="avatar me-avatar">我</div>
              </div>

              <!-- 评估卡片 -->
              <div v-else-if="m.kind === 'eval'" class="msg-row ai">
                <div class="avatar ai-avatar">评</div>
                <div class="eval-card" :class="{ failed: m.data.evaluation_failed }">
                  <div class="eval-head">
                    <a-progress
                      type="circle"
                      :percent="m.data.score ?? 0"
                      :size="56"
                      :stroke-width="8"
                      :color="scoreColor(m.data.score)"
                    />
                    <div class="eval-score-block">
                      <div class="eval-score-num">
                        {{ m.data.score ?? '-' }}<span class="unit">分</span>
                      </div>
                      <div class="eval-sub">本轮评估</div>
                    </div>
                    <a-tag v-if="m.data.evaluation_failed" color="red" size="large">评分未完成</a-tag>
                  </div>
                  <a-descriptions :column="1" bordered size="small" class="eval-desc">
                    <a-descriptions-item label="优点">
                      <div v-for="(s, k) in (m.data.strengths || [])" :key="k">· {{ s }}</div>
                    </a-descriptions-item>
                    <a-descriptions-item label="不足">
                      <div v-for="(s, k) in (m.data.weaknesses || [])" :key="k">· {{ s }}</div>
                    </a-descriptions-item>
                    <a-descriptions-item label="建议">
                      <div v-for="(s, k) in (m.data.suggestions || [])" :key="k">· {{ s }}</div>
                    </a-descriptions-item>
                    <a-descriptions-item label="参考回答">{{ m.data.model_answer }}</a-descriptions-item>
                  </a-descriptions>
                </div>
              </div>
            </template>
          </transition-group>

          <!-- 出题思考指示 -->
          <div v-if="loading && !questionStream && !question" class="msg-row ai">
            <div class="avatar ai-avatar">AI</div>
            <div class="bubble ai thinking">
              <span class="dot" /><span class="dot" /><span class="dot" />
              <span class="thinking-text">面试官正在出题…</span>
            </div>
          </div>

          <!-- 当前正在流式生成的题目 -->
          <div v-if="questionStream" class="msg-row ai">
            <div class="avatar ai-avatar">AI</div>
            <div class="bubble ai streaming">
              <div class="bubble-text">{{ questionStream }}<span class="caret">▋</span></div>
            </div>
          </div>

          <!-- 当前正在流式生成的评估 -->
          <div v-if="evalStream" class="msg-row ai">
            <div class="avatar ai-avatar">评</div>
            <div class="eval-card streaming">
              <div class="eval-head">
                <a-progress type="circle" :percent="0" :size="56" :stroke-width="8" :color="scoreColor(null)" />
                <div class="eval-score-block">
                  <div class="eval-score-num">评估中</div>
                  <div class="eval-sub">正在生成点评…</div>
                </div>
              </div>
              <div class="stream-text">{{ evalStream }}<span class="caret">▋</span></div>
            </div>
          </div>
        </div>

        <!-- 作答输入区（仅在当前题目已定稿、且未在评估时显示） -->
        <div v-if="question && !questionStream && !evalStream" class="composer">
          <a-textarea
            v-model="answer"
            :auto-size="{ minRows: 4, maxRows: 10 }"
            placeholder="在此输入你的回答…（也可点下方「语音输入」直接说话，或按 Ctrl + Enter 发送）"
            :max-length="2000"
            show-word-limit
            :disabled="loading"
            @keydown.ctrl.enter.exact.prevent="submit"
          />
          <div class="composer-actions">
            <a-button type="primary" :loading="loading" :disabled="!answer.trim()" @click="submit">
              提交回答
            </a-button>
            <a-button :loading="listening" :disabled="loading" @click="listen">语音输入</a-button>
            <a-button class="speak-btn-sm" size="mini" :disabled="!question" @click="speak(question)">
              朗读题目
            </a-button>
          </div>
        </div>

        <div v-if="wsStatus" class="ws-status">{{ wsStatus }}</div>
      </a-card>

      <!-- 完成阶段 -->
      <a-card v-else class="card">
        <a-result status="success" title="面试完成！">
          <template #subtitle>
            <div v-if="report" class="report">
              <a-statistic title="综合得分" :value="report.overall_score ?? '-'" suffix="分" />
              <p style="margin-top: 12px">岗位：{{ report.position_name }} · 类型：{{ report.interview_type }}</p>
            </div>
          </template>
          <template #extra>
            <a-button type="primary" @click="reset">再来一场</a-button>
          </template>
        </a-result>

        <a-divider v-if="report && report.details.length">逐题回顾</a-divider>
        <div v-for="(d, i) in (report?.details ?? [])" :key="i" class="qa-item">
          <div class="q">
            <span class="q-badge">Q{{ d.question_number }}</span>
            <span class="q-type">{{ d.question_type }}</span>
            {{ d.question }}
          </div>
          <div class="a">你的回答：{{ d.answer }}</div>
          <a-tag size="large" class="score-tag">得分 {{ d.score ?? '-' }}</a-tag>
          <div v-if="d.suggestions?.length" class="a suggest">建议：{{ d.suggestions.join('；') }}</div>
        </div>
      </a-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Message, Modal } from '@arco-design/web-vue'
import client, { TOKEN_KEY } from '../api/client'
import { streamPost } from '../api/stream'

const router = useRouter()
const route = useRoute()

type Phase = 'setup' | 'session' | 'done'

const phase = ref<Phase>('setup')
const loading = ref(false)
const config = reactive({
  position_name: '后端开发工程师',
  interview_type: 'mixed',
  difficulty_level: 'medium',
  total_rounds: 5,
  resume_id: null as string | null,
})

const popularPositions = ['后端开发工程师', '前端开发工程师', '产品经理', '数据分析师', '测试工程师']

const resumes = ref<any[]>([])

async function loadResumes() {
  try {
    const res = await client.get('/resumes')
    resumes.value = res.data
    const qid = route.query.resume_id as string
    if (qid) {
      config.resume_id = qid
    } else if (res.data.length) {
      config.resume_id = res.data[0].id
    }
  } catch (e) {
    resumes.value = []
  }
}

const interviewId = ref('')
const question = ref('')
const questionType = ref('')
const currentRound = ref(1)
const totalRounds = ref(5)
const answer = ref('')
const evaluation = ref<any>(null)
const report = ref<any>(null)
const listening = ref(false)
const wsStatus = ref('')
let ws: WebSocket | null = null

// —— 流式相关 ——
const questionStream = ref('') // 出题打字机文本
const evalStream = ref('') // 评估打字机文本
const streaming = ref(false) // 是否正在生成（题目/评估）

// —— 对话气泡记录（仅用于展示历史，不影响原有数据流）——
const chatLog = ref<any[]>([])
const chatRef = ref<HTMLElement | null>(null)
let msgSeq = 0
function pushMsg(m: any) {
  chatLog.value.push({ uid: ++msgSeq, ...m })
  scrollChat()
}
function scrollChat() {
  nextTick(() => {
    const el = chatRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

const progressPercent = computed(() =>
  Math.round((currentRound.value / Math.max(1, totalRounds.value)) * 100),
)

const TYPE_LABELS: Record<string, string> = {
  technical: '技术',
  behavioral: '行为',
  project: '项目',
  algorithm: '算法',
  system_design: '系统设计',
}
const DIFF_LABELS: Record<string, string> = {
  easy: '简单',
  medium: '中等',
  hard: '困难',
}
function typeLabel(t: string) {
  return TYPE_LABELS[t] || t || '面试题'
}
function diffLabel(t: string) {
  return DIFF_LABELS[t] || t
}
function scoreColor(s: number | null) {
  if (s == null) return '#cbd5e1'
  if (s >= 80) return '#16a34a'
  if (s >= 60) return '#4f46e5'
  if (s >= 40) return '#d97757'
  return '#dc2626'
}

// —— 续考（localStorage）——
const ONGOING_KEY = 'interviewai_ongoing'
const ongoing = ref<any>(null)

function loadOngoing() {
  try {
    const raw = localStorage.getItem(ONGOING_KEY)
    ongoing.value = raw ? JSON.parse(raw) : null
  } catch {
    ongoing.value = null
  }
}
function saveOngoing(obj: any) {
  try {
    localStorage.setItem(ONGOING_KEY, JSON.stringify(obj))
    ongoing.value = obj
  } catch {
    /* 忽略 */
  }
}
function clearOngoing() {
  try {
    localStorage.removeItem(ONGOING_KEY)
  } catch {
    /* 忽略 */
  }
  ongoing.value = null
}

async function start() {
  loading.value = true
  questionStream.value = ''
  evaluation.value = null
  evalStream.value = ''
  chatLog.value = []
  clearOngoing()
  try {
    await streamPost(
      '/api/v1/stream/start',
      { ...config },
      (ev) => {
        if (ev.type === 'meta') {
          interviewId.value = ev.interview_id
          currentRound.value = ev.current_round
          totalRounds.value = ev.total_rounds
          phase.value = 'session'
          openSocket(ev.interview_id)
        } else if (ev.type === 'token') {
          questionStream.value += ev.text
        } else if (ev.type === 'done') {
          question.value = ev.question
          questionType.value = ev.question_type
          questionStream.value = ''
          pushMsg({ role: 'ai', kind: 'question', text: ev.question, type: ev.question_type, num: currentRound.value })
          saveOngoing({
            interview_id: interviewId.value,
            position_name: config.position_name,
            interview_type: config.interview_type,
            difficulty_level: config.difficulty_level,
            total_rounds: totalRounds.value,
            resume_id: config.resume_id,
            current_round: currentRound.value,
            saved_at: Date.now(),
          })
        } else if (ev.type === 'error') {
          Message.error(ev.message || '出题失败')
        }
      },
    )
  } catch (e: any) {
    Message.error(e?.message || '开始面试失败')
    phase.value = 'setup'
  } finally {
    loading.value = false
  }
}

async function submit() {
  if (!answer.value.trim() || !question.value) {
    Message.warning('请先输入回答')
    return
  }
  loading.value = true
  streaming.value = true
  const myAnswer = answer.value
  evaluation.value = null
  evalStream.value = ''
  try {
    await streamPost(
      '/api/v1/stream/answer',
      { interview_id: interviewId.value, answer: answer.value },
      (ev) => {
        if (ev.type === 'token') {
          evalStream.value += ev.text
        } else if (ev.type === 'done') {
          evaluation.value = {
            score: ev.score,
            strengths: ev.strengths || [],
            weaknesses: ev.weaknesses || [],
            suggestions: ev.suggestions || [],
            model_answer: ev.model_answer,
            evaluation_failed: ev.evaluation_failed || false,
          }
          evalStream.value = ''
          currentRound.value = ev.current_round
          // 把本轮作答与评估沉淀进对话记录
          pushMsg({ role: 'me', kind: 'answer', text: myAnswer })
          pushMsg({ role: 'ai', kind: 'eval', data: evaluation.value })
          if (ev.completed) {
            Message.success('面试完成，正在生成能力报告…')
            clearOngoing()
            router.push(`/report/${interviewId.value}`)
          } else {
            question.value = ev.next_question
            questionType.value = ''
            answer.value = ''
            pushMsg({ role: 'ai', kind: 'question', text: ev.next_question, type: '', num: currentRound.value })
            // 更新续考进度
            if (ongoing.value) {
              saveOngoing({ ...ongoing.value, current_round: ev.current_round })
            }
            Message.success('已进入下一题')
          }
        } else if (ev.type === 'error') {
          Message.error(ev.message || '评估失败')
        }
      },
    )
  } catch (e: any) {
    Message.error(e?.message || '提交失败')
  } finally {
    loading.value = false
    streaming.value = false
  }
}

function reset() {
  closeSocket()
  phase.value = 'setup'
  answer.value = ''
  evaluation.value = null
  report.value = null
  questionStream.value = ''
  evalStream.value = ''
  chatLog.value = []
}

function confirmReset() {
  Modal.confirm({
    title: '重新开始？',
    content: '当前这一场面试的进度将被清空，确定要重新开始吗？',
    okText: '重新开始',
    cancelText: '取消',
    onOk: reset,
  })
}

// —— 续考：恢复上次未完成的面试 ——
async function resume() {
  const o = ongoing.value
  if (!o) return
  loading.value = true
  try {
    const res = await client.get(`/interviews/${o.interview_id}`)
    const data = res.data
    if (data.status === 'completed') {
      clearOngoing()
      router.push(`/report/${o.interview_id}`)
      return
    }
    interviewId.value = o.interview_id
    question.value = data.current_question || ''
    questionType.value = data.question_type || ''
    currentRound.value = data.current_round
    totalRounds.value = data.total_rounds
    answer.value = ''
    evaluation.value = null
    chatLog.value = data.current_question
      ? [{ uid: ++msgSeq, role: 'ai', kind: 'question', text: data.current_question, type: data.question_type || '', num: data.current_round }]
      : []
    phase.value = 'session'
    openSocket(o.interview_id)
    Message.success('已恢复上次面试')
  } catch (e: any) {
    Message.error(e?.response?.data?.detail || '恢复失败')
    clearOngoing()
  } finally {
    loading.value = false
  }
}

async function discardOngoing() {
  const o = ongoing.value
  if (!o) return
  try {
    await client.delete(`/interviews/${o.interview_id}`)
  } catch {
    /* 忽略删除失败（可能已不存在） */
  }
  clearOngoing()
  Message.success('已放弃该面试')
}

// —— WebSocket 实时事件推送（可选，失败静默降级，不影响主流程）——
function openSocket(id: string) {
  closeSocket()
  try {
    const token = localStorage.getItem(TOKEN_KEY)
    if (!token) return
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    ws = new WebSocket(`${proto}://${location.host}/api/v1/ws/interviews/${id}?token=${encodeURIComponent(token)}`)
    wsStatus.value = '实时状态：已连接'
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data)
        if (msg.type === 'evaluating') {
          wsStatus.value = `面试官正在评估第 ${msg.round} 轮回答…`
        } else if (msg.type === 'evaluated') {
          wsStatus.value = msg.completed
            ? `面试完成，综合评分 ${msg.score ?? '-'} 分`
            : `第 ${msg.round} 轮评分：${msg.score ?? '-'} 分`
        } else if (msg.type === 'completed') {
          wsStatus.value = '面试结束'
        }
      } catch {
        /* 忽略无法解析的消息 */
      }
    }
    ws.onerror = () => { wsStatus.value = '' }
    ws.onclose = () => { if (phase.value === 'session') wsStatus.value = '' }
  } catch {
    ws = null
  }
}

function closeSocket() {
  if (ws) {
    try { ws.close() } catch { /* 忽略 */ }
    ws = null
  }
  wsStatus.value = ''
}

onMounted(() => {
  loadResumes()
  loadOngoing()
})
onUnmounted(closeSocket)

function speak(text: string) {
  if (!('speechSynthesis' in window)) {
    Message.warning('当前浏览器不支持语音合成')
    return
  }
  const utter = new SpeechSynthesisUtterance(text)
  utter.lang = 'zh-CN'
  utter.rate = 1
  speechSynthesis.cancel()
  speechSynthesis.speak(utter)
}

function listen() {
  const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
  if (!SR) {
    Message.warning('当前浏览器不支持语音识别（建议用 Edge / Chrome）')
    return
  }
  const rec = new SR()
  rec.lang = 'zh-CN'
  rec.interimResults = false
  rec.onresult = (e: any) => {
    const text = e.results[0][0].transcript
    answer.value = answer.value ? answer.value + text : text
  }
  rec.onerror = (e: any) => {
    Message.error('语音识别失败：' + (e?.error || '未知错误'))
  }
  rec.onend = () => {
    listening.value = false
  }
  listening.value = true
  rec.start()
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  padding: 32px 16px 48px;
  background: linear-gradient(180deg, #f8fafc 0%, #eef2ff 100%);
}
.container {
  max-width: 900px;
  margin: 0 auto;
}
.brandbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 18px;
  padding-left: 4px;
}
.brand-dot {
  width: 11px;
  height: 11px;
  border-radius: 50%;
  background: #4f46e5;
  box-shadow: 0 0 0 4px rgba(79, 70, 229, 0.15);
}
.brand-name {
  font-weight: 700;
  font-size: 18px;
  color: #1e293b;
  letter-spacing: 0.3px;
}
.brand-sub {
  font-size: 13px;
  color: #94a3b8;
}

.card {
  border-radius: 16px;
  border: none;
  box-shadow: 0 6px 28px rgba(15, 23, 42, 0.06);
  background: #fff;
}
.resume-card {
  border-left: 4px solid #4f46e5;
  margin-bottom: 16px;
}
.resume-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.resume-title {
  font-weight: 600;
  color: #1e293b;
}
.resume-sub {
  font-size: 13px;
  color: #86909c;
  margin-top: 4px;
}
.resume-actions {
  display: flex;
  gap: 8px;
}

/* 配置阶段 */
.setup-card {
  padding: 8px 4px;
}
.setup-head {
  margin-bottom: 8px;
}
.setup-title {
  font-size: 20px;
  font-weight: 700;
  color: #1e293b;
}
.setup-desc {
  margin-top: 6px;
  font-size: 13px;
  color: #86909c;
  line-height: 1.7;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}
.chip {
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  color: #475569;
  border-radius: 999px;
  padding: 5px 12px;
  font-size: 12.5px;
  cursor: pointer;
  transition: all 0.18s;
}
.chip:hover {
  border-color: #4f46e5;
  color: #4f46e5;
}
.chip.on {
  background: #4f46e5;
  border-color: #4f46e5;
  color: #fff;
}

/* 会话卡 */
.session-card {
  overflow: hidden;
  padding: 18px 18px 20px;
}
.session-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.session-position {
  font-size: 18px;
  font-weight: 700;
  color: #1e293b;
}
.session-tags {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  flex-wrap: wrap;
}
.round-label {
  font-size: 13px;
  color: #64748b;
  font-weight: 500;
}
.type-tag {
  font-weight: 600;
  color: #4f46e5 !important;
  background: #eef2ff !important;
  border-color: #e0e4ff !important;
}
.restart-btn {
  flex: 0 0 auto;
  color: #94a3b8;
}

/* 带数字的 stepper */
.stepper {
  display: flex;
  align-items: center;
  margin-top: 16px;
  flex-wrap: wrap;
}
.step {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: #e2e8f0;
  color: #94a3b8;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  flex: 0 0 auto;
  transition: all 0.25s;
}
.step.done {
  background: #4f46e5;
  color: #fff;
}
.step.active {
  background: #4f46e5;
  color: #fff;
  box-shadow: 0 0 0 4px rgba(79, 70, 229, 0.18);
  transform: scale(1.08);
}
.step-line {
  flex: 1 1 auto;
  height: 2px;
  min-width: 8px;
  background: #e2e8f0;
  margin: 0 4px;
  transition: all 0.25s;
}
.step-line.done {
  background: #4f46e5;
}
.progress {
  height: 4px;
  background: #eef0f4;
  border-radius: 999px;
  margin-top: 12px;
  overflow: hidden;
}
.progress-bar {
  height: 100%;
  background: linear-gradient(90deg, #6366f1, #4f46e5);
  border-radius: 999px;
  transition: width 0.4s ease;
}
.hd {
  margin: 16px 0 16px;
}

/* 对话区 */
.chat {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-height: 52vh;
  overflow-y: auto;
  padding: 4px 6px 4px 2px;
}
.msg-row {
  display: flex;
  align-items: flex-end;
  gap: 10px;
}
.msg-row.ai {
  justify-content: flex-start;
}
.msg-row.me {
  justify-content: flex-end;
}
.avatar {
  flex: 0 0 auto;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  color: #fff;
}
.ai-avatar {
  background: #4f46e5;
}
.me-avatar {
  background: #1e293b;
}
.bubble {
  max-width: 78%;
  padding: 12px 16px;
  border-radius: 16px;
  line-height: 1.7;
  font-size: 15px;
  white-space: pre-wrap;
  word-break: break-word;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05);
}
.bubble.ai {
  background: #eef2ff;
  color: #1e293b;
  border-bottom-left-radius: 5px;
}
.bubble.me {
  background: #4f46e5;
  color: #fff;
  border-bottom-right-radius: 5px;
}
.bubble.streaming {
  background: #eef2ff;
}
.bubble-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.bubble-type {
  font-size: 11px;
  font-weight: 600;
  color: #4f46e5;
  background: rgba(79, 70, 229, 0.12);
  border-radius: 6px;
  padding: 1px 8px;
}
.q-num {
  font-size: 11px;
  font-weight: 700;
  color: #6366f1;
  background: rgba(79, 70, 229, 0.16);
  border-radius: 6px;
  padding: 1px 8px;
}
.bubble-text {
  white-space: pre-wrap;
}

/* 出题思考指示 */
.bubble.thinking {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 14px 16px;
}
.thinking-text {
  font-size: 13px;
  color: #6366f1;
  margin-left: 4px;
}
.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #6366f1;
  animation: bounce 1.2s infinite ease-in-out;
}
.dot:nth-child(2) {
  animation-delay: 0.15s;
}
.dot:nth-child(3) {
  animation-delay: 0.3s;
}
@keyframes bounce {
  0%, 60%, 100% {
    transform: translateY(0);
    opacity: 0.5;
  }
  30% {
    transform: translateY(-5px);
    opacity: 1;
  }
}

/* 评估卡片（气泡内） */
.eval-card {
  max-width: 82%;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-left: 4px solid #4f46e5;
  border-radius: 14px;
  padding: 14px 16px;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.05);
}
.eval-card.failed {
  border-left-color: #dc2626;
}
.eval-card.streaming {
  border-left-color: #94a3b8;
}
.eval-head {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 12px;
}
.eval-score-block {
  display: flex;
  flex-direction: column;
}
.eval-score-num {
  font-size: 22px;
  font-weight: 800;
  color: #1e293b;
  line-height: 1.1;
}
.eval-score-num .unit {
  font-size: 13px;
  font-weight: 500;
  color: #94a3b8;
  margin-left: 2px;
}
.eval-sub {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 2px;
}
.eval-desc {
  margin-top: 4px;
}
.stream-text {
  font-size: 14px;
  line-height: 1.8;
  color: #4e5969;
  white-space: pre-wrap;
}

/* 作答输入区 */
.composer {
  margin-top: 16px;
  border-top: 1px solid #eef0f4;
  padding-top: 16px;
}
.composer-actions {
  margin-top: 12px;
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.speak-btn-sm {
  color: #4f46e5;
}

.ws-status {
  margin-top: 12px;
  font-size: 12px;
  color: #94a3b8;
}
.caret {
  display: inline-block;
  margin-left: 2px;
  color: #4f46e5;
  animation: blink 1s steps(1) infinite;
}
@keyframes blink {
  50% {
    opacity: 0;
  }
}

/* 入场动画 */
.rise-enter-active {
  transition: all 0.35s ease;
}
.rise-enter-from {
  opacity: 0;
  transform: translateY(10px);
}
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.25s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* 完成页逐题回顾 */
.report {
  text-align: center;
}
.qa-item {
  margin-bottom: 16px;
  padding: 14px 16px;
  background: #f8fafc;
  border: 1px solid #eef0f4;
  border-radius: 12px;
}
.qa-item .q {
  font-weight: 600;
  margin-bottom: 8px;
  color: #1e293b;
  line-height: 1.6;
}
.q-badge {
  display: inline-block;
  font-size: 12px;
  font-weight: 700;
  color: #4f46e5;
  background: #eef2ff;
  border-radius: 6px;
  padding: 1px 8px;
  margin-right: 8px;
}
.q-type {
  display: inline-block;
  font-size: 11px;
  color: #64748b;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 0 7px;
  margin-right: 8px;
}
.qa-item .a {
  color: #4e5969;
  margin-bottom: 8px;
  line-height: 1.7;
}
.qa-item .a.suggest {
  color: #4f46e5;
}

@media (max-width: 640px) {
  .chat {
    max-height: 46vh;
  }
  .bubble,
  .eval-card {
    max-width: 86%;
  }
  .session-position {
    font-size: 16px;
  }
}
</style>
