#!/bin/bash
# Creates the admin Cognito user for the Kismet Admin Dashboard.
# Usage: ./scripts/create-admin-user.sh <UserPoolId> <Password>
# Example: ./scripts/create-admin-user.sh us-east-1_abc123 MySecurePassword!

USER_POOL_ID=$1
PASSWORD=$2

if [ -z "$USER_POOL_ID" ] || [ -z "$PASSWORD" ]; then
  echo "Usage: $0 <UserPoolId> <Password>"
  exit 1
fi

EMAIL="admin@kismet.com"

echo "Creating admin user: $EMAIL"

aws cognito-idp admin-create-user \
  --user-pool-id "$USER_POOL_ID" \
  --username "$EMAIL" \
  --temporary-password "$PASSWORD" \
  --message-action SUPPRESS

aws cognito-idp admin-set-user-password \
  --user-pool-id "$USER_POOL_ID" \
  --username "$EMAIL" \
  --password "$PASSWORD" \
  --permanent

echo "Done. Login at the Admin Dashboard with: $EMAIL"
