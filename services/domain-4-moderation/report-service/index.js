import { DynamoDBClient, ScanCommand, GetItemCommand, PutItemCommand, UpdateItemCommand, QueryCommand } from "@aws-sdk/client-dynamodb";
import { marshall, unmarshall } from "@aws-sdk/util-dynamodb";
import { EventBridgeClient, PutEventsCommand } from "@aws-sdk/client-eventbridge";
import { v4 as uuidv4 } from "uuid";

const dbClient = new DynamoDBClient({});
const ebClient = new EventBridgeClient({});

const TABLE_NAME = "kismet-reports";
const VALID_REASONS = ["harassment", "inappropriate_content", "spam", "fake_profile", "other"];
const VALID_RESOLUTIONS = ["warning", "ban", "dismiss"];

export const handler = async (event) => {
  const method = event.httpMethod;
  const path = event.resource || event.path;
  
  // Basic mock auth check
  const claims = event.requestContext?.authorizer?.claims || {};
  const userId = claims.sub || event.headers?.['x-user-id']; // Fallback for testing
  const isAdmin = claims['custom:role'] === 'admin' || event.headers?.['x-is-admin'] === 'true';

  if (!userId) {
    return { statusCode: 401, body: JSON.stringify({ error: "UNAUTHORIZED" }) };
  }

  try {
    if (method === "POST" && (path === "/reports" || path.endsWith("/reports"))) {
      return await createReport(event, userId);
    }
    
    if (method === "GET" && (path === "/reports" || path.endsWith("/reports"))) {
      if (!isAdmin) return { statusCode: 403, body: JSON.stringify({ error: "FORBIDDEN" }) };
      return await listReports(event);
    }
    
    if (method === "GET" && path.includes("/reports/") && !path.endsWith("/resolve")) {
      if (!isAdmin) return { statusCode: 403, body: JSON.stringify({ error: "FORBIDDEN" }) };
      return await getReport(event);
    }
    
    if (method === "PUT" && path.endsWith("/resolve")) {
      if (!isAdmin) return { statusCode: 403, body: JSON.stringify({ error: "FORBIDDEN" }) };
      return await resolveReport(event);
    }

    return { statusCode: 404, body: JSON.stringify({ error: "Not Found" }) };
  } catch (error) {
    console.error(error);
    return { statusCode: 500, body: JSON.stringify({ error: "Internal Server Error" }) };
  }
};

async function createReport(event, reporterId) {
  const body = JSON.parse(event.body || "{}");
  const { reportedUserId, reason, description } = body;

  if (!reportedUserId || !VALID_REASONS.includes(reason)) {
    return { statusCode: 400, body: JSON.stringify({ error: "VALIDATION_ERROR" }) };
  }

  // Check for unresolved conflicts (same reporter to same reportedUserId, pending status)
  // This requires a scan or query, but standard implementation might just do a basic check.
  // Assuming conflict happens if the same user has already reported this target and it's pending.
  // A GSI or a direct query could be used. We will do a simple scan for simplicity in this demo.
  const conflictCheck = await dbClient.send(new ScanCommand({
    TableName: TABLE_NAME,
    FilterExpression: "reporterId = :rid AND reportedUserId = :ruid AND #status = :s",
    ExpressionAttributeNames: { "#status": "status" },
    ExpressionAttributeValues: marshall({ ":rid": reporterId, ":ruid": reportedUserId, ":s": "pending" })
  }));

  if (conflictCheck.Items && conflictCheck.Items.length > 0) {
    return { statusCode: 409, body: JSON.stringify({ error: "CONFLICT" }) };
  }

  const reportId = `report-${uuidv4()}`;
  const now = new Date().toISOString();
  
  const reportItem = {
    reportId,
    pk: `REPORT#${reportId}`,
    sk: "META",
    reporterId,
    reportedUserId,
    reason,
    description: description || "",
    status: "pending",
    resolution: null,
    createdAt: now,
    resolvedAt: null
  };

  await dbClient.send(new PutItemCommand({
    TableName: TABLE_NAME,
    Item: marshall(reportItem)
  }));

  // Send EventBridge Event
  await ebClient.send(new PutEventsCommand({
    Entries: [{
      Source: "kismet.report-service",
      DetailType: "user.reported",
      Detail: JSON.stringify({
        reportId,
        reporterId,
        reportedUserId,
        reason,
        createdAt: now
      }),
      EventBusName: "default"
    }]
  }));

  // Cleanup for response
  delete reportItem.pk;
  delete reportItem.sk;
  delete reportItem.resolution;
  delete reportItem.resolvedAt;

  return { statusCode: 201, body: JSON.stringify(reportItem) };
}

