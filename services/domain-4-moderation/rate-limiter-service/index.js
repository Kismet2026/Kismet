import { DynamoDBClient, UpdateItemCommand, QueryCommand, DeleteItemCommand } from "@aws-sdk/client-dynamodb";
import { marshall, unmarshall } from "@aws-sdk/util-dynamodb";

const dbClient = new DynamoDBClient({});
const TABLE_NAME = "kismet-rate-limits";

const LIMITS = {
  swipes: { limit: 100, windowSeconds: 24 * 60 * 60 },
  messages: { limit: 50, windowSeconds: 60 * 60 },
  reports: { limit: 5, windowSeconds: 24 * 60 * 60 }
};

// Helper: Calculate window start (Unix MS) and resetsAt (ISO)
function getWindowInfo(action) {
  const now = new Date();
  const conf = LIMITS[action];
  if (!conf) throw new Error("Invalid action");

  let windowStart;
  let resetsAt;

  if (conf.windowSeconds === 86400) {
    // Start of UTC Day
    windowStart = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())).getTime();
    resetsAt = new Date(windowStart + 86400 * 1000);
  } else if (conf.windowSeconds === 3600) {
    // Start of UTC Hour
    windowStart = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), now.getUTCHours())).getTime();
    resetsAt = new Date(windowStart + 3600 * 1000);
  }

  return { timestamp: windowStart, resetsAt: resetsAt.toISOString(), ttl: Math.floor(resetsAt.getTime() / 1000) };
}

// Middleware function to check and increment limit
export async function checkRateLimit(userId, action) {
  if (!LIMITS[action]) return { allowed: true };

  const { timestamp, resetsAt, ttl } = getWindowInfo(action);
  const pk = `USER#${userId}#ACTION#${action}`;
  const sk = `WINDOW#${timestamp}`;

  try {
    const result = await dbClient.send(new UpdateItemCommand({
      TableName: TABLE_NAME,
      Key: marshall({ pk, sk }),
      UpdateExpression: "ADD #count :inc SET #ttl = if_not_exists(#ttl, :ttl)",
      ExpressionAttributeNames: {
        "#count": "count",
        "#ttl": "ttl"
      },
      ExpressionAttributeValues: marshall({
        ":inc": 1,
        ":ttl": ttl
      }),
      ReturnValues: "UPDATED_NEW"
    }));

    const count = unmarshall(result.Attributes).count;
    const limit = LIMITS[action].limit;

    if (count > limit) {
      return {
        allowed: false,
        statusCode: 429,
        error: "RATE_LIMIT_EXCEEDED",
        message: `You have exceeded the limit of ${limit} ${action} per ${LIMITS[action].windowSeconds === 86400 ? 'day' : 'hour'}.`,
        retryAfter: resetsAt
      };
    }

    return { allowed: true, remaining: limit - count };
  } catch (error) {
    console.error("Rate limit check failed", error);
    // Allow through if DB fails to not block users, but log it
    return { allowed: true };
  }
}

// Lambda Handler for Admin APIs
export const handler = async (event) => {
  const method = event.httpMethod;
  const path = event.resource || event.path;
  
  const claims = event.requestContext?.authorizer?.claims || {};
  const isAdmin = claims['custom:role'] === 'admin' || event.headers?.['x-is-admin'] === 'true';

  if (!isAdmin) {
    return { statusCode: 403, body: JSON.stringify({ error: "FORBIDDEN" }) };
  }

  try {
    if (method === "GET" && path.startsWith("/ratelimit/status/")) {
      return await getStatus(event);
    }
    
    if (method === "POST" && path.startsWith("/ratelimit/reset/")) {
      return await resetLimit(event);
    }

    return { statusCode: 404, body: JSON.stringify({ error: "Not Found" }) };
  } catch (error) {
    console.error(error);
    return { statusCode: 500, body: JSON.stringify({ error: "Internal Server Error" }) };
  }
};

async function getStatus(event) {
  const userId = event.pathParameters?.userId;
  if (!userId) return { statusCode: 404, body: JSON.stringify({ error: "NOT_FOUND" }) };

  const actions = Object.keys(LIMITS);
  const statusLimits = {};
  let foundAny = false;

  for (const action of actions) {
    const { timestamp, resetsAt } = getWindowInfo(action);
    const pk = `USER#${userId}#ACTION#${action}`;
    const sk = `WINDOW#${timestamp}`;

    // Use Query to get the exact current window count
    const result = await dbClient.send(new QueryCommand({
      TableName: TABLE_NAME,
      KeyConditionExpression: "pk = :pk AND sk = :sk",
      ExpressionAttributeValues: marshall({ ":pk": pk, ":sk": sk })
    }));

    const limit = LIMITS[action].limit;
    const used = result.Items && result.Items.length > 0 ? unmarshall(result.Items[0]).count : 0;
    
    if (used > 0) foundAny = true;

    statusLimits[action] = {
      used,
      limit,
      remaining: Math.max(0, limit - used),
      resetsAt
    };
  }

  if (!foundAny) {
    return { statusCode: 404, body: JSON.stringify({ error: "NOT_FOUND" }) };
  }

  return {
    statusCode: 200,
    body: JSON.stringify({ userId, limits: statusLimits })
  };
}

async function resetLimit(event) {
  const userId = event.pathParameters?.userId;
  if (!userId) return { statusCode: 404, body: JSON.stringify({ error: "NOT_FOUND" }) };

  const actions = Object.keys(LIMITS);

  for (const action of actions) {
    const { timestamp } = getWindowInfo(action);
    const pk = `USER#${userId}#ACTION#${action}`;
    const sk = `WINDOW#${timestamp}`;

    try {
      await dbClient.send(new DeleteItemCommand({
        TableName: TABLE_NAME,
        Key: marshall({ pk, sk })
      }));
    } catch (e) {
      // Ignore if not exists
    }
  }

  return {
    statusCode: 200,
    body: JSON.stringify({
      userId,
      message: "Rate limit counters have been reset.",
      resetAt: new Date().toISOString()
    })
  };
}