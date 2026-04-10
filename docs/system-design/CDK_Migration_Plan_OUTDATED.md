# Kismet — CDK 迁移计划

> 从 SAM 切换到 AWS CDK (Python)
> 制定日期：2026-04-01

---

## 1. 目标

将 Kismet 的基础设施定义从"各 service 手写 SAM template.yaml"改为"统一 CDK Python 项目"。

**核心产出：**
- 一个可复用的 `KismetService` construct，25 个 service 全复用
- 共享资源栈（Cognito、API Gateway、EventBridge、S3、CloudFront）
- 6 个域栈（每个域的 Lambda + DynamoDB + IAM + EventBridge Rule）
- 一条命令部署全部 / 单独部署某个域

---

## 2. 文件结构

```
infra/
├── app.py                         ← CDK 入口：定义所有 Stack
├── cdk.json                       ← CDK 配置
├── requirements.txt               ← CDK Python 依赖
├── README.md                      ← 部署说明（给队友看）
│
├── stacks/
│   ├── __init__.py
│   ├── shared_stack.py            ← 共享资源：Cognito, API GW, EventBridge, S3, CloudFront
│   ├── domain1_stack.py           ← Identity & Profiles (4 services)
│   ├── domain2_stack.py           ← Discovery & Matching (5 services)
│   ├── domain3_stack.py           ← Messaging (4 services)
│   ├── domain4_stack.py           ← Safety & Moderation (4 services)
│   ├── domain5_stack.py           ← Notifications & Engagement (4 services)
│   ├── domain6_stack.py           ← Analytics & Admin (4 services)
│   └── frontend_stack.py          ← 前端 S3 + CloudFront（可选）
│
├── constructs/
│   ├── __init__.py
│   └── kismet_service.py          ← 核心：可复用的 KismetService 模板
│
└── tests/                         ← CDK 单元测试（可选）
    └── test_shared_stack.py

services/                          ← 不变，各 service 的 Lambda 代码还在这里
├── domain-1-identity/
│   ├── auth-service/
│   │   ├── lambda_function.py     ← 队友写的业务代码
│   │   └── requirements.txt
│   ├── profile-service/
│   └── ...
└── ...
```

---

## 3. 实现步骤

### Phase 1：PM 搭框架（Day 1）

| 步骤 | 做什么 | 产出 |
|------|--------|------|
| 1.1 | 在 `infra/` 下 `cdk init app --language python` 初始化 CDK 项目 | `cdk.json`, `app.py`, `requirements.txt` |
| 1.2 | 安装 CDK 依赖 | `aws-cdk-lib`, `constructs` |
| 1.3 | 写 `constructs/kismet_service.py` — 核心可复用 construct | 见 §4 详细设计 |
| 1.4 | 写 `stacks/shared_stack.py` — 共享资源 | 见 §5 详细设计 |
| 1.5 | 写 `app.py` — 串联所有 Stack | 入口文件 |
| 1.6 | 运行 `cdk synth` 验证模板生成成功 | CloudFormation YAML |
| 1.7 | 运行 `cdk bootstrap` 初始化 CDK 环境 | S3 bucket for CDK assets |
| 1.8 | 部署 SharedStack：`cdk deploy KismetShared` | Cognito, API GW, EventBridge, S3 上线 |

### Phase 2：PM 写域栈模板 + 示例（Day 1-2）

| 步骤 | 做什么 | 产出 |
|------|--------|------|
| 2.1 | 写 `stacks/domain2_stack.py` 作为完整示例 | 5 个 service 的 CDK 配置 |
| 2.2 | 写一个 Lambda skeleton（`swipe-service/lambda_function.py`）作为示例 | 队友照着写 |
| 2.3 | 部署 Domain 2：`cdk deploy KismetDomain2` 验证端到端 | Lambda + DynamoDB + 路由全部上线 |
| 2.4 | 写其余 5 个域栈的框架（domain1/3/4/5/6_stack.py），留空让队友填 | 每个文件有注释指引 |

### Phase 3：队友填配置 + 写 Lambda（Day 2-3）

| 步骤 | 谁做 | 做什么 |
|------|------|--------|
| 3.1 | 各域同学 | 在自己域的 stack 文件里用 `KismetService(...)` 定义 service |
| 3.2 | 各域同学 | 在 `services/` 对应文件夹里写 `lambda_function.py` |
| 3.3 | 各域同学 | 本地 `cdk diff KismetDomainX` 预览变更 |
| 3.4 | 各域同学 | `cdk deploy KismetDomainX` 部署自己的域 |

