# Chat Duplicate Messages Postmortem — 2026-04-14

## Summary

Messages appeared twice on the sender's screen in chat. The root cause was **three competing message sources** writing to the same React state: optimistic insert, WebSocket echo, and HTTP polling — each adding the same message independently.

发送者在聊天界面看到自己的消息出现两遍。根本原因是**三个数据源同时往同一个 React state 写入**：乐观插入、WebSocket 回声、HTTP 轮询，各自独立添加同一条消息。

## Root Cause

### The Triple-Write Problem

When a user sends a message, three things happen almost simultaneously:

```
1. Optimistic Insert     →  setMessages([...prev, tempMsg])     // messageId: "temp-123"
2. WebSocket Echo        →  setMessages([...prev, wsMsg])       // messageId: "uuid-abc"
3. HTTP Poll (5s later)  →  setMessages([...prev, ...serverMsgs]) // messageId: "uuid-abc"
```

The same message appears with different IDs (`temp-123` from optimistic, `uuid-abc` from server), so deduplication by `messageId` fails. Result: 2-3 copies of the same message.

用户发送消息时，三件事几乎同时发生：
1. **乐观插入** — 立刻在本地添加 `temp-123`
2. **WebSocket 回声** — D3 的 `send_message.py` 广播给所有连接（包括发送者），添加 `uuid-abc`
3. **HTTP 轮询** — 5 秒后从服务器拉取，再次添加 `uuid-abc`

同一条消息有不同 ID（`temp-123` vs `uuid-abc`），按 messageId 去重失败。结果：同一条消息出现 2-3 次。

### Failed Fix Attempts

| Attempt | Approach | Why it failed |
|---------|----------|---------------|
| 1 | Filter WS messages where `senderId === myId` | WS broadcast sends back message with a different structure; `senderId` field name/format sometimes didn't match |
| 2 | Merge optimistic with server messages by keeping `temp-*` IDs | Poll returned server messages + old temp messages coexisted; content-based dedup is unreliable |
| 3 | Deduplicate by `messageId` in WS handler | Only catches exact ID matches; temp vs server IDs are always different |

## Correct Solution: Server as Single Source of Truth

**服务器是唯一数据源。** Stop trying to merge multiple sources client-side. Instead:

```typescript
// fetchMessages: always REPLACE state with server data
const fetchMessages = async () => {
  const data = await api.get(`/messages/match/${matchId}?limit=50`);
  setMessages(data.items.sort(...));  // Full replacement, no merge
};

// WebSocket: only used as a NOTIFICATION to trigger fetch
ws.onMessage(() => {
  fetchMessages();  // Don't add message directly — just re-fetch
});

// sendMessage: optimistic insert + delayed fetch
const sendMessage = async (content) => {
  setMessages(prev => [...prev, tempMsg]);  // Show immediately
  ws.send({ action: "sendMessage", content });
  setTimeout(fetchMessages, 1000);  // Replace temp with real after 1s
};
```

### Key Principles

1. **`setMessages(sorted)` not `setMessages(prev => [...prev, ...new])`**
   - Always replace, never merge. The server knows the truth.
   - 始终替换，从不合并。服务器知道真相。

2. **WebSocket = notification channel, not data channel**
   - WS events trigger `fetchMessages()`, they don't directly modify state.
   - WS 事件只触发 `fetchMessages()`，不直接修改状态。

3. **Optimistic insert is temporary**
   - `temp-*` message lives for ~1 second until the next `fetchMessages()` replaces it.
   - `temp-*` 消息只存活约 1 秒，直到下次 `fetchMessages()` 替换它。

4. **Multiple fetch calls are safe**
   - Calling `fetchMessages()` from WS handler, from timer, and from `setTimeout` after send — all fine because each call replaces state entirely.
   - 从 WS、定时器、发送后 setTimeout 多次调用 `fetchMessages()` 都安全，因为每次都是完全替换。

## Architecture

```
                    ┌─────────────────────┐
                    │   React State       │
                    │   messages: []      │
                    └──────▲──────────────┘
                           │
                    setMessages(sorted)    ← always full replacement
                           │
                    ┌──────┴──────────────┐
                    │   fetchMessages()   │
                    │   GET /messages/... │
                    └──────▲──▲──▲────────┘
                           │  │  │
              ┌────────────┘  │  └────────────┐
              │               │               │
        On mount         WS event        Every 5s poll
        (initial)     (notification)      (backup)
                     + 1s after send
```

## Lesson Learned

**Don't build a client-side CRDT when you have a reliable server.**

Real-time chat seems like it needs complex client-side state management (merge, dedup, conflict resolution). It doesn't. If you have a REST API that returns the full conversation, just call it. Use WebSocket purely as a "something changed" signal. The ~100ms extra latency is invisible to users and eliminates an entire class of consistency bugs.

**不要在有可靠服务器的情况下在客户端构建 CRDT。**

实时聊天看似需要复杂的客户端状态管理（合并、去重、冲突解决）。其实不需要。如果有一个返回完整对话的 REST API，直接调就行。WebSocket 纯粹作为"有变化了"的信号。多出的约 100ms 延迟对用户不可见，却消除了一整类一致性 bug。
