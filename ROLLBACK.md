# ROLLBACK — remove hardcoded Astar JWT (2026-10-14)

Change: 6 hardcoded JWTs in astar-island/*.py and dashboard/server.py replaced by `os.environ["AINM_JWT_TOKEN"]` (dashboard: `.get`).
Token was expired (exp March 2026), so no live credential was exposed.

Rollback: `git revert <commit>` or `git branch -D chore/remove-hardcoded-jwt` (nothing pushed/merged).
Local backup of pre-change files: `.backup/jwt-fix-*.tgz` in the main checkout.
Note: the old token remains in git history. Rewriting history of the public repo is a separate decision for Markus.
