#!/bin/bash
set -euo pipefail

# Creates the admin Cognito user for the Kismet Admin Dashboard.
# Usage: ./scripts/create-admin-user.sh <UserPoolId>
# Example: ./scripts/create-admin-user.sh us-east-1_abc123
# Or provide the password securely via the PASSWORD environment variable.

USER_POOL_ID=${1:-}

if [ -z "$USER_POOL_ID" ]; then
  echo "Usage: $0 <UserPoolId>"
  exit 1
fi

if [ -z "${PASSWORD:-}" ]; then
  read -rs -p "Enter admin password: " PASSWORD
  echo
  read -rs -p "Confirm admin password: " PASSWORD_CONFIRM
  echo

  if [ "$PASSWORD" != "$PASSWORD_CONFIRM" ]; then
    echo "Error: passwords do not match."
    exit 1
  fi
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