### Phase 4：集成验证（Day 3）

| 步骤 | 做什么 |
|------|--------|
| 4.1 | `cdk deploy --all` 全量部署 |
| 4.2 | 测试完整用户流：注册 → 资料 → 发现 → 划右 → 匹配 → 聊天 |
| 4.3 | 验证 EventBridge 事件链路 |

---

## 4. KismetService Construct 详细设计

这是整个 CDK 方案的核心。一次定义，25 次复用。

### 4.1 输入参数

```python
@dataclass
class KismetServiceProps:
    service_name: str          # "swipe" → Lambda: kismet-swipe, Table: kismet-swipe
    code_path: str             # "../services/domain-2-discovery/swipe-service"
    handler: str               # "lambda_function.handler" (默认)
    runtime: str               # "python3.12" (默认)

    # API Gateway 路由
    routes: list[dict]         # [{"method": "POST", "path": "/swipe", "auth": True}]

    # DynamoDB（可选，有的 service 没有表）
    table: dict | None         # {"pk": "userId:S", "sk": "targetUserId:S", "gsi": [...]}

    # EventBridge
    consume_events: list[str]  # ["swipe.created"] — 订阅哪些事件
    publish_events: bool       # True — 是否需要发事件的权限

    # 额外 AWS 权限（特殊 service 用）
    extra_policies: list       # [iam.PolicyStatement(...)] 比如 Comprehend, Rekognition

    # 额外环境变量
    environment: dict          # {"BAZI_API_URL": "https://..."}

    # S3 访问（Photo Service 用）
    s3_bucket: s3.Bucket | None

    # Cognito 引用（Auth Service 用）
    user_pool: cognito.UserPool | None
```

### 4.2 自动创建的资源

对每个 `KismetService` 实例，自动创建：

| 资源 | 命名规则 | 条件 |
|------|---------|------|
| Lambda Function | `kismet-{service_name}` | 始终创建 |
| IAM Role | 自动生成 | 始终创建，最小权限 |
| DynamoDB Table | `kismet-{service_name}` | 仅当 `table` 不为 None |
| DynamoDB GSI | `{gsi_name}-index` | 仅当 table 配置了 GSI |
| API GW Route | `/{path}` → Lambda | 仅当 `routes` 不为空 |
| EventBridge Rule | `kismet-{service}-on-{event}` | 仅当 `consume_events` 不为空 |
| CloudWatch Log Group | `/aws/lambda/kismet-{service}` | 自动 |

### 4.3 自动授权（IAM 最小权限）

```
Lambda → DynamoDB:        table.grant_read_write_data(function)        仅当有 table
Lambda → EventBridge:     event_bus.grant_put_events_to(function)      仅当 publish_events=True
Lambda → S3:              bucket.grant_read_write(function)            仅当有 s3_bucket
Lambda → Cognito:         user_pool.grant(function, ...)               仅当有 user_pool
Lambda → 其他:            extra_policies 里自定义                       仅当有特殊需求
```

---

## 5. SharedStack 详细设计

### 5.1 Cognito

```python
user_pool = cognito.UserPool(self, 'KismetUserPool',
    user_pool_name='kismet-user-pool',
    self_sign_up_enabled=True,
    sign_in_aliases=cognito.SignInAliases(email=True),
    auto_verify=cognito.AutoVerifiedAttrs(email=True),
    password_policy=cognito.PasswordPolicy(
        min_length=8,
        require_uppercase=False,
        require_symbols=False,
    ),
    removal_policy=RemovalPolicy.DESTROY,
)

user_pool_client = user_pool.add_client('WebClient',
    auth_flows=cognito.AuthFlow(
        user_password=True,
        user_srp=True,
    ),
)
```

### 5.2 API Gateway

```python
api = apigateway.RestApi(self, 'KismetApi',
    rest_api_name='kismet-api',
    deploy_options=apigateway.StageOptions(stage_name='dev'),
    default_cors_preflight_options=apigateway.CorsOptions(
        allow_origins=apigateway.Cors.ALL_ORIGINS,
        allow_methods=apigateway.Cors.ALL_METHODS,
        allow_headers=['Content-Type', 'Authorization'],
    ),
)

authorizer = apigateway.CognitoUserPoolsAuthorizer(self, 'CognitoAuth',
    cognito_user_pools=[user_pool],
)
```

