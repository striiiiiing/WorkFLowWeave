import type { BaseMessage } from '@langchain/core/messages'
import {
  AIMessage as AIMessageClass,
  HumanMessage as HumanMessageClass,
} from '@langchain/core/messages'
import type {
  AgentServerAdapter as LangGraphAgentServerAdapter,
  Event as ProtocolEvent,
} from '@langchain/vue'
import { createEventSource, type EventConnection } from '@/shared/api/eventSource'
import type { AgentsApi } from '../api/agentsApi'
import { mergeAgentEvents, parseAgentEvent } from '../model/public'
import type { AgentEvent, AgentSession, TurnAccepted } from '../model/public'

type AdapterCommand = Parameters<LangGraphAgentServerAdapter['send']>[0]
type AdapterResponse = Awaited<ReturnType<LangGraphAgentServerAdapter['send']>>
interface EventStreamParams {
  channels: string[]
}
interface EventStreamHandle {
  events: AsyncIterable<EventMessage>
  ready: Promise<void>
  close(): void
}
type EventMessage = ProtocolEvent

interface AgentMessagePart {
  role: 'human' | 'ai'
  id: string
  text: string
  reasoning: string
}

interface MessageProgress {
  started: boolean
  nextBlockIndex: number
  finished: boolean
}

interface AdapterOptions {
  sourceFactory?: (url: string) => EventConnection
  onConnectionState?: (state: 'loading' | 'connected' | 'reconnecting' | 'closed') => void
}

function messageIdentity(event: AgentEvent): string {
  const messageId = event.data.message_id
  const turnId = event.turn_id ?? 'unscoped'
  return `${event.session_id}:${typeof messageId === 'string' && messageId ? messageId : turnId}`
}

