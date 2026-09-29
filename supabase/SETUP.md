# Setting up the Sendit backend (Supabase)

Supabase is a hosted database with sign-in and file storage built in. The free plan is
enough for Sendit until well past the CU ski club launch. About 15 minutes, all in the browser.

## 1. Make the project
1. Go to **supabase.com** → *Start your project* → sign in (GitHub or email).
2. *New project*:
   - **Name:** `sendit`
   - **Database password:** click *Generate*, then save it in your password manager.
     You'll rarely need it, but you can't see it again.
   - **Region:** *West US* (closest to Boulder).
3. Wait about 2 minutes while it builds.

## 2. Create the tables
1. Left sidebar → **SQL Editor** → *New query*.
2. Open [`001_schema.sql`](001_schema.sql) in VS Code, copy everything, paste, click **Run**.
3. You should see *Success. No rows returned*. If there's a red error, copy it to Claude.
4. Check: left sidebar → **Table Editor**. You should see `tricks` (20 rows), `profiles`,
   `clips` and `votes`.

## 3. Turn on email sign-in
Left sidebar → **Authentication** → *Sign In / Providers* → make sure **Email** is on.
Leave "Confirm email" on, so people can't sign up as someone else's address.

## 4. Get the two keys the app needs
Left sidebar → **Project Settings** → **API** (or *Data API* / *API Keys*). Copy:
- **Project URL**, e.g. `https://abcdefgh.supabase.co`
- **Publishable key** (older projects call it the `anon` `public` key)

Both are **safe to put in the app**. They're designed to be public, because the security
lives in the rules inside `001_schema.sql`, not in hiding the key.

⚠️ **Never** copy the `service_role` / **secret** key anywhere. It skips every rule.

## Good to know
- Free projects **pause after 1 week with no activity**. Open the dashboard and click
  *Restore* if that happens. Nothing is lost.
- Video uploads are capped at 50 MB each (free plan). A 15-second 1080p phone clip is about 30 MB.