### 5.3 EventBridge

```python
event_bus = events.EventBus(self, 'KismetEventBus',
    event_bus_name='kismet-events',
)
```

### 5.4 S3

```python
photos_bucket = s3.Bucket(self, 'PhotosBucket',
    bucket_name=f'kismet-photos-{self.account}-dev',
    cors=[s3.CorsRule(
        allowed_methods=[s3.HttpMethods.GET, s3.HttpMethods.PUT],
        allowed_origins=['*'],
        allowed_headers=['*'],
    )],
    removal_policy=RemovalPolicy.DESTROY,
    auto_delete_objects=True,
)

analytics_bucket = s3.Bucket(self, 'AnalyticsBucket',
    bucket_name=f'kismet-analytics-{self.account}-dev',
    removal_policy=RemovalPolicy.DESTROY,
    auto_delete_objects=True,
)
```

### 5.5 Kinesis

Activity Logger 写入、Analytics Pipeline 读取，属于跨 service 共享资源，统一在 SharedStack 创建。

```python
activity_stream = kinesis.Stream(self, 'ActivityStream',
    stream_name='kismet-activity-stream',
    shard_count=1,
    removal_policy=RemovalPolicy.DESTROY,
)
```

### 5.6 SNS

Health Monitor 告警用，统一在 SharedStack 创建。

```python
health_alerts_topic = sns.Topic(self, 'HealthAlertsTopic',
    topic_name='kismet-health-alerts',
)
```

### 5.7 导出

SharedStack 把所有共享资源通过属性暴露给域栈：

```python
# 域栈通过 props 接收
class Domain2Stack(Stack):
    def __init__(self, scope, id, *, shared: SharedStack):
        api = shared.api
        event_bus = shared.event_bus
        authorizer = shared.authorizer
        # Domain 6 also uses:
        # shared.activity_stream
        # shared.health_alerts_topic
```

---

## 6. 域栈示例（Domain 2）

```python
# stacks/domain2_stack.py

class Domain2Stack(Stack):
    def __init__(self, scope, id, *, shared: SharedStack, **kwargs):
        super().__init__(scope, id, **kwargs)

        # --- Qinyuan 的 services ---

        KismetService(self, 'DiscoveryService',
            service_name='discovery',
            code_path='../services/domain-2-discovery/discovery-service',
            api=shared.api,
            authorizer=shared.authorizer,
            event_bus=shared.event_bus,
            routes=[
                {'method': 'GET', 'path': '/discovery', 'auth': True},
            ],
            table={
                'pk': {'name': 'userId', 'type': 'S'},
                'sk': {'name': 'candidateScore', 'type': 'S'},
            },
            consume_events=['profile.completed'],
            publish_events=False,
        )

        KismetService(self, 'SwipeService',
            service_name='swipe',
            code_path='../services/domain-2-discovery/swipe-service',
            api=shared.api,
            authorizer=shared.authorizer,
            event_bus=shared.event_bus,
            routes=[
                {'method': 'POST', 'path': '/swipe', 'auth': True},
                {'method': 'GET', 'path': '/swipe/history', 'auth': True},
            ],
            table={
                'pk': {'name': 'userId', 'type': 'S'},
                'sk': {'name': 'targetUserId', 'type': 'S'},
            },
            consume_events=[],
            publish_events=True,
        )

        KismetService(self, 'MatchService',
            service_name='match',
            code_path='../services/domain-2-discovery/match-service',
            api=shared.api,
            authorizer=shared.authorizer,
            event_bus=shared.event_bus,
            routes=[
                {'method': 'GET', 'path': '/matches', 'auth': True},
                {'method': 'GET', 'path': '/matches/{matchId}', 'auth': True},
                {'method': 'DELETE', 'path': '/matches/{matchId}', 'auth': True},
            ],
            table={
                'pk': {'name': 'matchId', 'type': 'S'},
                'sk': {'name': 'userId', 'type': 'S'},
            },
            consume_events=['swipe.created'],
            publish_events=True,
        )

        # --- Qinyuan 的 services ---

        KismetService(self, 'RecommendationService',
            service_name='recommendation',
            code_path='../services/domain-2-discovery/recommendation-service',
            api=shared.api,
            authorizer=shared.authorizer,
            event_bus=shared.event_bus,
            routes=[
                {'method': 'GET', 'path': '/recommend', 'auth': True},
                {'method': 'POST', 'path': '/recommend/refresh', 'auth': True},
            ],
            table={
                'pk': {'name': 'userId', 'type': 'S'},
                'sk': {'name': 'scoreCandidateId', 'type': 'S'},
            },
            consume_events=['profile.completed', 'swipe.created'],
            publish_events=False,
        )

        KismetService(self, 'BaziService',
            service_name='bazi',
            code_path='../services/domain-2-discovery/bazi-service',
            api=shared.api,
            authorizer=shared.authorizer,
            event_bus=shared.event_bus,
            routes=[
                {'method': 'POST', 'path': '/bazi/top-matches', 'auth': True},
            ],
            table=None,  # 无状态，或可选缓存表
            consume_events=[],
            publish_events=False,
        )
```

