#!/bin/bash
# Updates all test account display names to include "Test" as middle name

API_BASE="https://ihdsi4eg31.execute-api.us-east-1.amazonaws.com/dev"
PASSWORD="password123"

USERS=(
  "test1@kismet.com|Emma Test Zhang"
  "test2@kismet.com|Liam Test Chen"
  "test3@kismet.com|Sophia Test Wang"
  "test4@kismet.com|Noah Test Liu"
  "test5@kismet.com|Olivia Test Li"
  "test6@kismet.com|James Test Wu"
  "test7@kismet.com|Ava Test Huang"
  "test8@kismet.com|William Test Yang"
  "test9@kismet.com|Isabella Test Xu"
  "test10@kismet.com|Benjamin Test Zhou"
  "test11@kismet.com|Mia Test Sun"
  "test12@kismet.com|Lucas Test Tang"
  "test13@kismet.com|Charlotte Test Guo"
  "test14@kismet.com|Henry Test Luo"
  "test15@kismet.com|Amelia Test Feng"
  "test16@kismet.com|Alexander Test He"
  "test17@kismet.com|Harper Test Cheng"
  "test18@kismet.com|Ethan Test Jiang"
  "test19@kismet.com|Evelyn Test Zhu"
)

for entry in "${USERS[@]}"; do
  EMAIL=$(echo "$entry" | cut -d'|' -f1)
  NAME=$(echo "$entry" | cut -d'|' -f2)

  TOKEN=$(curl -s -X POST "$API_BASE/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('idToken',''))")

  USER_ID=$(curl -s "$API_BASE/profiles/me" -H "Authorization: $TOKEN" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('userId',''))" 2>/dev/null)

  # Try with sub from token if /profiles/me doesn't work
  if [ -z "$USER_ID" ]; then
    USER_ID=$(echo "$TOKEN" | python3 -c "
import sys, base64, json
token = sys.stdin.read().strip()
payload = token.split('.')[1]
payload += '=' * (4 - len(payload) % 4)
print(json.loads(base64.b64decode(payload)).get('sub',''))
")
  fi

  RESULT=$(curl -s -X PUT "$API_BASE/profiles/$USER_ID" \
    -H "Content-Type: application/json" \
    -H "Authorization: $TOKEN" \
    -d "{\"name\": \"$NAME\"}" | python3 -c "import sys,json; d=json.load(sys.stdin); print('ok' if 'userId' in d else d.get('error','unknown'))")

  echo "$EMAIL → $NAME: $RESULT"
done

echo ""
echo "Done!"
