# Upload SaiQuant AI to GitHub

This package is ready for the repository:
`https://github.com/sairajproductionsshirdi-prog/saiquant-ai`

## Easiest method: GitHub website

1. Extract `SaiQuant-AI-MVP-GitHub.zip` on your computer.
2. Open your empty GitHub repository.
3. Select **Add file → Upload files**.
4. Open the extracted `SaiQuant-AI-MVP-GitHub` folder.
5. Select all items inside the folder, including `.github`, `.gitignore`,
   `.env.example`, `saiquant`, `tests`, `README.md`, and `pyproject.toml`.
6. Drag them to GitHub and wait for the upload to finish.
7. In the commit box enter `Upload safe paper-trading MVP`.
8. Select **Commit changes**.
9. Open the **Actions** tab. The `Safety tests` workflow should finish with a
   green tick.

Do not upload a real `.env` file, database, API secret, access token, Android
signing key, or Zerodha credentials.

## Important deployment note

GitHub stores and tests the source code. GitHub Pages cannot run this Python
backend. A backend host will be required before an Android app can connect to
it. Live Zerodha order placement is intentionally absent from this release.
