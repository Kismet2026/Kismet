# Kismet — 微服务通信指南

> 这篇文档解释 Kismet 25 个微服务之间是如何通信的。
> 如果你对"多线程"、"异步"、"事件驱动"等概念有疑问，这篇文档可以帮你理清。

---

## 1. 先澄清几个概念

| 概念 | 定义 | 和 Kismet 的关系 |
|------|------|-----------------|
| **多线程 (Multithreading)** | 一个程序内部，多个线程同时执行代码，共享同一块内存 | Kismet **不涉及多线程**。每个 Lambda 函数就是一个独立的小程序，处理一个请求，处理完就结束 |
| **并发 (Concurrency)** | 多件事情同时发生 | 25 个 Lambda 可以同时处理不同用户的请求——这是 AWS 自动管理的并发，不需要你写代码 |
| **同步 (Synchronous)** | 发请求 → 等回复 → 拿到结果后才继续 | 前端调用 `POST /swipe` → 等 Lambda 返回 `{matched: true}` |
| **异步 (Asynchronous)** | 发消息 → 不等回复 → 继续做别的事 | Match Service 发一个 `match.created` 事件到 EventBridge → 不管谁什么时候处理 → 立刻返回 |

**一句话：我们的架构不是多线程，而是"多个独立的 Lambda 通过事件异步通信"。**

---

## 2. 两种通信模式

Kismet 的 25 个微服务之间，有且只有两种通信方式：

### 模式一：同步 HTTP 调用

```
前端（React）──HTTP 请求──→ API Gateway ──→ Lambda ──→ 返回响应 ──→ 前端拿到数据
```

**特点：** 调用方发请求后**等着**，直到拿到响应才继续。

**什么时候用：** 前端需要立刻拿到结果的场景。

**例子 —— 用户浏览发现页：**

```
1. 前端发请求: GET /discovery?age=20-25&location=boston
2. API Gateway 转发给 Discovery Lambda
3. Discovery Lambda 查 DynamoDB，拿到候选人列表
4. Discovery Lambda 调 Recommendation Lambda（HTTP）拿到排序分数
5. 返回排好序的候选人列表给前端
6. 前端展示
```

用户在等这个列表，所以必须同步。

### 模式二：异步事件（通过 EventBridge）

```
Lambda A ──发事件──→ EventBridge ──分发──→ Lambda B（独立处理）
                                        → Lambda C（独立处理）
                                        → Lambda D（独立处理）
```

**特点：** 发送方发完事件就**立刻返回**，不知道也不关心谁会处理这个事件。

**什么时候用：** 后续操作不影响当前请求的结果，可以在后台慢慢处理。

**例子 —— 用户划右匹配成功：**

```
1. 前端发请求: POST /swipe {targetUserId: "456", action: "like"}

2. Swipe Lambda:
   - 写入 DynamoDB（记录这次 like）
   - 发事件 swipe.created 到 EventBridge
   - 立刻返回给前端 {status: "ok"} ✅    ← 用户的请求到这里就结束了

3. EventBridge 在后台异步分发 swipe.created:
   └→ Match Lambda 收到事件
      - 查 DynamoDB：对方也 like 了我吗？
      - 是！→ 创建 match 记录
      - 发事件 match.created 到 EventBridge

4. EventBridge 继续异步分发 match.created:
   ├→ Push Notification Lambda → 给两个用户发推送 "It's a match!"
   ├→ Email Lambda → 给两个用户发邮件
   ├→ Icebreaker Lambda → 用 Bedrock 生成破冰话题
   └→ Activity Logger Lambda → 记录到 Kinesis 数据流
```

注意：步骤 3 和 4 完全在后台发生，用户在步骤 2 就已经拿到响应了。

---

## 3. 完整通信流程图

下图展示了一次"划右匹配"触发的完整事件链：

