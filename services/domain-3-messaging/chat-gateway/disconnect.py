import os

import boto3

TABLE = os.environ["CONNECTIONS_TABLE"]
db = boto3.resource("dynamodb").Table(TABLE)


def handler(event, context):
    connection_id = event["requestContext"]["connectionId"]

    db.delete_item(Key={"PK": f"CONN#{connection_id}", "SK": "META"})

    print(f"Disconnected: {connection_id}")
    return {"statusCode": 200, "body": "Disconnected"}
