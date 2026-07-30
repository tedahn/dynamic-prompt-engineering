# Pre-upload safety

Run this check before adding any file or pasted context to a ChatGPT Project. Keep this document local; it is a preflight checklist, not a default upload.

1. Confirm the correct Project, account, members, admin controls, retention policy, and approved data boundary.
2. Remove secrets: credentials, tokens, private keys, connection strings, recovery codes, internal endpoints, and production dumps.
3. Minimize or de-identify personal, health, financial, student, employment, legal, and customer data. Do not assume redaction is sufficient for re-identification risk.
4. Confirm rights to share source code, contracts, licensed research, customer material, and third-party content.
5. Upload only the smallest decision-relevant subset; prefer synthetic fixtures over production records.
6. Review repository exclusions such as `.env*`, secrets, generated artifacts, database exports, logs, uploads, and local caches.
7. Record who approved any sensitive inclusion, its purpose, review date, and deletion/correction procedure.
8. Recheck before sharing the Project, changing membership, connecting a source, or expanding scope.

If the data classification or account controls are unclear, stop and ask the responsible owner. Never upload merely because a file is present in a supplied repository.