```
用户操作
  │
  ▼
┌─────────────┐    POST /swipe     ┌──────────────┐
│   React     │ ──────────────────→│ API Gateway  │
│   前端      │ ←────────────────  │  (REST)      │
└─────────────┘   {status: "ok"}   └──────┬───────┘
                                          │
                                          ▼
                                   ┌──────────────┐
                                   │Swipe Lambda  │
                                   │ 写入 DynamoDB │
                                   └──────┬───────┘
                                          │ 发事件
                                          ▼
                              ┌───────────────────────┐
                              │   EventBridge Bus     │
                              │   (kismet-events)     │
                              └───┬───┬───┬───┬───────┘
             swipe.created 触发:  │   │   │   │
                                  │   │   │   │
                    ┌─────────────▼┐  │   │   │
                    │Match Lambda  │  │   │   │
                    │检测双向 like  │  │   │   │
                    └──────┬───────┘  │   │   │
                           │          │   │   │
                    发事件 match.created   │   │
                           │          │   │   │
              ┌────────────▼──────────▼───▼───▼──────────┐
              │          EventBridge Bus                  │
              └──┬──────────┬──────────┬────────────┬────┘
                 │          │          │            │
          ┌──────▼───┐ ┌───▼────┐ ┌───▼──────┐ ┌──▼───────┐
          │Push 推送  │ │Email   │ │Icebreaker│ │Activity  │
          │Lambda    │ │Lambda  │ │Lambda    │ │Logger    │
          │→ SNS 推送│ │→ SES   │ │→ Bedrock │ │→ Kinesis │
          └──────────┘ └────────┘ └──────────┘ └──────────┘
```

**关键点：**
- 用户只等到 Swipe Lambda 返回（~100ms）
- 后面的 5 个 Lambda 全部异步执行，互不阻塞
- 任何一个挂了都不影响其他的

---

## 4. Lambda 的并发模型

### 为什么不需要考虑多线程？

传统后端（比如 Java Spring Boot）：
```
一个服务器进程 → 开多个线程 → 同时处理多个请求 → 线程之间共享内存 → 需要加锁、防竞态
```

Lambda 的方式：
```
请求 A → AWS 启动 Lambda 实例 1 → 处理完 → 销毁
请求 B → AWS 启动 Lambda 实例 2 → 处理完 → 销毁
请求 C → AWS 启动 Lambda 实例 3 → 处理完 → 销毁
```

**每个请求都是独立的 Lambda 实例，互相不共享任何东西。** 不存在多线程竞争的问题。

如果同时来了 100 个请求，AWS 就启动 100 个 Lambda 实例，各自独立运行。这就是 Lambda 的"自动扩缩容"——你不需要管并发，AWS 帮你管。

### 那数据一致性怎么办？

既然每个 Lambda 独立运行，如果两个用户同时互相 like，Match Service 怎么保证不创建两个重复的 match？

答案是 **DynamoDB 条件写入**：

```python
# Match Lambda 里的代码
table.put_item(
    Item={'matchId': match_id, 'users': [user_a, user_b]},
    ConditionExpression='attribute_not_exists(matchId)'  # 如果已存在就失败
)
```

数据库层面保证唯一性，不需要多线程锁。

---

## 5. 什么时候用同步、什么时候用异步？

### 决策指南

```
前端需要立刻拿到结果吗？
  │
  ├─ 是 → 用同步 HTTP
  │       例：GET /discovery, GET /messages, POST /auth/login
  │
  └─ 否 → 用异步 EventBridge
          例：发推送、发邮件、记日志、内容审核
```

### Kismet 中的具体分类

| 同步 HTTP（前端直接调用，等结果） | 异步事件（后台处理，不阻塞用户） |
|----------------------------------|--------------------------------|
| 登录 / 注册 | 发送欢迎邮件 |
| 获取个人资料 | 图片审核（上传后异步扫描） |
| 浏览发现页 | 文字审核（发消息后异步扫描） |
| 划右/划左 | 匹配后发推送 |
| 获取聊天记录 | 匹配后生成破冰话题 |
| 发送消息 | 记录用户行为到数据湖 |
| 获取 BaZi 分数 | 定时任务（周报邮件等） |

---

## 6. EventBridge 事件一览

以下是 Kismet 中所有跨域事件的约定格式：

### match.created

```json
{
  "source": "kismet.match-service",
  "detail-type": "match.created",
  "detail": {
    "matchId": "match-789",
    "userIds": ["user-123", "user-456"],
    "timestamp": "2026-04-01T12:00:00Z"
  }
}
```

**发送者：** Match Service
**接收者：** Push Notification, Email, Icebreaker, Activity Logger

### message.sent

