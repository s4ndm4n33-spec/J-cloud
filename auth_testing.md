# Auth Testing Playbook (saved from integration_playbook_expert_v2)

## Step 1: Create Test User & Session (mongosh)
```
mongosh --eval "
use('test_database');
var userId = 'test-user-' + Date.now();
var sessionToken = 'test_session_' + Date.now();
db.users.insertOne({
  user_id: userId,
  email: 'test.user.' + Date.now() + '@example.com',
  name: 'Test User',
  picture: 'https://via.placeholder.com/150',
  created_at: new Date()
});
db.user_sessions.insertOne({
  user_id: userId,
  session_token: sessionToken,
  expires_at: new Date(Date.now() + 7*24*60*60*1000),
  created_at: new Date()
});
print('Session token: ' + sessionToken);
print('User ID: ' + userId);
"
```

## Step 2: Test Backend
```
curl -X GET "$BACKEND_URL/api/auth/me" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

## Step 3: Browser
Set cookie `session_token` (httpOnly, secure, sameSite=None) on the preview domain, then navigate to `/ide`.

## Success Indicators
- `/api/auth/me` returns user data
- IDE shell loads without redirect to /login

## Failure Indicators
- 401 Unauthorized
- Redirect back to /login

NOTE: Google OAuth has no app-managed password. Don't store passwords for it.
