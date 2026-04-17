# Kismet Live Demo — Lingyun's Deployment

## AWS Account
- **Account ID:** 465040459655
- **Region:** us-east-1
- **IAM Profile:** `admin-cli`

## Deploy Command
```bash
cd infra
AWS_PROFILE=admin-cli cdk deploy --all --require-approval never
```

## Deployed Stacks
| Stack | Status |
|-------|--------|
| KismetShared | ✅ |
| KismetDomain1 | ✅ |
| KismetDomain2 | ✅ |
| KismetDomain3 | ✅ |
| KismetDomain4 | ✅ |
| KismetDomain5 | ✅ |
| KismetDomain6 | ✅ |

## Endpoints
- **API Base URL:** https://ihdsi4eg31.execute-api.us-east-1.amazonaws.com/dev/
- **WebSocket URL:** wss://5x5fhii86j.execute-api.us-east-1.amazonaws.com/dev
- **Cognito User Pool ID:** us-east-1_QcZfsgi6A
- **Cognito Client ID:** 1afn6c6gph8v5qua3flajcs20e
- **Photos CDN:** https://d172bmctgvnuxt.cloudfront.net

## Frontend
- **Main App:** TBD (Vercel — set env vars below)
- **Admin Dashboard:** http://localhost:8501 (or Streamlit Cloud)

### Vercel Environment Variables
| Variable | Value |
|----------|-------|
| `NEXT_PUBLIC_API_BASE_URL` | `https://ihdsi4eg31.execute-api.us-east-1.amazonaws.com/dev` |
| `NEXT_PUBLIC_WS_URL` | `wss://5x5fhii86j.execute-api.us-east-1.amazonaws.com/dev` |

## Test Accounts
All accounts use password: `password123`

| Email | Display Name | Role |
|-------|-------------|------|
| test1@kismet.com | Emma Test Zhang | user |
| test2@kismet.com | Liam Test Chen | user |
| test3@kismet.com | Sophia Test Wang | user |
| test4@kismet.com | Noah Test Liu | user |
| test5@kismet.com | Olivia Test Li | user |
| test6@kismet.com | James Test Wu | user |
| test7@kismet.com | Ava Test Huang | user |
| test8@kismet.com | William Test Yang | user |
| test9@kismet.com | Isabella Test Xu | user |
| test10@kismet.com | Benjamin Test Zhou | user |
| test11@kismet.com | Mia Test Sun | user |
| test12@kismet.com | Lucas Test Tang | user |
| test13@kismet.com | Charlotte Test Guo | user |
| test14@kismet.com | Henry Test Luo | user |
| test15@kismet.com | Amelia Test Feng | user |
| test16@kismet.com | Alexander Test He | user |
| test17@kismet.com | Harper Test Cheng | user |
| test18@kismet.com | Ethan Test Jiang | user |
| test19@kismet.com | Evelyn Test Zhu | user |
| admin@kismet.com | Admin | admin |

## Scripts
```bash
# Create Cognito accounts
./scripts/create-test-users.sh us-east-1_QcZfsgi6A

# Create profiles (run after accounts created)
./scripts/create-test-profiles.sh

# Redeploy Domain 6 only
AWS_PROFILE=admin-cli cdk deploy KismetDomain6
```