```json
{
  "source": "kismet.message-service",
  "detail-type": "message.sent",
  "detail": {
    "messageId": "msg-001",
    "matchId": "match-789",
    "senderId": "user-123",
    "content": "Hey! Nice to meet you",
    "timestamp": "2026-04-01T12:05:00Z"
  }
}
```

**发送者：** Message Service
**接收者：** Text Moderation, Activity Logger

### photo.uploaded

```json
{
  "source": "kismet.photo-service",
  "detail-type": "photo.uploaded",
  "detail": {
    "photoId": "photo-001",
    "userId": "user-123",
    "s3Key": "photos/user-123/photo-001.jpg",
    "timestamp": "2026-04-01T11:00:00Z"
  }
}
```

**发送者：** Photo Service
**接收者：** Image Moderation, Activity Logger

### user.created

```json
{
  "source": "kismet.auth-service",
  "detail-type": "user.created",
  "detail": {
    "userId": "user-123",
    "email": "alice@example.com",
    "timestamp": "2026-04-01T10:00:00Z"
  }
}
```

**发送者：** Auth Service
**接收者：** Email Service (发欢迎邮件), Activity Logger

### user.reported

```json
{
  "source": "kismet.report-service",
  "detail-type": "user.reported",
  "detail": {
    "reportId": "report-001",
    "reporterId": "user-123",
    "reportedUserId": "user-456",
    "reason": "inappropriate behavior",
    "timestamp": "2026-04-01T14:00:00Z"
  }
}
```

**发送者：** Report Service
**接收者：** Admin Dashboard, Email Service (通知管理员), Activity Logger

### swipe.created

```json
{
  "source": "kismet.swipe-service",
  "detail-type": "swipe.created",
  "detail": {
    "userId": "user-123",
    "targetUserId": "user-456",
    "action": "like",
    "timestamp": "2026-04-01T12:00:00Z"
  }
}
```

**发送者：** Swipe Service
**接收者：** Match Service, Activity Logger

### profile.completed

```json
{
  "source": "kismet.profile-service",
  "detail-type": "profile.completed",
  "detail": {
    "userId": "user-123",
    "timestamp": "2026-04-01T10:30:00Z"
  }
}
```

**发送者：** Profile Service
**接收者：** Recommendation Service (开始索引), Activity Logger

---

## 7. FAQ

### Q: 我的 Service 需要调用另一个 Service 的数据怎么办？

**不要直接读别人的 DynamoDB 表。** 每个 service 的数据库是私有的。

正确做法：
- **同步需要：** 通过 HTTP 调用对方的 API（例：Recommendation Service 调 `GET /profiles/{userId}`）
- **异步需要：** 监听对方发的事件（例：Notification 监听 `match.created`）

### Q: EventBridge 事件会丢吗？

几乎不会。EventBridge 保证 at-least-once delivery（至少投递一次）。极端情况下可能收到重复事件，所以你的 Lambda 应该做**幂等处理**——即同一个事件处理两次，结果应该一样。

实际做法：用 `matchId` 或 `messageId` 作为唯一键，写 DynamoDB 时加 `ConditionExpression` 防重复。

### Q: 如果我的 Lambda 处理事件失败了怎么办？

EventBridge 会自动重试。你也可以配置死信队列（DLQ）把多次失败的事件存起来，后面排查。

对于课程项目，不需要配 DLQ——关注 CloudWatch Logs 里的错误日志即可。

### Q: 我怎么在本地测试事件？

可以用 AWS CLI 手动发事件：

```bash
aws events put-events --entries '[{
  "Source": "kismet.swipe-service",
  "DetailType": "swipe.created",
  "Detail": "{\"userId\":\"user-123\",\"targetUserId\":\"user-456\",\"action\":\"like\"}",
  "EventBusName": "kismet-events"
}]'
```

然后去 CloudWatch Logs 查看你的 Lambda 是否被触发。

### Q: 前端怎么知道后台异步操作完成了？

两种方式：
1. **推送通知：** 异步操作完成后，Notification Service 发推送给前端（需要 WebSocket 或 push notification）
2. **轮询：** 前端定时查询状态（例：每 5 秒调一次 `GET /matches` 看有没有新匹配）

对于 Kismet，推荐用**轮询**——简单可靠。

---

*配套文档：[Infrastructure Design](./Infrastructure_Design.md) · [PRD](./PRD.md)*
