# Contributing

Issues and pull requests are welcome.

Ground rules:
- Core stays stdlib-only. Optional features (browser, LLM SDKs) are extras.
- Tests run offline: python3 -m unittest discover -s tests
- No provider lock-in: nothing in src/findmejob outside llm.py may import a
  model SDK.
- Safety gates (guards.py, autonomy settings) are not bypassable by config
  tricks or prompt text. Strengthening them is welcome; weakening them needs
  a clear justification in the PR.
- Never commit real CVs, personal data, .env, data/ or output/ content.
