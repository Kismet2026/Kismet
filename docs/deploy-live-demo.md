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
- **Main App:** TBD (Vercel)
- **Admin Dashboard:** TBD (Streamlit Cloud)

## Test Accounts
All accounts use password: `password123`

| Email | Display Name | Role |
|-------|-------------|------|
| test1@kismet.com | Emma Zhang | user |
| test2@kismet.com | Liam Chen | user |
| test3@kismet.com | Sophia Wang | user |
| test4@kismet.com | Noah Liu | user |
| test5@kismet.com | Olivia Li | user |
| test6@kismet.com | James Wu | user |
| test7@kismet.com | Ava Huang | user |
| test8@kismet.com | William Yang | user |
| test9@kismet.com | Isabella Xu | user |
| test10@kismet.com | Benjamin Zhou | user |
| test11@kismet.com | Mia Sun | user |
| test12@kismet.com | Lucas Tang | user |
| test13@kismet.com | Charlotte Guo | user |
| test14@kismet.com | Henry Luo | user |
| test15@kismet.com | Amelia Feng | user |
| test16@kismet.com | Alexander He | user |
| test17@kismet.com | Harper Cheng | user |
| test18@kismet.com | Ethan Jiang | user |
| test19@kismet.com | Evelyn Zhu | user |
| admin@kismet.com | Admin | admin |

## Create Test Accounts
```bash
./scripts/create-test-users.sh us-east-1_QcZfsgi6A
```
