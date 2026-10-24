# Open issues: order and parallel work

Snapshot of 2026-10-24. Issue #27 holds the live order as bare numbered references.
This file records why each issue sits where it does and which issues can be worked on
at the same time; positions that change in #27 later are not reflected here.
Dependencies come from each issue body, and overlaps from the files each body names.

## Order and reasons

Tier 1, fixes and small generic pieces:

1. #10. Bug in every generated project; #26 needs its `delete_upload`.
2. #5. The other bug; small.
3. #11. Small; #13 and #24 need it.
4. #12. Small; after #11 so `tools.md` covers `requirements-dev.txt`.
5. #6. Its `models/` package and typed `current_user` come before #28 and #7 build on
   them, and #17 needs `paginate_select`. It must add `DuplicateRecordError`, which the
   template lacks and only #7 defines.
6. #28. Fixes case-sensitive email matching, which lets case variants register as
   separate accounts and makes a differently capitalized address fail to sign in. Also
   fixes the login timing leak, a small gain while `/register` answers 409 for a taken
   email. After #6 so it edits `models/user.py`; before #7 so the admin screens and the
   inactive-account check build on `normalize_email` and `complete_login`.
7. #7. Both #17 and #26 need it, and #16 and #18 build on its kit.

Tier 2, features more than one sibling app rebuilt:

8. #15. The `scripts/tests/` harness that the infrastructure issues' tests live in.
9. #13. Needs #11.
10. #14. No daily backup runs without a bucket; #24 needs `backup.sh --label`.
11. #22. Security gaps every generated project inherits.
12. #17. Needs #6 and #7, and #26 needs it; it should exist before a project writes
    services.
13. #16. Both #24 and #25 need it.
14. #18. Builds on the kit from #7.
15. #19. Ahead of #23 because hukilau's reminder job used both (`1a7fc99`).
16. #23. Scheduled jobs, which pair with the mailer for reminders.
17. #20. No dependencies either way.
18. #21. Edits `worktree-setup.sh` after #11, #16 and #28 have changed it.

The sign-in chain, new work that no sibling app has built:

19. #29. Heavy and coupled like Tier 3, but ahead of it because what it needs lands
    early. After #22 so the callback's `X-Requested-With` exemption is written with
    the callback.
20. #32. Needs #28 and #29; no outside developer account; works on localhost.
21. #30. Apple refuses localhost and IP redirect URIs, so it needs the staging host
    from #16 or a tunnel.
22. #31. Until Meta grants Advanced Access after Business Verification, only people
    with a role on the app can sign in.

Tier 3, heavy or coupled:

23. #24. Needs #16, #11 and #14.
24. #25. Needs #16 and #24.
25. #26. Needs #10, #7 and #17.
26. #4. Lands on the `deploy.sh` that #16 and #24 shape; narrowest audience.

## Working in parallel

### One checkout per agent

In a single checkout, `/plan-issue` requires a clean tree and runs
`git switch -c issue-<n>-<slug>` there, so two agents sharing a checkout abort or pull
each other off their branches. Give each agent its own clone or
`git worktree add ../<dir> --detach origin/main`. Give each its own `.env` whose
`COMPOSE_PROJECT_NAME` differs from every other checkout's: a shared name makes the
Docker stacks replace each other, while `npm run docker:up` already reassigns busy
ports. Build `.venv` and `node_modules` there before running `/plan-issue <n>`.
`scripts/worktree-setup.sh` automates this only for the bare-repo layout.

### Alongside #10

- #5 edits `app.py`, `api/auth.py` and `test_auth.py`; with #10 it shares only
  `ai/conventions.md`.
- #11 edits the requirements files, both Dockerfiles, the CI install step,
  `worktree-setup.sh` and the devcontainer; nothing in common with #10.
- #6 edits `utils.py`, `test_utils.py` and `conftest.py`, as #10 does, but different
  functions and fixtures; expect a small rebase.
- #15 adds `scripts/tests/` files, one CI step and one npm script. Its first tests skip
  `deploy.sh`, the script #10 edits. It moves ahead of #28 and #7 because neither can
  start yet.
- #12 is optional: it describes the requirements split from #11, so start it once #11
  merges, or let whichever of the two merges second add the cross-reference.

### Waiting on a merge

- #28 waits for #5 (the same `login_user` lines in `api/auth.py`) and #6 (which moves
  `User`).
- #7 waits for #28. Its move of the frontend tests into a mirrored tree collides with
  any open branch that edits frontend tests.
- #13 waits for #11, as the issue declares.

### Later waves

- After #11 and #15: #13, #14, #22, #23 and #21, whose tests live in the new harness;
  of these, #22 and #21 also edit files that #11 changes. Keep #13 and #22 apart, since
  both edit `docker/backend.Dockerfile` and `docker/entrypoint.sh`. Keep #14 and #23
  apart, since both add unit installation to the same part of `deploy.sh`.
- After #7: #17 and #18 together (generic services versus layout components).
- After #22 and #28: #29. After #29: #32, #30 and #31 together; they add separate
  provider entries to shared files, and only #32 adds a migration.
- Run #16 alone, with few branches open. It makes `staging` the default branch, so
  open PRs must be retargeted; `/plan-issue` reads the default branch, so issues
  planned afterwards branch from `staging` on their own.
- Then #24 after #16 and #14, and #25 after #24; #26 after #17; #4 after #24.
- Any time: #19 (a new mailer module) and #20 (a CSV helper and a download helper) are
  self-contained work for an idle agent.

### Collisions to plan for

- Migrations: #7, #17, #26, #28, #29 and #32 each add one. Two open at once start from
  the same head, so the second to merge re-points its `down_revision`, then reruns
  `db upgrade` and `db check`.
- Shared files: most branches also touch `ai/conventions.md`, `ai/project.md`,
  `README.md`, `.env.example`, the Compose files or `package-lock.json`. Those
  conflicts are small; regenerate the lock file with `npm install`.
