export const RECONNECT_MIN_MS = 500
export const RECONNECT_MAX_MS = 5000

export type EventConnection = Pick<EventSource, 'onopen' | 'onmessage' | 'onerror' | 'close'> &
  Partial<Pick<EventSource, 'addEventListener'>>

export interface EventSubscription<T> {
  url: () => string
  event?: string
  parse: (value: unknown) => T
  data: (value: T) => void
  state: (state: 'connected' | 'reconnecting') => void
  error: (cause: unknown) => void
}

export function createEventSource(
  sourceFactory: (url: string) => EventConnection = (url) => new EventSource(url),
  clock: Pick<typeof globalThis, 'setTimeout' | 'clearTimeout'> = globalThis,
) {
  let source: EventConnection | undefined
  let timer: ReturnType<typeof setTimeout> | undefined
  let generation = 0
  let attempts = 0

  function release() {
    source?.close()
    source = undefined
    if (timer !== undefined) clock.clearTimeout(timer)
    timer = undefined
  }

  function close() {
    generation++
    release()
  }

  function open<T>(subscription: EventSubscription<T>) {
    close()
    attempts = 0
    const owner = generation

    function connect() {
      if (owner !== generation || source) return
      const connection = sourceFactory(subscription.url())
      source = connection
      const current = () => owner === generation && source === connection
      connection.onopen = () => {
        if (!current()) return
        attempts = 0
        subscription.state('connected')
      }
      const read = (message: MessageEvent<string>) => {
        if (!current()) return
        try {
          subscription.data(subscription.parse(JSON.parse(message.data)))
        } catch (cause) {
          close()
          subscription.error(cause)
        }
      }
      if (subscription.event) {
        if (!connection.addEventListener) throw new Error('EventSource 不支持命名事件')
        connection.addEventListener(subscription.event, read as EventListener)
      } else connection.onmessage = read
      connection.onerror = () => {
        if (!current()) return
        release()
        subscription.state('reconnecting')
        timer = clock.setTimeout(
          connect,
          Math.min(RECONNECT_MIN_MS * 2 ** attempts++, RECONNECT_MAX_MS),
        )
      }
    }

    connect()
  }

  return { open, close }
}
