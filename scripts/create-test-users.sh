#!/bin/bash
# Usage: ./create-test-users.sh <UserPoolId>
# Example: ./create-test-users.sh us-east-1_abc123

USER_POOL_ID=$1

if [ -z "$USER_POOL_ID" ]; then
  echo "Usage: $0 <UserPoolId>"
  exit 1
fi

PASSWORD="password123"

USERS=(
  "test1@kismet.com"
  "test2@kismet.com"
  "test3@kismet.com"
  "test4@kismet.com"
  "test5@kismet.com"
  "test6@kismet.com"
  "test7@kismet.com"
  "test8@kismet.com"
  "test9@kismet.com"
  "test10@kismet.com"
  "test11@kismet.com"
  "test12@kismet.com"
  "test13@kismet.com"
  "test14@kismet.com"
  "test15@kismet.com"
  "test16@kismet.com"
  "test17@kismet.com"
  "test18@kismet.com"
  "test19@kismet.com"
  "admin@kismet.com"
)

for EMAIL in "${USERS[@]}"; do
  echo "Creating $EMAIL..."

  AWS_PROFILE=admin-cli aws cognito-idp admin-create-user \
    --user-pool-id "$USER_POOL_ID" \
    --username "$EMAIL" \
    --temporary-password "$PASSWORD" \
    --message-action SUPPRESS \
    --output json > /dev/null

  AWS_PROFILE=admin-cli aws cognito-idp admin-set-user-password \
    --user-pool-id "$USER_POOL_ID" \
    --username "$EMAIL" \
    --password "$PASSWORD" \
    --permanent

  echo "  ✓ $EMAIL"
done

echo ""
echo "Done! 20 accounts created with password: $PASSWORD"