---

## 7. 特殊 Service 处理

不是所有 25 个 service 都完全符合"Lambda + DynamoDB + API Route"的标准模式。以下 service 需要额外处理：

### 7.1 Auth Service — 需要 Cognito 权限

```python
KismetService(self, 'AuthService',
    service_name='auth',
    ...,
    user_pool=shared.user_pool,    # 自动授权 cognito:Admin*
    routes=[
        {'method': 'POST', 'path': '/auth/signup', 'auth': False},    # 注册不需要 JWT
        {'method': 'POST', 'path': '/auth/login', 'auth': False},     # 登录不需要 JWT
        {'method': 'POST', 'path': '/auth/refresh', 'auth': False},
        {'method': 'POST', 'path': '/auth/logout', 'auth': True},
    ],
)
```

### 7.2 Photo Service — 需要 S3 权限

```python
KismetService(self, 'PhotoService',
    service_name='photo',
    ...,
    s3_bucket=shared.photos_bucket,  # 自动授权 s3:PutObject, GetObject
)
```

### 7.3 Text Moderation — 需要 Comprehend 权限

```python
KismetService(self, 'TextModerationService',
    service_name='text-moderation',
    ...,
    extra_policies=[
        iam.PolicyStatement(
            actions=['comprehend:DetectToxicContent'],
            resources=['*'],
        ),
    ],
)
```

### 7.4 Image Moderation — 需要 Rekognition 权限

```python
KismetService(self, 'ImageModerationService',
    service_name='image-moderation',
    ...,
    s3_bucket=shared.photos_bucket,  # 读取图片
    extra_policies=[
        iam.PolicyStatement(
            actions=['rekognition:DetectModerationLabels'],
            resources=['*'],
        ),
    ],
)
```

### 7.5 Icebreaker Service — 需要 Bedrock 权限

```python
KismetService(self, 'IcebreakerService',
    service_name='icebreaker',
    ...,
    extra_policies=[
        iam.PolicyStatement(
            actions=['bedrock:InvokeModel'],
            resources=['*'],
        ),
    ],
)
```

### 7.6 Activity Logger — 需要 Kinesis 权限

```python
KismetService(self, 'ActivityLoggerService',
    service_name='activity-logger',
    ...,
    extra_policies=[
        iam.PolicyStatement(
            actions=['kinesis:PutRecord', 'kinesis:PutRecords'],
            resources=[kinesis_stream.stream_arn],
        ),
    ],
)
```

### 7.7 Health Monitor — 需要 CloudWatch + SNS 权限

```python
KismetService(self, 'HealthMonitorService',
    service_name='health-monitor',
    ...,
    routes=[
        {'method': 'GET', 'path': '/health', 'auth': False},        # 公开端点
        {'method': 'GET', 'path': '/health/{serviceName}', 'auth': True},
        {'method': 'POST', 'path': '/health/check', 'auth': True},
    ],
    extra_policies=[
        iam.PolicyStatement(
            actions=['cloudwatch:GetMetricData', 'cloudwatch:DescribeAlarms'],
            resources=['*'],
        ),
        iam.PolicyStatement(
            actions=['sns:Publish'],
            resources=[health_alerts_topic.topic_arn],
        ),
    ],
)
```

### 7.8 Rate Limiter — 中间件，不是 REST Service

