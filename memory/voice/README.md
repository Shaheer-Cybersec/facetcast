# Your voice samples (optional, private)

Facetcast learns your voice from each project's README. If you also want it to match how you
write on social media, add a few of your real posts here in any `.md` file, for example
`my_posts.md` (everything in this folder except this README is gitignored):

```markdown
## Post: linkedin
The full text of one LinkedIn post you published.
---
## Post: x
A tweet or a whole thread you wrote.
---
## Post: instagram
An Instagram caption.
---
```

- The profiler weighs these above the README when it builds your voice profile.
- `python -m memory.import_posts` also loads them into memory, so Facetcast never suggests an
  angle you already posted about (semantic dedup needs `requirements-embeddings.txt`).
