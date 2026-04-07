import { createClient } from "redis";

const redisClient = createClient({
  url: process.env.REDIS_URL || "redis://localhost:6379"
});

redisClient.on("error", (err) => console.error("Redis Client Error", err));
let redisConnected = false;

async function connectRedis() {
  if (!redisConnected) {
    await redisClient.connect();
    redisConnected = true;
  }
}

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

  return { timestamp: windowStart, resetsAt: resetsAt.toISOString(), ttlSeconds: Math.floor((resetsAt.getTime() - now.getTime()) / 1000) };
}

// Middleware function to check and increment limit
export async function checkRateLimit(userId, action) {
  if (!LIMITS[action]) return { allowed: true };
  await connectRedis();

  const { timestamp, resetsAt, ttlSeconds } = getWindowInfo(action);
  const key = `ratelimit:${userId}:${action}:${timestamp}`;

  try {
    // Increment the key
    const currentCount = await redisClient.incr(key);

    // If it's a new key, set the expiration
    if (currentCount === 1) {
      await redisClient.expire(key, ttlSeconds + 60); // adding 60s buffer
    }

    const limit = LIMITS[action].limit;

    if (currentCount > limit) {
      return {
        allowed: false,
        statusCode: 429,
        error: "RATE_LIMIT_EXCEEDED",
        message: `You have exceeded the limit of ${limit} ${action} per ${LIMITS[action].windowSeconds === 86400 ? 'day' : 'hour'}.`,
        retryAfter: resetsAt
      };
    }

    return { allowed: true, remaining: limit - currentCount };
  } catch (error) {
    console.error("Rate limit check failed", error);
    // Allow through if Redis fails to not block users, but log it
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

  await connectRedis();

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
    const key = `ratelimit:${userId}:${action}:${timestamp}`;

    const value = await redisClient.get(key);
    const used = value ? parseInt(value, 10) : 0;
    
    if (used > 0) foundAny = true;

    const limit = LIMITS[action].limit;

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
    const key = `ratelimit:${userId}:${action}:${timestamp}`;
    await redisClient.del(key);
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