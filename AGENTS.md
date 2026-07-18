# Stale AI development rules

- Keep the workflow deterministic wherever possible.
- GPT output must be validated with Pydantic schemas.
- Never edit outside the selected repository.
- Prefer the smallest patch that resolves generated regression failures.
- Preserve backward compatibility unless the source change explicitly removes it.
- Run existing tests and generated tests after changes.
- Do not fabricate source evidence.
