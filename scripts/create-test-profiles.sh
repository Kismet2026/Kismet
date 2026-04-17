#!/bin/bash
# Usage: ./create-test-profiles.sh
# Creates profiles for all test accounts

API_BASE="https://ihdsi4eg31.execute-api.us-east-1.amazonaws.com/dev"
PASSWORD="password123"

# name | gender | interestedIn | birthDate | birthTime | bio | interests
USERS=(
  "test1@kismet.com|Emma Zhang|female|male|1998-03-15|08:00|Coffee lover and bookworm|reading,coffee,hiking"
  "test2@kismet.com|Liam Chen|male|female|1997-07-22|14:30|CS student who loves basketball|basketball,coding,music"
  "test3@kismet.com|Sophia Wang|female|male|1999-01-10|06:00|Art major with a passion for travel|art,travel,yoga"
  "test4@kismet.com|Noah Liu|male|female|1996-11-05|20:00|Finance major, gym enthusiast|gym,finance,cooking"
  "test5@kismet.com|Olivia Li|female|everyone|1998-08-20|10:00|Biology student who loves nature|nature,photography,running"
  "test6@kismet.com|James Wu|male|female|1997-04-12|16:00|Music producer and gamer|music,gaming,movies"
  "test7@kismet.com|Ava Huang|female|male|1999-09-03|12:00|Pre-med student, loves cooking|cooking,medicine,dancing"
  "test8@kismet.com|William Yang|male|female|1996-06-28|09:00|Engineering major, rock climber|climbing,engineering,travel"
  "test9@kismet.com|Isabella Xu|female|male|1998-12-17|07:00|Psychology major, coffee addict|psychology,coffee,yoga"
  "test10@kismet.com|Benjamin Zhou|male|female|1997-02-14|22:00|Architecture student, photographer|photography,architecture,art"
  "test11@kismet.com|Mia Sun|female|male|1999-05-30|11:00|Marketing major, fitness lover|fitness,marketing,travel"
  "test12@kismet.com|Lucas Tang|male|female|1996-08-08|15:00|Data science student, chess player|chess,data,hiking"
  "test13@kismet.com|Charlotte Guo|female|male|1998-10-25|13:00|English major, aspiring writer|writing,reading,music"
  "test14@kismet.com|Henry Luo|male|female|1997-01-19|18:00|Physics major, stargazer|astronomy,physics,gaming"
  "test15@kismet.com|Amelia Feng|female|male|1999-07-07|08:30|Design student, plant lover|design,plants,coffee"
  "test16@kismet.com|Alexander He|male|female|1996-03-23|21:00|Law student, basketball fan|basketball,law,cooking"
  "test17@kismet.com|Harper Cheng|female|male|1998-06-11|10:30|Chemistry major, marathon runner|running,chemistry,travel"
  "test18@kismet.com|Ethan Jiang|male|female|1997-09-16|17:00|Business major, amateur chef|cooking,business,movies"
  "test19@kismet.com|Evelyn Zhu|female|male|1999-04-02|14:00|Neuroscience major, yoga teacher|yoga,neuroscience,art"
)

# Random locations around major US college cities
LOCATIONS=(
  "42.3601,-71.0589"   # Boston
  "37.8719,-122.2585"  # Berkeley
  "40.7282,-74.0776"   # New York
  "34.0689,-118.4452"  # UCLA
  "41.7943,-87.5907"   # Chicago
  "47.6553,-122.3035"  # Seattle
  "33.4255,-111.9400"  # Arizona State
  "30.2849,-97.7341"   # UT Austin
  "38.9869,-76.9426"   # College Park
  "42.3505,-71.1054"   # Boston area
)

echo "Creating profiles for test accounts..."
echo ""

for i in "${!USERS[@]}"; do
  entry="${USERS[$i]}"
  EMAIL=$(echo "$entry" | cut -d'|' -f1)
  NAME=$(echo "$entry" | cut -d'|' -f2)
  GENDER=$(echo "$entry" | cut -d'|' -f3)
  INTERESTED=$(echo "$entry" | cut -d'|' -f4)
  BIRTHDATE=$(echo "$entry" | cut -d'|' -f5)
  BIRTHTIME=$(echo "$entry" | cut -d'|' -f6)
  BIO=$(echo "$entry" | cut -d'|' -f7)
  INTERESTS_STR=$(echo "$entry" | cut -d'|' -f8)

  # Pick a location
  LOC="${LOCATIONS[$((i % ${#LOCATIONS[@]}))]}"
  LAT=$(echo "$LOC" | cut -d',' -f1)
  LNG=$(echo "$LOC" | cut -d',' -f2)

  # Format interests as JSON array
  INTERESTS_JSON=$(echo "$INTERESTS_STR" | python3 -c "import sys; items=sys.stdin.read().strip().split(','); print('[' + ','.join(['\"'+x+'\"' for x in items]) + ']')")

  echo "Logging in as $EMAIL..."

  # Login
  LOGIN_RESPONSE=$(curl -s -X POST "$API_BASE/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\": \"$EMAIL\", \"password\": \"$PASSWORD\"}")

  TOKEN=$(echo "$LOGIN_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('idToken',''))" 2>/dev/null)

  if [ -z "$TOKEN" ]; then
    echo "  ✗ Login failed for $EMAIL"
    continue
  fi

  # Create profile
  PROFILE_RESPONSE=$(curl -s -X POST "$API_BASE/profiles" \
    -H "Content-Type: application/json" \
    -H "Authorization: $TOKEN" \
    -d "{
      \"name\": \"$NAME\",
      \"bio\": \"$BIO\",
      \"gender\": \"$GENDER\",
      \"interestedIn\": \"$INTERESTED\",
      \"birthDate\": \"$BIRTHDATE\",
      \"birthTime\": \"$BIRTHTIME\",
      \"location\": {\"latitude\": $LAT, \"longitude\": $LNG},
      \"interests\": $INTERESTS_JSON
    }")

  STATUS=$(echo "$PROFILE_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print('ok' if 'userId' in d else d.get('error','unknown'))" 2>/dev/null)

  if [ "$STATUS" = "ok" ]; then
    echo "  ✓ $NAME ($EMAIL)"
  else
    echo "  ✗ $EMAIL — $STATUS"
  fi
done

echo ""
echo "Done!"