async function listReports(event) {
  const qs = event.queryStringParameters || {};
  const limit = parseInt(qs.limit || "20", 10);
  const cursor = qs.cursor;

  const scanParams = {
    TableName: TABLE_NAME,
    Limit: Math.min(limit, 50)
  };

  if (cursor) {
    scanParams.ExclusiveStartKey = JSON.parse(Buffer.from(cursor, "base64").toString("utf-8"));
  }

  const result = await dbClient.send(new ScanCommand(scanParams));
  const items = (result.Items || []).map(i => {
    const item = unmarshall(i);
    delete item.pk;
    delete item.sk;
    delete item.description; // Description excluded in list per contract
    delete item.resolution;
    delete item.resolvedAt;
    return item;
  });

  const response = {
    items,
    count: items.length,
    nextCursor: result.LastEvaluatedKey ? Buffer.from(JSON.stringify(result.LastEvaluatedKey)).toString("base64") : null
  };

  return { statusCode: 200, body: JSON.stringify(response) };
}

async function getReport(event) {
  const reportId = event.pathParameters?.reportId;
  if (!reportId) return { statusCode: 404, body: JSON.stringify({ error: "NOT_FOUND" }) };

  const result = await dbClient.send(new GetItemCommand({
    TableName: TABLE_NAME,
    Key: marshall({ pk: `REPORT#${reportId}`, sk: "META" })
  }));

  if (!result.Item) {
    return { statusCode: 404, body: JSON.stringify({ error: "NOT_FOUND" }) };
  }

  const item = unmarshall(result.Item);
  delete item.pk;
  delete item.sk;

  return { statusCode: 200, body: JSON.stringify(item) };
}

async function resolveReport(event) {
  const reportId = event.pathParameters?.reportId;
  const body = JSON.parse(event.body || "{}");
  const { resolution } = body;

  if (!reportId) return { statusCode: 404, body: JSON.stringify({ error: "NOT_FOUND" }) };
  if (!VALID_RESOLUTIONS.includes(resolution)) {
    return { statusCode: 400, body: JSON.stringify({ error: "VALIDATION_ERROR" }) };
  }

  const now = new Date().toISOString();

  try {
    const result = await dbClient.send(new UpdateItemCommand({
      TableName: TABLE_NAME,
      Key: marshall({ pk: `REPORT#${reportId}`, sk: "META" }),
      UpdateExpression: "SET #status = :resolvedStatus, resolution = :res, resolvedAt = :now",
      ConditionExpression: "attribute_exists(pk) AND #status = :pendingStatus",
      ExpressionAttributeNames: { "#status": "status" },
      ExpressionAttributeValues: marshall({
        ":resolvedStatus": "resolved",
        ":res": resolution,
        ":now": now,
        ":pendingStatus": "pending"
      }),
      ReturnValues: "ALL_NEW"
    }));

    const item = unmarshall(result.Attributes);
    return {
      statusCode: 200,
      body: JSON.stringify({
        reportId: item.reportId,
        reportedUserId: item.reportedUserId,
        reason: item.reason,
        status: item.status,
        resolution: item.resolution,
        resolvedAt: item.resolvedAt
      })
    };
  } catch (err) {
    if (err.name === "ConditionalCheckFailedException") {
      // Could be because it doesn't exist OR it's already resolved
      const check = await dbClient.send(new GetItemCommand({
        TableName: TABLE_NAME,
        Key: marshall({ pk: `REPORT#${reportId}`, sk: "META" })
      }));
      if (!check.Item) {
        return { statusCode: 404, body: JSON.stringify({ error: "NOT_FOUND" }) };
      }
      return { statusCode: 409, body: JSON.stringify({ error: "CONFLICT" }) }; // Already processed
    }
    throw err;
  }
}