function textContent(value: unknown): string {
  if (typeof value === 'string') return value
  if (!Array.isArray(value)) return ''
  return value
    .map((part) =>
      isRecord(part) && part.type === 'text' && typeof part.text === 'string' ? part.text : '',
    )
    .join('')
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function partsFromEvent(
  event: AgentEvent,
  includeCompletedText: boolean,
): Array<{
  type: 'text' | 'reasoning'
  value: string
}> {
  const content = event.data.content
  const fromContent: Array<{ type: 'text' | 'reasoning'; value: string }> = []
  if (Array.isArray(content)) {
    for (const part of content) {
      if (!isRecord(part)) continue
      if (part.type === 'text' && typeof part.text === 'string')
        fromContent.push({ type: 'text', value: part.text })
      else if (part.type === 'reasoning' && typeof part.reasoning === 'string')
        fromContent.push({ type: 'reasoning', value: part.reasoning })
      else if (part.type === 'thinking' && typeof part.thinking === 'string')
        fromContent.push({ type: 'reasoning', value: part.thinking })
    }
  } else if (typeof content === 'string') fromContent.push({ type: 'text', value: content })

  if (event.type === 'message.completed' && includeCompletedText) {
    const text = typeof event.data.text === 'string' ? event.data.text : ''
    if (text) fromContent.push({ type: 'text', value: text })
  }

  const reasoning = typeof event.data.reasoning === 'string' ? event.data.reasoning : ''
  const hasContentReasoning = fromContent.some((part) => part.type === 'reasoning')
  if (reasoning && !hasContentReasoning) fromContent.push({ type: 'reasoning', value: reasoning })
  return fromContent.filter((part) => part.value.length > 0)
}

export function agentHistoryToMessages(events: AgentEvent[]): BaseMessage[] {
  const messages = new Map<string, AgentMessagePart>()
  for (const event of events) {
    if (event.type === 'message.user') {
      const identity = messageIdentity(event)
      messages.set(identity, {
        role: 'human',
        id: identity,
        text: textContent(event.data.text),
        reasoning: '',
      })
      continue
    }
    if (event.type !== 'message.delta' && event.type !== 'message.completed') continue
    const identity = messageIdentity(event)
    const current = messages.get(identity) ?? {
      role: 'ai',
      id: identity,
      text: '',
      reasoning: '',
    }
    for (const part of partsFromEvent(
      event,
      event.type === 'message.completed' && !event.data.incremental,
    ))
      current[part.type] += part.value
    messages.set(identity, current)
  }

  return [...messages.values()].map((message) => {
    if (message.role === 'human')
      return new HumanMessageClass({ id: message.id, content: message.text })
    const content: Array<{ type: string; text?: string; reasoning?: string }> = []
    if (message.text) content.push({ type: 'text', text: message.text })
    if (message.reasoning) content.push({ type: 'reasoning', reasoning: message.reasoning })
    return new AIMessageClass({ id: message.id, content })
  })
}

function sourceText(value: unknown): string {
  if (typeof value === 'string') return value
  if (Array.isArray(value))
    return value
      .map((part) =>
        isRecord(part) && part.type === 'text' && typeof part.text === 'string' ? part.text : '',
      )
      .join('')
  return ''
}

function timestamp(event: AgentEvent): number {
  const value = Date.parse(event.at)
  if (!Number.isFinite(value)) throw new Error(`Agent 事件 ${event.id} 的时间戳无效`)
  return value
}

function makeProtocolEvent(
  event: AgentEvent,
  index: number,
  method: string,
  data: Record<string, unknown>,
): ProtocolEvent {
  return {
    type: 'event',
    event_id: `${event.session_id}:${event.id}:${method}:${index}`,
    seq: event.id,
    method,
    params: { namespace: [], timestamp: timestamp(event), data },
  } as ProtocolEvent
}

function messageProtocolEvents(
  event: AgentEvent,
  progress: Map<string, MessageProgress>,
  startIndex: number,
): ProtocolEvent[] {
  const identity = messageIdentity(event)
  const state = progress.get(identity) ?? { started: false, nextBlockIndex: 0, finished: false }
  const protocol: ProtocolEvent[] = []
  let index = startIndex

  const add = (data: Record<string, unknown>) => {
    protocol.push(makeProtocolEvent(event, index++, 'messages', data))
  }
  const startMessage = (role: 'ai' | 'human') => {
    if (state.started) return
    add({ event: 'message-start', role, id: identity })
    state.started = true
  }
  const addBlock = (part: { type: 'text' | 'reasoning'; value: string }) => {
    const blockIndex = state.nextBlockIndex++
    const content =
      part.type === 'text' ? { type: 'text', text: '' } : { type: 'reasoning', reasoning: '' }
    const delta =
      part.type === 'text'
        ? { type: 'text-delta', text: part.value }
        : { type: 'reasoning-delta', reasoning: part.value }
    const finalContent =
      part.type === 'text'
        ? { type: 'text', text: part.value }
        : { type: 'reasoning', reasoning: part.value }
    add({ event: 'content-block-start', index: blockIndex, content })
    add({ event: 'content-block-delta', index: blockIndex, delta })
    add({ event: 'content-block-finish', index: blockIndex, content: finalContent })
  }

  if (event.type === 'message.user') {
    startMessage('human')
    const text = sourceText(event.data.text)
    if (text) addBlock({ type: 'text', value: text })
    add({ event: 'message-finish' })
    state.finished = true
  } else if (event.type === 'message.delta' || event.type === 'message.completed') {
    startMessage('ai')
    const includeCompletedText = event.type === 'message.completed' && !event.data.incremental
    for (const part of partsFromEvent(event, includeCompletedText)) addBlock(part)
    if (event.type === 'message.completed') {
      add({ event: 'message-finish' })
      state.finished = true
    }
  }

  progress.set(identity, state)
  return protocol
}

function specializedProtocolEvents(
  event: AgentEvent,
  progress: Map<string, MessageProgress>,
): ProtocolEvent[] {
  const output: ProtocolEvent[] = []
  let index = 0
  const add = (method: string, data: Record<string, unknown>) => {
    output.push(makeProtocolEvent(event, index++, method, data))
  }

  if (event.type.startsWith('message.')) output.push(...messageProtocolEvents(event, progress, 0))
  else if (event.type.startsWith('turn.')) {
    const lifecycle =
      event.type === 'turn.started'
        ? 'started'
        : event.type === 'turn.completed'
          ? 'completed'
          : event.type === 'turn.failed'
            ? 'failed'
            : event.type === 'turn.cancelled' || event.type === 'turn.interrupted'
              ? 'interrupted'
              : undefined
    if (lifecycle)
      add('lifecycle', {
        event: lifecycle,
        ...(typeof event.data.error === 'string' ? { error: event.data.error } : {}),
      })
  } else if (event.type === 'tool.started') {
    add('tools', {
      event: 'tool-started',
      tool_call_id: event.data.tool_call_id ?? event.data.tool_key,
      tool_name: event.data.name ?? 'unknown',
      input: event.data.arguments,
    })
  } else if (event.type === 'tool.completed') {
    add('tools', {
      event: 'tool-finished',
      tool_call_id: event.data.tool_call_id ?? event.data.tool_key,
      output: event.data.result,
    })
  } else if (event.type === 'tool.outcome_unknown') {
    add('tools', {
      event: 'tool-error',
      tool_call_id: event.data.tool_call_id ?? event.data.tool_key,
      message: '工具结果未知，不会自动重做',
    })
  }
  return output
}

function eventsForSubscription(
  event: AgentEvent,
  params: EventStreamParams,
  progress: Map<string, MessageProgress>,
): EventMessage[] {
  const result: EventMessage[] = []
  const hasCustom = params.channels.includes('custom') || params.channels.includes('custom:agent')
  if (hasCustom)
    result.push(
      makeProtocolEvent(event, 0, 'custom', {
        name: 'agent',
        payload: event,
      }),
    )

  for (const protocolEvent of specializedProtocolEvents(event, progress)) {
    const method = String(protocolEvent.method)
    const channel = method === 'input.requested' ? 'input' : method
    if (params.channels.includes(channel as (typeof params.channels)[number]))
      result.push(protocolEvent)
  }
  return result
}

function protocolStateMessages(events: AgentEvent[]): BaseMessage[] {
  return agentHistoryToMessages(events)
}

function requestMessage(input: unknown): string {
  if (!isRecord(input) || !Array.isArray(input.messages))
    throw new Error('LangChain submit 缺少 Agent 消息')
  const message = [...input.messages].reverse().find((item) => {
    if (!isRecord(item)) return false
    return item.type === 'human' || item.type === 'user' || item.role === 'user'
  })
  if (!isRecord(message)) throw new Error('LangChain submit 缺少用户消息')
  const text = sourceText(message.content)
  if (!text.trim()) throw new Error('Agent 消息不能为空')
  return text
}

function errorText(cause: unknown): string {
  if (cause instanceof Error) return cause.message
  if (typeof cause === 'string') return cause
  return 'Agent 请求失败'
}

class AsyncMessageQueue<T> implements AsyncIterable<T> {
  #values: T[] = []
  #waiters: Array<{
    resolve: (result: IteratorResult<T>) => void
    reject: (cause: unknown) => void
  }> = []
  #closed = false
  #failure: unknown

  push(value: T) {
    if (this.#closed) return
    const waiter = this.#waiters.shift()
    if (waiter) waiter.resolve({ done: false, value })
    else this.#values.push(value)
  }

  fail(cause: unknown) {
    if (this.#closed) return
    this.#failure = cause
    this.#closed = true
    for (const waiter of this.#waiters.splice(0)) waiter.reject(cause)
  }

  close() {
    this.#closed = true
    for (const waiter of this.#waiters.splice(0)) waiter.resolve({ done: true, value: undefined })
  }

  [Symbol.asyncIterator](): AsyncIterator<T> {
    return {
      next: () => {
        if (this.#values.length)
          return Promise.resolve({ done: false, value: this.#values.shift()! })
        if (this.#failure) return Promise.reject(this.#failure)
        if (this.#closed) return Promise.resolve({ done: true, value: undefined })
        return new Promise((resolve, reject) => this.#waiters.push({ resolve, reject }))
      },
      return: async () => {
        this.close()
        return { done: true, value: undefined }
      },
    }
  }
}

export class AgentServerAdapter implements LangGraphAgentServerAdapter {
  #sessionId = ''
  #sources = new Map<() => void, 'loading' | 'connected' | 'reconnecting'>()
  #sourceFactory: (url: string) => EventConnection
  #onConnectionState?: AdapterOptions['onConnectionState']
  #reportedConnectionState?: 'loading' | 'connected' | 'reconnecting' | 'closed'
  #submissionWaiters = new Map<
    string,
    {
      promise: Promise<TurnAccepted>
      resolve: (accepted: TurnAccepted) => void
      reject: (cause: unknown) => void
    }
  >()
  #snapshot?: { session: AgentSession; events: AgentEvent[] }

  constructor(
    private readonly api: AgentsApi,
    options: AdapterOptions = {},
  ) {
    this.#sourceFactory = options.sourceFactory ?? ((url) => new EventSource(url))
    this.#onConnectionState = options.onConnectionState
  }

  get threadId(): string {
    return this.#sessionId
  }

  setThreadId(threadId: string) {
    if (threadId === this.#sessionId) return
    this.#closeSources()
    this.#sessionId = threadId
  }

  async open(): Promise<void> {}

  async send(command: AdapterCommand): Promise<AdapterResponse> {
    try {
      if (command.method === 'run.start') return await this.#submit(command)
      if (command.method === 'state.get') {
        const state = await this.getState()
        return {
          type: 'success',
          id: command.id,
          result: state
            ? {
                values: state.values,
                next: state.next,
                tasks: state.tasks,
                checkpoint: state.checkpoint,
                parent_checkpoint: state.parent_checkpoint,
                metadata: state.metadata,
              }
            : { values: { messages: [] }, next: [] },
        }
      }
      if (command.method === 'state.fork') return await this.#forkCheckpoint(command)
      if (command.method === 'subscription.subscribe')
        return {
          type: 'success',
          id: command.id,
          result: { subscription_id: `agent-${command.id}` },
        }
      if (command.method === 'subscription.unsubscribe')
        return { type: 'success', id: command.id, result: {} }
      return {
        type: 'error',
        id: command.id,
        error: 'not_supported',
        message: `WorkFLowWeave 不支持 ${command.method}`,
      }
    } catch (cause) {
      const requestId = this.#requestIdFromCommand(command)
      if (requestId) this.#rejectSubmission(requestId, cause)
      return {
        type: 'error',
        id: command.id,
        error: 'unknown_error',
        message: errorText(cause),
      }
    }
  }

  async *events(): AsyncIterable<never> {}

  openEventStream(params: EventStreamParams): EventStreamHandle {
    const sessionId = this.#requireSession()
    const queue = new AsyncMessageQueue<EventMessage>()
    const transport = createEventSource(this.#sourceFactory)
    const progress = new Map<string, MessageProgress>()
    let cursor = 0
    let resolveReady!: () => void
    let rejectReady!: (cause: unknown) => void
    let readyResolved = false
    const ready = new Promise<void>((resolve, reject) => {
      resolveReady = resolve
      rejectReady = reject
    })
    const release = () => {
      if (!this.#sources.delete(release)) return
      if (!readyResolved) {
        readyResolved = true
        resolveReady()
      }
      transport.close()
      queue.close()
      this.#reportConnectionState()
    }
    this.#sources.set(release, 'loading')
    this.#reportConnectionState()

    transport.open({
      url: () =>
        `/api/channels/web/sessions/${encodeURIComponent(sessionId)}/events?after=${cursor}`,
      parse: parseAgentEvent,
      data: (event) => {
        if (event.session_id !== sessionId) {
          const cause = new Error('Agent 事件会话不匹配')
          if (!readyResolved) rejectReady(cause)
          queue.fail(cause)
          release()
          return
        }
        cursor = Math.max(cursor, event.id)
        for (const protocolEvent of eventsForSubscription(event, params, progress))
          queue.push(protocolEvent)
      },
      state: (state) => {
        if (!this.#sources.has(release)) return
        this.#sources.set(release, state)
        this.#reportConnectionState()
        if (state === 'connected' && !readyResolved) {
          readyResolved = true
          resolveReady()
        }
      },
      error: (cause) => {
        if (!readyResolved) {
          readyResolved = true
          rejectReady(cause)
        }
        queue.fail(cause)
        release()
      },
    })

    return { events: queue, ready, close: release }
  }

  async close(): Promise<void> {
    this.#closeSources()
  }

  async getState<StateType = unknown>(): Promise<{
    values: StateType
    next?: unknown
    tasks?: unknown
    checkpoint?: { checkpoint_id?: string } | null
    parent_checkpoint?: { checkpoint_id?: string } | null
    metadata?: Record<string, unknown>
  } | null> {
    const sessionId = this.#requireSession()
    const snapshot = this.#snapshot?.session.session_id === sessionId ? this.#snapshot : undefined
    const [events, session] = snapshot
      ? ([snapshot.events, snapshot.session] as const)
      : await Promise.all([
          this.api.history(sessionId).then((history) => history.map(parseAgentEvent)),
          this.api.get(sessionId),
        ])
    const lastCheckpoint = [...events]
      .reverse()
      .find(
        (event) => event.type === 'turn.completed' && typeof event.data.checkpoint_id === 'string',
      )
    const values = { messages: protocolStateMessages(events) } as StateType
    return {
      values,
      ...(session.status === 'running' ? {} : { next: [] }),
      checkpoint: lastCheckpoint
        ? { checkpoint_id: String(lastCheckpoint.data.checkpoint_id) }
        : null,
      metadata: { session_id: session.session_id, status: session.status },
    }
  }

  async getHistory<StateType = unknown>(options?: {
    limit?: number
  }): Promise<Array<{ values: StateType; checkpoint?: { checkpoint_id?: string } | null }>> {
    const sessionId = this.#requireSession()
    const events =
      this.#snapshot?.session.session_id === sessionId
        ? this.#snapshot.events
        : (await this.api.history(sessionId)).map(parseAgentEvent)
    const checkpointEvents = events.filter(
      (event) => event.type === 'turn.completed' && typeof event.data.checkpoint_id === 'string',
    )
    const limit = options?.limit
    const selected =
      limit === undefined
        ? checkpointEvents
        : checkpointEvents.slice(
            Math.max(0, checkpointEvents.length - Math.max(0, Math.floor(limit))),
          )
    return selected.reverse().map((checkpoint) => {
      const end = events.indexOf(checkpoint)
      return {
        values: { messages: protocolStateMessages(events.slice(0, end + 1)) } as StateType,
        checkpoint: { checkpoint_id: String(checkpoint.data.checkpoint_id) },
      }
    })
  }

  async submit(
    sessionId: string,
    text: string,
    requestId: string,
    append: boolean,
  ): Promise<TurnAccepted> {
    if (this.#requireSession() !== sessionId) throw new Error('Agent session 已切换')
    const accepted = append
      ? await this.api.append(sessionId, requestId, text)
      : await this.api.send(sessionId, requestId, text)
    return accepted
  }

  waitForSubmission(requestId: string): Promise<TurnAccepted> {
    const existing = this.#submissionWaiters.get(requestId)
    if (existing) return existing.promise
    let resolve!: (accepted: TurnAccepted) => void
    let reject!: (cause: unknown) => void
    const promise = new Promise<TurnAccepted>((resolvePromise, rejectPromise) => {
      resolve = resolvePromise
      reject = rejectPromise
    })
    this.#submissionWaiters.set(requestId, { promise, resolve, reject })
    return promise
  }

  rejectSubmission(requestId: string, cause: unknown) {
    this.#rejectSubmission(requestId, cause)
  }

  async cancel(sessionId: string): Promise<AgentSession> {
    if (this.#requireSession() !== sessionId) throw new Error('Agent session 已切换')
    return this.api.cancel(sessionId)
  }

  fork(
    sessionId: string,
    payload: { turn_id?: string; model?: string; message_id?: string } = {},
  ): ReturnType<AgentsApi['fork']> {
    const activeSession = this.#requireSession()
    if (
      sessionId !== activeSession &&
      !this.#snapshot?.events.some((event) => event.session_id === sessionId)
    )
      throw new Error('Agent 分支来源不属于当前会话历史')
    return this.api.fork(sessionId, payload)
  }

  seedEvents(events: AgentEvent[]) {
    return mergeAgentEvents([], events.map(parseAgentEvent))
  }

  seedSession(session: AgentSession, events: AgentEvent[]) {
    this.#snapshot = { session, events: this.seedEvents(events) }
  }

  #requireSession(): string {
    if (!this.#sessionId) throw new Error('Agent stream 没有绑定会话')
    return this.#sessionId
  }

  #closeSources() {
    for (const close of [...this.#sources.keys()]) close()
  }

  #reportConnectionState() {
    const states = [...this.#sources.values()]
    const next = states.includes('connected')
      ? 'connected'
      : states.includes('reconnecting')
        ? 'reconnecting'
        : states.length
          ? 'loading'
          : 'closed'
    if (next === this.#reportedConnectionState) return
    this.#reportedConnectionState = next
    this.#onConnectionState?.(next)
  }

  async #submit(
    command: Extract<AdapterCommand, { method: 'run.start' }>,
  ): Promise<AdapterResponse> {
    const sessionId = this.#requireSession()
    const params = command.params
    const metadata = isRecord(params.metadata) ? params.metadata : {}
    const requestId = typeof metadata.agent_request_id === 'string' ? metadata.agent_request_id : ''
    if (!requestId) throw new Error('LangChain submit 缺少 request_id')
    const accepted =
      metadata.agent_action === 'compact'
        ? await this.api.compact(sessionId)
        : await this.submit(
            sessionId,
            requestMessage(params.input),
            requestId,
            metadata.agent_action === 'append',
          )
    this.#resolveSubmission(requestId, accepted)
    return {
      type: 'success',
      id: command.id,
      result: { run_id: accepted.turn_id },
    }
  }

  async #forkCheckpoint(
    command: Extract<AdapterCommand, { method: 'state.fork' }>,
  ): Promise<AdapterResponse> {
    const sessionId = this.#requireSession()
    const history = (await this.api.history(sessionId)).map(parseAgentEvent)
    const event = [...history]
      .reverse()
      .find(
        (item) =>
          item.type === 'turn.completed' &&
          item.data.checkpoint_id === command.params.checkpoint_id &&
          typeof item.turn_id === 'string',
      )
    if (!event?.turn_id) throw new Error('Agent checkpoint 不存在或不能创建分支')
    const forked = await this.api.fork(event.session_id, { turn_id: event.turn_id })
    return {
      type: 'success',
      id: command.id,
      result: { thread_id: forked.session_id, run_id: '' },
    }
  }

  #requestIdFromCommand(command: AdapterCommand): string | undefined {
    if (command.method !== 'run.start' || !isRecord(command.params.metadata)) return
    const requestId = command.params.metadata.agent_request_id
    return typeof requestId === 'string' && requestId ? requestId : undefined
  }

  #resolveSubmission(requestId: string, accepted: TurnAccepted) {
    const waiter = this.#submissionWaiters.get(requestId)
    if (!waiter) return
    this.#submissionWaiters.delete(requestId)
    waiter.resolve(accepted)
  }

  #rejectSubmission(requestId: string, cause: unknown) {
    const waiter = this.#submissionWaiters.get(requestId)
    if (!waiter) return
    this.#submissionWaiters.delete(requestId)
    waiter.reject(cause)
  }
}