Rate Limiter 通过 API Gateway Usage Plans 实现，在 SharedStack 中配置：

```python
# shared_stack.py 中
usage_plan = api.add_usage_plan('RateLimitPlan',
    throttle=apigateway.ThrottleSettings(
        rate_limit=100,      # 每秒 100 请求
        burst_limit=200,
    ),
)
```

Rate Limiter 的 per-user 限流通过 ElastiCache (Redis) 实现，见 Rate Limiter Service 配置。

### 7.9 Push Notification Service — 需要 SNS 权限

```python
KismetService(self, 'PushNotificationService',
    service_name='push-notification',
    ...,
    extra_policies=[
        iam.PolicyStatement(
            actions=['sns:Publish', 'sns:CreatePlatformEndpoint'],
            resources=[f'arn:aws:sns:{self.region}:{self.account}:app/*/kismet-*'],
        ),
    ],
)
```

### 7.10 Email Service — 需要 SES 权限

```python
KismetService(self, 'EmailService',
    service_name='email',
    ...,
    extra_policies=[
        iam.PolicyStatement(
            actions=['ses:SendEmail', 'ses:SendTemplatedEmail'],
            resources=[f'arn:aws:ses:{self.region}:{self.account}:identity/*'],
        ),
    ],
)
```

---

## 8. 队友需要做的事

### 他们看到的：

```python
# stacks/domain2_stack.py — Qinyuan 需要做的事：

# 1. 确认自己 service 的配置（路由、表结构、事件）
KismetService(self, 'SwipeService',
    service_name='swipe',
    code_path='../services/domain-2-discovery/swipe-service',
    # ... 配置已填好，review 一下
)

# 2. 去写自己的 Lambda handler
# services/domain-2-discovery/swipe-service/lambda_function.py
```

### 他们需要的命令：

```bash
# 进入 infra 目录
cd infra/

# 安装依赖（第一次）
pip install -r requirements.txt

# 预览自己域会创建什么资源
cdk diff KismetDomain2

# 部署自己的域
cdk deploy KismetDomain2

# 查看部署状态
cdk list

# 出问题了想回滚
cdk destroy KismetDomain2
```

---

## 9. 部署顺序

```
cdk bootstrap                    ← PM 执行一次（初始化 CDK 环境）
    │
    ▼
cdk deploy KismetShared          ← PM 部署共享资源
    │                               （Cognito, API GW, EventBridge, S3）
    │
    ├──→ cdk deploy KismetDomain1   ← Quinn Gao, KS
    ├──→ cdk deploy KismetDomain2   ← Qinyuan
    ├──→ cdk deploy KismetDomain3   ← Parker, QX, Jiaxin
    ├──→ cdk deploy KismetDomain4   ← Yue, Amber
    ├──→ cdk deploy KismetDomain5   ← Nili, Xiaoyuan
    └──→ cdk deploy KismetDomain6   ← Jessica, Lingyun
              │
              ▼
         cdk deploy --all           ← PM 最终全量部署（集成测试）
```

6 个域可以并行部署，互不干扰。

---

## 10. 文档更新

完成 CDK 迁移后需要更新：

| 文档 | 更新内容 |
|------|---------|
| `docs/Infrastructure_Design.md` | §7 部署策略从 SAM 改为 CDK |
| `infra/README.md` | 新建：CDK 安装、部署、常见命令 |
| `docs/Kismet_Setup_Guide.md` | 更新 Getting Started 部分 |

---

## 11. 时间估算

| 阶段 | 谁做 | 时间 |
|------|------|------|
| Phase 1: CDK 框架 + SharedStack + KismetService construct | PM | 3-4 小时 |
| Phase 2: 域栈模板 + 示例 Lambda + 端到端验证 | PM | 2-3 小时 |
| Phase 3: 队友填配置 + 写 Lambda | 各域同学 | 每人 1-2 小时 |
| Phase 4: 全量部署 + 集成测试 | PM + 所有人 | 2-3 小时 |

**PM 总投入：~6 小时（可在 Day 1-2 完成）**
**队友投入：每人 ~1-2 小时配置 CDK，剩余时间专注写 Lambda 业务代码**

---

*配套文档：[Infrastructure Design](./Infrastructure_Design.md) · [API Contracts](./api-contracts/) · [Event Schema](./event-schema.json)*
