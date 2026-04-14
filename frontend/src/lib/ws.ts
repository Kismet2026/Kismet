type MessageHandler = (data: unknown) => void;

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "";

export class KismetWebSocket {
  private ws: WebSocket | null = null;
  private handlers = new Set<MessageHandler>();
  private userId: string;
  private matchId: string;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private intentionallyClosed = false;

  constructor(userId: string, matchId: string) {
    this.userId = userId;
    this.matchId = matchId;
  }

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) return;
    this.intentionallyClosed = false;

    const url = `${WS_URL}?userId=${this.userId}&matchId=${this.matchId}`;
    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      this.reconnectAttempts = 0;
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        this.handlers.forEach((handler) => handler(data));
      } catch {
        // ignore non-JSON messages
      }
    };

    this.ws.onclose = () => {
      if (!this.intentionallyClosed) this.scheduleReconnect();
    };

    this.ws.onerror = () => {
      this.ws?.close();
    };
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) return;
    // Exponential backoff: 1s, 2s, 4s, 8s, 16s
    const delay = Math.min(1000 * 2 ** this.reconnectAttempts, 16_000);
    this.reconnectAttempts++;
    this.reconnectTimer = setTimeout(() => this.connect(), delay);
  }

  onMessage(handler: MessageHandler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  disconnect(): void {
    this.intentionallyClosed = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
    this.ws = null;
  }

  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }
}
