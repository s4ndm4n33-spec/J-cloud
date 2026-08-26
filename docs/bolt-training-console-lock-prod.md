# Bolt Prompt — Lock Training Console to Production

Paste this whole message into the existing bolt.new Training Console project.

---

Lock the API base URL to production so the console never accidentally reads
from preview data.

## Change

1. In the Settings panel (`apiBaseUrl` field), set the default to
   `https://blue-j-gauntlet.com` and make it read-only unless the user
   holds Shift while clicking the field (escape hatch for the owner).

2. On app boot, if `localStorage.apiBaseUrl` contains the string
   `preview.emergentagent.com`, silently overwrite it to
   `https://blue-j-gauntlet.com` and toast:
   `"Restored production API endpoint"`.

3. After `/api/training/health` responds, compare `data.public_backend_url`
   to the current `apiBaseUrl`. If they don't match, show a persistent red
   banner: `"Console is pointing at {apiBaseUrl} but backend reports
   {data.public_backend_url} — data will be from the wrong environment"`.

4. Under the health pills add a small chip that reads either
   `SOURCE · PROD` (green) or `SOURCE · PREVIEW` (amber) based on whether
   `apiBaseUrl` includes `blue-j-gauntlet.com`.

## Why

Every dataset export, training run, and DPO review is scoped to whichever
backend the console calls. Preview has junk/test data; prod has real user
chronicle signal. Mixing the two would poison a fine-tune.

## Don't

- Don't remove the Settings escape hatch — the owner may need to point at
  a staging URL during migrations.
- Don't add a build-time env var; keep this as a client-side lock so the
  same bundle works for owner + any future collaborators.
