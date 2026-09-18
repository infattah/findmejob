# Security policy

- Secrets belong in .env (gitignored) or your coding agent's own secret
  store, never in config.json, issues, or pull requests.
- The local UI binds to 127.0.0.1 and has no authentication. Do not expose
  it beyond localhost.
- Browser automation uses a persistent local profile under
  data/browser-profile. It can hold logged-in sessions; treat the data/
  directory as private and never commit it.
- Report vulnerabilities by opening a private security advisory on GitHub
  rather than a public issue.
